"""
browser_profiles.py — izole tarayici profilleri (gizlilik + test amacli).

AMAC: Birbirinden tamamen yalitilmis tarayici oturumlari. Her profilin
kendi cerezleri, localStorage'i ve onbellegi vardir; biri digerinin
oturumunu goremez. Iki mesru kullanim:

  1. GIZLILIK: is/kisisel gezintiyi ayirmak — bir sitedeki oturum baska
     profildeki gezintiyi izleyemez.
  2. TEST: kendi sitenizi ayni anda farkli rollerde (admin / normal
     kullanici / cikis yapmis ziyaretci) acip davranisini karsilastirmak.

── KAPSAM SINIRI (bilerek) ─────────────────────────────────────────────
Bu modul PARMAK IZI SAHTECILIGI (fingerprint spoofing) ya da proxy
rotasyonu YAPMAZ ve coklu hesap otomasyonu icin tasarlanmamistir. Yalnizca
depolama yalitimi + acik, durust bir tarayici oturumu saglar. Kimlik
bilgisi gerekiyorsa credentials.py (isletim sistemi kasasi) kullanilir;
profil dosyalarina ASLA sifre yazilmaz.

Playwright kurulu degilse modul yine import edilir; launch() anlamli bir
hata dondurur (ALES cokmeye devam etmez).
"""

import json
import shutil
from datetime import datetime
from pathlib import Path

try:
    from config_manager import APPDATA
    BASE_DIR = APPDATA / "browser_profiles"
except Exception:
    BASE_DIR = Path("browser_profiles")

PROFILES_FILE = BASE_DIR / "profiles.json"


def _ensure_dir() -> Path:
    BASE_DIR.mkdir(parents=True, exist_ok=True)
    return BASE_DIR


# ═════════════════════════════════════════════════════════════════════
# PROFIL KAYIT DEFTERI  (sir ICERMEZ)
# ═════════════════════════════════════════════════════════════════════
def load_profiles() -> dict:
    _ensure_dir()
    if PROFILES_FILE.exists():
        try:
            return json.loads(PROFILES_FILE.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {"profiles": []}


def save_profiles(data: dict):
    _ensure_dir()
    PROFILES_FILE.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def list_profiles() -> list:
    out = []
    for p in load_profiles().get("profiles", []):
        d = BASE_DIR / p["id"]
        out.append({
            **p,
            "exists": d.exists(),
            "size_mb": round(sum(f.stat().st_size for f in d.rglob("*") if f.is_file()) / 1048576, 2)
                       if d.exists() else 0.0,
        })
    return out


def create_profile(profile_id: str, label: str = "", note: str = "") -> dict:
    """Yeni izole profil olustur. profile_id dosya adi olarak kullanilir."""
    pid = "".join(c for c in (profile_id or "").strip() if c.isalnum() or c in "-_")
    if not pid:
        return {"ok": False, "error": "Gecersiz profil kimligi"}
    data = load_profiles()
    if any(p["id"] == pid for p in data["profiles"]):
        return {"ok": False, "error": f"'{pid}' zaten var"}
    (BASE_DIR / pid).mkdir(parents=True, exist_ok=True)
    entry = {
        "id": pid,
        "label": label or pid,
        "note": note,
        "created": datetime.now().isoformat(),
    }
    data["profiles"].append(entry)
    save_profiles(data)
    return {"ok": True, "profile": entry}


def delete_profile(profile_id: str, wipe: bool = True) -> dict:
    """Profili kayittan sil; wipe=True ise diskteki verisini de sil."""
    data = load_profiles()
    before = len(data["profiles"])
    data["profiles"] = [p for p in data["profiles"] if p["id"] != profile_id]
    if len(data["profiles"]) == before:
        return {"ok": False, "error": "Profil bulunamadi"}
    save_profiles(data)
    if wipe:
        try:
            shutil.rmtree(BASE_DIR / profile_id, ignore_errors=True)
        except Exception as e:
            return {"ok": True, "warning": f"Kayit silindi ama dosyalar kalmis olabilir: {e}"}
    return {"ok": True}


def clear_profile_data(profile_id: str) -> dict:
    """Profilin cerez/depolama verisini temizle (profil kaydi kalir).
    'Bu profilde her yerden cikis yap' anlamina gelir."""
    d = BASE_DIR / profile_id
    if not d.exists():
        return {"ok": False, "error": "Profil dizini yok"}
    try:
        shutil.rmtree(d, ignore_errors=True)
        d.mkdir(parents=True, exist_ok=True)
        return {"ok": True}
    except Exception as e:
        return {"ok": False, "error": str(e)}


# ═════════════════════════════════════════════════════════════════════
# TARAYICI BASLATMA (Playwright kalici baglam)
# ═════════════════════════════════════════════════════════════════════
async def launch(profile_id: str, headless: bool = False, viewport: dict = None):
    """Profili kendi KALICI baglaminda ac (cerezler diskte kalir, bir
    sonraki acilista oturum korunur). Doner: (context, playwright) —
    cagiran ikisini de kapatmali:  await ctx.close(); await pw.stop()

    Kasitli olarak sade: user-agent/timezone/locale sahteciligi yok,
    proxy yok. Yalitim depolama duzeyindedir."""
    d = BASE_DIR / profile_id
    if not d.exists():
        return None, None, f"Profil yok: {profile_id}"
    try:
        from playwright.async_api import async_playwright
    except Exception:
        return None, None, ("Playwright kurulu degil. Kurulum: "
                            "pip install playwright && playwright install chromium")
    try:
        pw = await async_playwright().start()
        ctx = await pw.chromium.launch_persistent_context(
            user_data_dir=str(d),
            headless=headless,
            viewport=viewport or {"width": 1280, "height": 800},
        )
        return ctx, pw, None
    except Exception as e:
        return None, None, f"Tarayici acilamadi: {e}"


async def open_url(profile_id: str, url: str, headless: bool = False):
    """Tek seferlik yardimci: profili ac, adrese git, sayfayi dondur."""
    ctx, pw, err = await launch(profile_id, headless=headless)
    if err:
        return {"ok": False, "error": err}
    try:
        page = ctx.pages[0] if ctx.pages else await ctx.new_page()
        await page.goto(url, wait_until="domcontentloaded", timeout=30000)
        return {"ok": True, "title": await page.title(), "url": page.url,
                "_ctx": ctx, "_pw": pw}
    except Exception as e:
        try:
            await ctx.close(); await pw.stop()
        except Exception:
            pass
        return {"ok": False, "error": str(e)}
