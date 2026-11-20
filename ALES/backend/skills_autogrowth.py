"""
skills_autogrowth.py — Sinirli (bounded) beceri ogrenme. Agent0 ikamesi.

Ali'nin onayladigi ikame: "Agent0 -> sinirli kendi kendine ogrenme".
Agent0 kendi kodunu yeniden yazip kendini cogaltir; ALES bunu YAPMAZ.
Buradaki ogrenme sunlarla sinirlidir:

  ALES sadece skills.json'a EKLENECEK bir giris ONERIR. Kullanici UI'dan
  onaylayana kadar HICBIR SEY degismez. Onaylanan giris Fast Path girdisi
  olur (LLM'e ugramayan dogrudan arac cagrisi).

ALES kendi kodunu degistirmez, yeni modul yazmaz, kendini kopyalamaz.
Ogrenilen sey yalnizca "su kalip su araci cagirir" eslesmesidir — veri,
kod degil.

NEDEN ONAY SART: Fast Path girdisi SIFIR LLM denetimiyle calisir. Yanlis
ogrenilmis bir kalip, kullanici baska bir sey isterken sessizce yanlis araci
calistirir ve bunu fark etmenin yolu yoktur. Bu yuzden kapi insanda.

NEDEN SADECE SALT-OKUNUR ARACLAR: Otomatik onerilen bir girdinin adimlari
SAFE_STEP_TOOLS ile sinirli. Bir kalip yanlis eslesirse "ekran goruntusu al"
gereksiz bir is olur; "delete_path" GERI DONUSU OLMAYAN bir kayiptir. Yikici
araclari iceren Fast Path girdileri ELLE yazilmali (skills.json), otomatik
onerilmez. open_app gibi yan etkili ama yikici olmayan araclar da bilerek
disarida: tohum skills.json'da elle var, ama OGRENILMIS bir kalip uygulama
acmasin.

ESIKLER (hepsi bilincli olarak yuksek):
  MIN_OCCURRENCES  ayni kalip + AYNI arac dizisi bu kadar kez gorulmeli
  MIN_WORDS/MAX_WORDS  cok kisa/cok uzun mesajlar kalip olmaz
  Argumanlar TUM tekrarlarda AYNI olmali (yoksa genelleme yanlis olur)
  Zaten Fast Path eslesen mesajlar icin oneri uretilmez (gereksiz golgeleme)
  Reddedilen kalip BIR DAHA onerilmez (kullaniciyi tekrar tekrar rahatsiz
  etmek, oneri sistemini kapatilan bir seye cevirir)
"""
import hashlib
import json
import os
import re
import threading
import time
from pathlib import Path

try:
    from config_manager import get_appdata_dir
    _APPDATA = get_appdata_dir()
except Exception:
    _APPDATA = Path(".")

PROPOSALS_FILE = _APPDATA / "skills_proposals.json"
APPDATA_SKILLS = _APPDATA / "skills.json"
LOCAL_SKILLS = Path(__file__).parent / "skills.json"

try:
    import fast_path
except Exception:
    fast_path = None

# ─── ESIKLER ───────────────────────────────────────────────────────────
MIN_OCCURRENCES = 3
MIN_WORDS = 2
MAX_WORDS = 6            # fast_path max_words ile ayni ruh: kisa emirler
MAX_STEPS = 2            # 3+ adimli is "kalip" degil, akis; AI'da kalsin
MAX_OBSERVATIONS = 300
MAX_PROPOSALS = 40
MIN_KEYWORD_LEN = 3

# Fast Path'e OTOMATIK onerilebilecek araclar: hepsi salt-okunur.
SAFE_STEP_TOOLS = frozenset({
    "take_screenshot", "get_system_info",
    "get_crypto_prices", "get_exchange_rates", "get_weather",
    "get_news_tr", "get_worldview",
    "list_directory", "get_file_info", "read_file", "search_files",
    "get_fiverr_tasks", "list_schedules", "list_notification_rules",
    "get_all_facts", "get_user_profile", "list_skills", "list_personas",
    "search_memory", "list_connectors", "list_installed_skills",
})

# Kalip olmaya UYGUN OLMAYAN mesajlar: soru/kod istekleri. fast_path'teki
# _META_WORDS ile ayni fikir — orada eslesmeyi, burada OGRENMEYI engeller.
_META_WORDS = {
    "nasil", "neden", "niye", "how", "why", "what", "nedir", "yaz", "kod",
    "code", "ornek", "acikla", "explain", "write", "script", "fonksiyon",
    "function", "api", "hakkinda", "farki", "karsilastir", "mi", "mu", "mi?",
}

