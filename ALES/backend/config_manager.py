"""
Kalici config ve memory yonetimi.
Dosyalar AppData'da saklanir — uygulama silinse bile kalmaya devam eder.
"""
import os, json
from pathlib import Path
from datetime import datetime

def get_appdata_dir() -> Path:
    """Windows AppData/Roaming/ALES klasoru"""
    base = os.environ.get('APPDATA') or os.path.expanduser('~')
    d = Path(base) / 'ALES'
    d.mkdir(parents=True, exist_ok=True)
    return d

APPDATA = get_appdata_dir()
CONFIG_FILE = APPDATA / 'config.json'


# ═══════════════════════════════════════════════════════════════════════
# .env YUKLEYICI
# ═══════════════════════════════════════════════════════════════════════
# NEDEN VAR (2026-09-05): get_key() config.json'da deger bulamazsa ortam
# degiskenine dusuyor ve docstring'i "key'ler .env'de tutulabilir" diyor.
# Ama .env dosyasini OKUYAN HICBIR SEY YOKTU: python-dotenv requirements'ta
# duruyordu, load_dotenv() ise hicbir yerde cagrilmiyordu. Sonucu sessiz ve
# kotu olurdu -- anahtarlar config.json'dan .env'e tasindiginda ALES butun
# saglayicilari "anahtar yok" sanip zincirin tamamini kapatirdi ve sebep
# hicbir yerde yazmazdi. Bu fonksiyon o bosluğu kapatiyor.
#
# UC KARAR VE GEREKCELERI:
#  (1) MEVCUT ORTAM DEGISKENI EZILMEZ. Kullanici bir oturumda bilincli
#      olarak "set GROQ_API_KEY=..." dediyse, diskteki eski bir .env onu
#      geri almamalidir. Yani .env yalnizca BOS olani doldurur.
#  (2) DORT YERE BAKILIR ve ilk bulunan kazanir: exe'nin yani (paketli
#      surumde .env oraya konur), proje koku, backend/, calisma klasoru.
#      __file__ tabanli yollar oncelikli cunku calisma klasoru servis
#      olarak baslatildiginda C:\Windows\System32 olabiliyor.
#  (3) TAM FAIL-OPEN: dosya yok, okunamiyor, bozuk satir var ya da
#      python-dotenv kurulu degil -> sessizce hicbir sey yapilmaz. Bir
#      yapilandirma dosyasinin yokluğu uygulamayi baslatmamaya sebep degil.
#
# GUVENLIK: hicbir DEGER yazdirilmaz. Sadece kac anahtarin yuklendigi ve
# hangi dosyadan geldigi soylenir -- anahtarin kendisi asla gunluge girmez.
_ENV_LOADED_FROM = None
_ENV_LOADED_COUNT = 0


def _env_candidates():
    """Aranacak .env yollari, oncelik sirasiyla."""
    import sys
    here = Path(__file__).resolve().parent          # .../ALES/backend
    root = here.parent                              # .../ALES
    out = []
    # Paketli surum (ALES.exe): .env exe'nin YANINDA durur. sys._MEIPASS
    # gecici klasordur ve her kapanista silinir -> oraya bakmak anlamsiz.
    if getattr(sys, "frozen", False):
        out.append(Path(sys.executable).resolve().parent / ".env")
    out += [root / ".env", here / ".env", Path.cwd() / ".env"]
    seen, uniq = set(), []
    for p in out:
        s = str(p)
        if s not in seen:
            seen.add(s)
            uniq.append(p)
    return uniq


def _parse_env_text(text: str) -> dict:
    """Kucuk .env cozumleyici (python-dotenv yoksa yedek).

    Destekler: KEY=VALUE, 'export KEY=VALUE', # yorum, tirnakli deger.
    Desteklemez: cok satirli deger, ${DEGISKEN} genislemesi. Anahtar
    saklamak icin bu kadari yeter; daha fazlasi gerekirse python-dotenv
    zaten kurulu ve once o denenir.
    """
    out = {}
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        if line.startswith("export "):
            line = line[7:].lstrip()
        k, _, v = line.partition("=")
        k = k.strip()
        if not k:
            continue
        v = v.strip()
        # Yorumu at (yalnizca tirnaksiz degerde; tirnak icinde # gecerlidir)
        if v[:1] in ("'", '"'):
            q = v[0]
            end = v.find(q, 1)
            v = v[1:end] if end > 0 else v[1:]
        elif " #" in v:
            v = v.split(" #", 1)[0].strip()
        out[k] = v
    return out


def load_env_file() -> dict:
    """.env dosyasini ortama yukler. Zaten dolu olan degiskene DOKUNMAZ.

    Doner: {"loaded": bool, "path": str|None, "count": int} -- UI/gunluk
    icin. Deger DONDURMEZ, sadece sayar.
    """
    global _ENV_LOADED_FROM, _ENV_LOADED_COUNT
    for path in _env_candidates():
        try:
            if not path.is_file():
                continue
        except Exception:
            continue
        pairs = {}
        try:
            # python-dotenv varsa onu tercih et (kacis dizileri, cok satirli
            # deger gibi ayrik durumlari bizim cozumleyiciden iyi ele alir).
            from dotenv import dotenv_values
            pairs = {k: v for k, v in dotenv_values(str(path)).items()
                     if k and v is not None}
        except Exception:
            try:
                pairs = _parse_env_text(path.read_text(encoding="utf-8-sig"))
            except Exception:
                continue
        n = 0
        for k, v in pairs.items():
            # KARAR (1): mevcut degeri EZMEYIZ.
            if not (os.environ.get(k) or "").strip():
                os.environ[k] = v
                n += 1
        _ENV_LOADED_FROM, _ENV_LOADED_COUNT = str(path), n
        # Yalnizca SAYI ve YOL -- anahtarin kendisi asla basilmaz.
        print(f"[config] .env yuklendi: {path} ({n} degisken)")
        return {"loaded": True, "path": str(path), "count": n}
    return {"loaded": False, "path": None, "count": 0}


