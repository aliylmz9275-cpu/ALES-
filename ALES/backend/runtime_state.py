"""
runtime_state.py — ALES calisma-zamani durum yoneticisi (Faz 3 / Priority 3).

Performance / Heavy / Headless / Sleep anahtarlarini ve "agir modul" kayit
defterini tek yerden yonetir. resource_monitor.py OLCER, bu modul KARAR
VERIR ve UYGULAR; main.py ise gercek etkileri (WebSocket kapatma, TTS
duraklatma) callback olarak baglar.

Neden ayri modul: mod tanimlari (config_manager.DEFAULT_MODES) statik
konfigurasyondur; burasi ise ANLIK durumdur (su an headless miyiz, uyuyor
muyuz, hangi modul duraklatildi). Ikisini karistirmamak dairesel importu
ve "config'e yazdim ama calisan surece yansimadi" hatasini onler.

── Priority 2 kararina saygi ───────────────────────────────────────────
Ali bilgisayar-kullanan (computer-use) entegrasyonlari ERTELEDI. Bu yuzden
agent_s3 / aguvis / gui_thinker / nanobrowser / open_infra_agent burada
KAYITLI ama available=False'tur. Heavy mod bunlari "acik" gosterip sessizce
o karari cignemez; UI'da "mevcut degil (ertelendi)" olarak gorunurler.
"""

import logging
import os
import tempfile
import threading
import time
from pathlib import Path