_TR = str.maketrans({"ç": "c", "ğ": "g", "ı": "i", "İ": "i", "ö": "o",
                     "ş": "s", "ü": "u", "Ç": "c", "Ğ": "g", "Ö": "o",
                     "Ş": "s", "Ü": "u", "I": "i"})
_PUNCT_RE = re.compile(r"[^\w\s]", re.U)
_WS_RE = re.compile(r"\s+")

_lock = threading.RLock()
_obs = {}                # pattern_key -> {"norm","count","tools","args","samples","first","last"}
_data = None             # {"proposals": {...}, "rejected": [...], "approved": [...]}
_notify_cb = None        # main.py WS bildirimi baglar
_stats = {"observed": 0, "skipped_meta": 0, "skipped_unsafe": 0,
          "skipped_existing": 0, "proposed": 0, "approved": 0,
          "rejected": 0, "last_error": None}


# ─── NORMALIZASYON ─────────────────────────────────────────────────────
def _norm(text: str) -> str:
    """fast_path._norm + noktalama temizligi. Kalip anahtari bundan uretilir."""
    t = (text or "").translate(_TR).casefold()
    t = _PUNCT_RE.sub(" ", t)
    return _WS_RE.sub(" ", t).strip()


def _pattern_key(norm: str, tools: list) -> str:
    """Kalip = normalize mesaj + arac dizisi. Ikisi birlikte anahtar olur;
    ayni mesajin farkli araclarla cozulmesi AYRI kaliptir (ve hicbiri esige
    tek basina ulasmazsa oneri cikmaz — dogru davranis)."""
    raw = norm + "||" + ">".join(tools)
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()[:16]


# ─── KALICILIK ─────────────────────────────────────────────────────────
def _load() -> dict:
    global _data
    if _data is not None:
        return _data
    d = {"proposals": {}, "rejected": [], "approved": []}
    try:
        if PROPOSALS_FILE.exists():
            raw = json.loads(PROPOSALS_FILE.read_text(encoding="utf-8"))
            if isinstance(raw, dict):
                d["proposals"] = raw.get("proposals") or {}
                d["rejected"] = list(raw.get("rejected") or [])
                d["approved"] = list(raw.get("approved") or [])
    except Exception:
        pass
    _data = d
    return _data


def _save():
    """Atomik yazim (.tmp -> os.replace)."""
    try:
        d = _load()
        PROPOSALS_FILE.parent.mkdir(parents=True, exist_ok=True)
        tmp = PROPOSALS_FILE.with_suffix(".tmp")
        tmp.write_text(json.dumps({"saved_at": time.time(), **d},
                                  ensure_ascii=False, indent=1),
                       encoding="utf-8")
        os.replace(str(tmp), str(PROPOSALS_FILE))
    except Exception as e:
        with _lock:
            _stats["last_error"] = f"kayit: {type(e).__name__}: {e}"


def set_notify(cb) -> None:
    """main.py bir geri cagri baglar; yeni oneri cikinca WS'e gider."""
    global _notify_cb
    _notify_cb = cb


def _notify(proposal: dict):
    if not callable(_notify_cb):
        return
    try:
        _notify_cb(proposal)
    except Exception:
        pass          # bildirim hatasi ogrenmeyi DUSURMEMELI