def env_file_status() -> dict:
    """UI/teshis icin: .env okundu mu, nereden, kac degisken.

    ANAHTAR ISIMLERI dahi listelenmez -- yalnizca sayi. "hangi saglayicinin
    anahtari cozulebiliyor" bilgisini main.py'deki /env-status ucu ekler
    (yine yalnizca var/yok olarak); maskeli onizleme /credentials/audit'te.
    """
    return {"loaded": _ENV_LOADED_FROM is not None,
            "path": _ENV_LOADED_FROM,
            "count": _ENV_LOADED_COUNT,
            "searched": [str(p) for p in _env_candidates()]}


# Import aninda bir kez cagrilir: config_manager'i import eden HER modul
# (model_router, main, multi_agent ...) get_key() cagirmadan once .env'in
# yuklenmis olmasini bekler. Fonksiyonun kendisi tamamen fail-open.
try:
    load_env_file()
except Exception as _e:
    print(f"[config] .env yuklenemedi, atlandi: {_e}")

MEMORY_FILE = APPDATA / 'memory.json'
LONG_MEMORY_FILE = APPDATA / 'long_memory.json'
PERSONA_FILE = APPDATA / 'persona.json'
SCHEDULES_FILE = APPDATA / 'schedules.json'
NOTIF_FILE = APPDATA / 'notifications.json'
ACTION_LOG_FILE = APPDATA / 'action_log.json'
ACTION_LOG_MAX = 200  # eski kayitlar otomatik atilir, dosya sismesin

def load_action_log() -> list:
    if ACTION_LOG_FILE.exists():
        try: return json.loads(ACTION_LOG_FILE.read_text(encoding='utf-8'))
        except: pass
    return []

def append_action_log(text: str):
    log = load_action_log()
    log.append({"time": datetime.now().isoformat(), "text": text})
    if len(log) > ACTION_LOG_MAX:
        log = log[-ACTION_LOG_MAX:]
    ACTION_LOG_FILE.write_text(json.dumps(log, ensure_ascii=False, indent=2), encoding='utf-8')

def load_config() -> dict:
    # Once AppData'ya bak, sonra local'e
    for f in [CONFIG_FILE, Path('config.json')]:
        if f.exists():
            try: return json.loads(f.read_text(encoding='utf-8'))
            except: pass
    return {'groq_key': '', 'cerebras_key': '', 'gemini_key': '', 'sambanova_key': '', 'openrouter_key': '', 'nvidia_key': ''}

def save_config(cfg: dict):
    CONFIG_FILE.write_text(json.dumps(cfg, ensure_ascii=False, indent=2), encoding='utf-8')
    # Local kopyada da tut (backend icin)
    try: Path('config.json').write_text(json.dumps(cfg, ensure_ascii=False, indent=2), encoding='utf-8')
    except: pass
    try:
        import versioned_config
        versioned_config.record_version("config", cfg, reason="save_config cagrisi")
    except Exception:
        pass

def load_memory() -> dict:
    for f in [MEMORY_FILE, Path('memory.json')]:
        if f.exists():
            try: return json.loads(f.read_text(encoding='utf-8'))
            except: pass
    return {'short': [], 'fiverr_tasks': [], 'pending_approvals': []}

def save_memory(mem: dict):
    MEMORY_FILE.write_text(json.dumps(mem, ensure_ascii=False, indent=2), encoding='utf-8')
    try: Path('memory.json').write_text(json.dumps(mem, ensure_ascii=False, indent=2), encoding='utf-8')
    except: pass

print(f"[CONFIG] AppData klasoru: {APPDATA}")

# ═══════════════════════════════════════════════════════════════════
# MODE / MODEL / TIMEOUT SISTEMI (Faz 1 — model_router.py bunlari okur)
# ═══════════════════════════════════════════════════════════════════
# Katman -> (saglayici, model kimligi). Hepsi config.json'daki "models"
# ile override edilebilir.
#
# ONEMLI — BU LISTEYI TAHMINLE DEGISTIRME. Saglayicilar model adlarini
# haber vermeden kaldiriyor; eski ad geriye 400/404 donduruyor ve zincir
# "hicbir katman yanit vermedi" diyor. Dogru is akisi:
#     GET /test-models
# Her katmani gercekten dener, olu model kimligini soyler ve saglayicinin
# KENDI listesinden yakin adlari onerir. Oradaki adi buraya (veya
# config.json > models > <katman> > model alanina) yaz.
#
# 2026-08-26 durumu:
#   code   ESKIDEN qwen/qwen-2.5-coder-32b-instruct -> OpenRouter
#          katalogunda ARTIK YOK (dogrulandi: openrouter.ai/api/v1/models).
#          Yerine ayni saticinin guncel orta boy modeli konuldu. Koda ozel
#          alternatifler de katalogda mevcut: kwaipilot/kat-coder-pro-v2.5,
#          bytedance-seed/seed-2.0-code.
#   heavy  moonshotai/kimi-k3 katalogda VAR, dogrulandi -- degistirilmedi.
#   fast / fallback / vision / unrestricted: saglayici dokumanlarina
#          erisilemedigi icin DOGRULANAMADI, bu yuzden DOKUNULMADI.
#          Calisip calismadigini /test-models soyler.
DEFAULT_MODELS = {
    "fast":         {"provider": "cerebras",   "model": "gpt-oss-120b"},
    "fallback":     {"provider": "groq",       "model": "openai/gpt-oss-120b"},
    "vision":       {"provider": "gemini",     "model": "gemini-3.8-flash"},
    "code":         {"provider": "openrouter", "model": "qwen/qwen3.8-27b"},
    "unrestricted": {"provider": "nvidia",     "model": "deepseek-ai/deepseek-v4-pro"},
    "heavy":        {"provider": "openrouter", "model": "moonshotai/kimi-k3"},
}