# ─── Agir modul kayit defteri ────────────────────────────────────────
# available=False -> henuz entegre edilmedi / bilincli ertelendi.
# heavy_local=True -> Performance modda ilk kapatilacaklar.
MODULES = {
    "opendex_ui":       {"label": "Yerel HUD",        "heavy_local": True,  "available": True,
                         "note": "Frontend'e gomulu HUD (Talking Dot + Typing Cursor)."},
    "shadowbroker":     {"label": "Shadowbroker",     "heavy_local": True,  "available": False,
                         "note": "Ayri Docker servisi; kullanici baslatmali."},
    "realtime_tts":     {"label": "Akisli TTS",       "heavy_local": True,  "available": False,
                         "note": "acilista yoklanir (audio_streamer)."},
    "open_infra_agent": {"label": "Open Infra Agent", "heavy_local": True,  "available": False,
                         "note": "Ertelendi (Docker/Linux masaustu, v0.1)."},
    "nanobrowser":      {"label": "Nanobrowser",      "heavy_local": True,  "available": False,
                         "note": "Ayri Chrome eklentisi; Python'dan cagrilmaz."},
    "gui_thinker":      {"label": "GUI-Thinker",      "heavy_local": True,  "available": False,
                         "note": "Ertelendi (computer-use)."},
    "agent_s3":         {"label": "Agent S3",         "heavy_local": True,  "available": False,
                         "note": "Ertelendi (computer-use, onay kapisi sart)."},
    "aguvis":           {"label": "Aguvis",           "heavy_local": True,  "available": False,
                         "note": "Ertelendi (GPU 7B VLM, eksik surum)."},
    "tts":              {"label": "Sesli yanit (TTS)", "heavy_local": False, "available": True,
                         "note": "Mevcut edge-tts tabanli ses."},
    "websocket":        {"label": "WebSocket akisi",  "heavy_local": False, "available": True,
                         "note": "Canli token/log akisi."},
    # ── Yeni moduller (available acilista GERCEKTEN yoklanir) ────────
    # heavy_local KASITLI olarak False: bunlari Performance modda kapatmak
    # maliyet dusurmez, DAVRANISI bozar (arac cagrisi sessizce kaybolur).
    # Tek istisna "predictive": onun tum isi spekulatif ekstra istir, yani
    # kaynak sikisinca ilk kesilmesi gereken sey odur.
    "codeact":          {"label": "CodeAct yurutucu", "heavy_local": False, "available": False,
                         "note": "acilista yoklanir (code_act_executor)."},
    "agent_jit":        {"label": "Agent JIT",        "heavy_local": False, "available": False,
                         "note": "acilista yoklanir (agent_jit)."},
    "predictive":       {"label": "Ongorulu on-yukleme", "heavy_local": True, "available": False,
                         "note": "acilista yoklanir (predictive)."},
    "plugins":          {"label": "Eklenti yukleyici", "heavy_local": False, "available": False,
                         "note": "acilista yoklanir (plugin_loader)."},
    "skills_growth":    {"label": "Beceri ogrenme",   "heavy_local": False, "available": False,
                         "note": "acilista yoklanir (skills_autogrowth)."},
    "self_heal":        {"label": "Kendini toparlama", "heavy_local": False, "available": False,
                         "note": "acilista yoklanir (self_heal)."},
    "native_desktop":   {"label": "Windows masaustu", "heavy_local": False, "available": False,
                         "note": "acilista yoklanir (native_desktop)."},
    "vector_memory":    {"label": "Vektor hafiza",    "heavy_local": False, "available": False,
                         "note": "acilista yoklanir (sqlite-vec)."},
    # ── Faz 2/3/6 moduller (2026-09-05) ─────────────────────────────
    # heavy_local=True olanlar Performance modda (0% kaynak) ILK kesilir:
    # hepsi "ekstra/spekulatif is" — kapatilinca cevap gelmeye devam eder,
    # sadece hizlandirma ya da ogrenme durur. heavy_local=False olanlar
    # DAVRANIS/verim icin gerekli oldugu icin kesilmez (token_optimizer
    # kapatmak kaynak KAZANDIRMAZ, tam tersi: daha cok token gonderilir).
    "token_optimizer":  {"label": "DEPO token optimizasyonu", "heavy_local": False, "available": False,
                         "note": "acilista yoklanir (token_optimizer)."},
    "spec_cache":       {"label": "SpecCache (spekulatif onbellek)", "heavy_local": True, "available": False,
                         "note": "acilista yoklanir (speculative_cache)."},
    "batch_inference":  {"label": "Toplu cikarim (CONCUR)", "heavy_local": True, "available": False,
                         "note": "acilista yoklanir (batch_inference)."},
    "moa":              {"label": "Ajan Karisimi (MoA/DMoA)", "heavy_local": True, "available": False,
                         "note": "acilista yoklanir (mixture_of_agents)."},
    "cer":              {"label": "Deneyim tekrari (CER)", "heavy_local": False, "available": False,
                         "note": "acilista yoklanir (contextual_experience_replay)."},
    "self_evolution":   {"label": "Oz-gelisim (SE/MUSE/Agent0)", "heavy_local": False, "available": False,
                         "note": "acilista yoklanir (self_evolution)."},
    "reflection":       {"label": "Oz-yansima (Reflexion)", "heavy_local": True, "available": False,
                         "note": "acilista yoklanir (reflection_agent)."},
    "darwin_godel":     {"label": "Darwin Godel evrimi", "heavy_local": True, "available": False,
                         "note": "acilista yoklanir (darwin_godel)."},
    "openclaw":         {"label": "OpenClaw koprusu", "heavy_local": True, "available": False,
                         "note": "acilista yoklanir (openclaw_bridge)."},
    "evo_cua":          {"label": "EvoCUA bilgisayar-kullanimi", "heavy_local": True, "available": False,
                         "note": "acilista yoklanir (evo_cua_bridge)."},
    "adaptive_timeouts": {"label": "Uyarlanir zaman asimi", "heavy_local": False, "available": False,
                         "note": "acilista yoklanir (adaptive_timeouts)."},
    "versioned_config": {"label": "Surumlu yapilandirma", "heavy_local": False, "available": False,
                         "note": "acilista yoklanir (versioned_config)."},
}

