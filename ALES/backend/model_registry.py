"""
model_registry.py — otomatik model kesfi + saglik denetimi.

AMAC: "model adini bir daha elle guncellemek zorunda kalmamak". Saglayicilar
model kimliklerini haber vermeden kaldiriyor; eski kimlik geriye 404/400
donduruyor ve zincir "hicbir katman yanit vermedi" diyor. Bu modul her
saglayicinin CANLI model listesini periyodik olarak ceker, onbellege yazar,
yapilandirmadaki kimlikleri o listeye karsi dogrular ve bir kimlik gercekten
oldugunde ayni aileden calisan bir kimlige KENDILIGINDEN gecer.

─────────────────────────────────────────────────────────────────────────
TASARIMIN EN ONEMLI KARARI — "VERI YOKSA ENGELLEME"
─────────────────────────────────────────────────────────────────────────
Bir modeli devre disi birakmanin iki ayri gerekcesi olabilir:

  (a) Model saglayicinin listesinde GORUNMUYOR.
  (b) Modele yapilan GERCEK bir cagri "boyle bir model yok" dedi.

Yalnizca (b) kesin kanittir. (a) tek basina yeterli DEGILDIR, cunku:
  - /models listesi anahtarin erisebildigi her modeli gostermiyor (NVIDIA
    ve Gemini alt kume donduruyor),
  - istek zaman asimina ugrayip yarim/bos liste donebiliyor,
  - saglayici gecici 500 verdiginde liste bos gelir.
Bos ya da eksik bir listeye bakip modelleri kapatmak, CALISAN bir kurulumu
tamamen offline birakirdi — yani bu ozellik guvenilirligi artirmak yerine
tek basina en buyuk ariza kaynagi olurdu.

Bu yuzden:
  (a) -> durum WARN, arayuzde "listede yok" + oneri gosterilir, CAGRI YAPILIR.
  (b) -> kara listeye alinir, ayni aileden bir kimlige gecilir, bir daha
         denenmez. Karar `overrides` olarak onbellege yazilir, yani yeniden
         baslatmadan sonra da gecerli kalir.

KRITIK: karar config.json'a YAZILMAZ. Kullanicinin yapilandirmasi tek dogru
kaynak olarak kalir; otomatik duzeltme ayri bir katmanda (model_cache.json >
overrides) durur ve arayuzden tek tikla geri alinabilir. Boylece otomatik
sistem kullanicinin ayarini sessizce ezmez.

─────────────────────────────────────────────────────────────────────────
NVIDIA NIM ADRESI HAKKINDA UYARI
─────────────────────────────────────────────────────────────────────────
"http://0.0.0.0:8000/v1/models" adresi BILINCLI OLARAK varsayilan DEGIL.
ALES'in kendi uvicorn sunucusu da 0.0.0.0:8000'de duruyor (main.py). O adres
sorgulanirsa ALES KENDINE istek atar, kendi 404'unu alir, "NVIDIA'da hic
model yok" sonucuna varir ve unrestricted katmanini bozuk sanardi. Varsayilan
bu yuzden gercek bulut adresi (integrate.api.nvidia.com). Kendi NIM
konteynerini calistiranlar icin config.json > "nim_base_url" (veya
ALES_NIM_BASE_URL) ile acikca verilebilir; kendi portumuza bakan bir adres
verilirse reddedilir (bkz. _reject_self_url).
"""
import asyncio
import json
import os
import re
import time
from collections import deque
from datetime import datetime, timezone
from pathlib import Path

from config_manager import get_appdata_dir, get_key, load_config, DEFAULT_MODELS

# ─── SABITLER ────────────────────────────────────────────────────────
CACHE_FILE = get_appdata_dir() / "model_cache.json"
REFRESH_INTERVAL_S = 1800.0      # 30 dakika (istenen periyot)
HTTP_TIMEOUT_S = 5.0             # istenen 5s zaman asimi
EVENT_MAX = 200                  # "yeni/kaldirilan model" gunlugu boyu
LOG_MAX = 300                    # dogrulama/fallback karar gunlugu boyu

# Saglayici -> kesif ayarlari.
#   url    : model listesi adresi
#   auth   : "bearer" | "none" | "query"  (query = ?key=... , Gemini native)
#   strip  : yanittaki kimliklerden atilacak onek
#   alt    : birincil adres calismazsa denenecek ikinci adres
#
# ONEK MESELESI (sessiz hata kaynagi): Gemini'nin NATIVE ucu kimlikleri
# "models/gemini-2.0-flash" diye dondurur, OpenAI-uyumlu ucu ise
# "gemini-2.0-flash". model_router OpenAI-uyumlu istemciyle konustugu icin
# ONEKSIZ kimlik kullanir. Normalize etmezsek her Gemini modeli "listede yok"
# gorunurdu -- yani dogrulama her tur yanlis alarm verirdi.
_SPECS = {
    "openrouter": {
        "url": "https://openrouter.ai/api/v1/models",
        "auth": "none",          # herkese acik, anahtar gerekmez
        "strip": "",
        "alt": None,
        "label": "OpenRouter",
    },
    "groq": {
        "url": "https://api.groq.com/openai/v1/models",
        "auth": "bearer",
        "strip": "",
        "alt": None,
        "label": "Groq",
    },
    "cerebras": {
        "url": "https://api.cerebras.ai/v1/models",
        "auth": "bearer",
        "strip": "",
        "alt": None,
        "label": "Cerebras",
    },
    "gemini": {
        # Birincil: OpenAI-uyumlu uc -- model_router'in GERCEKTEN kullandigi
        # kimlik bicimini (oneksiz) verir.
        "url": "https://generativelanguage.googleapis.com/v1beta/openai/models",
        "auth": "bearer",
        "strip": "models/",
        # Yedek: native uc (?key=...). Bazi bolgelerde/anahtar turlerinde
        # OpenAI-uyumlu uc 404 verebiliyor.
        "alt": {"url": "https://generativelanguage.googleapis.com/v1beta/models",
                "auth": "query", "strip": "models/"},
        "label": "Gemini",
    },
    "nvidia": {
        # Bkz. dosya basindaki "NVIDIA NIM ADRESI" uyarisi.
        "url": "https://integrate.api.nvidia.com/v1/models",
        "auth": "bearer",
        "strip": "",
        "alt": None,
        "label": "NVIDIA NIM",
    },
    "sambanova": {
        "url": "https://api.sambanova.ai/v1/models",
        "auth": "bearer",
        "strip": "",
        "alt": None,
        "label": "SambaNova",
    },
}