# ─── HEAVY-ONLY KATMAN KAPISI ──────────────────────────────────────────
# Kimi K3 (heavy katmani) SADECE bunu acikca isteyen modlarda kullanilir.
# NEDEN: heavy katmani en pahali ve en yavas yol (heavy_s = 60s). Zincire
# sessizce girerse "Gorev" modunda basit bir soru 60 saniye bekleyebilir ve
# kullanici neden yavasladigini goremez. Bu yuzden zincirde "heavy" yazsa
# bile mod heavy_ok=True demiyorsa katman ZINCIRDEN DUSURULUR.
#
# Mod bazli izin: DEFAULT_MODES[mode]["heavy_ok"]. Tanimli degilse False.
# config.json['modes'][mode]['heavy_ok'] = true ile kullanici acabilir.
HEAVY_ONLY_LAYERS = frozenset({"heavy"})

# ─── KATMAN ZAMAN ASIMLARI (saniye) ────────────────────────────────────
# KRITIK — 2026-08-26'da DUZELTILDI. Eski degerler fast_s=1.5 / fallback_s=3.0
# idi ve zincirin HER ZAMAN duşmesine sebep oluyordu ("Ana model zinciri
# erisilemedi, OpenRouter ile yanit verildi" hatasi).
#
# NEDEN eski degerler calismazdi: model_router.stream_chat bu sureyi
#     asyncio.wait_for(client.chat.completions.create(..., stream=True))
# etrafina sariyor. stream=True oldugu icin bu await, TOKEN URETIMINI degil
# AKISIN ACILMASINI bekler -- ama akisin acilmasi su islerin TAMAMINI icerir:
#     DNS + TCP + TLS el sikismasi + ISTEGIN TAMAMININ YUKLENMESI
#     + saglayicinin istem-isleme (prefill) suresi ilk SSE baytina kadar
# Istek govdesi kucuk degil: BASE_SYSTEM + LUBV + uzun donem hafiza + profil
# + son baglam + ~35 aracin JSON semasi (Turkce aciklamalar Turkce
# karakterler yuzunden token basina daha az karakter tasir, yani sema
# maliyeti sanildigindan buyuk). Soguk baglantida TLS tek basina 300-800ms.
# Yani 1.5 saniye, istegin yuklenmesine bile yetmiyordu -> her cagri
# TimeoutError -> zincir tukendi -> main.py'nin araci OLMAYAN duz-metin
# yedegine duşuldu. Kullanicinin gordugu "araclar calismiyor" sikayeti
# BUNUN SONUCUDUR, ayri bir hata degil (bkz. main.py RouterError blogu).
#
# ESKIDEN amac "hizli katman hizli olsun, degilse atla" idi; ama ulasilamaz
# kadar kisa bir butce o amaci kendi kendine bozuyor: katman ASLA kazanamaz.
# Calisan-ama-yavas, calismayan-ama-hizlidan iyidir.
#
# Kademelendirme KORUNDU (fast < fallback < vision < code < unrestricted
# < heavy), sadece gercekci taban degerlere cekildi. Sicak baglantida
# (surec icindeki ikinci ve sonraki cagrilar) Cerebras zaten ~0.3-0.8s'de
# aciliyor; bu degerler ust sinir, beklenen sure degil.
DEFAULT_TIMEOUTS = {
    "fast_s": 12.0,         # Cerebras -> bu sureyi asarsa Groq'a duş
    "fallback_s": 20.0,     # Groq
    "vision_s": 25.0,       # Gemini Flash (gorsel — resim yuklemesi yavas)
    "code_s": 45.0,         # Qwen Coder (kod/plan)
    "unrestricted_s": 60.0, # DeepSeek (Cheat)
    "heavy_s": 120.0,       # Kimi K3 (Heavy — dogruluk oncelikli)
}