# ─── GOZLEM ────────────────────────────────────────────────────────────
def observe(user_message: str, tool_calls: list, ok: bool = True,
            mode: str = "") -> dict:
    """Basarili bir turu kaydet.

    tool_calls: [{"tool": ad, "args": {...}}, ...] — turda calisan araclar,
                CALISMA SIRASIYLA.
    Doner: {"observed":bool, "reason":str, "proposal":dict|None}
    """
    out = {"observed": False, "reason": "", "proposal": None}
    if not ok:
        out["reason"] = "basarisiz tur"
        return out

    norm = _norm(user_message)
    words = norm.split()
    if not (MIN_WORDS <= len(words) <= MAX_WORDS):
        out["reason"] = "mesaj uzunlugu kalip icin uygun degil"
        return out
    if set(words) & _META_WORDS:
        with _lock:
            _stats["skipped_meta"] += 1
        out["reason"] = "soru/kod istegi — kalip olmaz"
        return out

    calls = [c for c in (tool_calls or []) if isinstance(c, dict) and c.get("tool")]
    if not calls or len(calls) > MAX_STEPS:
        out["reason"] = f"arac sayisi uygun degil ({len(calls)})"
        return out

    tools = [str(c["tool"]) for c in calls]
    unsafe = [t for t in tools if t not in SAFE_STEP_TOOLS]
    if unsafe:
        with _lock:
            _stats["skipped_unsafe"] += 1
        out["reason"] = ("otomatik onerilemez arac(lar): " + ", ".join(unsafe)
                         + " — Fast Path girdisi elle yazilmali")
        return out

    # Zaten Fast Path eslesiyorsa ogrenmenin anlami yok (golgeleme olur).
    if fast_path is not None:
        try:
            if fast_path.find_match(user_message):
                with _lock:
                    _stats["skipped_existing"] += 1
                out["reason"] = "mevcut bir Fast Path girdisi zaten esliyor"
                return out
        except Exception:
            pass

    key = _pattern_key(norm, tools)
    d = _load()
    if key in (d.get("rejected") or []):
        out["reason"] = "kullanici bu kalibi reddetti"
        return out
    if key in (d.get("proposals") or {}):
        out["reason"] = "bu kalip icin oneri zaten var"
        return out

    args_sig = json.dumps([c.get("args") or {} for c in calls],
                          sort_keys=True, ensure_ascii=False, default=str)

    with _lock:
        _stats["observed"] += 1
        e = _obs.get(key)
        if e is None:
            if len(_obs) >= MAX_OBSERVATIONS:
                # En eski/en az gorulen gozlemleri at; tablo sinirsiz buyumesin.
                for k, _ in sorted(_obs.items(),
                                   key=lambda kv: (kv[1]["count"], kv[1]["last"]))[:20]:
                    _obs.pop(k, None)
            e = _obs[key] = {"norm": norm, "count": 0, "tools": tools,
                             "args_sig": args_sig,
                             "args": [c.get("args") or {} for c in calls],
                             "samples": [], "words_max": len(words),
                             "first": time.time(), "last": time.time(),
                             "mode": mode}
        if e["args_sig"] != args_sig:
            # Argumanlar farkli: ayni kalip degil. Genelleme yapmiyoruz cunku
            # hangi argumanin degisken oldugunu bilmiyoruz (regex capture'i
            # tahmin etmek yanlis eslesme uretir).
            e["count"] = 1
            e["args_sig"] = args_sig
            e["args"] = [c.get("args") or {} for c in calls]
            e["samples"] = []
            out["reason"] = "argumanlar degisti, sayac sifirlandi"
            e["last"] = time.time()
            return out

        e["count"] += 1
        e["last"] = time.time()
        e["words_max"] = max(e["words_max"], len(words))
        if user_message and user_message not in e["samples"]:
            e["samples"] = (e["samples"] + [user_message[:200]])[:5]
        count = e["count"]
        snapshot = dict(e)

    out["observed"] = True
    out["reason"] = f"{count}/{MIN_OCCURRENCES}"
    if count >= MIN_OCCURRENCES:
        p = _make_proposal(key, snapshot)
        if p:
            out["proposal"] = p
            out["reason"] = "oneri uretildi"
    return out


# ─── ONERI URETIMI ─────────────────────────────────────────────────────
def _keywords_from(samples: list, norm: str) -> list:
    """Ortak, ayirt edici kelimeleri sec.

    Tum orneklerde gecen ve MIN_KEYWORD_LEN'den uzun kelimeleri aliyoruz.
    Sadece TEK kelime kalirsa kalip cok genis olur ("ekran" -> her ekran
    mesajini yakalar); o durumda normalize mesajin ilk iki kelimesini
    kullaniyoruz. fast_path formati: [[k1, k2]] = VE-icinde.
    """
    sets = [set(_norm(s).split()) for s in (samples or []) if s]
    common = set.intersection(*sets) if sets else set(norm.split())
    common = {w for w in common if len(w) >= MIN_KEYWORD_LEN
              and w not in _META_WORDS and not w.isdigit()}
    ordered = [w for w in norm.split() if w in common]
    if len(ordered) >= 2:
        return [ordered[:3]]
    toks = [w for w in norm.split() if len(w) >= 2][:2]
    return [toks] if toks else [[norm[:20]]]