_PROVIDER_KEYNAME = {
    "groq": "groq_key", "cerebras": "cerebras_key", "gemini": "gemini_key",
    "openrouter": "openrouter_key", "nvidia": "nvidia_key",
    "sambanova": "sambanova_key",
}

# SambaNova icin statik yedek liste (istenen davranis: "genel bir uc yoksa
# statik listeye dus ve UYAR"). Bu liste TAHMIN degil, yedek; kullanildiginda
# durum WARN olur ve arayuzde "statik liste" yazar. Dogrulamada bu listeye
# BAKILMAZ -- yalnizca arayuzde ne bekledigimizi gostermek icindir.
_STATIC_FALLBACK = {
    "sambanova": [
        "Meta-Llama-3.3-70B-Instruct",
        "Meta-Llama-3.1-8B-Instruct",
        "Meta-Llama-3.1-405B-Instruct",
        "Qwen2.5-72B-Instruct",
        "DeepSeek-R1-Distill-Llama-70B",
    ],
}

# Sohbet modeli OLMAYANLARI yedek secerken disla. Bir kimlik olduğunde
# yerine gomme (embedding) veya goruntu-uretim modeli koymak, hatayi
# "model yok"tan "model yanlis sey yapiyor"a cevirmek olurdu.
_NOT_CHAT = re.compile(
    r"(embed|embedding|rerank|moderation|guard|whisper|tts|speech|audio"
    r"|image|imagen|dall|stable-diffusion|sdxl|flux|video|veo|upscal"
    r"|bge-|e5-|gecko|aqa)", re.I)

# Yedek secmeyi tamamen engelleyecek isaretler: bunlar "onizleme/deneysel"
# surumler; bir uretim zincirini kendiliginden bunlara tasimak istemeyiz.
_RISKY = re.compile(r"(preview|experimental|-exp\b|alpha|beta|nightly)", re.I)

# Alanina ozel / zayif veya guvenlik amacli modelleri genel sohbet icin tercih etme
_NOT_PREFERRED_CHAT = re.compile(
    r"(allam|guard|prompt-guard|orpheus|canopylabs|native-audio|tts|live-translate|transcribe)",
    re.I
)

# Saglayici bazli en iyi SOTA modeller (Groq -> openai/gpt-oss-120b, Gemini -> gemini-3.8-flash, vb.)
_PROVIDER_PREFERRED_DEFAULTS = {
    "groq": [
        "openai/gpt-oss-120b",
        "llama-3.3-70b-versatile",
        "llama-3.1-70b-versatile",
        "openai/gpt-oss-20b",
        "llama-3.1-8b-instant",
        "mixtral-8x7b-32768",
    ],
    "gemini": [
        "gemini-3.8-flash",
        "gemini-3.7-flash",
        "gemini-3.6-flash",
        "gemini-3.5-flash",
        "gemini-2.5-flash",
        "gemini-2.0-flash",
    ],
    "cerebras": [
        "gpt-oss-120b",
        "qwen-3.8-27b",
        "llama-3.3-70b",
        "llama3.3-70b",
        "llama3.1-70b",
        "llama-3.1-70b",
        "llama3.1-8b",
    ],
    "nvidia": [
        "deepseek-ai/deepseek-v4-pro",
        "deepseek-ai/deepseek-r1",
        "meta/llama-3.3-70b-instruct",
        "nvidia/llama-3.1-nemotron-70b-instruct",
    ],
    "sambanova": [
        "Meta-Llama-3.3-70B-Instruct",
        "Meta-Llama-3.1-70B-Instruct",
        "Meta-Llama-3.1-8B-Instruct",
        "Qwen2.5-72B-Instruct",
    ],
    "openrouter": [
        "qwen/qwen3.8-27b",
        "qwen/qwen-2.5-coder-32b-instruct",
        "meta-llama/llama-3.3-70b-instruct",
        "deepseek/deepseek-chat",
    ]
}

# ── ISE YARAMAZ YEDEK ────────────────────────────────────────────────
# "Boyle bir model yok" (404) ile KARISTIRILMAMALI. Asagidakiler model ADI
# dogru oldugu halde modelin BU HESAPTA ya da BU IS ICIN kullanilamaz
# oldugunu soyler ve tekrar denemekle degismez:
#   * 402 payment_required            -> ucretli; bu hesapta kapali
#   * "tool calling is not supported" -> arac cagirmayan model. ALES'in
#     butun akisi arac cagirir, yani boyle bir model bizim icin issizdir.
#
# Bu kalip YALNIZCA ALES'in kendi koydugu yedekler icin kullanilir
# (bkz. retire_override). Kullanicinin config.json'a KENDI yazdigi modele
# bu yuzden dokunmuyoruz: oradaki 402 bir faturalandirma tercihi olabilir
# ve modeli bizim kaldirmamiz gerekmez.
_SUBSTITUTE_UNUSABLE_PAT = re.compile(
    r"(payment[_ ]required"
    r"|tool[_ ]?call(ing|s)?[^.]{0,40}(not|un)[_ ]?support"
    r"|does not support tool"
    r"|no endpoints found that support tool)", re.I)


def substitute_unusable(error) -> bool:
    """Bir OTOMATIK YEDEGIN kalici olarak ise yaramaz oldugunu soyluyor mu?"""
    return bool(_SUBSTITUTE_UNUSABLE_PAT.search(str(error)))


def _now_iso() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