# ─── KATMAN BASINA CIKTI TOKEN SINIRI ──────────────────────────────────
# KRITIK — ikinci ariza sebebi. model_router varsayilan olarak her katmana
# max_tokens=4096 gonderiyordu. Ama max_tokens BAGLAM PENCERESINDEN
# REZERVE EDILIR: saglayici "istem + max_tokens <= pencere" kuralini
# uygular. Cerebras'in ucretsiz katmaninda llama-3.3-70b penceresi 8192
# token; 4096'si ciktiya ayrilinca ISTEME sadece ~4096 token kalir. Yukaridaki
# istem (sistem + hafiza + ~35 arac semasi) bunu rahatca asiyor -> saglayici
# ZAMAN ASIMI DEGIL, aninda 400 "context length exceeded" donuyor.
# Bu, kullanicinin hatayi HER SEFERINDE gormesini aciklar (zaman asimi
# degisken olurdu, baglam hatasi belirlenimcidir).
#
# Cozum: hizli/kucuk pencereli katmanlarda ciktiyi kucult. 1024 token
# ALES'in sohbet yanitlari icin bol (arac cagrilari cok daha kisa), ve
# istem icin ~7000 token birakir.
# NOT: model_router bunu bir TAVAN olarak uygular; cagiran daha kucuk bir
# deger isterse o kazanir. Ayrica gercek bir baglam hatasi gelirse
# _is_context_error + kucultup tekrar deneme devreye girer (o kod, bu
# tahminlerin yanlis oldugu saglayicilar icin guvenlik agi).
DEFAULT_MAX_OUT = {
    "fast_s": 1024,         # Cerebras ucretsiz: 8192 pencere
    "fallback_s": 2048,     # Groq: 128k pencere ama TPM sinirlari dar
    "vision_s": 2048,
    "code_s": 4096,         # kod uretimi uzun olabilir
    "unrestricted_s": 4096,
    "heavy_s": 4096,
}

# config.json anahtari -> ortam degiskeni. Key config'de yoksa env'e bakilir
# (cloud/CI'da .env veya panel env'inden gelir; repo'ya yazilmasi sart degil).
_ENV_KEY_MAP = {
    "groq_key": "GROQ_API_KEY", "cerebras_key": "CEREBRAS_API_KEY",
    "gemini_key": "GEMINI_API_KEY", "openrouter_key": "OPENROUTER_API_KEY",
    "nvidia_key": "NVIDIA_API_KEY", "sambanova_key": "SAMBANOVA_API_KEY",
    "elevenlabs_key": "ELEVENLABS_API_KEY",
}

def get_key(name: str) -> str:
    """Once config.json, sonra ortam degiskeni. Boylece key'ler .env'de
    tutulabilir ve repo'ya commit edilmesi gerekmez (config.json'a yazilmis
    key'lerin degistirilmesi/rotate edilmesi onerilir)."""
    val = (load_config().get(name) or "").strip()
    if not val:
        env_name = _ENV_KEY_MAP.get(name)
        val = (os.environ.get(env_name) or "").strip() if env_name else ""
    return val if _credential_usable(name, val) else ""


# ─── YANLIS TURDE KIMLIK BILGISI TESPITI ───────────────────────────────
# 2026-08-26'da eklendi. config.json'daki gemini_key bir API ANAHTARI
# DEGIL, bir Google OAuth2 ERISIM JETONU idi ("AQ." ile baslayan tur).
# generativelanguage.googleapis.com'un OpenAI-uyumlu ucu bunu api_key
# olarak kabul etmez -> her cagri 401. Sonucu dort yerde birden goruluyordu:
#   1) model_router vision katmani (25s butcesini bosa yakiyordu)
#   2) multi_agent._call_gemini — main.py'nin ILK duz-metin yedegi; bu
#      yuzden zincir duştugunde cevap hep SambaNova/OpenRouter'dan geliyordu
#   3) model_registry'nin Gemini yoklamasi -> surekli ERROR
#   4) uzun donem hafiza gomme (LTM) -> yerel gomucuye duşuyordu
#
# KURAL — YALNIZCA POZITIF KANITLA REDDET: bir kimlik bilgisini "bekledigim
# one ek ile baslamiyor" diye ATMAK yanlis olur (saglayicilar bicim
# degistirir; bkz. model_registry.py basindaki fail-open gerekcesi). Sadece
# BASKA BIR TURUN kesin imzasi varsa reddediyoruz. "ya29." Google
# OAuth jetonlarinin bilinen oneki. Modern Gemini API anahtarlari "AIza" veya "AQ." ile baslar.
# Yani burada "belli ki OAuth jetonu" testi yapiliyor.
#
# GUVENLIK: deger HICBIR ZAMAN yazdirilmaz/loglanmaz — sadece turu soylenir.
_WRONG_TYPE = {
    "gemini_key": (
        ("ya29.",),
        "Google OAuth2 erisim jetonu (API anahtari degil). "
        "aistudio.google.com/apikey adresinden gecerli bir Gemini "
        "API anahtari alip config.json > gemini_key alanina yazin.",
    ),
}
_warned_bad_key = set()


def _credential_usable(name: str, val: str) -> bool:
    """Bu deger bu alan icin DOGRU TURDE bir kimlik bilgisi mi?

    Bos deger veya tanimsiz alan -> dokunulmaz (True/False dogal akis).
    Yanlis tur tespit edilirse: bir kez uyarilir ve YOK sayilir. Yok
    saymak, 401 ile denemekten iyidir — zincir katmani aninda atlar,
    zaman asimi butcesini harcamaz ve yedek siraya gecer.
    """
    if not val:
        return False
    rule = _WRONG_TYPE.get(name)
    if not rule:
        return True
    prefixes, why = rule
    if not val.startswith(prefixes):
        return True
    if name not in _warned_bad_key:
        _warned_bad_key.add(name)
        print(f"[CONFIG] UYARI: {name} yanlis turde bir kimlik bilgisi "
              f"iceriyor ve YOK SAYILIYOR -> {why}")
    return False