# id -> (import edilecek modul adi, modulden durum okuma sekli)
# "info" = modulun info() sozlugunden available/note; "custom" = ozel kod.
_PROBES = {
    "codeact":        ("code_act_executor", "info"),
    "agent_jit":      ("agent_jit", "info"),
    "predictive":     ("predictive", "info"),
    "plugins":        ("plugin_loader", "info"),
    "skills_growth":  ("skills_autogrowth", "info"),
    "self_heal":      ("self_heal", "info"),
    "native_desktop": ("native_desktop", "info"),
    "realtime_tts":   ("audio_streamer", "info"),
    "vector_memory":  ("long_term_memory", "vector"),
    # Faz 2/3/6: bu modullerin info() fonksiyonu YOK; refresh_modules
    # bunu zaten kaldirir (nfo={} -> available True varsayilir), yani
    # "import edilebiliyorsa aciktir" anlamina gelir. Dogru davranis bu:
    # bu moduller saf-Python, harici bagimliligi olmayan modullerdir.
    "token_optimizer":   ("token_optimizer", "info"),
    "spec_cache":        ("speculative_cache", "info"),
    "batch_inference":   ("batch_inference", "info"),
    "moa":               ("mixture_of_agents", "info"),
    "cer":               ("contextual_experience_replay", "info"),
    "self_evolution":    ("self_evolution", "info"),
    "reflection":        ("reflection_agent", "info"),
    "darwin_godel":      ("darwin_godel", "info"),
    "openclaw":          ("openclaw_bridge", "info"),
    "evo_cua":           ("evo_cua_bridge", "info"),
    "adaptive_timeouts": ("adaptive_timeouts", "info"),
    "versioned_config":  ("versioned_config", "info"),
}
_probed = False


def set_available(name: str, ok: bool, note: str = None) -> bool:
    """Bir modulun GERCEK durumunu isaretle (main.py import edebildi mi)."""
    m = MODULES.get(name)
    if not m:
        return False
    with _lock:
        m["available"] = bool(ok)
        if note:
            m["note"] = note[:180]
    return True


def refresh_modules(force: bool = False) -> dict:
    """Yeni modulleri GERCEKTEN import ederek durumlarini gunceller.

    NEDEN: eskiden bu tablo elle "available: False" yazilmis sabitlerden
    olusuyordu ve modul calisir hale geldiginde tablo yanlis kaliyordu
    (UI "mevcut degil" derken arac calisiyordu). Artik cevabi modulun
    KENDISI veriyor: her yeni modulun info() fonksiyonu var.
    Yoklama bir kez yapilir; `force=True` ile tekrar denenir (kullanici
    eksik pip paketini kurduktan sonra UI'dan tazeleyebilsin).
    """
    global _probed
    if _probed and not force:
        return {k: MODULES[k]["available"] for k in _PROBES}
    import importlib
    out = {}
    for mid, (modname, how) in _PROBES.items():
        ok, note = False, ""
        try:
            mod = importlib.import_module(modname)
            if how == "vector":
                vi = mod.vector_info()
                ok = bool(vi.get("extension_loaded"))
                note = ("sqlite-vec aktif; %s kayit indeksli."
                        % vi.get("indexed", 0)) if ok else \
                       "sqlite-vec yok -> Python kosinus yedegi calisiyor."
            else:
                nfo = mod.info() if hasattr(mod, "info") else {}
                ok = bool(nfo.get("available", True))
                note = str(nfo.get("note") or nfo.get("engine") or
                           nfo.get("backend") or "")[:180]
                if not note:
                    note = f"{modname} yuklendi."
        except Exception as e:
            ok, note = False, f"{modname} yuklenemedi: {e}"[:180]
        set_available(mid, ok, note)
        out[mid] = ok
    _probed = True
    return out


def module_available(name: str) -> bool:
    with _lock:
        m = MODULES.get(name)
        return bool(m and m.get("available"))


def module_active(name: str) -> bool:
    """Kullanilabilir MI ve duraklatilmamis MI. Cagri yerlerinin sormasi
    gereken tek soru budur (ornegin predictive prefetch)."""
    with _lock:
        m = MODULES.get(name)
        return bool(m and m.get("available") and not _state["paused"].get(name))


