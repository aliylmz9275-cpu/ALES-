"""
credentials.py — ALES kimlik bilgisi yoneticisi (Windows Credential Manager).

NEDEN: Su anda API key'leri config.json'da DUZ METIN duruyor; profil/hesap
sifreleri de oyle saklanacakti. Bu hem ALES'in kendi kuralina aykiri
("ASLA kaydetme: sifre, API key, ozel/mahrem bilgi") hem de dosya yedege,
buluta ya da bir depoya sizdiginda dogrudan hesap kaybi demek.

COZUM: Sirlar isletim sisteminin kasasinda tutulur. Windows'ta bu
Credential Manager'dir (DPAPI ile kullanici hesabina bagli sifrelenir);
macOS'ta Keychain, Linux'ta Secret Service. `keyring` kutuphanesi bu
farklari soyutlar.

TASARIM:
  * keyring YOKSA ALES calismaya devam eder — sadece kasa devre disi olur
    ve mevcut config.json/env davranisi surer (get_key zaten env'e duser).
  * OKUMA sirasi: kasa -> config.json -> ortam degiskeni. Boylece tasima
    kademeli yapilabilir; bir anda her seyi kirmaz.
  * Bu modul sirlari ASLA loglamaz/yazdirmaz. Sadece "var/yok" ve maskeli
    onizleme (son 4 karakter) doner.
"""

import os

SERVICE = "ALES"

try:
    import keyring
    from keyring.errors import KeyringError
    _HAS_KEYRING = True
except Exception:                                    # pragma: no cover
    keyring = None
    KeyringError = Exception
    _HAS_KEYRING = False


# Kasanin GERCEKTEN calistigi bir kez olculur ve onbelleklenir.
# None = henuz denenmedi | True/False = probe sonucu.
_vault_ok = None
_PROBE_NAME = "__ales_vault_probe__"


def _probe() -> bool:
    """Tek seferlik GERCEK yaz/oku/sil denemesi.

    Yalnizca kendi sentinel kaydini kullanir, sonunda siler — gercek
    sirlara DOKUNMAZ. available()/set_secret()/get_secret() gibi
    sarmalayicilari cagirmaz, dogrudan keyring'e gider: yoksa
    available() -> _probe -> set_secret -> available() sonsuz dongusu olurdu."""
    if not _HAS_KEYRING:
        return False
    sentinel = "ok"
    got = None
    try:
        backend = keyring.get_keyring()
        if backend is None or "fail" in backend.__class__.__name__.lower():
            return False
        keyring.set_password(SERVICE, _PROBE_NAME, sentinel)
        got = keyring.get_password(SERVICE, _PROBE_NAME)
    except Exception:
        return False
    finally:
        # Sentinel HER durumda temizlenmeye calisilir (yarim kayit kalmasin);
        # silme hatasi probe sonucunu etkilemez.
        try:
            keyring.delete_password(SERVICE, _PROBE_NAME)
        except Exception:
            pass
    return got == sentinel


def available(force: bool = False) -> bool:
    """Kasa GERCEKTEN kullanilabilir mi?

    ESKI HALI YANLIS YESIL VERIYORDU: sadece backend sinif adinda 'fail'
    gecip gecmedigine bakiyordu. Oysa `ChainerBackend` gibi bir backend'in
    adinda 'fail' YOKTUR ama hicbir alt backend'i calismiyor olabilir; ya da
    Credential Manager politika/kullanici profili yuzunden erisilemez
    olabilir. O durumda available() True der, hemen ardindan set_secret()
    sessizce False doner -> cagiran "kasa var" sanip yazdigini kaybeder.

    Bu yuzden sinif adina degil GERCEK bir yaz/oku/sil denemesine bakilir.
    Sonuc surec boyunca onbelleklenir (her cagride kasaya gitmek pahali);
    force=True ile yeniden olculur."""
    global _vault_ok
    if not _HAS_KEYRING:
        return False
    if _vault_ok is None or force:
        _vault_ok = _probe()
        if not _vault_ok:
            print("[CRED] Kasa erisilemez (probe basarisiz) -> "
                  "config.json/ortam degiskeni kullanilacak.")
    return _vault_ok


def backend_name() -> str:
    if not _HAS_KEYRING:
        return "yok (keyring kurulu degil)"
    try:
        name = keyring.get_keyring().__class__.__name__
    except Exception:
        return "bilinmiyor"
    # Probe basarisiz olduysa bunu SOYLE: sadece "WinVaultKeyring" gorup
    # kasanin calistigini sanmak tam olarak duzeltilen yanlis yesildi.
    if _vault_ok is False:
        return f"{name} (erisilemez)"
    return name


# ═════════════════════════════════════════════════════════════════════
# TEMEL OKUMA / YAZMA
# ═════════════════════════════════════════════════════════════════════
def set_secret(name: str, value: str) -> bool:
    """Sirri kasaya yaz. Basarisizsa False (cagiran karar verir)."""
    if not name or value is None:
        return False
    if not available():
        return False
    try:
        keyring.set_password(SERVICE, name, str(value))
        return True
    except KeyringError as e:
        print(f"[CRED] Kasaya yazilamadi ({name}): {type(e).__name__}")
        return False
    except Exception as e:
        print(f"[CRED] Kasa hatasi ({name}): {type(e).__name__}")
        return False