def credential_problems() -> list:
    """UI/teshis: yanlis TURDE oldugu icin yok sayilan alanlar.
    Deger dondurulmez, sadece alan adi ve aciklama."""
    out = []
    cfg = load_config()
    for name, (prefixes, why) in _WRONG_TYPE.items():
        raw = (cfg.get(name) or "").strip()
        if not raw:
            env_name = _ENV_KEY_MAP.get(name)
            raw = (os.environ.get(env_name) or "").strip() if env_name else ""
        if raw and raw.startswith(prefixes):
            out.append({"field": name, "problem": why})
    return out


# ═══════════════════════════════════════════════════════════════════
# MOD TANIMLARI (6 mod). "chain" = katman anahtarlari (DEFAULT_MODELS).
#   multi=False -> chain sirali fallback (biri duşerse sonrakine)
#   multi=True  -> chain'deki modeller AYNI ANDA yarisir, en iyi/hizli secilir
# UYARI (guvenlik karari "Model-only unrestricted"): Cheat modu SADECE
# modeli DeepSeek V4'e cevirir; CodeAct onay kapisi ve timeout'lar AYNEN
# korunur — AI kodu otomatik calistirilmaz, kapilar kaldirilmaz.
# ═══════════════════════════════════════════════════════════════════
DEFAULT_MODE = "auto"
DEFAULT_MODES = {
    "task": {
        "label": "Task",
        "description": "Maksimum hiz. Sadece Cerebras + Groq (kucuk/hizli modeller).",
        "chain": ["fast", "fallback"],
        "vision": "vision", "code": "code",
        "fast_path": True, "multi": False, "unrestricted": False,
        "disable_local_heavy": False,
    },
    "cheat": {
        "label": "Cheat",
        "description": "DeepSeek V4 birincil (kisitsiz model). Gorsel->Gemini, kod->Qwen. "
                       "Sadece model degisir; onay kapisi/timeout korunur.",
        "chain": ["unrestricted", "fallback"],
        "vision": "vision", "code": "code",
        "fast_path": True, "multi": False, "unrestricted": True,
        "disable_local_heavy": False,
    },
    "auto": {
        "label": "Auto",
        "description": "Gorev tipine gore uzman modele yonlendir (varsayilan).",
        "chain": ["fast", "fallback"],
        "vision": "vision", "code": "code",
        "fast_path": True, "multi": False, "unrestricted": False,
        "disable_local_heavy": False,
    },
    "multi": {
        "label": "Multi",
        "description": "3-5 modeli ayni anda cagir, en hizli/en iyi yaniti sec.",
        "chain": ["fast", "fallback", "code", "vision"],
        "vision": "vision", "code": "code",
        "fast_path": True, "multi": True, "unrestricted": False,
        "disable_local_heavy": False,
    },
    "performance": {
        "label": "Performance",
        "description": "Agir yerel modulleri kapat (OpenDex UI, Shadowbroker, RealtimeTTS); "
                       "bulut API'lere kaydir.",
        "chain": ["fast", "fallback"],
        "vision": "vision", "code": "code",
        "fast_path": True, "multi": False, "unrestricted": False,
        "disable_local_heavy": True,
        "disabled_modules": ["opendex_ui", "shadowbroker", "realtime_tts"],
    },
    "heavy": {
        "label": "Heavy",
        "description": "En guclu modeller (Kimi K3, DeepSeek V4, Gemini 2.0 Flash) paralel; "
                       "Fast Path kapali; dogruluk oncelikli. LLM Meclisi OTOMATIK acik.",
        "chain": ["heavy", "unrestricted", "vision"],
        "vision": "vision", "code": "code",
        "fast_path": False, "multi": True, "unrestricted": False,
        "disable_local_heavy": False,
        # Kimi K3 SADECE burada ve Council'da acik (bkz. HEAVY_ONLY_LAYERS).
        "heavy_ok": True,
        # Heavy = dogruluk oncelikli, o yuzden meclis burada kendiliginden acilir.
        "council": True, "council_strategy": "synthesized",
    },
    "council": {
        "label": "Council",
        "description": "LLM Meclisi: 6 modele kadar ayni anda sorulur, yanitlar "
                       "anonimlestirilip hakem modele degerlendirtilir ve tek "
                       "cevap sentezlenir. En yavas ama en dogru mod.",
        "chain": ["heavy", "unrestricted", "fallback"],
        "vision": "vision", "code": "code",
        # Fast Path kapali: meclis modunda amac hiz degil dogruluk.
        "fast_path": False, "multi": True, "unrestricted": False,
        "disable_local_heavy": False,
        # Council zincirinde "heavy" ZATEN yaziliydi ve mod dogruluk
        # oncelikli; izni kapatmak calisan bir modu sessizce zayiflatirdi.
        # Kapatmak istersen: burayi False yap (tek boolean).
        "heavy_ok": True,
        "council": True, "council_strategy": "synthesized",
    },
    "big_ales": {
        "label": "Big ALES",
        "description": "Buyuk orkestrator (Puter uzerinden, API ANAHTARI GEREKMEZ): "
                       "istek once Hermes 405B ile net ve yasal bicimde yeniden "
                       "yazilir, sonra NORMAL ALES zincirinden gecer. Puter girisi "
                       "bir kez yapilir, ucreti kullanicinin kendi hesabi karsilar.",
        # Zincir kasitli olarak NORMAL zincir: orkestrator modeli SECMEZ,
        # yalnizca istegi netlestirir. Yurutmeyi yine ALES yapar.
        "chain": ["fast", "fallback"],
        "vision": "vision", "code": "code",
        # Fast Path KAPALI. Sebep: fast_path basit istekleri modele hic
        # ugramadan yanitlar; acik birakirsak kullanici bu modu secmesine
        # ragmen orkestrator devreye GIRMEZ, yani mod adini tasidigi isi
        # yapmaz. Heavy/Council de ayni gerekceyle kapatiyor.
        "fast_path": False, "multi": False, "unrestricted": False,
        "disable_local_heavy": False,
        "big_ales": True,
        "big_ales_model": "nousresearch/hermes-3-llama-3.1-405b",
    },
}