def _reject_self_url(url: str) -> bool:
    """Kendi sunucumuza bakan bir kesif adresini reddet.

    NEDEN: ALES uvicorn'u 0.0.0.0:<ALES_PORT|8000> uzerinde. Kesif oraya
    yonlendirilirse ALES kendine sorar, kendi cevabini "saglayici yaniti"
    sanar ve o saglayiciyi bozuk isaretler. Sessiz ve teshisi cok zor bir
    ariza; bu yuzden acikca engelliyoruz.
    """
    try:
        port = str(int(os.environ.get("ALES_PORT", "8000") or 8000))
    except Exception:
        port = "8000"
    low = (url or "").lower()
    for host in ("0.0.0.0", "127.0.0.1", "localhost", "[::1]", "::1"):
        if f"//{host}:{port}" in low or f"//{host}/" in low or low.endswith(f"//{host}"):
            return True
    return False


def _nim_override() -> str:
    """Kendi NIM konteynerini calistiranlar icin opsiyonel adres."""
    val = (load_config().get("nim_base_url")
           or os.environ.get("ALES_NIM_BASE_URL") or "").strip()
    if not val:
        return ""
    base = val.rstrip("/")
    if not base.endswith("/models"):
        base = base + "/models"
    return base


# ─── YANIT AYRISTIRMA ────────────────────────────────────────────────
def _parse_models(payload, strip: str = "") -> tuple:
    """Farkli saglayici bicimlerini tek bir kimlik listesine indir.

    Doner: (ids, meta) — meta yalnizca fiyat/baglam bilgisi VEREN
    saglayicilarda (OpenRouter) dolu olur.

    Desteklenen bicimler:
      OpenAI-uyumlu : {"data": [{"id": "..."} , ...]}
      Gemini native : {"models": [{"name": "models/...",
                                   "supportedGenerationMethods": [...]}, ...]}
      Duz liste     : [{"id": ...}, ...]  veya  ["id", ...]
    """
    rows = []
    if isinstance(payload, dict):
        rows = payload.get("data") or payload.get("models") or payload.get("results") or []
    elif isinstance(payload, list):
        rows = payload
    out, meta = [], {}
    for r in rows:
        if isinstance(r, str):
            mid = r
            row = {}
        elif isinstance(r, dict):
            mid = str(r.get("id") or r.get("name") or r.get("model") or "")
            row = r
        else:
            continue
        if strip and mid.startswith(strip):
            mid = mid[len(strip):]
        mid = mid.strip()
        if not mid:
            continue
        # Gemini native: generateContent desteklemeyenler sohbet modeli degil
        # (gomme/sayac modelleri). Bilgi varsa kullanilir; yoksa dokunulmaz.
        gm = row.get("supportedGenerationMethods")
        if isinstance(gm, list) and gm and not any(
                str(x).startswith("generateContent") for x in gm):
            continue
        out.append(mid)
        # OpenRouter fiyat/baglam bilgisi veriyor -> yedek secerken PAHALI
        # modele kendiliginden gecmemek icin kullaniyoruz.
        info = {}
        pr = row.get("pricing")
        if isinstance(pr, dict):
            try:
                info["prompt_usd"] = float(pr.get("prompt") or 0.0)
                info["completion_usd"] = float(pr.get("completion") or 0.0)
            except Exception:
                pass
        for k_src, k_dst in (("context_length", "context"),
                             ("created", "created")):
            if row.get(k_src) is not None:
                try: info[k_dst] = int(row[k_src])
                except Exception: pass
        if info:
            meta[mid] = info
    ids = sorted(set(out))
    return ids, meta


