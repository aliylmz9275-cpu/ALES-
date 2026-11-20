"""
predictive.py — Spekulatif on-getirme (predictive execution).

NEDEN: Arac dongusunde adim N'in sonucu modele gonderilirken model dusunur;
o sirada CPU/IO bostur. Adim N+1'in muhtemelen isteyecegi veriyi (taze ekran
goruntusu, ekrandaki ogenin koordinati, klasor listesi) simdiden alirsak,
model karar verdiginde veri ELDE HAZIRDIR ve adim beklemeden baslar.

SPEKULASYONUN TEK GERCEK SORUSU: bir seyi "belki gerekir" diye calistirmak.
Bu ekran goruntusu icin zararsizdir. click_at, type_text, press_key,
delete_path, write_file, send_notification icin FELAKETTIR.

Bu yuzden ALLOWLIST kullaniyoruz, blocklist DEGIL. Blocklist, biri yeni bir
yikici arac ekledigi anda SESSIZCE acik kalir — yeni arac listede olmadigi
icin "guvenli" sayilir. Allowlist ise bilinmeyen her seye kapali dogar.
Buradaki isimler main.py'deki gercek arac adlariyla birebir dogrulandi
(dikkat: arac "find_on_screen", "find_element_on_screen" DEGIL).

analyze_screen BILEREK YOK: salt-okunur ama bir vision LLM cagrisi yapar,
yani token harcar. Kullanilmayan bir spekulasyon burada para maliyeti
dogurur; onbellek kazanci bunu hakli cikarmaz.

DONGU TEHLIKESI: Bir on-getirme, tamamlaninca yeni bir on-getirme
tetiklerse sistem kendini surekli besler ve makineyi doldurur. Cozum
yapisal: prefetch_for() SADECE run_agent'in arac dongusunden (orkestrasyon
katmani) cagrilir, execute_tool_async'in icinden ASLA. Ayrica asagida
_depth sayaci ile ikinci bir kapi var (kemer + askii).
"""
import json
import threading
import time

# SpecCache'in ogrendigi (arac -> sonraki arac) tablosunu OKUMAK icin.
# ZORUNLU DEGIL: modul yoksa tahmin katmani kendi _pairs tablosuyla
# calismaya devam eder. Ic ice import olmadigina dikkat: speculative_cache
# predictive'i import ETMIYOR (dogrulandi), yani dairesel import yok.
try:
    import speculative_cache
except Exception:
    speculative_cache = None

# ─── ALLOWLIST ─────────────────────────────────────────────────────────
# main.py TOOLS (satir 351) ve execute_tool (satir 537) ile dogrulandi.
READONLY_PREFETCHABLE = frozenset({
    "take_screenshot",       # ekran durumu — en cok ise yarayan
    "find_on_screen",        # OCR/gorsel arama; koordinat uretir
    "get_system_info",
    "list_directory", "get_file_info", "read_file", "search_files",
    "get_crypto_prices", "get_exchange_rates", "get_weather",
    "get_news_tr", "get_worldview",
    "get_fiverr_tasks", "list_schedules", "list_notification_rules",
    "get_all_facts", "get_user_profile", "list_skills", "list_personas",
})

# TAZELIK: Bayat ekran goruntusu, HIC ekran goruntusu olmamasindan DAHA
# KOTUDUR — model artik var olmayan bir dugmeye tiklamaya calisir ve
# hatayi anlamaz. O yuzden ekran/OCR TTL'leri cok kisa.
TTL_S = {
    "take_screenshot": 1.5,
    "find_on_screen": 1.5,
    "get_system_info": 3.0,
    "list_directory": 5.0,
    "get_file_info": 5.0,
    "read_file": 5.0,
    "search_files": 5.0,
    "get_fiverr_tasks": 15.0,
    "list_schedules": 15.0,
    "list_notification_rules": 15.0,
    "get_all_facts": 15.0,
    "get_user_profile": 15.0,
    "list_skills": 30.0,
    "list_personas": 30.0,
}
DEFAULT_TTL_S = 60.0        # piyasa/haber/hava gibi ag verileri

MAX_INFLIGHT = 2            # spekulasyon gercek istegi ac biraktirmasin
MAX_CACHE = 64              # onbellek girdisi ust siniri
MAX_PAIRS = 200             # ogrenilen gecis tablosu ust siniri
MIN_PAIR_COUNT = 3          # bu kadar gorulmeden ogrenilmis sayilmaz
MAX_DEPTH = 1               # on-getirme icinden on-getirme YASAK