# Meclisin varsayilan ayarlari. config.json['council'] ile override edilir;
# UI'daki Ayarlar anahtari da buraya yazar.
DEFAULT_COUNCIL = {
    "enabled": False,          # mod "council"/"heavy" degilse global anahtar
    "strategy": "synthesized",  # synthesized | best_of_n | weighted | majority
    "timeout_s": 5.0,           # model basina
    "judge_timeout_s": 20.0,
    "cache": True,
}


def get_models() -> dict:
    """DEFAULT_MODELS + config.json['models'] override (katman bazli)."""
    models = {k: dict(v) for k, v in DEFAULT_MODELS.items()}
    for layer, ov in (load_config().get("models") or {}).items():
        if layer in models and isinstance(ov, dict):
            models[layer].update(ov)
    return models


def get_timeouts() -> dict:
    """DEFAULT_TIMEOUTS + config.json['timeouts'] override."""
    t = dict(DEFAULT_TIMEOUTS)
    for k, v in (load_config().get("timeouts") or {}).items():
        if k in t:
            try: t[k] = float(v)
            except Exception: pass
    return t


def get_max_out() -> dict:
    """DEFAULT_MAX_OUT + config.json['max_out'] override.

    Anahtarlar timeouts ile AYNI ("fast_s", "fallback_s", ...) — boylece
    model_router'daki mevcut _LAYER_TIMEOUT eslemesi tekrar kullanilabilir
    ve katman adi -> alan adi cevirisi iki yerde ayri ayri tutulmaz.
    """
    m = dict(DEFAULT_MAX_OUT)
    for k, v in (load_config().get("max_out") or {}).items():
        if k in m:
            try: m[k] = max(256, int(v))   # 256 alti: yanit ortada kesilir
            except Exception: pass
    return m


def get_mode() -> str:
    """Aktif mod (config.json['mode']). Gecersizse DEFAULT_MODE."""
    m = (load_config().get("mode") or DEFAULT_MODE).lower()
    return m if m in DEFAULT_MODES else DEFAULT_MODE


def set_mode(mode: str) -> str:
    """Aktif modu degistir ve config.json'a yaz. Gecersiz mod -> ValueError."""
    mode = (mode or "").lower()
    if mode not in DEFAULT_MODES:
        raise ValueError(f"Bilinmeyen mod: {mode}. Gecerli: {list(DEFAULT_MODES)}")
    cfg = load_config()
    cfg["mode"] = mode
    save_config(cfg)
    return mode


def list_modes() -> list:
    """UI icin mod listesi (id, label, aciklama, aktif mi)."""
    active = get_mode()
    return [{"id": k, "label": v["label"], "description": v["description"],
             # heavy_ok: bu modda Kimi K3 (heavy katmani) kullanilabilir mi.
             "heavy_ok": bool(v.get("heavy_ok", False)),
             "active": k == active} for k, v in DEFAULT_MODES.items()]


def get_mode_config(mode: str = None) -> dict:
    """Bir modun tam cozumlenmis konfigurasyonu: chain'deki her katman
    (provider+model) ile birlikte. model_router.py bunu okuyup zinciri kurar.
    config.json['modes'][mode] ile alan bazli override edilebilir."""
    mode = (mode or get_mode()).lower()
    base = dict(DEFAULT_MODES.get(mode, DEFAULT_MODES[DEFAULT_MODE]))
    ov = (load_config().get("modes") or {}).get(mode)
    if isinstance(ov, dict):
        base.update(ov)
    models = get_models()

    def _layer(key):
        return {"layer": key, **models.get(key, {})}

    # ── Heavy-only kapisi ──────────────────────────────────────────
    # Zincirde yazan katman ile IZIN VERILEN katman ayni sey degil.
    heavy_ok = bool(base.get("heavy_ok", False))
    chain_keys = [k for k in base.get("chain", ["fast", "fallback"]) if k in models]
    dropped = []
    if not heavy_ok:
        dropped = [k for k in chain_keys if k in HEAVY_ONLY_LAYERS]
        chain_keys = [k for k in chain_keys if k not in HEAVY_ONLY_LAYERS]
    if not chain_keys:
        # GUVENLIK KAPISI: model_router.race_chain/chat_chain bos zincirde
        # RouterError("zincir bos") atar, yani mod tamamen calismaz hale
        # gelirdi. Filtre her seyi dusurduyse guvenli varsayilana donuyoruz.
        chain_keys = [k for k in ("fast", "fallback") if k in models] or list(models)[:1]

    return {
        "mode": mode,
        "label": base.get("label", mode),
        "description": base.get("description", ""),
        "chain": [_layer(k) for k in chain_keys],
        "vision": _layer(base.get("vision", "vision")),
        "code": _layer(base.get("code", "code")),
        "fast_path": bool(base.get("fast_path", True)),
        "multi": bool(base.get("multi", False)),
        "unrestricted": bool(base.get("unrestricted", False)),
        "heavy_ok": heavy_ok,
        # UI/log icin seffaflik: hangi katman neden zincirde YOK.
        "dropped_layers": dropped,
        "disable_local_heavy": bool(base.get("disable_local_heavy", False)),
        "disabled_modules": list(base.get("disabled_modules", [])),
        "timeouts": get_timeouts(),
        # Katman basina cikti tavani (bkz. DEFAULT_MAX_OUT). Zaman asimlariyla
        # ayni anahtarlari kullanir, model_router ikisini birlikte okur.
        "max_out": get_max_out(),
        # LLM Meclisi: mod acik diyorsa VEYA kullanici global anahtari
        # actiysa calisir. Heavy/Council modlari kendiliginden acar.
        "council": bool(base.get("council", False)) or bool(get_council()["enabled"]),
        "council_strategy": base.get("council_strategy") or get_council()["strategy"],
        # Big ALES: istek NORMAL zincire girmeden once Puter uzerindeki
        # orkestratorle yeniden yazilsin mi. model_router bunu okuyor.
        # Mod acmasa bile kullanici Ayarlar'dan global anahtari acabilir.
        "big_ales": bool(base.get("big_ales", False)) or bool(get_big_ales()["enabled"]),
        "big_ales_model": (base.get("big_ales_model")
                           or get_big_ales()["model"]),
        "big_ales_timeout_s": get_big_ales()["timeout_s"],
    }