# ─── ANA SINIF ───────────────────────────────────────────────────────
class ModelRegistry:
    """Saglayici model listelerini ceker, onbellekler, dogrular, iyilestirir."""

    def __init__(self, cache_path: Path = None, timeout: float = HTTP_TIMEOUT_S):
        self.cache_path = Path(cache_path or CACHE_FILE)
        self.timeout = float(timeout)
        # provider -> {ids, meta, status, source, fetched_at, error, count}
        self.providers: dict = {}
        # provider -> {model_id: {"since":..., "reason":...}}
        self.blacklist: dict = {}
        # provider -> {dead_model: live_model}  (otomatik duzeltmeler)
        self.overrides: dict = {}
        self.events = deque(maxlen=EVENT_MAX)   # kesfedilen/kaldirilan modeller
        self.log = deque(maxlen=LOG_MAX)        # dogrulama + fallback kararlari
        self.last_refresh: str = ""
        self.last_error: str = ""
        self._lock = asyncio.Lock()
        self._task = None
        self._loaded = False
        self.load_cache()

    # ── kalicilik ────────────────────────────────────────────────────
    def load_cache(self) -> bool:
        """Son bilinen iyi listeyi diskten oku. Yoksa sessizce gec."""
        try:
            target_path = self.cache_path
            if not target_path.exists() and Path("model_cache.json").exists():
                target_path = Path("model_cache.json")
            if not target_path.exists():
                self._note("INFO", "onbellek dosyasi yok — ilk yenilemeye kadar "
                                   "config_manager.DEFAULT_MODELS gecerli")
                return False
            d = json.loads(target_path.read_text(encoding="utf-8"))
        except Exception as e:
            self._note("WARN", f"onbellek okunamadi ({e}) — yok sayiliyor")
            return False
        provs = d.get("providers")
        if isinstance(provs, dict):
            for p, row in provs.items():
                if not isinstance(row, dict):
                    continue
                self.providers[p] = {
                    "ids": list(row.get("ids") or []),
                    "meta": dict(row.get("meta") or {}),
                    "status": row.get("status") or "WARN",
                    # Diskten gelen her sey "cache" kaynaklidir; canli
                    # olmadigini arayuzde ayirt edebilmek onemli.
                    "source": "cache",
                    "fetched_at": row.get("fetched_at") or "",
                    "error": row.get("error") or "",
                    "count": len(row.get("ids") or []),
                }
        if isinstance(d.get("blacklist"), dict):
            # Baslangicta: Kullanici tarafindan acikca kara listeye alinmamis
            # modelleri temizle. Onceki otomatik kara listeye alma tum zinciri kirmisti.
            explicit_bl = {}
            for prov, models in d["blacklist"].items():
                if isinstance(models, dict):
                    kept = {m: info for m, info in models.items()
                            if isinstance(info, dict) and info.get("explicit") is True}
                    if kept:
                        explicit_bl[prov] = kept
            self.blacklist = explicit_bl
            if d.get("blacklist") and not explicit_bl:
                self.save_cache()
        if isinstance(d.get("overrides"), dict):
            self.overrides = {k: dict(v) for k, v in d["overrides"].items()
                              if isinstance(v, dict)}
        for ev in (d.get("events") or [])[-EVENT_MAX:]:
            if isinstance(ev, dict):
                self.events.append(ev)
        self.last_refresh = d.get("last_refresh") or ""
        self._loaded = True
        n = sum(len(v.get("ids") or []) for v in self.providers.values())
        self._note("INFO", f"onbellek yuklendi: {len(self.providers)} saglayici, "
                           f"{n} model (son yenileme: {self.last_refresh or 'bilinmiyor'})")
        return True

    def save_cache(self):
        """Atomik yazim: gecici dosya + replace.

        NEDEN ATOMIK: yenileme 30 dakikada bir kosuyor ve tam o anda kapanan
        bir surec yarim JSON birakabilir; bir sonraki acilis onbellegi
        okuyamayip TUM listeyi kaybederdi.
        """
        data = {
            "version": 1,
            "last_refresh": self.last_refresh,
            "providers": {
                p: {"ids": v.get("ids") or [], "meta": v.get("meta") or {},
                    "status": v.get("status"), "fetched_at": v.get("fetched_at"),
                    "error": v.get("error") or ""}
                for p, v in self.providers.items()
            },
            "blacklist": self.blacklist,
            "overrides": self.overrides,
            "events": list(self.events)[-EVENT_MAX:],
        }
        try:
            self.cache_path.parent.mkdir(parents=True, exist_ok=True)
            tmp = self.cache_path.with_suffix(".json.tmp")
            content = json.dumps(data, ensure_ascii=False, indent=2)
            tmp.write_text(content, encoding="utf-8")
            os.replace(tmp, self.cache_path)
            try:
                Path("model_cache.json").write_text(content, encoding="utf-8")
            except Exception:
                pass
        except Exception as e:
            self._note("WARN", f"onbellek yazilamadi: {e}")

    # ── gunlukleme ───────────────────────────────────────────────────
    def _note(self, level: str, text: str):
        """Her dogrulama/fallback karari buraya yazilir (istenen: 'her
        dogrulama denemesini ve fallback kararini gunlukle')."""
        self.log.append({"time": _now_iso(), "level": level, "text": str(text)[:400]})
        if level in ("WARN", "ERROR"):
            print(f"[REGISTRY] {level}: {text}")

    def _event(self, provider: str, kind: str, model: str, extra: str = ""):
        self.events.append({"time": _now_iso(), "provider": provider,
                            "kind": kind, "model": model, "extra": extra})

    # ── tek saglayici cekimi ─────────────────────────────────────────
    async def _fetch(self, client, provider: str, spec: dict) -> tuple:
        """(ids, meta, error) doner. Basarisizsa ids bos."""
        url = spec["url"]
        if provider == "nvidia":
            ov = _nim_override()
            if ov:
                if _reject_self_url(ov):
                    return [], {}, ("nim_base_url ALES'in kendi portuna işaret "
                                    "ediyor — yok sayıldı")
                url = ov
        if _reject_self_url(url):
            return [], {}, "kesif adresi ALES'in kendi portuna işaret ediyor"

        headers = {"Accept": "application/json",
                   "User-Agent": "ALES-ModelRegistry/1.0"}
        params = {}
        auth = spec.get("auth", "bearer")
        if auth != "none":
            key = get_key(_PROVIDER_KEYNAME.get(provider, ""))
            if not key:
                # Istenen davranis: anahtar yok/gecersiz -> UNAVAILABLE, atla.
                return [], {}, "__NOKEY__"
            if auth == "bearer":
                headers["Authorization"] = f"Bearer {key}"
            else:                       # query (Gemini native)
                params["key"] = key
        if provider == "openrouter":
            # OpenRouter sirala/atif basliklarini istiyor; anahtar GEREKMEZ.
            headers["HTTP-Referer"] = "https://localhost/ales"
            headers["X-Title"] = "ALES"
        try:
            r = await client.get(url, headers=headers, params=params or None,
                                 timeout=self.timeout)
        except Exception as e:
            return [], {}, f"{type(e).__name__}: {e}"
        if r.status_code >= 400:
            body = ""
            try:
                body = r.text[:200]
            except Exception:
                pass
            return [], {}, _scrub(f"HTTP {r.status_code} {body}")
        try:
            payload = r.json()
        except Exception as e:
            return [], {}, f"yanit JSON degil: {e}"
        ids, meta = _parse_models(payload, spec.get("strip", ""))
        return ids, meta, ("liste bos dondu" if not ids else "")

    async def refresh_provider(self, provider: str, client=None) -> dict:
        """Tek saglayiciyi yenile. Sonuc satirini doner (status/ids/error)."""
        spec = _SPECS.get(provider)
        if not spec:
            return {"status": "ERROR", "error": "bilinmeyen saglayici", "ids": []}

        import httpx
        own = client is None
        if own:
            client = httpx.AsyncClient(follow_redirects=True)
        prev = self.providers.get(provider) or {}
        prev_ids = set(prev.get("ids") or [])
        try:
            ids, meta, err = await self._fetch(client, provider, spec)
            # Birincil bos dondu -> alternatif uc (Gemini).
            if not ids and err != "__NOKEY__" and spec.get("alt"):
                self._note("INFO", f"{provider}: birincil uc basarisiz ({err}) "
                                   f"-> alternatif uc deneniyor")
                ids, meta, err2 = await self._fetch(client, provider, spec["alt"])
                if ids:
                    err = ""
                else:
                    err = f"{err} | alt: {err2}"
        finally:
            if own:
                try: await client.aclose()
                except Exception: pass

        row = {"ids": ids, "meta": meta, "fetched_at": _now_iso(),
               "error": "", "source": "live", "status": "OK",
               "count": len(ids)}

        if err == "__NOKEY__":
            # Anahtar yok: onbellekteki liste DURUR (silmiyoruz), durum
            # UNAVAILABLE. Silmek, anahtar geri girildiginde 30 dakika boyunca
            # dogrulamasiz kalmak demekti.
            row.update(ids=list(prev_ids), meta=prev.get("meta") or {},
                       status="UNAVAILABLE", source=prev.get("source") or "cache",
                       fetched_at=prev.get("fetched_at") or "",
                       error="anahtar yok veya boş", count=len(prev_ids))
            self._note("INFO", f"{provider}: anahtar yok — atlandi (UNAVAILABLE)")
        elif not ids:
            # Istenen davranis: zaman asimi/hata -> ONBELLEKTEKI listeyi kullan
            # ve UYAR. Onbellek de yoksa statik yedek, o da yoksa bos.
            static = _STATIC_FALLBACK.get(provider) or []
            if prev_ids:
                row.update(ids=sorted(prev_ids), meta=prev.get("meta") or {},
                           status="WARN", source="cache",
                           fetched_at=prev.get("fetched_at") or "",
                           error=err, count=len(prev_ids))
                self._note("WARN", f"{provider}: canli liste alinamadi ({err}) "
                                   f"— onbellek kullaniliyor ({len(prev_ids)} model)")
            elif static:
                row.update(ids=list(static), status="WARN", source="static",
                           error=err, count=len(static))
                self._note("WARN", f"{provider}: genel model listesi ucu yok/erisilemedi "
                                   f"({err}) — STATIK yedek liste kullaniliyor. "
                                   f"Dogrulama bu saglayici icin devre disi.")
            else:
                row.update(status="ERROR", source="none", error=err, count=0)
                self._note("ERROR", f"{provider}: liste alinamadi ve onbellek yok ({err}) "
                                    f"— config_manager.DEFAULT_MODELS gecerli kalir")
        else:
            # Basarili: yeni/kaldirilan modelleri gunlukle.
            new = sorted(set(ids) - prev_ids)
            gone = sorted(prev_ids - set(ids))
            if prev_ids:            # ilk cekimde 300 model "yeni" gorunmesin
                for m in new[:40]:
                    self._event(provider, "added", m)
                for m in gone[:40]:
                    self._event(provider, "removed", m)
                if new or gone:
                    self._note("INFO", f"{provider}: +{len(new)} yeni / "
                                       f"-{len(gone)} kaldirilan model")
            else:
                self._note("INFO", f"{provider}: ilk liste alindi ({len(ids)} model)")
            # Kara listedeki bir model geri gelmisse kara listeden CIKAR:
            # saglayici modeli geri actiysa onu sonsuza dek yasaklamak yanlis.
            bl = self.blacklist.get(provider) or {}
            revived = [m for m in list(bl) if m in ids]
            for m in revived:
                bl.pop(m, None)
                self._event(provider, "revived", m, "kara listeden cikarildi")
                self._note("INFO", f"{provider}/{m}: listeye geri dondu — "
                                   f"kara listeden cikarildi")
            if revived and not bl:
                self.blacklist.pop(provider, None)

        self.providers[provider] = row
        return row

    async def refresh_all_providers(self, force: bool = False) -> dict:
        """TUM saglayicilari es zamanli yenile. Toplam sure ~timeout kadardir.

        `_lock`: 30 dakikalik zamanlayici ile arayuzdeki YENILE dugmesi ayni
        ana denk gelebilir. Kilit olmasa iki tur ayni onbellek dosyasina
        yazip birbirini ezerdi.
        """
        if self._lock.locked() and not force:
            self._note("INFO", "yenileme zaten suruyor — atlandi")
            return self.status()
        async with self._lock:
            import httpx
            t0 = time.time()
            self.last_error = ""
            async with httpx.AsyncClient(follow_redirects=True) as client:
                res = await asyncio.gather(
                    *[self.refresh_provider(p, client) for p in _SPECS],
                    return_exceptions=True)
            for p, r in zip(list(_SPECS), res):
                if isinstance(r, BaseException):
                    self.providers[p] = {
                        "ids": (self.providers.get(p, {}).get("ids") or []),
                        "meta": {}, "status": "ERROR", "source": "cache",
                        "fetched_at": "", "error": _scrub(repr(r)),
                        "count": len(self.providers.get(p, {}).get("ids") or []),
                    }
                    self._note("ERROR", f"{p}: yenileme istisnasi — {r!r}")
            self.last_refresh = _now_iso()
            # Yapilandirmadaki kimlikleri yeni listeye karsi dogrula.
            self.validate_configured()
            self.save_cache()
            ok = sum(1 for v in self.providers.values() if v.get("status") == "OK")
            self._note("INFO", f"yenileme bitti: {ok}/{len(_SPECS)} saglayici OK "
                               f"({time.time()-t0:.1f}s)")
        return self.status()

    # ── dogrulama ────────────────────────────────────────────────────
    def validate_configured(self) -> list:
        """config'deki her katmanin kimligi saglayicinin listesinde mi?

        Sonuc SADECE raporlanir; hicbir katman burada kapatilmaz (bkz. dosya
        basindaki 'VERI YOKSA ENGELLEME' karari).
        """
        try:
            from config_manager import get_models
            models = get_models()
        except Exception as e:
            self._note("WARN", f"yapilandirma okunamadi: {e}")
            return []
        out = []
        for layer, m in models.items():
            prov, mid = m.get("provider", ""), m.get("model", "")
            state = self.check(prov, mid)
            out.append({"layer": layer, **state})
            if state["known"] is False:
                self._note("WARN",
                           f"{layer} ({prov}/{mid}): saglayicinin listesinde YOK. "
                           f"Oneriler: {', '.join(state['suggestions'][:3]) or 'yok'}. "
                           f"Cagri YINE denenecek (liste eksik olabilir).")
            elif state["known"] is None:
                self._note("INFO", f"{layer} ({prov}/{mid}): liste yok, "
                                   f"dogrulama atlandi")
        return out

    def check(self, provider: str, model: str) -> dict:
        """Tek bir (saglayici, model) icin durum. `known`:
             True  = listede var
             False = liste VAR ama model icinde yok
             None  = liste alinamadi -> hukum yok (cagri engellenmez)
        """
        row = self.providers.get(provider) or {}
        ids = row.get("ids") or []
        source = row.get("source") or "none"
        eff = self.effective_model(provider, model)
        # Statik yedek listeye karsi dogrulama YAPILMAZ: o liste saglayicinin
        # gercegi degil, bizim yedek notumuz. Yanlis alarm uretirdi.
        if not ids or source in ("static", "none"):
            known = None
        else:
            known = eff in ids
        return {
            "provider": provider, "model": model,
            "effective_model": eff,
            "overridden": eff != model,
            "known": known,
            "blacklisted": self.is_blacklisted(provider, eff),
            "list_source": source,
            "list_count": len(ids),
            "suggestions": ([] if known is not False
                            else self.suggest(provider, eff)),
        }

    def ids_for(self, provider: str) -> list:
        return list((self.providers.get(provider) or {}).get("ids") or [])

    # ── kara liste + otomatik duzeltme ───────────────────────────────
    def is_blacklisted(self, provider: str, model: str) -> bool:
        return model in (self.blacklist.get(provider) or {})

    def add_blacklist(self, provider: str, model: str, reason: str = ""):
        """KALICI olarak kaldirilmis modeli isaretle — bir daha denenmez.

        Buraya YALNIZCA gercek bir cagrinin 'boyle bir model yok' demesiyle
        girilir (bkz. dosya basi). Liste eksikligi buraya yazmaz.
        """
        self.blacklist.setdefault(provider, {})[model] = {
            "since": _now_iso(), "reason": str(reason)[:300]}
        self._event(provider, "blacklisted", model, str(reason)[:120])
        self._note("WARN", f"{provider}/{model} kara listeye alindi: {reason}")
        self.save_cache()

    def clear_blacklist(self, provider: str = None, model: str = None) -> int:
        """Arayuzden geri alma. Kacis kapisi olmayan bir kara liste, yanlis
        bir kayit olustugunda modeli kalici olarak kaybettirirdi."""
        n = 0
        if provider and model:
            if (self.blacklist.get(provider) or {}).pop(model, None) is not None:
                n = 1
            if provider in self.blacklist and not self.blacklist[provider]:
                self.blacklist.pop(provider, None)
        elif provider:
            n = len(self.blacklist.pop(provider, {}) or {})
        else:
            n = sum(len(v) for v in self.blacklist.values())
            self.blacklist = {}
        self._note("INFO", f"kara liste temizlendi ({n} kayit)")
        self.save_cache()
        return n

    def effective_model(self, provider: str, model: str) -> str:
        """Otomatik duzeltme uygulanmis GERCEK model kimligi.

        config.json'a dokunmadigimiz icin, duzeltilmis kimlik burada
        cozumlenir. Zincir/arayuz hep bu fonksiyondan gecer.
        """
        return (self.overrides.get(provider) or {}).get(model) or model

    def set_override(self, provider: str, dead: str, live: str, reason: str = ""):
        self.overrides.setdefault(provider, {})[dead] = live
        self._event(provider, "substituted", live, f"{dead} yerine")
        self._note("WARN", f"{provider}: {dead} -> {live} (otomatik degisim). "
                           f"Sebep: {reason}. config.json DEGISMEDI; "
                           f"geri almak icin Ayarlar > Model Kesfi > SIFIRLA.")
        self.save_cache()

    def clear_overrides(self, provider: str = None) -> int:
        n = (len(self.overrides.pop(provider, {}) or {}) if provider
             else sum(len(v) for v in self.overrides.values()))
        if not provider:
            self.overrides = {}
        if n:
            self._note("INFO", f"otomatik model degisimleri sifirlandi ({n})")
            self.save_cache()
        return n

    # ── yedek model secimi ───────────────────────────────────────────
    def retire_override(self, provider: str, dead: str, reason: str = "") -> str:
        """ALES'in KENDI koydugu yedegi geri al ve o yedegi kara listeye at.

        NEDEN GEREKLI — olculmus bir ariza: set_override bir kez yazildiktan
        sonra hicbir kod yolunda yeniden gozden gecirilmiyordu. 2026-08-26'da
        cerebras/llama-3.3-70b 404 verdi ve yerine gemma-4-31b konuldu;
        gemma-4-31b ise her cagrida 402 "payment required" donuyor. Ayni gun
        groq/llama-3.3-70b-versatile -> allam-2-7b konuldu; o da arac cagirmayi
        desteklemiyor. performance modunun zinciri yalnizca ["fast","fallback"]
        oldugu icin IKI katmanin ikisi de olu yedege bagliydi: sohbet KALICI
        olarak calismaz hale geldi ve geri alacak bir mekanizma YOKTU.

        Yedegi kara listeye ALIYORUZ: suggest() kara listeyi suzdugu icin bir
        sonraki pick_alternative ayni ise yaramaz adayi tekrar secemez. Aksi
        halde geri al -> ayni adayi sec -> yine basarisiz dongusune girerdik.

        Doner: geri alinan yedegin adi, yoksa "".
        """
        cur = (self.overrides.get(provider) or {}).get(dead)
        if not cur:
            return ""
        self.overrides[provider].pop(dead, None)
        if not self.overrides[provider]:
            self.overrides.pop(provider, None)
        self.add_blacklist(provider, cur,
                           f"yedek ise yaramadi: {str(reason)[:150]}")
        self._event(provider, "override_retired", cur, f"{dead} icin")
        self._note("WARN", f"{provider}: {dead} -> {cur} otomatik degisimi GERI "
                           f"ALINDI. Sebep: {str(reason)[:150]}. {cur} kara "
                           f"listede; yeni bir yedek aranacak.")
        self.save_cache()
        return cur

    async def heal_substitute(self, provider: str, configured: str,
                              error: str = "") -> str:
        """Ise yaramaz bir OTOMATIK YEDEGI yenisiyle degistir.

        SIRA ONEMLI: once yedegi geri al + kara listeye at, SONRA taze listeden
        yeni aday sec. Ters sirada suggest() hala eski yedegi havuzda gorur ve
        ayni adayi geri verir — sonsuz dongu.

        Doner: yeni yedek adi, yoksa "" (o zaman katman duser ve zincir bir
        sonrakine gecer; uydurma bir model adiyla devam ETMIYORUZ).
        """
        retired = self.retire_override(provider, configured, error)
        if not retired:
            return ""
        try:
            await self.refresh_provider(provider)
        except Exception as e:
            # Liste cekilemese de geri alma GECERLI kalir: ise yaramaz yedekle
            # devam etmek her durumda daha kotu.
            self._note("ERROR", f"{provider}: yeni yedek icin liste "
                                f"cekilemedi: {e}")
        alt = self.pick_alternative(provider, configured)
        if not alt or alt == retired:
            self._note("WARN", f"{provider}/{configured}: kullanilabilir bir "
                               f"yedek KALMADI — Ayarlar > Modeller'den elle "
                               f"secim gerekiyor.")
            return ""
        self.set_override(provider, configured, alt,
                          f"onceki yedek ({retired}) ise yaramadi")
        return alt

    def suggest(self, provider: str, model: str, limit: int = 6) -> list:
        """Olen kimlik icin yakin adaylar (en olasi once).

        Sira: ayni satici oneki -> ad benzerligi -> sohbet-disi olanlari at
        -> onizleme/deneysel olanlari geri it -> ucuzu tercih et.
        """
        ids = self.ids_for(provider)
        if not ids:
            return []
        import difflib
        bl = self.blacklist.get(provider) or {}
        pool = [i for i in ids if i not in bl and not _NOT_CHAT.search(i)]
        if not pool:
            return []
        vendor = model.split("/")[0] + "/" if "/" in model else ""
        same_vendor = [i for i in pool if vendor and i.startswith(vendor)]
        base = same_vendor or pool
        # Ad govdesi: "qwen/qwen-2.5-coder-32b-instruct" -> "qwen-coder"
        stem = re.sub(r"[^a-z]+", " ", model.split("/")[-1].lower()).split()
        stem = [w for w in stem if len(w) > 2 and w not in
                ("instruct", "chat", "latest", "preview", "free", "it")]
        scored = []
        meta = (self.providers.get(provider) or {}).get("meta") or {}
        for i in base:
            low = i.lower()
            s = difflib.SequenceMatcher(None, model.lower(), low).ratio()
            # Ayni aile kelimeleri agir tartilir: surum numarasi degisse bile
            # "qwen" + "coder" tutuyorsa dogru aileyiz.
            s += 0.25 * sum(1 for w in stem if w in low) / max(1, len(stem))
            if _RISKY.search(low):
                s -= 0.30
            price = (meta.get(i) or {}).get("completion_usd")
            if isinstance(price, (int, float)):
                if price == 0:
                    s += 0.12                     # bedava/dahil olan surum
                elif price > 0.00002:             # ~20 USD / 1M token uzeri
                    s -= 0.20
            scored.append((s, i))
        scored.sort(key=lambda x: (-x[0], x[1]))
        return [i for _, i in scored[:limit]]

    def pick_alternative(self, provider: str, model: str) -> str:
        """Otomatik degisim icin TEK aday. SOTA saglayici onceliklerine gore en iyi alternatifi secer."""
        prov = (provider or "").lower().strip()
        live_ids = self.ids_for(prov)
        bl = self.blacklist.get(prov) or {}
        pref_list = _PROVIDER_PREFERRED_DEFAULTS.get(prov, [])

        # 1. Once saglayicinin canli IDs icindeki oncelikli modelleri kontrol et (orn: Groq -> openai/gpt-oss-120b, Gemini -> gemini-3.8-flash)
        if live_ids:
            for pref in pref_list:
                if pref in live_ids and pref not in bl and pref != model:
                    return pref

        # 2. String benzerligi ile arama yap (ozel isimli veya ayni aileden modeller icin)
        cands = self.suggest(prov, model, limit=4)
        if cands:
            filtered_cands = [c for c in cands if not _NOT_PREFERRED_CHAT.search(c) and c != model]
            if filtered_cands:
                return filtered_cands[0]
            if cands[0] != model:
                return cands[0]

        # 3. Canli listeden genel sohbet modeli sec
        if live_ids:
            for m_id in live_ids:
                if (m_id not in bl and m_id != model and
                        not _NOT_CHAT.search(m_id) and not _NOT_PREFERRED_CHAT.search(m_id)):
                    return m_id

        # 4. Canli liste yoksa oncelikli varsayilanlardan ilkini don
        for pref in pref_list:
            if pref not in bl and pref != model:
                return pref

        return ""

    async def heal(self, provider: str, model: str, error: str = "") -> str:
        """Istenen 'kendi kendini iyilestirme': model adi gecersizse veya 404 verdiyse
        saglayicinin listesini TAZE cek, en iyi alternatif modeli bul, kara listeye al,
        override kaydet ve yeni adi dondur."""
        prov = (provider or "").lower().strip()
        self._note("WARN", f"{prov}/{model}: gecersiz model/404 hatasi — "
                           f"liste tazeleniyor. Hata: {str(error)[:160]}")
        try:
            await self.refresh_provider(prov)
        except Exception as e:
            self._note("ERROR", f"{prov}: iyilestirme icin liste cekilemedi: {e}")

        alt = self.pick_alternative(prov, model)
        if not alt or alt == model:
            return ""

        self.add_blacklist(prov, model, f"saglayici reddetti/404: {str(error)[:120]}")
        self.set_override(prov, model, alt, "gecersiz model / 404 auto-heal")
        self.save_cache()

        # config_manager'daki config.json'u dinamik guncelle
        try:
            import config_manager
            cfg = config_manager.load_config()
            models_cfg = cfg.setdefault("models", {})
            for layer_name, ldata in models_cfg.items():
                if isinstance(ldata, dict) and ldata.get("provider") == prov and ldata.get("model") == model:
                    ldata["model"] = alt
            config_manager.save_config(cfg)
        except Exception as ex:
            print(f"[REGISTRY] config.json guncelleme hatasi: {ex}")

        msg = f"⚠️ Model {model} removed. Auto-switched to Model {alt}."
        print(f"[ROUTER] {msg}")
        try:
            from config_manager import append_action_log
            append_action_log("auto_heal", f"{prov}: {msg}")
        except Exception:
            pass

        return alt

    # ── zamanlayici ──────────────────────────────────────────────────
    async def scheduler(self, interval_s: float = REFRESH_INTERVAL_S,
                        first_delay_s: float = 1.0):
        """30 dakikada bir yenile. ANA DONGUYU BLOKLAMAZ: tamami async,
        httpx.AsyncClient kullanir ve tek gorev icinde uyur.

        Acilista 1 saniye bekler ve canli modelleri hemen cekip dogrular.
        """
        try:
            await asyncio.sleep(max(0.0, first_delay_s))
            while True:
                try:
                    await self.refresh_all_providers()
                    try:
                        import auto_model_discovery
                        if auto_model_discovery is not None:
                            auto_model_discovery._reconcile()
                    except Exception:
                        pass
                except asyncio.CancelledError:
                    raise
                except Exception as e:
                    # Zamanlayici ASLA olmemeli: bir tur patlarsa sonrakini bekle.
                    self.last_error = f"{type(e).__name__}: {e}"
                    self._note("ERROR", f"yenileme turu basarisiz: {e}")
                await asyncio.sleep(interval_s)
        except asyncio.CancelledError:
            self._note("INFO", "zamanlayici durduruldu")
            raise

    # ── arayuz verisi ────────────────────────────────────────────────
    def status(self) -> dict:
        """Ayarlar > Gelismis > MODEL KESFI panelinin tek veri kaynagi."""
        try:
            from config_manager import get_models
            configured = get_models()
        except Exception:
            configured = dict(DEFAULT_MODELS)
        rows = []
        for p, spec in _SPECS.items():
            v = self.providers.get(p) or {}
            used_by = sorted(l for l, m in configured.items()
                             if m.get("provider") == p)
            rows.append({
                "provider": p,
                "label": spec["label"],
                "status": v.get("status") or "WARN",
                "count": int(v.get("count") or len(v.get("ids") or [])),
                "source": v.get("source") or "none",
                "fetched_at": v.get("fetched_at") or "",
                "error": v.get("error") or "",
                "has_key": (spec.get("auth") == "none"
                            or bool(get_key(_PROVIDER_KEYNAME.get(p, "")))),
                "auth_required": spec.get("auth") != "none",
                "used_by": used_by,
                "blacklisted": sorted((self.blacklist.get(p) or {})),
                "overrides": dict(self.overrides.get(p) or {}),
            })
        layers = []
        for layer, m in configured.items():
            st = self.check(m.get("provider", ""), m.get("model", ""))
            layers.append({"layer": layer, **st})
        return {
            "available": True,
            "last_refresh": self.last_refresh,
            "interval_s": REFRESH_INTERVAL_S,
            "timeout_s": self.timeout,
            "cache_file": str(self.cache_path),
            "running": bool(self._task and not self._task.done()),
            "providers": rows,
            "layers": layers,
            "events": list(self.events)[-40:][::-1],
            "log": list(self.log)[-60:][::-1],
            "totals": {
                "models": sum(int(r["count"]) for r in rows),
                "ok": sum(1 for r in rows if r["status"] == "OK"),
                "warn": sum(1 for r in rows if r["status"] == "WARN"),
                "error": sum(1 for r in rows if r["status"] == "ERROR"),
                "unavailable": sum(1 for r in rows if r["status"] == "UNAVAILABLE"),
                "blacklisted": sum(len(v) for v in self.blacklist.values()),
                "overrides": sum(len(v) for v in self.overrides.values()),
                # Kac katman "listede yok" durumunda. Arayuzde en tepede
                # gosterilir; kullanicinin bakmasi gereken tek sayi bu.
                "stale_layers": sum(1 for l in layers if l["known"] is False),
            },
            "note": ("Liste alınamadığında model KAPATILMAZ — sadece uyarı verilir. "
                     "Bir model yalnızca gerçek bir çağrı 'böyle bir model yok' "
                     "dediğinde kara listeye alınıp otomatik değiştirilir."),
        }