SLEEP_AFTER_S = 300.0        # 5 dakika hareketsizlik -> uyku (item 6)

_lock = threading.RLock()
_state = {
    "performance_mode": False,
    "heavy_mode": False,
    "headless_mode": False,
    "sleep_mode": True,          # ozellik ACIK (uyuyabilir); "asleep" ise anlik durum
    "asleep": False,
    "paused": {},                # modul_adi -> True (duraklatildi)
    "last_activity": time.time(),
    "degraded": False,           # kaynak baskisiyla otomatik dusuruldu mu
    "log_level": "INFO",
}
_cbs = {"module": [], "ui": [], "sleep": [], "wake": []}


# ═════════════════════════════════════════════════════════════════════
# CALLBACK KAYDI (main.py gercek etkileri buraya baglar)
# ═════════════════════════════════════════════════════════════════════
def register(event: str, fn):
    """event: 'module' (name, paused) | 'ui' (visible) | 'sleep' | 'wake'."""
    if event in _cbs and callable(fn):
        _cbs[event].append(fn)
    return fn


def _fire(event: str, *args):
    for fn in list(_cbs.get(event, [])):
        try:
            fn(*args)
        except Exception as e:
            print(f"[RUNTIME] {event} callback hatasi: {e}")


# ═════════════════════════════════════════════════════════════════════
# CONFIG KOPRUSU
# ═════════════════════════════════════════════════════════════════════
def _save(**kv):
    """Anahtarlari config.json'a yaz (kalici olsun)."""
    try:
        from config_manager import load_config, save_config
        cfg = load_config() or {}
        cfg.update(kv)
        save_config(cfg)
    except Exception as e:
        print(f"[RUNTIME] config yazilamadi: {e}")


def load_from_config():
    """Acilista config.json'daki anahtarlari uygula."""
    try:
        from config_manager import load_config
        cfg = load_config() or {}
    except Exception:
        cfg = {}
    with _lock:
        for k in ("performance_mode", "heavy_mode", "headless_mode", "sleep_mode"):
            if k in cfg:
                _state[k] = bool(cfg[k])
    if _state["performance_mode"]:
        set_performance(True, persist=False)
    if _state["heavy_mode"]:
        set_heavy(True, persist=False)
    if _state["headless_mode"]:
        set_headless(True, persist=False)
    return snapshot()


# ═════════════════════════════════════════════════════════════════════
# MODUL DURAKLATMA
# ═════════════════════════════════════════════════════════════════════
def pause_module(name: str, reason: str = "") -> bool:
    if name not in MODULES:
        return False
    with _lock:
        if _state["paused"].get(name):
            return True
        _state["paused"][name] = True
    print(f"[RUNTIME] Duraklatildi: {name} ({reason or 'istek'})")
    _fire("module", name, True)
    return True


def resume_module(name: str) -> bool:
    if name not in MODULES:
        return False
    with _lock:
        if not _state["paused"].pop(name, None):
            return True
    print(f"[RUNTIME] Devam: {name}")
    _fire("module", name, False)
    return True


def is_paused(name: str) -> bool:
    with _lock:
        return bool(_state["paused"].get(name))


def heavy_local_modules() -> list:
    return [k for k, v in MODULES.items() if v.get("heavy_local")]


# ═════════════════════════════════════════════════════════════════════
# 2) PERFORMANCE MODE
# ═════════════════════════════════════════════════════════════════════
def _set_log_level(level: str):
    try:
        logging.getLogger().setLevel(getattr(logging, level, logging.INFO))
        for name in ("uvicorn", "uvicorn.access", "uvicorn.error", "httpx"):
            logging.getLogger(name).setLevel(getattr(logging, level, logging.INFO))
        with _lock:
            _state["log_level"] = level
    except Exception:
        pass