# ─── MODEL KATMANLARI (UI: /models) ────────────────────────────────────
def layer_allowed(layer: str, mode: str = None) -> bool:
    """Bu katman bu modda kullanilabilir mi?

    model_router._call_layer bunu savunma amacli ikinci kez cagirir: bir
    cagri yolu get_mode_config()'i atlayip dogrudan "heavy" isterse yine
    engellenir (tek kapiya guvenmiyoruz).
    """
    if layer not in HEAVY_ONLY_LAYERS:
        return True
    try:
        return bool(get_mode_config(mode).get("heavy_ok"))
    except Exception:
        return False          # fail-closed: emin olamiyorsak pahali yol KAPALI


def heavy_available() -> bool:
    """Heavy katmani gercekten kullanilabilir mi: hem anahtar var hem izin."""
    models = get_models()
    h = models.get("heavy") or {}
    prov = h.get("provider")
    if not prov:
        return False
    try:
        if not get_key(f"{prov}_key"):
            return False
    except Exception:
        return False
    return any(m.get("heavy_ok") for m in DEFAULT_MODES.values())


def list_model_layers() -> list:
    """UI icin katman tablosu: hangi katman, hangi model, acik mi, neden.

    Kullanicinin "Kimi K3 nerede?" sorusunun cevabi burasi — modele gore
    izin durumu ve anahtar durumu birlikte gorunur.
    """
    models = get_models()
    timeouts = get_timeouts()
    active_mode = get_mode()
    out = []
    for layer, m in models.items():
        prov = m.get("provider", "")
        try:
            has_key = bool(get_key(f"{prov}_key"))
        except Exception:
            has_key = False
        heavy_only = layer in HEAVY_ONLY_LAYERS
        allowed_modes = sorted(k for k, v in DEFAULT_MODES.items()
                               if (not heavy_only) or v.get("heavy_ok"))
        out.append({
            "layer": layer,
            "provider": prov,
            "model": m.get("model", ""),
            "timeout_s": timeouts.get(f"{layer}_s"),
            "heavy_only": heavy_only,
            "has_key": has_key,
            "allowed_modes": allowed_modes,
            "active_now": layer_allowed(layer, active_mode),
            "reason": ("" if has_key else f"{prov} anahtari yok")
                      or ("" if layer_allowed(layer, active_mode)
                          else f"'{active_mode}' modunda kapali (heavy_ok=False)"),
        })
    return sorted(out, key=lambda x: (x["heavy_only"], x["layer"]))


def get_council() -> dict:
    """Meclis ayarlari: DEFAULT_COUNCIL + config.json['council'] override."""
    c = dict(DEFAULT_COUNCIL)
    ov = load_config().get("council")
    if isinstance(ov, dict):
        c.update({k: v for k, v in ov.items() if k in c})
    return c


# ─── BIG ALES (Puter orkestratoru) ─────────────────────────────────────
# Mod ("big_ales") ZATEN acar; bu global anahtar Ali'nin istedigi Ayarlar
# duymesi icin: kullanici modu degistirmeden de orkestratoru acabilsin.
# API ANAHTARI YOK — odemeyi kullanicinin Puter hesabi karsilar, giris
# arayuzde bir kez yapilir (bkz. backend/puter_connector.py).
DEFAULT_BIG_ALES = {
    "enabled": False,
    "model": "nousresearch/hermes-3-llama-3.1-405b",
    "timeout_s": 60.0,
}
BIG_ALES_MODELS = (
    "nousresearch/hermes-3-llama-3.1-405b",
    "nousresearch/hermes-3-llama-3.1-70b",
    "nousresearch/hermes-4-70b",
)


def get_big_ales() -> dict:
    """DEFAULT_BIG_ALES + config.json['big_ales'] override."""
    c = dict(DEFAULT_BIG_ALES)
    ov = load_config().get("big_ales")
    if isinstance(ov, dict):
        c.update({k: v for k, v in ov.items() if k in c})
    if c["model"] not in BIG_ALES_MODELS:            # bozuk config -> guvenli
        c["model"] = DEFAULT_BIG_ALES["model"]
    try:
        c["timeout_s"] = max(5.0, float(c["timeout_s"]))
    except Exception:
        c["timeout_s"] = DEFAULT_BIG_ALES["timeout_s"]
    return c