# ─── STATIK GECIS TABLOSU ──────────────────────────────────────────────
# "su araci calistirdiysan, siradaki muhtemelen bu" — sadece ipucu.
_AFTER = {
    "open_app":       ["take_screenshot"],
    "click_at":       ["take_screenshot"],
    "type_text":      ["take_screenshot"],
    "press_key":      ["take_screenshot"],
    "analyze_screen": ["take_screenshot"],
    "get_crypto_prices": ["get_exchange_rates"],
    "get_exchange_rates": ["get_crypto_prices"],
    "get_news_tr":    ["get_worldview"],
    "list_directory": ["get_file_info"],
    "search_files":   ["get_file_info"],
}

# take_screenshot -> find_on_screen zinciri SADECE kullanicinin mesaji
# tiklama/arama ima ediyorsa kurulur. Aksi halde her ekran goruntusunden
# sonra bosuna OCR calistirmis olurduk (pahali ve gurultulu).
_CLICK_HINTS = ("tikla", "tıkla", "click", "bas", "sec", "seç", "bul",
                "ara", "dugme", "düğme", "buton", "button", "ac", "aç",
                "gir", "yaz", "input", "kutu", "alan", "link", "menu")

_lock = threading.RLock()
_cache = {}          # ckey -> {"tool","args","value","ts","ttl"}
_pairs = {}          # "prev>next" -> count
_inflight = set()    # ckey — ayni seyi iki kez istemeyelim
_depth = 0           # on-getirme icinde miyiz
_sem = None          # asyncio.Semaphore, tembel kurulur

_stats = {"scheduled": 0, "completed": 0, "hits": 0, "misses": 0,
          "expired": 0, "failed": 0, "skipped_unsafe": 0,
          "skipped_depth": 0, "saved_s": 0.0, "evicted": 0}


# ─── ANAHTAR / TTL ─────────────────────────────────────────────────────
def _ckey(tool: str, args: dict) -> str:
    """Arac + argumanlarin kanonik anahtari. Argumanlar sirali JSON'a
    cevrilir; boylece farkli siralanmis ayni dict de HIT verir."""
    try:
        a = json.dumps(args or {}, sort_keys=True, ensure_ascii=False,
                       default=str)
    except Exception:
        a = str(args)
    return f"{tool}|{a}"


def _ttl(tool: str) -> float:
    return float(TTL_S.get(tool, DEFAULT_TTL_S))


def _evict():
    now = time.time()
    dead = [k for k, e in _cache.items() if now - e["ts"] > e["ttl"]]
    for k in dead:
        _cache.pop(k, None)
    if len(_cache) > MAX_CACHE:
        for k, _ in sorted(_cache.items(), key=lambda kv: kv[1]["ts"])[
                :len(_cache) - MAX_CACHE]:
            _cache.pop(k, None)
            _stats["evicted"] += 1


# ─── TAHMIN ────────────────────────────────────────────────────────────
def observe(prev_tool: str, next_tool: str) -> None:
    """Gercekte gorulen (prev -> next) gecisini say. MIN_PAIR_COUNT'a
    ulasan ciftler predict_next'te statik tabloya eklenir."""
    if not prev_tool or not next_tool or prev_tool == next_tool:
        return
    if next_tool not in READONLY_PREFETCHABLE:
        return                                   # ogrenmenin anlami yok
    with _lock:
        k = f"{prev_tool}>{next_tool}"
        _pairs[k] = _pairs.get(k, 0) + 1
        if len(_pairs) > MAX_PAIRS:
            # En az gorulen ciftleri at; tablo sinirsiz buyumesin.
            for kk, _ in sorted(_pairs.items(), key=lambda kv: kv[1])[
                    :len(_pairs) - MAX_PAIRS]:
                _pairs.pop(kk, None)