def temp_dir() -> str:
    """'RAM disk (tmpfs)' istegi: Windows'ta tmpfs YOKTUR ve RAM-disk icin
    ucuncu parti surucu (ImDisk vb.) kurmak gerekir — bunu kullanicinin
    haberi olmadan yapmak dogru degil. Gercek karsilik: dosya islerini
    tek bir gecici klasore topluyoruz (SSD onbellegi zaten RAM'de tutar);
    ALES_RAMDISK ortam degiskeni tanimliysa (kullanici gercek bir RAM-disk
    surucusu olusturduysa) O kullanilir."""
    ram = os.environ.get("ALES_RAMDISK")
    base = Path(ram) if ram and Path(ram).exists() else Path(tempfile.gettempdir())
    d = base / "ales_tmp"
    try:
        d.mkdir(parents=True, exist_ok=True)
    except Exception:
        return tempfile.gettempdir()
    return str(d)


def set_performance(on: bool, persist: bool = True) -> dict:
    """Performance modu: agir yerel modulleri kapat, buluta kaydir,
    log seviyesini ERROR yap, gecici dosyalari tek klasorde topla."""
    on = bool(on)
    with _lock:
        _state["performance_mode"] = on
    if on:
        for name in heavy_local_modules():
            pause_module(name, "performance")
        pause_module("websocket", "performance")     # sadece aktif gorevde acilir
        _set_log_level("ERROR")
        os.environ["ALES_TMP"] = temp_dir()
        # router zaten bulut saglayicilari kullanir; modu da performance'a al
        try:
            from config_manager import set_mode
            set_mode("performance")
        except Exception:
            pass
    else:
        for name in heavy_local_modules():
            resume_module(name)
        resume_module("websocket")
        _set_log_level("INFO")
    if persist:
        _save(performance_mode=on)
    print(f"[RUNTIME] Performance modu: {'ACIK' if on else 'KAPALI'}")
    return snapshot()


# ═════════════════════════════════════════════════════════════════════
# 3) HEAVY MODE
# ═════════════════════════════════════════════════════════════════════
def set_heavy(on: bool, persist: bool = True) -> dict:
    """Heavy mod: en guclu modeller paralel (Kimi K3 + DeepSeek V4 +
    Gemini), Fast Path KAPALI, 5 ajan tam tartisma. Model zinciri
    config_manager.DEFAULT_MODES['heavy'] tarafindan tanimlidir
    (chain=[heavy, unrestricted, vision], multi=True, fast_path=False)."""
    on = bool(on)
    with _lock:
        _state["heavy_mode"] = on
        if on:
            _state["performance_mode"] = False       # ikisi birlikte olamaz
    try:
        from config_manager import set_mode
        set_mode("heavy" if on else "auto")
    except Exception as e:
        print(f"[RUNTIME] mod degistirilemedi: {e}")
    if on:
        resume_module("websocket")
        _set_log_level("INFO")
        if persist:
            _save(heavy_mode=True, performance_mode=False)
    elif persist:
        _save(heavy_mode=False)
    print(f"[RUNTIME] Heavy modu: {'ACIK' if on else 'KAPALI'}")
    return snapshot()


# ═════════════════════════════════════════════════════════════════════
# 5) HEADLESS MODE
# ═════════════════════════════════════════════════════════════════════
def set_headless(on: bool, persist: bool = True) -> dict:
    """Headless: UI cizilmez, sadece ses/API ile etkilesim. Kullanici
    "ALES, ekrani goster" dediginde show_ui() cagrilir."""
    on = bool(on)
    with _lock:
        _state["headless_mode"] = on
    if on:
        pause_module("opendex_ui", "headless")
    else:
        resume_module("opendex_ui")
    _fire("ui", not on)
    if persist:
        _save(headless_mode=on)
    print(f"[RUNTIME] Headless: {'ACIK' if on else 'KAPALI'}")
    return snapshot()


def show_ui() -> dict:
    """"ALES, ekrani goster" — headless'i gecici olarak kaldirir."""
    return set_headless(False)


