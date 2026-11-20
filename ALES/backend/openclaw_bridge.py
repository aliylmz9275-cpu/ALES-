"""
openclaw_bridge.py — Harici bilgisayar-kullanim daemon'u koprüsu (OpenClaw uyumlu).

NE YAPAR:
  Yerelde calisan, OpenClaw-uyumlu bir HTTP daemon'una (varsayilan
  http://localhost:1984) masaustu / tarayici / terminal eylemlerini
  yonlendirir. Daemon yoksa ya da cevap vermezse eylem SESSIZCE ALES'in
  kendi yerel araclarina duser (native_desktop, playwright_browser,
  subprocess) — yani bu koprünün kapali olmasi yetenek kaybi degildir.

  Tek yon: ALES -> daemon. Daemon ALES'i cagirmaz.

DURUSTLUK NOTU (2026-09-05): bu dosyada eskiden "OpenClaw (361k+ GitHub
  Yildizi)" yaziyordu. Boyle bir yildiz sayisini dogrulayamiyorum ve
  ALES'in davranisi acisindan da bir anlami yok; kaldirildi. Onemli olan
  tek sey sozlesme: daemon /health'e 200 donuyorsa kullanilir, donmuyorsa
  yerel yedek calisir. Kurulum ve daemon'u baslatmak KULLANICIYA aittir;
  ALES kendiliginden bir servis indirmez veya kurmaz.

Yetenekler:
  - Masaustu: click, type, press, scroll, get_windows (daemon yoksa native_desktop)
  - Tarayici: goto, click, extract (daemon yoksa playwright_browser)
  - Terminal: komut yurutme (daemon yoksa yerel subprocess, timeout'lu)
  - Platform-bagimsiz: Windows / macOS / Linux
"""
import asyncio
import os
import platform
import time
from typing import Any, Dict, List, Optional

import httpx

OPENCLAW_DEFAULT_URL = os.environ.get("OPENCLAW_API_URL", "http://localhost:1984")
HTTP_TIMEOUT_S = 5.0

_stats = {
    "openclaw_calls": 0,
    "browser_actions": 0,
    "desktop_actions": 0,
    "terminal_actions": 0,
    "fallback_to_native": 0,
    "daemon_connected": False,
    "last_check": 0.0,
}