def _scrub(text) -> str:
    """Hata metinlerinden anahtarlari temizle.

    GUVENLIK: bu metinler /model-discovery ile arayuze gidiyor ve sunucu
    0.0.0.0'a bagli. Bazi saglayicilar 401 govdesinde anahtari geri
    yansitiyor; ham govdeyi oldugu gibi gostermek sizinti olurdu.
    """
    out = str(text)
    for kname in set(_PROVIDER_KEYNAME.values()):
        try:
            v = get_key(kname)
        except Exception:
            continue
        if v and len(v) >= 8:
            out = out.replace(v, "***")
    return out


# ─── MODUL DUZEYI TEKIL ORNEK ────────────────────────────────────────
# model_router ve main.py bunu paylasir (iki ayri onbellek/kara liste olmasin).
registry = ModelRegistry()


async def refresh_all_providers(force: bool = False) -> dict:
    return await registry.refresh_all_providers(force=force)


def status() -> dict:
    return registry.status()


def start_scheduler(interval_s: float = REFRESH_INTERVAL_S):
    """main.py acilista cagirir. Gorev nesnesini doner (iptal edilebilir)."""
    if registry._task and not registry._task.done():
        return registry._task
    registry._task = asyncio.create_task(registry.scheduler(interval_s))
    return registry._task