# ═════════════════════════════════════════════════════════════════════
# 6) SLEEP MODE
# ═════════════════════════════════════════════════════════════════════
def touch():
    """Herhangi bir kullanici etkilesiminde cagrilir (uyku sayacini sifirlar)."""
    with _lock:
        _state["last_activity"] = time.time()
        was = _state["asleep"]
    if was:
        wake("etkilesim")


def idle_seconds() -> float:
    with _lock:
        return time.time() - _state["last_activity"]


def sleep_now(reason: str = "hareketsizlik") -> dict:
    with _lock:
        if _state["asleep"]:
            return snapshot()
        _state["asleep"] = True
    for name in heavy_local_modules():
        pause_module(name, "sleep")
    pause_module("websocket", "sleep")
    print(f"[RUNTIME] Uyku modu ({reason}).")
    _fire("sleep")
    return snapshot()


def wake(reason: str = "uyandirma") -> dict:
    with _lock:
        if not _state["asleep"]:
            return snapshot()
        _state["asleep"] = False
        _state["last_activity"] = time.time()
    resume_module("websocket")
    if not _state["performance_mode"]:
        for name in heavy_local_modules():
            resume_module(name)
    print(f"[RUNTIME] Uyandi ({reason}).")
    _fire("wake")
    return snapshot()


def check_sleep() -> bool:
    """Periyodik cagrilir (resource_monitor turunda). Suresi dolduysa uyut."""
    with _lock:
        enabled = _state["sleep_mode"]
        asleep = _state["asleep"]
    if enabled and not asleep and idle_seconds() >= SLEEP_AFTER_S:
        sleep_now()
        return True
    return False


def set_sleep_enabled(on: bool) -> dict:
    with _lock:
        _state["sleep_mode"] = bool(on)
    if not on:
        wake("uyku kapatildi")
    _save(sleep_mode=bool(on))
    return snapshot()


# ═════════════════════════════════════════════════════════════════════
# KAYNAK BASKISI KOPRUSU (resource_monitor callback'leri)
# ═════════════════════════════════════════════════════════════════════
def on_resource_degrade(report: dict):
    """Israrli/kritik kaynak asimi -> otomatik dusuk-tuketim moduna gec."""
    with _lock:
        if _state["degraded"]:
            return
        _state["degraded"] = True
    metrics = ", ".join(f"{b['metric'].upper()} %{b['value']}" for b in report.get("breached", []))
    print(f"[RUNTIME] Kaynak baskisi ({metrics}) -> dusuk tuketim moduna geciliyor.")
    set_headless(True, persist=False)          # UI kapan
    pause_module("tts", "kaynak")              # sadece metin cikti
    pause_module("shadowbroker", "kaynak")
    pause_module("websocket", "kaynak")
    for name in heavy_local_modules():
        pause_module(name, "kaynak")


def on_resource_restore(report: dict):
    """Kaynaklar rahatladi -> otomatik dusurulenleri geri ac. Kullanicinin
    KENDI actigi Performance/Headless ayarlarina dokunmayiz."""
    with _lock:
        if not _state["degraded"]:
            return
        _state["degraded"] = False
        perf = _state["performance_mode"]
    print("[RUNTIME] Kaynaklar normale dondu -> moduller geri aciliyor.")
    resume_module("tts")
    resume_module("websocket")
    if not perf:
        set_headless(False, persist=False)
        for name in heavy_local_modules():
            resume_module(name)


# ═════════════════════════════════════════════════════════════════════
def snapshot() -> dict:
    with _lock:
        s = dict(_state)
        s["paused"] = dict(_state["paused"])
    s["idle_s"] = round(idle_seconds(), 1)
    s["sleep_after_s"] = SLEEP_AFTER_S
    s["temp_dir"] = os.environ.get("ALES_TMP", "")
    s["modules"] = [
        {"id": k, "label": v["label"], "available": v["available"],
         "heavy_local": v["heavy_local"], "note": v["note"],
         "paused": bool(s["paused"].get(k))}
        for k, v in MODULES.items()
    ]
    return s
