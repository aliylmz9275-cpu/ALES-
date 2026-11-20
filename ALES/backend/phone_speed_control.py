"""
phone_speed_control.py — ALES telefon/ADB hiz profili ve cihaz ayarlari.

ONEMLI TASARIM (Ali'nin bildirdigi "ayar sifirlaniyor" sorununun kok
cozumu): Ayarlar KISMI (partial) guncellenir. Yani sadece verilen
alanlar degistirilir, DOKUNULMAYAN her alan eski degerini korur. Eskiden
tum ayar objesi bir butun olarak yazildigi icin, bir alani degistirip
kaydedince digerleri (bos gonderildikleri icin) siniyordu. Artik
update_settings() yalnizca gelen anahtarlari uygular.

Tum ayarlar AppData/ALES/phone_speed.json icinde saklanir - uygulama
silinse bile kalir (config_manager ile ayni dizin mantigi).
"""
import json
from pathlib import Path

try:
    from config_manager import get_appdata_dir
    SETTINGS_FILE = get_appdata_dir() / "phone_speed.json"
except Exception:
    SETTINGS_FILE = Path("phone_speed.json")

# ─── HIZ PROFILLERI ──────────────────────────────────────────────
# "En hizli" (turbo): poll araligini dibe cek, buffer'i minimumda tut,
# gereksiz beklemeleri sifirla. "normal"/"safe" daha temkinli.
SPEED_PROFILES = {
    "turbo": {
        "poll_interval_ms": 100,     # UI polling dongusu araligi
        "xml_buffer_s": 0.3,         # uiautomator dump sonrasi XML tampon beklemesi
        "action_gap_s": 0.05,        # ardisik aksiyonlar arasi minimum bosluk
        "max_poll_loops": 40,        # 40 * 100ms = ~4s ust sinir (element bekleme)
        "vision_timeout_s": 7.0,     # gorsel fallback icin sert zaman asimi
        "max_retries": 2,            # self-healing devreye girmeden once deneme
    },
    "normal": {
        "poll_interval_ms": 250,
        "xml_buffer_s": 0.3,
        "action_gap_s": 0.2,
        "max_poll_loops": 30,
        "vision_timeout_s": 9.0,
        "max_retries": 3,
    },
    "safe": {
        "poll_interval_ms": 500,
        "xml_buffer_s": 0.5,
        "action_gap_s": 0.5,
        "max_poll_loops": 20,
        "vision_timeout_s": 12.0,
        "max_retries": 3,
    },
}

DEFAULT_SETTINGS = {
    # Cihaz
    "adb_serial": "",            # bos = ilk bagli cihaz otomatik
    "adb_path": "adb",           # PATH'te degilse tam yol verilebilir
    # Hiz
    "speed_profile": "turbo",    # Ali'nin istegi: "yapabilecegin en hizli"
    # Model (advisor / vision)
    "model_mode": "auto",        # auto = once Ollama, sonra bulut
    "ollama_url": "http://localhost:11434",
    "ollama_model": "qwen2.5-coder:7b",
    "ollama_vision_model": "qwen2.5-coder:7b",
    # Twitter ban korumasi
    "twitter_follow_limit": 10,
    "twitter_cooldown_s": 300,
    # Ses
    "voice_enabled": True,       # sesli konusma modu acik/kapali (buton ile degisir)
    "voice_streaming": True,     # kelime kelime akan TTS
    # Otomasyon
    "adaptive_latency": True,    # ag gecikmesine gore poll araligini ayarla
}


def _read() -> dict:
    if SETTINGS_FILE.exists():
        try:
            return json.loads(SETTINGS_FILE.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {}


def load_settings() -> dict:
    """Kaydedilmis ayarlari (varsa) DEFAULT_SETTINGS uzerine bindirerek
    doner - yeni bir ayar alani eklendiginde eski dosyalar da bozulmadan
    varsayilani alir."""
    merged = dict(DEFAULT_SETTINGS)
    merged.update(_read())
    return merged


def save_settings(settings: dict):
    """Ayarlarin TAMAMINI yazar (dahili kullanim). Panelden gelen kismi
    guncellemeler icin update_settings kullanilmali."""
    SETTINGS_FILE.write_text(json.dumps(settings, ensure_ascii=False, indent=2), encoding="utf-8")


def update_settings(patch: dict) -> dict:
    """
    KISMI guncelleme - "ayar sifirlaniyor" sorununun cozumu.

    Yalnizca `patch` icinde GERCEKTEN gelen (None olmayan) anahtarlari
    uygular; digerleri eski degerini korur. Bos string ("") de gecerli bir
    deger sayilir SADECE metin alanlarinda degil - ama None her zaman
    "dokunma" anlamina gelir. Boylece Ali bir alani degistirip kaydettiginde
    diger alanlar asla sifirlanmaz.
    """
    current = load_settings()
    for k, v in (patch or {}).items():
        if v is None:
            continue  # "dokunulmadi" -> eski deger korunur
        current[k] = v
    save_settings(current)
    return current


def get_active_profile() -> dict:
    """Aktif hiz profilinin parametrelerini doner. Kullanici tekil alanlari
    (orn. poll_interval_ms) settings icinde override etmisse onlar da
    profilin uzerine bindirilir."""
    s = load_settings()
    profile = dict(SPEED_PROFILES.get(s.get("speed_profile", "turbo"), SPEED_PROFILES["turbo"]))
    for k in ("poll_interval_ms", "xml_buffer_s", "action_gap_s",
              "max_poll_loops", "vision_timeout_s", "max_retries"):
        if k in s and isinstance(s[k], (int, float)):
            profile[k] = s[k]
    return profile


# ─── SES MODU (buton ile ac/kapa) ────────────────────────────────
def is_voice_enabled() -> bool:
    return bool(load_settings().get("voice_enabled", True))


def set_voice_enabled(enabled: bool) -> dict:
    """Sesli konusma modunu ac/kapat. Frontend'deki kucuk butona baglidir.
    Diger ayarlara DOKUNMAZ (partial update)."""
    return update_settings({"voice_enabled": bool(enabled)})


def toggle_voice() -> dict:
    return set_voice_enabled(not is_voice_enabled())