def predict_next(tool_name: str, args: dict, history: list = None,
                 user_message: str = "") -> list:
    """[(tool, args), ...] — bir sonraki adimda muhtemelen gerekecek,
    ON-GETIRILEBILIR araclar. Guvenli olmayan hicbir sey donmez."""
    out = []
    seen = set()
    msg = (user_message or "").casefold()
    wants_click = any(h in msg for h in _CLICK_HINTS)

    def _add(t, a=None):
        if t not in READONLY_PREFETCHABLE:
            return
        k = _ckey(t, a or {})
        if k in seen:
            return
        seen.add(k)
        out.append((t, a or {}))

    for t in _AFTER.get(tool_name, []):
        _add(t)

    if tool_name == "take_screenshot" and wants_click:
        # Elemanin adini kullanicinin mesajindan cikaramayiz; find_on_screen
        # "element" zorunlu arguman istiyor. Bu yuzden tahmin ancak model
        # daha once bir eleman adi kullandiysa (history) kurulabilir.
        for h in reversed(history or []):
            if isinstance(h, dict) and h.get("tool") == "find_on_screen":
                el = (h.get("args") or {}).get("element")
                if el:
                    _add("find_on_screen", {"element": el,
                                            "region": (h.get("args") or {}).get("region", "auto")})
                break

    if tool_name == "list_directory":
        # Klasor listesinden ilk girdinin bilgisini turetmek ucuz degil
        # (cikti metin), o yuzden ayni yolun kendi bilgisini alalim.
        p = (args or {}).get("path")
        if p:
            _add("get_file_info", {"path": p})

    # Ogrenilmis gecisler
    with _lock:
        learned = [k.split(">", 1)[1] for k, c in _pairs.items()
                   if c >= MIN_PAIR_COUNT and k.startswith(tool_name + ">")]
    for t in learned:
        if t == "find_on_screen":
            continue                             # arguman uretemeyiz
        _add(t)

    # SpecCache'in gecis tablosu (EN SONDA, en dusuk oncelikle)
    #
    # NEDEN BURADA: main.py her turda speculative_cache.register_transition()
    # cagiriyordu ama predict_next_steps() hicbir yerden OKUNMUYORDU — yani
    # SpecCache yalnizca YAZIYOR, ogrendigi hicbir sey bir ise yaramiyordu.
    # main.py'nin oradaki yorumu "predictive bunu on-getirme sirasi icin
    # kullanir" diyordu; DEMIYORDU. Artik gercekten kullaniyor.
    #
    # NEDEN EN SONDA: iki tablo ayni seyi FARKLI esiklerle ogreniyor.
    # Buradaki _pairs MIN_PAIR_COUNT=3 goruse kadar bir gecisi "ogrenilmis"
    # saymaz; SpecCache ise TEK gorusten sonra listeye ekler. Daha zayif
    # kanit demek: daha dusuk oncelik. out[:MAX_INFLIGHT] kirpmasi zaten
    # sonda oldugu icin guclu tahminler varsa bunlar dogal olarak elenir.
    #
    # _add() KAPISI AYNEN GECERLI: READONLY_PREFETCHABLE'da olmayan bir ad
    # (SpecCache "click"/"type" gibi serbest metinler de ogrenir) sessizce
    # dusurulur. Bu yuzden guvensiz bir arac buradan asla sizamaz.
    if speculative_cache is not None:
        try:
            for t in speculative_cache.predict_next_steps(tool_name):
                if t == "find_on_screen":
                    continue                     # arguman uretemeyiz
                _add(t)
        except Exception:
            pass                                 # tahmin katmani, zorunlu degil

    return out[:MAX_INFLIGHT]                    # semafor kadarindan fazlasi bosa


# ─── ON-GETIRME ────────────────────────────────────────────────────────
def _get_sem():
    global _sem
    if _sem is None:
        import asyncio
        _sem = asyncio.Semaphore(MAX_INFLIGHT)
    return _sem


async def _run_one(tool: str, args: dict, execute_async):
    """Tek on-getirme. HATA YUKARIYA CIKMAZ: basarisiz bir tahmin bir
    olay degildir; kullaniciya hata gostermek yanlis olur."""
    global _depth
    ck = _ckey(tool, args)
    sem = _get_sem()
    async with sem:
        t0 = time.time()
        with _lock:
            _depth += 1
        try:
            val = await execute_async(tool, args)
            with _lock:
                _cache[ck] = {"tool": tool, "args": args, "value": val,
                              "ts": time.time(), "ttl": _ttl(tool),
                              "cost_s": round(time.time() - t0, 3)}
                _stats["completed"] += 1
                _evict()
        except Exception:
            with _lock:
                _stats["failed"] += 1
        finally:
            with _lock:
                _depth = max(0, _depth - 1)
                _inflight.discard(ck)