def _make_proposal(key: str, e: dict) -> dict:
    """Gozlemi skills.json girdisine cevir ve BEKLEYEN oneri olarak sakla."""
    d = _load()
    with _lock:
        if len(d.get("proposals") or {}) >= MAX_PROPOSALS:
            _stats["last_error"] = "bekleyen oneri siniri dolu"
            return None

    tools = e["tools"]
    steps = [{"tool": t, "args": (e["args"][i] if i < len(e["args"]) else {})}
             for i, t in enumerate(tools)]
    name = "auto_" + re.sub(r"[^a-z0-9]+", "_", e["norm"])[:28].strip("_")
    entry = {
        "name": name or f"auto_{key}",
        "platform": "any",
        "enabled": True,
        "match": {
            "keywords": _keywords_from(e.get("samples"), e["norm"]),
            "max_words": min(MAX_WORDS, max(3, e.get("words_max", 4) + 1)),
        },
        "steps": steps,
        "error_handling": "route_to_ai",
        # Kaynagi girdinin ICINDE tutuyoruz: kullanici skills.json'a bakinca
        # bu girdinin elle mi yazildigini otomatik mi ogrenildigini gorsun.
        "_source": "skills_autogrowth",
        "_learned_at": time.time(),
    }
    proposal = {
        "id": key,
        "status": "pending",
        "created": time.time(),
        "pattern": e["norm"],
        "samples": e.get("samples") or [],
        "occurrences": e.get("count", 0),
        "tools": tools,
        "entry": entry,
        "why": (f"'{e['norm']}' kalibi {e.get('count', 0)} kez ayni araclarla "
                f"({' -> '.join(tools)}) cozuldu. Onaylarsan bu istek bundan "
                "sonra LLM'e hic gitmeden dogrudan calisir."),
        "risk": ("Adimlarin hepsi salt-okunur. Yanlis eslesirse gereksiz bir "
                 "sorgu yapilir, veri kaybi olmaz."),
    }
    with _lock:
        d.setdefault("proposals", {})[key] = proposal
        _stats["proposed"] += 1
        _obs.pop(key, None)          # oneri cikti, gozlemi tut­maya gerek yok
    _save()
    _notify(proposal)
    return proposal


# ─── ONAY / RED ────────────────────────────────────────────────────────
def _read_skills_file(p: Path):
    try:
        if p.exists():
            raw = json.loads(p.read_text(encoding="utf-8"))
            if isinstance(raw, list):
                return {"skills": raw}, True
            if isinstance(raw, dict):
                return raw, True
    except Exception:
        pass
    return None, False


def _ensure_appdata_skills() -> dict:
    """AppData/skills.json'i garanti et — GEREKIRSE repo kopyasindan tohumla.

    KRITIK: fast_path.load_skills() AppData kopyasi VARSA onu okur ve
    backend/skills.json'a HIC BAKMAZ. Onaya tek bir girdi yazip AppData
    dosyasini olusturursak, tohum 7 becerinin hepsi SESSIZCE kaybolur.
    Bu yuzden dosya yoksa once repo kopyasini oldugu gibi tasiyoruz.
    """
    doc, ok = _read_skills_file(APPDATA_SKILLS)
    if ok and isinstance(doc.get("skills"), list):
        return doc
    seed, ok2 = _read_skills_file(LOCAL_SKILLS)
    if ok2 and isinstance(seed.get("skills"), list):
        return seed
    return {"_README": "ALES Fast Path becerileri (skills_autogrowth tarafindan "
                       "olusturuldu).", "skills": []}


def _write_appdata_skills(doc: dict) -> bool:
    try:
        APPDATA_SKILLS.parent.mkdir(parents=True, exist_ok=True)
        tmp = APPDATA_SKILLS.with_suffix(".tmp")
        tmp.write_text(json.dumps(doc, ensure_ascii=False, indent=2),
                       encoding="utf-8")
        os.replace(str(tmp), str(APPDATA_SKILLS))
        return True
    except Exception as e:
        with _lock:
            _stats["last_error"] = f"skills.json yazma: {type(e).__name__}: {e}"
        return False