def get_secret(name: str, fallback_config_key: str = None) -> str:
    """Sirri getir. Sira: kasa -> config.json -> ortam degiskeni.
    Hicbiri yoksa bos string."""
    if available():
        try:
            val = keyring.get_password(SERVICE, name)
            if val:
                return val
        except Exception:
            pass
    # geriye donuk uyumluluk: mevcut config.json / env yolu
    try:
        from config_manager import get_key
        val = get_key(fallback_config_key or name)
        if val:
            return val
    except Exception:
        pass
    return (os.environ.get(name.upper()) or "").strip()


def delete_secret(name: str) -> bool:
    if not available():
        return False
    try:
        keyring.delete_password(SERVICE, name)
        return True
    except Exception:
        return False


def has_secret(name: str) -> bool:
    if not available():
        return False
    try:
        return bool(keyring.get_password(SERVICE, name))
    except Exception:
        return False


def mask(value: str) -> str:
    """Loglanabilir maskeli gosterim: 'sk-...4f2a' gibi. Sirri ifsa etmez."""
    if not value:
        return ""
    v = str(value)
    return f"...{v[-4:]}" if len(v) > 8 else "****"


# ═════════════════════════════════════════════════════════════════════
# config.json -> kasa TASIMA
# ═════════════════════════════════════════════════════════════════════
# Tasinacak bilinen key alanlari (config_manager._ENV_KEY_MAP ile ayni set).
KNOWN_KEYS = [
    "groq_key", "cerebras_key", "gemini_key", "openrouter_key",
    "nvidia_key", "sambanova_key", "elevenlabs_key",
]


def audit() -> dict:
    """config.json'da DUZ METIN duran sir var mi? Degerleri DONDURMEZ,
    sadece nerede oldugunu ve maskeli onizlemesini bildirir."""
    try:
        from config_manager import load_config
        cfg = load_config() or {}
    except Exception:
        cfg = {}
    findings = []
    for k in KNOWN_KEYS:
        raw = (cfg.get(k) or "").strip()
        findings.append({
            "key": k,
            "in_config_plaintext": bool(raw),
            "in_vault": has_secret(k),
            "preview": mask(raw) if raw else "",
        })
    exposed = [f["key"] for f in findings if f["in_config_plaintext"]]
    return {
        "vault_available": available(),
        "backend": backend_name(),
        "findings": findings,
        "exposed_count": len(exposed),
        "exposed": exposed,
    }


def migrate_to_vault(remove_from_config: bool = True) -> dict:
    """config.json'daki duz metin sirlari kasaya tasi.

    remove_from_config=True ise tasima BASARILI olan alan config.json'dan
    SILINIR (asil amac bu). Kasa yoksa hicbir sey silinmez — sirri
    kaybetmemek her zaman onceliklidir.

    NOT: Tasima sonrasi bu key'lerin saglayici panelinden YENILENMESI
    (rotate) yine de onerilir; dosyada bir kez duz metin durduysa
    yedeklerde/depoda kopyasi kalmis olabilir.
    """
    if not available():
        return {"ok": False, "error": "Kasa kullanilamiyor (keyring yok/backend yok).",
                "backend": backend_name(), "migrated": [], "failed": []}
    try:
        from config_manager import load_config, save_config
        cfg = load_config() or {}
    except Exception as e:
        return {"ok": False, "error": f"config okunamadi: {e}", "migrated": [], "failed": []}

    migrated, failed = [], []
    for k in KNOWN_KEYS:
        raw = (cfg.get(k) or "").strip()
        if not raw:
            continue
        if set_secret(k, raw):
            migrated.append(k)
            if remove_from_config:
                cfg[k] = ""
        else:
            failed.append(k)
    if migrated and remove_from_config:
        try:
            save_config(cfg)
        except Exception as e:
            return {"ok": False, "error": f"config yazilamadi: {e}",
                    "migrated": migrated, "failed": failed}
    return {"ok": True, "migrated": migrated, "failed": failed,
            "backend": backend_name(),
            "note": "Tasinan key'leri saglayici panelinden yenilemeniz (rotate) onerilir."}


# ═════════════════════════════════════════════════════════════════════
# PROFIL (hesap) SIFRELERI — profiles.json'a ASLA duz metin yazma
# ═════════════════════════════════════════════════════════════════════
def profile_secret_name(profile_id: str, field: str = "password") -> str:
    return f"profile:{profile_id}:{field}"


def set_profile_password(profile_id: str, password: str) -> bool:
    """Profil sifresini kasaya yaz. profiles.json'da sadece profil KIMLIGI
    durur, sifre asla dosyaya yazilmaz."""
    return set_secret(profile_secret_name(profile_id), password)


def get_profile_password(profile_id: str) -> str:
    return get_secret(profile_secret_name(profile_id)) if available() else ""


def delete_profile_password(profile_id: str) -> bool:
    return delete_secret(profile_secret_name(profile_id))