async def prefetch_for(tool_name: str, args: dict, execute_async,
                       history: list = None, user_message: str = "") -> int:
    """Siradaki adim(lar) icin on-getirme baslat. BEKLEMEZ.

    SADECE run_agent'in arac dongusunden cagrilmali. execute_tool_async'in
    icinden cagrilirsa dongu olusur (bkz. modul basligi); _depth kapisi bunu
    yakalar ama yapisal cozum cagri yerini dogru secmektir.

    Doner: kac tane on-getirme siraya alindi.
    """
    import asyncio
    with _lock:
        if _depth >= MAX_DEPTH:
            _stats["skipped_depth"] += 1
            return 0
    if not callable(execute_async):
        return 0

    n = 0
    for tool, a in predict_next(tool_name, args, history, user_message):
        if tool not in READONLY_PREFETCHABLE:
            with _lock:
                _stats["skipped_unsafe"] += 1
            continue
        ck = _ckey(tool, a)
        with _lock:
            if ck in _inflight:
                continue
            e = _cache.get(ck)
            if e and time.time() - e["ts"] <= e["ttl"]:
                continue                         # zaten taze
            _inflight.add(ck)
            _stats["scheduled"] += 1
        try:
            asyncio.create_task(_run_one(tool, a, execute_async))
            n += 1
        except Exception:
            with _lock:
                _inflight.discard(ck)
                _stats["scheduled"] = max(0, _stats["scheduled"] - 1)
    return n


def take(tool_name: str, args: dict) -> str:
    """Hazir ve TAZE bir on-getirme varsa tuket ve dondur, yoksa None.

    Ucuz ve senkron: main.py bunu her arac cagrisinin hemen oncesinde
    cagirir. Suresi gecmis girdi MISS sayilir ve atilir — bayat veri
    dondurmek sessiz yanlislik uretir.
    """
    if tool_name not in READONLY_PREFETCHABLE:
        return None
    ck = _ckey(tool_name, args or {})
    with _lock:
        e = _cache.pop(ck, None)
        if not e:
            _stats["misses"] += 1
            return None
        if time.time() - e["ts"] > e["ttl"]:
            _stats["expired"] += 1
            _stats["misses"] += 1
            return None
        _stats["hits"] += 1
        _stats["saved_s"] += float(e.get("cost_s") or 0.0)
        return e["value"]


def peek(tool_name: str, args: dict) -> dict:
    """Tuketmeden bak (tanilama icin)."""
    ck = _ckey(tool_name, args or {})
    with _lock:
        e = _cache.get(ck)
        if not e:
            return None
        age = time.time() - e["ts"]
        return {"tool": e["tool"], "age_s": round(age, 2), "ttl": e["ttl"],
                "fresh": age <= e["ttl"], "chars": len(str(e.get("value") or ""))}


def clear() -> None:
    with _lock:
        _cache.clear()
        _inflight.clear()


# ─── ISTATISTIK / BILGI ────────────────────────────────────────────────
def stats() -> dict:
    with _lock:
        s = dict(_stats)
        total = s["hits"] + s["misses"]
        s["hit_rate"] = round(s["hits"] / total, 4) if total else 0.0
        s["saved_s"] = round(s["saved_s"], 3)
        s["cached"] = len(_cache)
        s["inflight"] = len(_inflight)
        s["depth"] = _depth
        s["pairs_learned"] = sum(1 for c in _pairs.values() if c >= MIN_PAIR_COUNT)
        s["pairs_tracked"] = len(_pairs)
        s["max_inflight"] = MAX_INFLIGHT
        return s


def reset_stats() -> dict:
    with _lock:
        _stats.update({"scheduled": 0, "completed": 0, "hits": 0, "misses": 0,
                       "expired": 0, "failed": 0, "skipped_unsafe": 0,
                       "skipped_depth": 0, "saved_s": 0.0, "evicted": 0})
    return stats()


def info() -> dict:
    """UI: kullanici neyin on-getirilebildigini gorebilsin."""
    with _lock:
        learned = sorted(
            [{"pair": k, "count": c} for k, c in _pairs.items()
             if c >= MIN_PAIR_COUNT],
            key=lambda x: -x["count"])[:20]
    return {
        "prefetchable": sorted(READONLY_PREFETCHABLE),
        "ttl": dict(TTL_S), "default_ttl_s": DEFAULT_TTL_S,
        "max_inflight": MAX_INFLIGHT, "max_cache": MAX_CACHE,
        "learned_pairs": learned,
        "note": ("Allowlist tabanli: listede olmayan hicbir arac "
                 "on-getirilmez. Yikici araclar (tiklama, yazma, silme, "
                 "bildirim) hicbir kosulda spekulatif calistirilmaz."),
    }