def approve(pid: str) -> dict:
    """Oneriyi skills.json'a yaz ve Fast Path'i yeniden yukle.

    Yeniden baslatma gerekmez: fast_path.reload_skills() cagirilir.
    """
    d = _load()
    with _lock:
        p = (d.get("proposals") or {}).get(pid)
    if not p:
        return {"ok": False, "error": f"oneri yok: {pid}"}
    if p.get("status") != "pending":
        return {"ok": False, "error": f"oneri zaten '{p.get('status')}'"}

    entry = dict(p.get("entry") or {})
    # SON KAPI: onay aninda tekrar bakiyoruz. Oneri uretildikten sonra dosya
    # elle duzenlenmis olabilir; yikici bir adim iceriyorsa yazmiyoruz.
    bad = [s.get("tool") for s in entry.get("steps") or []
           if s.get("tool") not in SAFE_STEP_TOOLS]
    if bad or not entry.get("steps"):
        return {"ok": False,
                "error": f"guvenli olmayan/eksik adim: {bad or 'adim yok'}"}

    doc = _ensure_appdata_skills()
    skills = list(doc.get("skills") or [])
    names = {s.get("name") for s in skills}
    if entry.get("name") in names:
        entry["name"] = f"{entry['name']}_{pid[:6]}"
    skills.append(entry)
    doc["skills"] = skills
    if not _write_appdata_skills(doc):
        return {"ok": False, "error": "skills.json yazilamadi"}

    reloaded = 0
    if fast_path is not None:
        try:
            reloaded = len(fast_path.reload_skills() or [])
        except Exception:
            reloaded = 0

    with _lock:
        p["status"] = "approved"
        p["decided"] = time.time()
        d.setdefault("approved", []).append(pid)
        d["proposals"].pop(pid, None)
        _stats["approved"] += 1
    _save()
    return {"ok": True, "id": pid, "name": entry.get("name"),
            "skills_total": len(skills), "fast_path_reloaded": reloaded,
            "file": str(APPDATA_SKILLS)}


def reject(pid: str, reason: str = "") -> dict:
    """Oneriyi reddet ve kalibi KALICI olarak sustur.

    Kalibi hatirliyoruz cunku aksi halde ayni kalip 3 tekrar sonra tekrar
    onerilir; oneri sistemi kullanicinin kapatacagi bir gurultuye doner.
    """
    d = _load()
    with _lock:
        p = (d.get("proposals") or {}).get(pid)
        if not p:
            return {"ok": False, "error": f"oneri yok: {pid}"}
        p["status"] = "rejected"
        p["decided"] = time.time()
        p["reject_reason"] = (reason or "")[:300]
        if pid not in d.setdefault("rejected", []):
            d["rejected"].append(pid)
        d["proposals"].pop(pid, None)
        _obs.pop(pid, None)
        _stats["rejected"] += 1
    _save()
    return {"ok": True, "id": pid, "suppressed": True}


# ─── LISTELEME / ISTATISTIK ────────────────────────────────────────────
def list_proposals(status: str = "pending") -> list:
    d = _load()
    with _lock:
        items = list((d.get("proposals") or {}).values())
    if status and status != "all":
        items = [p for p in items if p.get("status") == status]
    return sorted(items, key=lambda p: p.get("created", 0), reverse=True)


def pending_count() -> int:
    return len(list_proposals("pending"))


def get_proposal(pid: str) -> dict:
    d = _load()
    with _lock:
        p = (d.get("proposals") or {}).get(pid)
        return dict(p) if p else None


def observations(limit: int = 20) -> list:
    """Henuz esige ulasmamis kaliplar — UI'da "ogrenilmek uzere" listesi."""
    with _lock:
        items = sorted(_obs.values(), key=lambda e: -e["count"])[:max(1, int(limit))]
        return [{"pattern": e["norm"], "count": e["count"],
                 "needed": MIN_OCCURRENCES, "tools": e["tools"],
                 "last": e["last"]} for e in items]


def clear_observations() -> int:
    with _lock:
        n = len(_obs)
        _obs.clear()
    return n


def stats() -> dict:
    d = _load()
    with _lock:
        s = dict(_stats)
        s["pending"] = sum(1 for p in (d.get("proposals") or {}).values()
                           if p.get("status") == "pending")
        s["rejected_patterns"] = len(d.get("rejected") or [])
        s["approved_total"] = len(d.get("approved") or [])
        s["watching"] = len(_obs)
    s["min_occurrences"] = MIN_OCCURRENCES
    s["safe_tools"] = len(SAFE_STEP_TOOLS)
    s["file"] = str(PROPOSALS_FILE)
    s["skills_file"] = str(APPDATA_SKILLS)
    return s


def info() -> dict:
    """UI: sinirlarin ne oldugunu kullanici gorebilsin."""
    return {
        "min_occurrences": MIN_OCCURRENCES,
        "word_range": [MIN_WORDS, MAX_WORDS],
        "max_steps": MAX_STEPS,
        "safe_step_tools": sorted(SAFE_STEP_TOOLS),
        "requires_approval": True,
        "note": ("ALES kendi kodunu DEGISTIRMEZ. Sadece skills.json'a "
                 "eklenecek bir girdi onerir; onaylamadan hicbir sey "
                 "degismez. Onerilen adimlar salt-okunur araclarla sinirli."),
    }