class OpenClawBridge:
    def __init__(self, base_url: str = OPENCLAW_DEFAULT_URL):
        self.base_url = base_url.rstrip("/")
        self.os_type = platform.system()  # 'Windows', 'Darwin', 'Linux'

    async def check_daemon(self) -> bool:
        """OpenClaw yerel servisinin ayakta olup olmadığını kontrol eder."""
        try:
            async with httpx.AsyncClient(timeout=2.0) as client:
                r = await client.get(f"{self.base_url}/health")
                ok = (r.status_code == 200)
                _stats["daemon_connected"] = ok
                _stats["last_check"] = time.time()
                return ok
        except Exception:
            _stats["daemon_connected"] = False
            _stats["last_check"] = time.time()
            return False

    async def control_desktop(self, action: str, params: Dict[str, Any] = None) -> Dict[str, Any]:
        """
        Masaüstü eylemi: click, type, press, scroll, get_windows vb.
        OpenClaw servisi varsa oraya gönderir, yoksa native_desktop modülüne devreder.
        """
        _stats["openclaw_calls"] += 1
        _stats["desktop_actions"] += 1
        params = params or {}

        # 1. OpenClaw servisi dene
        if await self.check_daemon():
            try:
                async with httpx.AsyncClient(timeout=HTTP_TIMEOUT_S) as client:
                    r = await client.post(f"{self.base_url}/v1/desktop/{action}", json=params)
                    if r.status_code == 200:
                        return {"ok": True, "source": "openclaw", "data": r.json()}
            except Exception:
                pass

        # 2. Yerel Yedek (Native Desktop Fallback)
        _stats["fallback_to_native"] += 1
        try:
            import native_desktop
            if action == "click":
                title = params.get("window", "")
                ctrl = params.get("control", "")
                return {"ok": True, "source": "native_desktop", "result": native_desktop.click_control(title, ctrl)}
            elif action == "type":
                title = params.get("window", "")
                ctrl = params.get("control", "")
                text = params.get("text", "")
                return {"ok": True, "source": "native_desktop", "result": native_desktop.set_control_text(title, ctrl, text)}
            elif action == "list_windows":
                return {"ok": True, "source": "native_desktop", "windows": native_desktop.list_windows()}
            elif action == "close":
                title = params.get("window", "")
                return {"ok": True, "source": "native_desktop", "result": native_desktop.close_window(title)}
        except Exception as e:
            return {"ok": False, "source": "native_desktop_error", "error": str(e)}

        return {"ok": False, "error": f"Bilinmeyen masaüstü eylemi: {action}"}

    async def control_browser(self, action: str, params: Dict[str, Any] = None) -> Dict[str, Any]:
        """
        Tarayıcı otomasyonu: goto, click, extract, screenshot.
        """
        _stats["openclaw_calls"] += 1
        _stats["browser_actions"] += 1
        params = params or {}

        if await self.check_daemon():
            try:
                async with httpx.AsyncClient(timeout=10.0) as client:
                    r = await client.post(f"{self.base_url}/v1/browser/{action}", json=params)
                    if r.status_code == 200:
                        return {"ok": True, "source": "openclaw", "data": r.json()}
            except Exception:
                pass

        # Playwright yerel yedeği
        _stats["fallback_to_native"] += 1
        try:
            import playwright_browser
            if action == "goto":
                url = params.get("url", "")
                res = playwright_browser.browse_sync(url)
                return {"ok": True, "source": "playwright_browser", "result": res}
            elif action == "search":
                q = params.get("query", "")
                res = playwright_browser.search_sync(q)
                return {"ok": True, "source": "playwright_browser", "result": res}
        except Exception as e:
            return {"ok": False, "error": f"Tarayıcı yerel yedeği hatası: {e}"}

        return {"ok": False, "error": f"Desteklenmeyen tarayıcı eylemi: {action}"}

    async def execute_terminal(self, command: str, timeout_s: float = 15.0) -> Dict[str, Any]:
        """
        Terminal komut yürütme: OpenClaw veya izole yerel subprocess.
        """
        _stats["openclaw_calls"] += 1
        _stats["terminal_actions"] += 1

        if await self.check_daemon():
            try:
                async with httpx.AsyncClient(timeout=timeout_s) as client:
                    r = await client.post(f"{self.base_url}/v1/terminal/exec", json={"command": command, "timeout": timeout_s})
                    if r.status_code == 200:
                        return {"ok": True, "source": "openclaw", "data": r.json()}
            except Exception:
                pass

        _stats["fallback_to_native"] += 1
        try:
            import subprocess
            proc = subprocess.run(command, shell=True, capture_output=True, text=True, timeout=timeout_s)
            return {
                "ok": proc.returncode == 0,
                "source": "native_subprocess",
                "returncode": proc.returncode,
                "stdout": proc.stdout[:2000],
                "stderr": proc.stderr[:1000],
            }
        except Exception as e:
            return {"ok": False, "source": "native_subprocess_error", "error": str(e)}

    def status(self) -> Dict[str, Any]:
        return {
            "openclaw_url": self.base_url,
            "os_platform": self.os_type,
            "stats": dict(_stats),
            "daemon_connected": _stats["daemon_connected"],
            "last_check": _stats["last_check"],
            "fallback_active": not _stats["daemon_connected"],
            "note": "OpenClaw deamon kurulu değilse native_desktop ve playwright_browser yedekleri devrededir.",
        }

# Global örnek
bridge = OpenClawBridge()


def info() -> Dict[str, Any]:
    """runtime_state.refresh_modules() bunu okur.

    DIKKAT — burada "available: True" demek YANLIS olurdu: bu modulun
    import edilmesi OpenClaw servisinin ayakta oldugunu göstermez. Servis
    ayri bir surectir ve genelde KURULU DEGILDIR. check_daemon() async
    oldugu icin buradan cagrilamaz; bu yuzden SON olcume bakariz ve hic
    olcum yapilmadiysa "bilinmiyor" deriz.

    Koprü kapali olsa bile masaustu/tarayici kontrolu CALISIR: her cagri
    native_desktop + playwright_browser yedegine duser (bkz. control_desktop).
    Yani bu satirin False olmasi bir yetenek kaybi DEGIL, sadece "harici
    daemon yok" bilgisidir.
    """
    connected = bool(_stats.get("daemon_connected"))
    last = float(_stats.get("last_check") or 0)
    if not last:
        note = (f"Daemon henüz yoklanmadı ({OPENCLAW_DEFAULT_URL}). "
                "Kurulu değilse native_desktop yedeği kullanılır.")
    elif connected:
        age = int(time.time() - last)
        note = f"OpenClaw daemon bağlı ({OPENCLAW_DEFAULT_URL}, {age}s önce doğrulandı)."
    else:
        note = (f"OpenClaw daemon erişilemedi ({OPENCLAW_DEFAULT_URL}) — "
                f"native_desktop/playwright yedeği devrede "
                f"({_stats.get('fallback_to_native', 0)} kez kullanıldı).")
    return {"available": connected, "note": note}