def set_big_ales(**kw) -> dict:
    """Big ALES ayarlarini guncelle (UI'daki Ayarlar anahtari buraya yazar).
    Model beyaz listenin disindaysa ValueError — yanlis model adi
    kullanicinin Puter hesabinda beklenmeyen ucret dogurabilir."""
    if "model" in kw and kw["model"] not in BIG_ALES_MODELS:
        raise ValueError(f"Bilinmeyen Big ALES modeli: {kw['model']}. "
                         f"Gecerli: {list(BIG_ALES_MODELS)}")
    cfg = load_config()
    cur = dict(DEFAULT_BIG_ALES)
    cur.update(cfg.get("big_ales") or {})
    for k, v in kw.items():
        if k not in DEFAULT_BIG_ALES:
            continue
        if k == "enabled":
            cur[k] = bool(v)
        elif k == "timeout_s":
            try: cur[k] = max(5.0, float(v))
            except Exception: pass
        else:
            cur[k] = v
    cfg["big_ales"] = cur
    save_config(cfg)
    return cur


def set_council(**kw) -> dict:
    """Meclis ayarlarini guncelle (UI'daki Ayarlar anahtari buraya yazar).
    Sadece bilinen alanlar kabul edilir; gecersiz strateji -> ValueError."""
    valid_strategies = {"synthesized", "best_of_n", "weighted", "majority"}
    if "strategy" in kw and kw["strategy"] not in valid_strategies:
        raise ValueError(f"Bilinmeyen strateji: {kw['strategy']}. "
                         f"Gecerli: {sorted(valid_strategies)}")
    cfg = load_config()
    cur = dict(DEFAULT_COUNCIL)
    cur.update(cfg.get("council") or {})
    for k, v in kw.items():
        if k not in DEFAULT_COUNCIL:
            continue
        if k in ("enabled", "cache"):
            cur[k] = bool(v)
        elif k in ("timeout_s", "judge_timeout_s"):
            cur[k] = max(1.0, float(v))
        else:
            cur[k] = v
    cfg["council"] = cur
    save_config(cfg)
    return cur


# ═══════════════════════════════════════════════════════════════════
# KALICI SISTEM PROMPTU (LUBV) — her konusmaya system rolu olarak enjekte
# ═══════════════════════════════════════════════════════════════════
SYSTEM_PROMPTS_FILE = APPDATA / 'system_prompts.json'
_LOCAL_PROMPTS = Path(__file__).parent / 'system_prompts.json'


def load_system_prompts() -> dict:
    """system_prompts.json: once AppData (kullanici duzenlemesi kalici),
    sonra backend/ (repo ile gelen varsayilan)."""
    for f in [SYSTEM_PROMPTS_FILE, Path('system_prompts.json'), _LOCAL_PROMPTS]:
        if f.exists():
            try: return json.loads(f.read_text(encoding='utf-8'))
            except Exception: pass
    return {}


def get_system_prompt(name: str = "lubv") -> str:
    """Kalici sistem promptunu dondur. Kayit iki formati destekler:
       "lubv": "<metin>"   veya   "lubv": {"enabled": true, "text": "<metin>"}.
    enabled=False ya da metin yoksa bos string doner (enjeksiyon atlanir)."""
    val = load_system_prompts().get(name)
    if isinstance(val, dict):
        if not val.get("enabled", True):
            return ""
        return (val.get("text") or "").strip()
    return val.strip() if isinstance(val, str) else ""


def save_system_prompts(data: dict):
    """system_prompts.json'u AppData'ya yaz (kullanici duzenlemesi kalicidir).

    load_system_prompts() ONCE AppData'ya baktigi icin buraya yazmak repo ile
    gelen backend/system_prompts.json varsayilanini golgeler — guncelleme
    kullanicinin metnini ezmez."""
    SYSTEM_PROMPTS_FILE.parent.mkdir(parents=True, exist_ok=True)
    SYSTEM_PROMPTS_FILE.write_text(
        json.dumps(data, ensure_ascii=False, indent=2), encoding='utf-8')


def set_system_prompt(name: str = "lubv", text: str = None,
                      enabled: bool = None) -> dict:
    """Kalici sistem promptunu yaz/ac/kapat. Doner: {enabled, text, chars}.

    text=None ise metne DOKUNULMAZ (sadece anahtari cevirmek icin), enabled=None
    ise duruma dokunulmaz. Ilk kez metin yazilirken enabled ayrica verilmediyse
    OTOMATIK acilmaz — kullanici once metni gorup sonra bilerek etkinlestirir;
    boylece yarim yapistirilmis bir metin sessizce her konusmaya girmez."""
    data = load_system_prompts() or {}
    cur = data.get(name)
    if isinstance(cur, str):                 # eski duz-metin formatini yukselt
        cur = {"enabled": True, "text": cur}
    elif not isinstance(cur, dict):
        cur = {"enabled": False, "text": ""}

    if text is not None:
        cur["text"] = str(text)
    if enabled is not None:
        cur["enabled"] = bool(enabled)
    # Metin bossa acik kalmasi anlamsiz — enjeksiyon zaten bos string uretir.
    if not (cur.get("text") or "").strip():
        cur["enabled"] = False

    data[name] = cur
    save_system_prompts(data)
    return {"enabled": bool(cur["enabled"]), "text": cur["text"],
            "chars": len(cur["text"])}
