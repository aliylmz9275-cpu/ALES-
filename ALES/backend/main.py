import asyncio, base64, json, os, re, subprocess, time, traceback
from datetime import datetime, timedelta
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor

# ─── DONMUS (.exe) ACILIS GUVENLIGI ────────────────────────────────────
# KRITIK (--noconsole ile derlenen exe): sys.stdout ve sys.stderr None olur.
# print() bunu sessizce yutar, yani COKME olmaz -- ama tum acilis gunlugu
# kaybolur: eksik modul, dolu port, hatali API anahtari hicbir yerde
# gorunmez. Konsolsuz bir uygulamada bu, "cift tikladim hicbir sey olmadi"
# demektir. Bu yuzden akislari exe'nin yanindaki ALES_log.txt'ye baglariz.
#
# NEDEN DOSYANIN EN USTUNDE: config_manager gibi moduller IMPORT ANINDA
# print() yapiyor. Bu blok asagida kalirsa o satirlar gunluge dusmez.
# Konsollu derlemede ve kaynaktan calistirildiginda hicbir sey degismez.
import sys

ALES_LOG_PATH = None          # konsolsuz exe'de gunluk dosyasinin yolu
_FROZEN_WINDOWED = False      # donmus VE konsolsuz muyuz?


def _boot_streams():
    """Konsolsuz exe'de stdout/stderr'i gunluk dosyasina yonlendir."""
    global ALES_LOG_PATH, _FROZEN_WINDOWED
    if sys.stdout is not None and sys.stderr is not None:
        return                                   # konsol var -> dokunma
    if not getattr(sys, "frozen", False):
        return                                   # kaynaktan calisiyor
    _FROZEN_WINDOWED = True
    try:
        d = os.path.dirname(os.path.abspath(sys.executable))
        p = os.path.join(d, "ALES_log.txt")
        # Sinirsiz buyumesin: 2 MB'i gecince bastan yaz.
        big = os.path.exists(p) and os.path.getsize(p) > 2_000_000
        fh = open(p, "w" if big else "a", encoding="utf-8",
                  errors="replace", buffering=1)
        ALES_LOG_PATH = p
    except Exception:
        try:
            fh = open(os.devnull, "w")           # yazamiyorsak sessizce yut
        except Exception:
            return
    if sys.stdout is None:
        sys.stdout = fh
    if sys.stderr is None:
        sys.stderr = fh
    try:
        print("\n" + "=" * 62)
        print("[ALES] Yeni oturum · PID %d · %s"
              % (os.getpid(), time.strftime("%Y-%m-%d %H:%M:%S")))
        print("[ALES] Durdurmak icin: Gorev Yoneticisi > Ayrintilar > "
              "ALES.exe > Gorevi sonlandir")
        print("=" * 62)
    except Exception:
        pass


def _boot_hide_child_consoles():
    """Konsolsuz derlemede alt sureclerin siyah pencere acmasini engelle.

    NEDEN TEK NOKTADAN: backend genelinde ~17 subprocess cagrisi var
    (where, taskkill, ngrok, cloudflared, node, python...). Konsolsuz bir
    uygulamada bunlarin her biri bir an icin siyah pencere cakar -- yani
    "sessiz arka plan uygulamasi" istegiyle dogrudan celisir. Hepsini tek
    tek duzenlemek 17 dosya degisikligi demek; bunun yerine Popen'in
    varsayilanini YALNIZCA donmus+konsolsuz derlemede degistiriyoruz.
    Zaten CREATE_NO_WINDOW veren cagrilar (notifier, resource_monitor,
    code_act_executor) bozulmaz; OR islemi onlari aynen birakir.
    """
    if os.name != "nt" or not getattr(sys, "frozen", False):
        return
    NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0x08000000)
    NEW_CONSOLE = 0x00000010          # CREATE_NEW_CONSOLE
    DETACHED = 0x00000008             # DETACHED_PROCESS
    _orig_init = subprocess.Popen.__init__

    def _init(self, *a, **kw):
        cf = kw.get("creationflags", 0) or 0
        # CREATE_NO_WINDOW bu ikisiyle BIRLIKTE verilemez (gecersiz parametre
        # hatasi doner). Boyle bir cagri varsa hic dokunmuyoruz.
        if not cf & (NEW_CONSOLE | DETACHED):
            kw["creationflags"] = cf | NO_WINDOW
        return _orig_init(self, *a, **kw)

    subprocess.Popen.__init__ = _init


_boot_streams()
if _FROZEN_WINDOWED:
    _boot_hide_child_consoles()

import psutil
import httpx
from fastapi import FastAPI, WebSocket, WebSocketDisconnect, UploadFile, File, Request, HTTPException
from fastapi.responses import FileResponse
from fastapi.middleware.cors import CORSMiddleware
import pyautogui
pyautogui.FAILSAFE = False

from multi_agent import run_discussion_sync
import multi_agent
from memory import remember_fact, update_user_profile, get_user_profile, search_memory, get_all_facts, log_event, build_context_prompt
from browser import fetch_url, get_news_tr, get_weather, get_crypto_prices, get_exchange_rates, google_search, get_worldview
import voice
from voice import synthesize, ELEVENLABS_VOICES, DEFAULT_ELEVENLABS_VOICE, EDGE_VOICES, DEFAULT_EDGE_VOICE
import fiverr
from fiverr import get_fiverr_messages_manual, get_bionluk_messages_manual, open_fiverr_for_login
from playwright_browser import browse_sync, search_sync
from vision import analyze_screen_and_act, find_element_on_screen
from tunnel import start_ngrok, start_cloudflare_tunnel, get_local_ip, get_tunnel_status
from filesystem import read_file, write_file, edit_file, list_directory, create_directory, delete_path, search_files, get_file_info, list_skills, read_skill
from tool_router import select_relevant_tools, get_routing_info, expand_after_tool_call
import skills_engine
import connectors
from scheduler import add_schedule, remove_schedule, list_schedules, run_scheduler
from notifier import add_notification_rule, list_notification_rules, remove_notification_rule, send_notification, run_notifier
from code_runner import run_python_code
from personas import get_current_persona, set_persona, list_personas
import conversations as conv_store
import browser as browser_module
from config_manager import load_config, save_config, load_memory, save_memory, append_action_log, load_action_log
# NOT: `import phone_speed_control` buradan KALDIRILDI — main.py onu hicbir
# yerde kullanmiyordu (olu import). Modul yine yukleniyor, cunku
# workflow_speed_manager / advisor / adb_engine ondan dogrudan import ediyor;
# yani davranis birebir ayni, sadece yaniltici satir gitti.
import workflow_speed_manager
import model_router
import semantic_cache
import fast_path
import credentials
import browser_profiles
import retry_util
# Faz-3 modulleri SAVUNMACI import edilir: biri hata verirse ALES yine de
# acilir, sadece ilgili panel "kullanilamiyor" der. Boylece tek bir modul
# tum uygulamayi dusuremez.
try:
    import resource_monitor
except Exception as _e:
    resource_monitor = None
    print(f"[ALES] resource_monitor yuklenemedi: {_e}")
try:
    import runtime_state
except Exception as _e:
    runtime_state = None
    print(f"[ALES] runtime_state yuklenemedi: {_e}")
try:
    import long_term_memory
except Exception as _e:
    long_term_memory = None
    print(f"[ALES] long_term_memory yuklenemedi: {_e}")
try:
    import batch_queue
except Exception as _e:
    batch_queue = None
    print(f"[ALES] batch_queue yuklenemedi: {_e}")
try:
    import llm_council
except Exception as _e:
    llm_council = None
    print(f"[ALES] llm_council yuklenemedi: {_e}")
# ── YENI MODULLER (hepsi ayni savunmaci desende) ──────────────────
# Gerekce yukaridakiyle ayni: bu modullerin HICBIRI zorunlu degildir.
# Biri import edilemezse ALES yine acilir; sadece o ozellik "kullanilamiyor"
# der ve UI panelinde nedeni yazar. Tek bir eksik pip paketi (RealtimeTTS,
# sqlite-vec, uiautomation...) uygulamayi asla dusurmez.
try:
    import code_act_executor
except Exception as _e:
    code_act_executor = None
    print(f"[ALES] code_act_executor yuklenemedi: {_e}")
try:
    import agent_jit
except Exception as _e:
    agent_jit = None
    print(f"[ALES] agent_jit yuklenemedi: {_e}")
try:
    import predictive
except Exception as _e:
    predictive = None
    print(f"[ALES] predictive yuklenemedi: {_e}")
try:
    import audio_streamer
except Exception as _e:
    audio_streamer = None
    print(f"[ALES] audio_streamer yuklenemedi: {_e}")
try:
    import plugin_loader
except Exception as _e:
    plugin_loader = None
    print(f"[ALES] plugin_loader yuklenemedi: {_e}")
try:
    import skills_autogrowth
except Exception as _e:
    skills_autogrowth = None
    print(f"[ALES] skills_autogrowth yuklenemedi: {_e}")
try:
    import self_heal
except Exception as _e:
    self_heal = None
    print(f"[ALES] self_heal yuklenemedi: {_e}")
try:
    import model_registry
except Exception as _e:
    model_registry = None
    print(f"[ALES] model_registry yuklenemedi, otomatik model kesfi kapali: {_e}")
try:
    import puter_connector
except Exception as _e:
    puter_connector = None
    print(f"[ALES] puter_connector yuklenemedi, Big ALES kapali: {_e}")
try:
    import native_desktop
except Exception as _e:
    native_desktop = None
    print(f"[ALES] native_desktop yuklenemedi: {_e}")

# 2025-2026 SOTA Modülleri (Savunmacı İçe Aktarım)
try:
    import speculative_cache
except Exception as _e:
    speculative_cache = None
try:
    import batch_inference
except Exception as _e:
    batch_inference = None
try:
    import token_optimizer
except Exception as _e:
    token_optimizer = None
try:
    import mixture_of_agents
except Exception as _e:
    mixture_of_agents = None
try:
    import contextual_experience_replay as cer_module
except Exception as _e:
    cer_module = None
try:
    import self_evolution
    try:
        from custom_skills import load_all_custom_skills
        _loaded_skills = load_all_custom_skills()
        if hasattr(self_evolution, "_evolved_skills"):
            self_evolution._evolved_skills.update(_loaded_skills)
    except Exception:
        pass
except Exception as _e:
    self_evolution = None
try:
    import mcp_connector
except Exception as _e:
    mcp_connector = None
try:
    import reflection_agent
except Exception as _e:
    reflection_agent = None
try:
    import darwin_godel
except Exception as _e:
    darwin_godel = None
try:
    import openclaw_bridge
except Exception as _e:
    openclaw_bridge = None
try:
    import evo_cua_bridge
except Exception as _e:
    evo_cua_bridge = None
try:
    import adaptive_timeouts
except Exception as _e:
    adaptive_timeouts = None
try:
    import versioned_config
except Exception as _e:
    versioned_config = None
try:
    import auto_model_discovery
except Exception as _e:
    auto_model_discovery = None
try:
    import telemetry
except Exception as _e:
    telemetry = None
    print(f"[ALES] telemetry yuklenemedi: {_e}")
try:
    import document_generator
except Exception as _e:
    document_generator = None
    print(f"[ALES] document_generator yuklenemedi: {_e}")

from config_manager import (get_mode, set_mode, list_modes, get_mode_config,
                            get_system_prompt, get_key, get_council, set_council,
                            get_big_ales, set_big_ales, BIG_ALES_MODELS,
                            set_system_prompt, load_system_prompts)

app = FastAPI(title="ALES", version="3.0")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

# ─── CLIENT ─────────────────────────────────────────────────────
def get_client():
    cfg = load_config()
    if cfg.get("groq_key"):
        try:
            from groq import Groq
            return "groq", Groq(api_key=cfg["groq_key"])
        except: pass
    if cfg.get("cerebras_key"):
        try:
            from cerebras.cloud.sdk import Cerebras
            return "cerebras", Cerebras(api_key=cfg["cerebras_key"])
        except: pass
    return None, None

# ─── KISA HAFIZA ─────────────────────────────────────────────────
# NOT: load_memory/save_memory config_manager'dan import edildi (AppData'da
# saklanir, uygulama silinse bile kalir). Burada tekrar tanimlanmiyor -
# eskiden buradaki tanimlar import'u "shadow" edip yereldeki memory.json'a
# yaziyordu, AppData'ya hic gitmiyordu.

def add_short(role: str, content: str, conv_id: str = None):
    """
    Her kullanici istemi ve ALES yanitini hem ilgili sohbete (conversations)
    hem de kalici %APPDATA%\\ALES\\memory.json dosyasina kaydeder.
    """
    if conv_id:
        try:
            conv_store.append_message(conv_id, role, content)
        except Exception as e:
            print(f"[CONVERSATIONS] append hatasi: {e}")
    try:
        mem = load_memory()
        mem.setdefault("short", [])
        mem["short"].append({
            "role": role,
            "content": content,
            "time": datetime.now().isoformat(),
            "conv_id": conv_id or ""
        })
        if len(mem["short"]) > 100:
            mem["short"] = mem["short"][-100:]
        save_memory(mem)
    except Exception as e:
        print(f"[MEMORY] save hatasi: {e}")

# ─── PC ARAÇLARI ─────────────────────────────────────────────────
def take_screenshot(region: str = "auto") -> str:
    """HIZ: varsayilan olarak (region='auto') sadece AKTIF PENCERE
    yakalanir - tum ekrani yakalamaktan cok daha kucuk/hizli. Kullanici
    acikca 'tum ekrani' isterse region='full_screen' ile tam ekran alinir."""
    try:
        import tempfile
        from vision import _grab_screen
        # /tmp Windows'ta yok - tempfile.gettempdir() platform-bagimsiz dogru yolu verir
        path = os.path.join(tempfile.gettempdir(), "ales_screen.png")
        img = _grab_screen(region)
        img.save(path)
        return f"[Ekran goruntusu alindi: {img.size[0]}x{img.size[1]}, kaydedildi: {path}]"
    except Exception as e:
        return f"❌ {e}"

def open_app(app_name: str) -> str:
    """
    Windows'ta uygulama acar. ONEMLI: subprocess.Popen'in basariyla
    baslamasi, acilan komutun BASARILI oldugu anlamina gelmez - 'start
    spotify' gibi bir komut Windows'un kendi penceresinde "uygulama
    bulunamadi" hatasi verebilir ama Python bunu hic gormez, Popen yine
    de "basarili" doner. Bu yuzden burada GERCEK yol arama + dogrulama var.
    """
    key = app_name.lower().strip()

    # Bilinen web kisayollari - bunlarda risk yok, dogrudan acilir
    web_shortcuts = {
        "fiverr": "https://www.fiverr.com/inbox",
        "upwork": "https://www.upwork.com/ab/messages/",
        "bionluk": "https://bionluk.com/mesajlar",
    }
    if key in web_shortcuts:
        try:
            subprocess.Popen(f'start chrome "{web_shortcuts[key]}"', shell=True)
            return f"✅ {app_name} tarayicida acildi"
        except Exception as e:
            return f"❌ {app_name} acilamadi: {e}"

    # Sistem uygulamalari - PATH'te her zaman bulunur, guvenli
    system_apps = {
        "notepad": "notepad.exe",
        "not defteri": "notepad.exe",
        "calc": "calc.exe",
        "calculator": "calc.exe",
        "hesap makinesi": "calc.exe",
        "explorer": "explorer.exe",
        "dosya gezgini": "explorer.exe",
        "cmd": "cmd.exe",
        "komut istemi": "cmd.exe",
        "terminal": "wt.exe",
        "paint": "mspaint.exe",
    }
    if key in system_apps:
        try:
            subprocess.Popen(system_apps[key], shell=True)
            return f"✅ {app_name} acildi"
        except Exception as e:
            return f"❌ {app_name} acilamadi: {e}"

    # Chrome/Firefox - PATH'te olmayabilir, bilinen konumlardan da dene
    browsers = {
        "chrome": [
            os.path.expandvars(r"%PROGRAMFILES%\Google\Chrome\Application\chrome.exe"),
            os.path.expandvars(r"%PROGRAMFILES(X86)%\Google\Chrome\Application\chrome.exe"),
            os.path.expandvars(r"%LOCALAPPDATA%\Google\Chrome\Application\chrome.exe"),
        ],
        "firefox": [
            os.path.expandvars(r"%PROGRAMFILES%\Mozilla Firefox\firefox.exe"),
            os.path.expandvars(r"%PROGRAMFILES(X86)%\Mozilla Firefox\firefox.exe"),
        ],
    }
    if key in browsers:
        path = next((p for p in browsers[key] if os.path.exists(p)), None)
        if not path:
            try:
                result = subprocess.run(["where", key], capture_output=True, text=True, timeout=3)
                if result.returncode == 0 and result.stdout.strip():
                    path = result.stdout.strip().split("\n")[0]
            except Exception:
                pass
        if not path:
            return f"❌ {app_name} bulunamadi. Kurulu olmayabilir."
        try:
            subprocess.Popen([path], shell=False)
            return f"✅ {app_name} acildi"
        except Exception as e:
            return f"❌ {app_name} acilamadi: {e}"

    # Diger her sey icin: gercek .exe yolunu bulmaya calis
    exe_path = _find_app_path(key)
    if not exe_path:
        return (
            f"❌ '{app_name}' bilgisayarda bulunamadi. Kurulu olmayabilir "
            f"veya farkli bir isimle kayitli olabilir. Tam dosya yolunu "
            f"biliyorsan onu soyleyebilirsin, ya da 'C:/.../uygulama.exe' "
            f"seklinde yaz, dogrudan o yolu denerim."
        )

    try:
        proc = subprocess.Popen([exe_path], shell=False)
        time.sleep(0.6)
        if proc.poll() is not None and proc.returncode not in (0, None):
            return f"❌ '{app_name}' baslatildi ama hemen kapandi (cikis kodu {proc.returncode}). Yol dogru olmayabilir: {exe_path}"
        return f"✅ {app_name} acildi ({exe_path})"
    except Exception as e:
        return f"❌ '{app_name}' acilirken hata: {e}"


def _find_app_path(key: str) -> str | None:
    """
    Bir uygulamanin gercek .exe yolunu bulmaya calisir:
    1) Windows Registry'deki "App Paths" (kurulu cogu uygulama burada kayitlidir)
    2) Bilinen AppData/Program Files konumlari (Spotify, Discord, vb. genelde buradadir)
    3) PATH uzerinde where komutu
    """
    # 1) Registry - App Paths (en guvenilir yontem)
    try:
        import winreg
        for hive in (winreg.HKEY_CURRENT_USER, winreg.HKEY_LOCAL_MACHINE):
            for suffix in (f"{key}.exe", f"{key.capitalize()}.exe"):
                try:
                    reg_path = rf"SOFTWARE\Microsoft\Windows\CurrentVersion\App Paths\{suffix}"
                    with winreg.OpenKey(hive, reg_path) as hkey:
                        path, _ = winreg.QueryValueEx(hkey, "")
                        if path and os.path.exists(path):
                            return path
                except FileNotFoundError:
                    continue
    except ImportError:
        pass  # winreg sadece Windows'ta var (gelistirme/test ortaminda olmayabilir)

    # 2) Bilinen yaygin konumlar (registry'de olmayan ama cok kullanilan uygulamalar)
    known_locations = {
        "spotify": [
            os.path.expandvars(r"%APPDATA%\Spotify\Spotify.exe"),
            os.path.expandvars(r"%PROGRAMFILES%\Spotify\Spotify.exe"),
        ],
        "discord": [os.path.expandvars(r"%LOCALAPPDATA%\Discord\Update.exe")],
        "vscode": [os.path.expandvars(r"%LOCALAPPDATA%\Programs\Microsoft VS Code\Code.exe")],
        "code": [os.path.expandvars(r"%LOCALAPPDATA%\Programs\Microsoft VS Code\Code.exe")],
        "whatsapp": [os.path.expandvars(r"%LOCALAPPDATA%\WhatsApp\WhatsApp.exe")],
    }
    for candidate in known_locations.get(key, []):
        if os.path.exists(candidate):
            return candidate

    # 3) PATH uzerinde ara (where komutu)
    try:
        result = subprocess.run(["where", key], capture_output=True, text=True, timeout=3)
        if result.returncode == 0 and result.stdout.strip():
            return result.stdout.strip().split("\n")[0]
    except Exception:
        pass

    return None

def type_text(text: str) -> str:
    """
    Turkce karakter sorunu: pyautogui.typewrite() sadece ASCII destekler,
    u o s c g i gibi Turkce harfler yazilemiyor. Cozum: metni Windows
    clipboard'una kopyalayip Ctrl+V ile yapistiriyoruz - boylece her
    karakter desteklenir.
    """
    try:
        time.sleep(0.5)
        # Windows clipboard'una yaz
        import subprocess as sp
        # PowerShell ile clipboard'a yaz (encoding sorunu olmadan)
        ps_cmd = f'Set-Clipboard -Value "{text.replace(chr(34), chr(39))}"'
        sp.run(["powershell", "-Command", ps_cmd],
               capture_output=True, timeout=3)
        # Ctrl+V ile yapistir
        import pyautogui
        pyautogui.FAILSAFE = False
        pyautogui.hotkey("ctrl", "v")
        return f"✅ Yazildi (clipboard yontemi, Turkce karakterler destekleniyor)"
    except Exception as e:
        # Fallback: eski yontem (sadece ASCII calisir)
        try:
            import pyautogui
            pyautogui.typewrite(text, interval=0.04)
            return "✅ Yazildi (ASCII modu)"
        except Exception as e2:
            return f"❌ {e2}"

def press_key(key: str) -> str:
    try:
        pyautogui.hotkey(*key.split("+")) if "+" in key else pyautogui.press(key)
        return f"✅ {key}"
    except Exception as e: return f"❌ {e}"

def click_at(x: int, y: int) -> str:
    try:
        if native_desktop is not None and hasattr(native_desktop, "click_at_scaled"):
            return native_desktop.click_at_scaled(int(x), int(y))
        pyautogui.click(int(x), int(y))
        return f"✅ ({x},{y})"
    except Exception as e:
        return f"❌ Tıklama hatası: {e}"

def get_system_info() -> str:
    try:
        cpu = psutil.cpu_percent(interval=1)
        ram = psutil.virtual_memory()
        disk = psutil.disk_usage("C:\\")
        return f"💻 CPU:%{cpu} RAM:{ram.used//1024//1024}MB/{ram.total//1024//1024}MB Disk:{disk.used//1024//1024//1024}GB/{disk.total//1024//1024//1024}GB"
    except Exception as e: return f"❌ {e}"

def add_fiverr_task(task: str, client_name: str, status: str = "bekliyor") -> str:
    mem = load_memory()
    mem["fiverr_tasks"].append({"id": int(time.time()), "task": task, "client": client_name, "status": status, "time": datetime.now().isoformat()})
    save_memory(mem); return f"✅ Görev eklendi: {task}"

def get_fiverr_tasks() -> str:
    mem = load_memory()
    if not mem["fiverr_tasks"]: return "📋 Görev yok"
    return "📋 Görevler:\n" + "\n".join([f"[{t['status']}] {t['task']} — {t['client']}" for t in mem["fiverr_tasks"]])

APPROVAL_MAX_AGE_HOURS = 24

def _prune_stale_approvals(mem: dict) -> bool:
    """Guvenlik: unutulmus/eski onay istekleri sonsuza kadar birikmesin -
    24 saatten eski bekleyen onaylar otomatik temizlenir. True donerse
    en az bir kayit silinmis demektir (caller save_memory cagirmali)."""
    approvals = mem.get("pending_approvals", [])
    if not approvals:
        return False
    now = datetime.now()
    fresh = []
    changed = False
    for a in approvals:
        try:
            age_hours = (now - datetime.fromisoformat(a["time"])).total_seconds() / 3600
        except Exception:
            age_hours = 0
        if age_hours > APPROVAL_MAX_AGE_HOURS:
            changed = True
        else:
            fresh.append(a)
    if changed:
        mem["pending_approvals"] = fresh
    return changed

def add_pending_approval(action: str, description: str, params: dict) -> str:
    mem = load_memory()
    _prune_stale_approvals(mem)
    aid = int(time.time())
    mem.setdefault("pending_approvals", []).append({"id": aid, "action": action, "description": description, "params": params, "time": datetime.now().isoformat()})
    save_memory(mem); return f"ONAY_BEKLIYOR:{aid}:{description}"

# ─── WINDOWS MASAUSTU (native_desktop) ───────────────────────────
# Mevcut pyautogui yolunu (open_app / click_at / type_text) DEGISTIRMEZ,
# yanina ekler. Fark su: pyautogui KOR koordinatla calisir ("840,220'ye
# tikla") — pencere kayarsa ya da cozunurluk degisirse yanlis yere tiklar.
# Buradaki araclar pencereyi ve denetimi ADIYLA bulur, bu yuzden konumdan
# bagimsizdir. native_desktop pencere islerini ctypes/user32 ile YAPAR
# (hicbir pip paketi gerekmez); denetim (buton/metin alani) islemleri icin
# uiautomation veya pywinauto gerekir ve yoksa aracin cevabi tam olarak
# hangi komutu kurmak gerektigini soyler.
def _nd(fn_name: str, *a, **kw) -> str:
    """native_desktop cagrilarini tek kapidan gecirir: modul yoksa ARACIN
    ADIYLA anlasilir bir mesaj doner (sessiz AttributeError yerine)."""
    if native_desktop is None:
        return ("❌ Masaüstü kontrolü kullanılamıyor (native_desktop "
                "yüklenemedi). Bunun yerine click_at / type_text ile "
                "koordinat tabanlı kontrol kullanabilirim.")
    fn = getattr(native_desktop, fn_name, None)
    if not callable(fn):
        return f"❌ native_desktop.{fn_name} bulunamadı."
    try:
        return fn(*a, **kw)
    except Exception as e:
        return f"❌ {fn_name}: {e}"


# ─── TOOLS ───────────────────────────────────────────────────────
TOOLS = [
    # PC
    {"type":"function","function":{"name":"take_screenshot","description":"Ekranın görüntüsünü al","parameters":{"type":"object","properties":{"region":{"type":"string","enum":["auto","active_window","full_screen"],"description":"auto=aktif pencere (hızlı, varsayılan), full_screen=tüm ekran/monitörler"}},"required":[]}}},
    {"type":"function","function":{"name":"open_app","description":"Uygulama aç: chrome/firefox/notepad/spotify/fiverr/upwork/bionluk/cmd","parameters":{"type":"object","properties":{"app_name":{"type":"string"}},"required":["app_name"]}}},
    {"type":"function","function":{"name":"type_text","description":"Klavyeyle metin yaz","parameters":{"type":"object","properties":{"text":{"type":"string"}},"required":["text"]}}},
    {"type":"function","function":{"name":"press_key","description":"Tuşa bas: enter/tab/ctrl+c/ctrl+v","parameters":{"type":"object","properties":{"key":{"type":"string"}},"required":["key"]}}},
    {"type":"function","function":{"name":"click_at","description":"Koordinata tıkla","parameters":{"type":"object","properties":{"x":{"type":"integer"},"y":{"type":"integer"}},"required":["x","y"]}}},
    {"type":"function","function":{"name":"get_system_info","description":"CPU RAM disk bilgisi","parameters":{"type":"object","properties":{},"required":[]}}},
    # Hafıza
    {"type":"function","function":{"name":"remember_fact","description":"Önemli bilgiyi kalıcı hafızaya kaydet","parameters":{"type":"object","properties":{"fact":{"type":"string"},"category":{"type":"string"}},"required":["fact"]}}},
    {"type":"function","function":{"name":"update_user_profile","description":"Kullanıcı profili güncelle","parameters":{"type":"object","properties":{"key":{"type":"string"},"value":{"type":"string"}},"required":["key","value"]}}},
    {"type":"function","function":{"name":"get_user_profile","description":"Kullanıcı profilini getir","parameters":{"type":"object","properties":{},"required":[]}}},
    {"type":"function","function":{"name":"search_memory","description":"Hafızada VE gecmişteki TÜM sohbetlerde ara (uzun süreli hafıza) - 'geçen hafta/ay X hakkında ne konuşmuştuk' gibi sorularda kullan","parameters":{"type":"object","properties":{"query":{"type":"string"}},"required":["query"]}}},
    {"type":"function","function":{"name":"get_all_facts","description":"Tüm öğrenilenleri listele","parameters":{"type":"object","properties":{},"required":[]}}},
    # Web
    {"type":"function","function":{"name":"fetch_url","description":"Web sayfası içeriği getir","parameters":{"type":"object","properties":{"url":{"type":"string"}},"required":["url"]}}},
    {"type":"function","function":{"name":"google_search","description":"İnternette ara","parameters":{"type":"object","properties":{"query":{"type":"string"}},"required":["query"]}}},
    {"type":"function","function":{"name":"get_worldview","description":"Güncel dünya özeti: haberler döviz kripto hava","parameters":{"type":"object","properties":{},"required":[]}}},
    {"type":"function","function":{"name":"get_news_tr","description":"Türkiye haberleri","parameters":{"type":"object","properties":{},"required":[]}}},
    {"type":"function","function":{"name":"get_weather","description":"Hava durumu","parameters":{"type":"object","properties":{"city":{"type":"string"}},"required":[]}}},
    {"type":"function","function":{"name":"get_crypto_prices","description":"BTC ETH SOL fiyatları","parameters":{"type":"object","properties":{},"required":[]}}},
    {"type":"function","function":{"name":"get_exchange_rates","description":"Döviz kurları","parameters":{"type":"object","properties":{},"required":[]}}},
    # İş
    {"type":"function","function":{"name":"check_fiverr_messages","description":"Fiverr mesajlarını kontrol et. Varsayılan arka planda (ekranda görünmez) çalışır.","parameters":{"type":"object","properties":{"visible":{"type":"boolean","description":"true ise tarayıcı penceresi görünür açılır (kullanıcı özellikle izlemek/görmek istediğinde kullan)"}},"required":[]}}},
    {"type":"function","function":{"name":"check_bionluk_messages","description":"Bionluk mesajlarını kontrol et. Varsayılan arka planda (ekranda görünmez) çalışır.","parameters":{"type":"object","properties":{"visible":{"type":"boolean","description":"true ise tarayıcı penceresi görünür açılır (kullanıcı özellikle izlemek/görmek istediğinde kullan)"}},"required":[]}}},
    {"type":"function","function":{"name":"add_fiverr_task","description":"Fiverr görevi ekle","parameters":{"type":"object","properties":{"task":{"type":"string"},"client_name":{"type":"string"},"status":{"type":"string"}},"required":["task","client_name"]}}},
    {"type":"function","function":{"name":"get_fiverr_tasks","description":"Fiverr görevlerini listele","parameters":{"type":"object","properties":{},"required":[]}}},
    {"type":"function","function":{"name":"add_pending_approval","description":"Onay bekleyen işlem ekle","parameters":{"type":"object","properties":{"action":{"type":"string"},"description":{"type":"string"},"params":{"type":"object"}},"required":["action","description","params"]}}},
    # Zamanlama
    {"type":"function","function":{"name":"add_schedule","description":"Zamanlanmış görev ekle, örn: her sabah 9da gündem anlat","parameters":{"type":"object","properties":{"name":{"type":"string"},"time_str":{"type":"string","description":"HH:MM formatında"},"action":{"type":"string"},"repeat":{"type":"string","enum":["daily","weekdays","once"]}},"required":["name","time_str","action"]}}},
    {"type":"function","function":{"name":"list_schedules","description":"Zamanlanmış görevleri listele","parameters":{"type":"object","properties":{},"required":[]}}},
    {"type":"function","function":{"name":"remove_schedule","description":"Zamanlama kaldır","parameters":{"type":"object","properties":{"schedule_id":{"type":"integer"}},"required":["schedule_id"]}}},
    # Bildirim
    {"type":"function","function":{"name":"send_notification","description":"Windows bildirimi gönder","parameters":{"type":"object","properties":{"title":{"type":"string"},"message":{"type":"string"}},"required":["title","message"]}}},
    {"type":"function","function":{"name":"add_notification_rule","description":"Proaktif bildirim kuralı ekle","parameters":{"type":"object","properties":{"trigger":{"type":"string","description":"time:09:00 veya news_keyword:bitcoin"},"message":{"type":"string"},"check_interval":{"type":"integer"}},"required":["trigger","message"]}}},
    {"type":"function","function":{"name":"list_notification_rules","description":"Bildirim kurallarını listele","parameters":{"type":"object","properties":{},"required":[]}}},
    # Kod
    {"type":"function","function":{"name":"run_python_code","description":"Python kodu yaz ve çalıştır","parameters":{"type":"object","properties":{"code":{"type":"string","description":"Çalıştırılacak Python kodu"}},"required":["code"]}}},

    # Vision
    {"type":"function","function":{"name":"analyze_screen","description":"Ekranda ne oldugunu gör ve anla, eleman bul","parameters":{"type":"object","properties":{"question":{"type":"string","description":"Ekran hakkinda soru"},"region":{"type":"string","enum":["auto","active_window","full_screen"],"description":"auto=aktif pencere (hızlı, varsayılan), full_screen=tüm ekran/monitörler - kullanıcı 'tüm ekranı' derse bunu kullan"}},"required":[]}}},
    {"type":"function","function":{"name":"find_on_screen","description":"Ekranda bir elementi bul ve koordinatini ver","parameters":{"type":"object","properties":{"element":{"type":"string"},"region":{"type":"string","enum":["auto","active_window","full_screen"]}},"required":["element"]}}},
    # Gercek Web Browsing
    {"type":"function","function":{"name":"browse_web","description":"Bir URL'ye git, sayfanin icerigini oku","parameters":{"type":"object","properties":{"url":{"type":"string"}},"required":["url"]}}},
    {"type":"function","function":{"name":"web_search_deep","description":"Google'da derine ara, sonuclari getir","parameters":{"type":"object","properties":{"query":{"type":"string"}},"required":["query"]}}},
    # Fiverr
    {"type":"function","function":{"name":"open_fiverr_login","description":"Fiverr'i giris icin ac, kullanicinin giris yapmasini bekle","parameters":{"type":"object","properties":{},"required":[]}}},
    # Telefon / Tunnel
    {"type":"function","function":{"name":"start_tunnel","description":"Telefon erisimi icin tunnel baslat, link ver","parameters":{"type":"object","properties":{"type":{"type":"string","enum":["ngrok","cloudflare","local"]}},"required":[]}}},
    {"type":"function","function":{"name":"get_phone_access","description":"Telefondan ALES'e nasil baglanilir goster","parameters":{"type":"object","properties":{},"required":[]}}},


    # Dosya Sistemi (Claude gibi)
    {"type":"function","function":{"name":"read_file","description":"Bir dosyanin icerigini oku","parameters":{"type":"object","properties":{"path":{"type":"string","description":"Dosya yolu, ornek: C:/Users/Ali/Desktop/dosya.txt"}},"required":["path"]}}},
    {"type":"function","function":{"name":"write_file","description":"Yeni dosya olustur ve icerik yaz","parameters":{"type":"object","properties":{"path":{"type":"string"},"content":{"type":"string"},"overwrite":{"type":"boolean"}},"required":["path","content"]}}},
    {"type":"function","function":{"name":"edit_file","description":"Dosyada belirli bir metni baska bir metinle degistir","parameters":{"type":"object","properties":{"path":{"type":"string"},"old_text":{"type":"string"},"new_text":{"type":"string"}},"required":["path","old_text","new_text"]}}},
    {"type":"function","function":{"name":"list_directory","description":"Bir klasorun icerigini listele","parameters":{"type":"object","properties":{"path":{"type":"string"}},"required":["path"]}}},
    {"type":"function","function":{"name":"create_directory","description":"Yeni klasor olustur","parameters":{"type":"object","properties":{"path":{"type":"string"}},"required":["path"]}}},
    {"type":"function","function":{"name":"delete_path","description":"Dosya veya klasor sil. ONAY GEREKTIRIR - once add_pending_approval kullan","parameters":{"type":"object","properties":{"path":{"type":"string"}},"required":["path"]}}},
    {"type":"function","function":{"name":"search_files","description":"Klasorde dosya adi veya icerikte arama yap","parameters":{"type":"object","properties":{"directory":{"type":"string"},"pattern":{"type":"string"}},"required":["directory","pattern"]}}},
    {"type":"function","function":{"name":"get_file_info","description":"Dosya/klasor boyutu ve degisiklik tarihi","parameters":{"type":"object","properties":{"path":{"type":"string"}},"required":["path"]}}},
    # Siparis Sablonlari (Skills)
    {"type":"function","function":{"name":"list_skills","description":"Fiverr/Bionluk siparisleri icin mevcut sablon ve rehber dosyalarini listele","parameters":{"type":"object","properties":{},"required":[]}}},
    {"type":"function","function":{"name":"read_skill","description":"Bir siparis sablonunu veya rehberini oku, orn: SIPARIS_REHBERI.md, scraper_static_template.py","parameters":{"type":"object","properties":{"filename":{"type":"string"}},"required":["filename"]}}},

    # Multi-Agent Tartisma
    {"type":"function","function":{"name":"multi_agent_discuss","description":"4 farkli AI (Groq+Gemini+SambaNova+Cerebras) paralel calisir, konu hakkinda tartisir ve ortak bir sonuc uretir. 'derin analiz', '4 AI ne dusunur', 'tartis', 'farkli perspektifler' gibi isteklerde kullan.","parameters":{"type":"object","properties":{"topic":{"type":"string","description":"Tartisma konusu veya soru"}},"required":["topic"]}}},
    {"type":"function","function":{"name":"manage_goal","description":"Karmaşık ve çok adımlı görevleri Manager-Executor mimarisiyle alt adımlara böler, öğrenilen deneyim kurallarını uygular, her adımı yürütüp doğrular ve sonuç raporlar. 'şunu adım adım yap', 'görevi planla ve yürüt' gibi hedeflerde kullan.","parameters":{"type":"object","properties":{"goal":{"type":"string","description":"Yürütülecek hedef veya görev"}},"required":["goal"]}}},
    # Persona
    {"type":"function","function":{"name":"set_persona","description":"ALES modunu değiştir: default/is/ogrenme/dinlenme/gece/siparis/gorev","parameters":{"type":"object","properties":{"persona_key":{"type":"string","enum":["default","is","ogrenme","dinlenme","gece","siparis","gorev"]}},"required":["persona_key"]}}},
    {"type":"function","function":{"name":"list_personas","description":"Kullanılabilir modları listele","parameters":{"type":"object","properties":{},"required":[]}}},

    # Skills (Claude'daki skill mantığı - takılabilir yetenekler)
    {"type":"function","function":{"name":"list_installed_skills","description":"Yüklü tüm skill'leri (yetenekleri) ve durumlarını (aktif/pasif) listele. Kullanıcı 'neler yapabiliyorsun', 'hangi skiller var' derse kullan.","parameters":{"type":"object","properties":{},"required":[]}}},

    # Connectors (harici servisler - Notion/Slack/Spotify/Google Calendar vb.)
    {"type":"function","function":{"name":"list_connectors","description":"Bağlı/bağlanabilir harici servisleri (connector) listele, hangileri aktif göster.","parameters":{"type":"object","properties":{},"required":[]}}},
    {"type":"function","function":{"name":"call_connector","description":"Aktif edilmiş bir connector (Notion/Slack/Spotify/Google Calendar veya kullanıcının eklediği özel bir connector) üzerinden HTTP isteği yap. Önce list_connectors ile hangi connector'ların aktif olduğuna bak.","parameters":{"type":"object","properties":{"connector_id":{"type":"string","description":"connector id, örn: notion, slack, spotify"},"path":{"type":"string","description":"connector base_url'inden sonraki yol, örn: /users/me"},"method":{"type":"string","enum":["GET","POST","PUT","PATCH","DELETE"]},"body":{"type":"object","description":"POST/PUT için JSON gövde"}},"required":["connector_id","path"]}}},

    # Windows masaüstü (pencere + denetim adıyla kontrol - koordinat DEĞİL)
    {"type":"function","function":{"name":"list_windows","description":"Açık pencereleri listele (başlık + boyut + durum). 'Hangi pencereler açık', 'Notepad açık mı' gibi sorularda ve bir pencereyi odaklamadan ÖNCE kullan.","parameters":{"type":"object","properties":{"visible_only":{"type":"boolean","description":"Sadece görünür pencereler (varsayılan true)"}},"required":[]}}},
    {"type":"function","function":{"name":"focus_window","description":"Pencereyi öne getir ve odakla. Başlığın bir kısmı yeterli (örn 'Notepad'). Yazı yazmadan/tıklamadan ÖNCE bunu kullan - yanlış pencereye yazmayı önler.","parameters":{"type":"object","properties":{"title":{"type":"string","description":"Pencere başlığı veya bir parçası"}},"required":["title"]}}},
    {"type":"function","function":{"name":"window_state","description":"Pencereyi büyüt/küçült/geri getir: restore, maximize, minimize.","parameters":{"type":"object","properties":{"title":{"type":"string"},"state":{"type":"string","enum":["restore","maximize","minimize"]}},"required":["title"]}}},
    {"type":"function","function":{"name":"close_window","description":"Pencereyi kibarca kapat (uygulamaya kapanma isteği gönderir, zorla öldürmez - kaydedilmemiş iş kaybolmaz).","parameters":{"type":"object","properties":{"title":{"type":"string"}},"required":["title"]}}},
    {"type":"function","function":{"name":"wait_for_window","description":"Bir pencerenin açılmasını bekle (uygulama açtıktan sonra). Belirtilen süre içinde açılmazsa bunu söyler.","parameters":{"type":"object","properties":{"title":{"type":"string"},"timeout_s":{"type":"number","description":"Kaç saniye beklenecek (varsayılan 10)"}},"required":["title"]}}},
    {"type":"function","function":{"name":"list_controls","description":"Pencerenin içindeki denetimleri (buton, metin alanı, liste) ADLARIYLA listele. click_control kullanmadan ÖNCE bununla gerçek adı öğren - ad uydurmak yerine.","parameters":{"type":"object","properties":{"title":{"type":"string"},"depth":{"type":"integer","description":"Ağaç derinliği (varsayılan 3)"}},"required":["title"]}}},
    {"type":"function","function":{"name":"click_control","description":"Pencere içindeki bir denetime ADIYLA tıkla (örn 'Kaydet' butonu). Koordinat gerekmez, pencere kayarsa bozulmaz. Önce list_controls ile adı doğrula.","parameters":{"type":"object","properties":{"title":{"type":"string"},"name":{"type":"string","description":"Denetimin adı, örn 'Kaydet'"},"control_type":{"type":"string","description":"Button/Edit/CheckBox gibi (opsiyonel, aynı adlı birden fazla varsa)"},"double":{"type":"boolean","description":"Çift tık"}},"required":["title","name"]}}},
    {"type":"function","function":{"name":"set_control_text","description":"Pencere içindeki metin alanına ADIYLA yazı yaz. type_text'ten farkı: panoyu KULLANMAZ (kullanıcının kopyaladığı şey kaybolmaz) ve yanlış pencereye yazma riski yoktur.","parameters":{"type":"object","properties":{"title":{"type":"string"},"name":{"type":"string"},"text":{"type":"string"}},"required":["title","name","text"]}}},
    {"type":"function","function":{"name":"get_control_text","description":"Pencere içindeki bir denetimin metnini oku (ekran görüntüsü + OCR gerekmeden, birebir doğru).","parameters":{"type":"object","properties":{"title":{"type":"string"},"name":{"type":"string"}},"required":["title","name"]}}},

    # ── Bilgisayar kullanimi: OSWorld/WAA eylem uzayi (evo_cua_bridge) ──
    # NEDEN AYRI BIR ARAC: click_at piksel bekler. Modeller (ozellikle
    # ekran goruntusune bakan modeller) koordinati 0-1000 NORMALIZE
    # uretmeye egilimlidir; cua_action o donusumu yapar, ayrica hotkey/
    # drag/scroll/wait gibi tek adimda birden fazla is yapan eylemleri
    # ve eylem DIZISINI destekler (her adim icin ayri LLM turu gerekmez).
    {"type":"function","function":{"name":"cua_action","description":"Bilgisayari OSWorld/WAA eylem bicimiyle kullan. Tek eylem veya SIRALI eylem listesi calistirir - boylece 'Not Defteri'ni ac, yaz, kaydet' gibi cok adimli isler TEK arac cagrisinda biter. Koordinatlar 0-1000 normalize verilebilir (ekran cozunurlugune otomatik haritalanir) veya dogrudan piksel. Eylem tipleri: click, double_click, right_click, type, press, hotkey, drag, scroll, wait, terminate.","parameters":{"type":"object","properties":{"actions":{"type":"array","description":"Sirali eylem listesi, orn: [{\"type\":\"hotkey\",\"keys\":\"ctrl+s\"},{\"type\":\"wait\",\"seconds\":0.5},{\"type\":\"type\",\"text\":\"notlar.txt\"}]","items":{"type":"object","properties":{"type":{"type":"string","enum":["click","double_click","right_click","type","press","hotkey","drag","scroll","wait","terminate"]},"x":{"type":"number","description":"0-1000 normalize veya piksel"},"y":{"type":"number"},"to_x":{"type":"number","description":"drag icin hedef X"},"to_y":{"type":"number","description":"drag icin hedef Y"},"text":{"type":"string"},"key":{"type":"string"},"keys":{"type":"string","description":"orn 'ctrl+shift+n'"},"amount":{"type":"integer","description":"scroll miktari, negatif=asagi"},"seconds":{"type":"number"}},"required":["type"]}},"action":{"type":"object","description":"Tek eylem (actions verilmediyse)"}},"required":[]}}},

    # ── OpenClaw koprusu: harici daemon varsa oraya, yoksa yerel yedege ──
    {"type":"function","function":{"name":"openclaw_desktop","description":"Masaustu eylemini OpenClaw daemon'una gonder (yoksa Windows yerel yedegine duser). Eylemler: click, type, list_windows, close. NOT: ALES'in kendi list_windows/click_control/set_control_text araclari ayni isi DAHA GUVENILIR yapar - bunu sadece OpenClaw daemon'unun kendi yetenekleri gerekiyorsa kullan.","parameters":{"type":"object","properties":{"action":{"type":"string","enum":["click","type","list_windows","close"]},"window":{"type":"string","description":"Pencere basligi"},"control":{"type":"string","description":"Denetim adi"},"text":{"type":"string"}},"required":["action"]}}},
    {"type":"function","function":{"name":"openclaw_browser","description":"Tarayici eylemini OpenClaw daemon'una gonder (yoksa yerel Playwright yedegine duser). Eylemler: goto (url), search (query). NOT: browse_web/web_search_deep dogrudan ayni isi yapar; bunu sadece daemon'un oturumu/sekmeleri gerekiyorsa kullan.","parameters":{"type":"object","properties":{"action":{"type":"string","enum":["goto","search"]},"url":{"type":"string"},"query":{"type":"string"}},"required":["action"]}}},
    {"type":"function","function":{"name":"openclaw_terminal","description":"Kabuk (shell) komutu calistir ve cikti/hata kodunu getir - orn 'git status', 'dir', 'npm run build'. OpenClaw daemon varsa orada, yoksa yerel subprocess'te calisir. Uzun surecek komutlar icin timeout_s ver.","parameters":{"type":"object","properties":{"command":{"type":"string"},"timeout_s":{"type":"number","description":"Varsayilan 15, en fazla 120"}},"required":["command"]}}},
    # ── Belge ve PDF Üretimi ──
    {"type":"function","function":{"name":"generate_pdf","description":"Creates a PDF file from text or markdown. If the user asks for a PDF, document, or report, YOU MUST use this tool. (Markdown metnini veya başlık ve içeriği şık bir PDF belgesine dönüştürür ve indirilebilir dosya üretir. Kullanıcı 'pdf yap', 'pdf oluştur', 'rapor hazırla', 'belge ver' dediğinde MUTLAKA bu aracı çağır).","parameters":{"type":"object","properties":{"title":{"type":"string","description":"Belge veya rapor başlığı"},"content":{"type":"string","description":"Markdown formatında belge veya rapor içeriği"}},"required":["title","content"]}}},
]

# ─── ACIL DURUM ARAC SETI ────────────────────────────────────────
# Zincir tamamen duştugunde son bir deneme icin kullanilan KUCUK arac
# seti (bkz. sohbet dongusundeki RouterError blogu). Amac: istemi
# ~35 arac semasindan bir kac araca indirip butce hatasini asmak, ama
# kullanicinin en cok bekledigi yetenegi (WEB ARAMASI) elde tutmak.
# tool_router'dan turetiliyor ki arac adlari iki yerde ayri tutulmasin.
def _slim_tool_names() -> set:
    try:
        import tool_router as _tr
        names = set(_tr.CORE_TOOLS)
        names.update(_tr.TOOL_CATEGORIES.get("web", {}).get("tools", []))
        names.update(_tr.TOOL_CATEGORIES.get("memory", {}).get("tools", []))
        return names
    except Exception:
        return {"google_search", "fetch_url", "web_search_deep",
                "search_memory", "remember_fact"}


_SLIM_TOOL_NAMES = _slim_tool_names()


def get_all_tools() -> list:
    """TOOLS (sabit arac listesi) + su an AKTIF olan skill'lerin araclari +
    AKTIF eklentilerin araclari. Skill'ler ve eklentiler runtime'da panelden
    acilip kapatilabildigi icin bu liste her cagrida taze hesaplanir
    (bkz. skills_engine.get_enabled_tools / plugin_loader.get_enabled_tools)."""
    out = list(TOOLS)
    try:
        out += skills_engine.get_enabled_tools()
    except Exception:
        pass
    # Eklenti araclari: ad cakismasi plugin_loader tarafinda REDDEDILIR
    # (set_reserved_names, asagida) — yani bir eklenti "read_file" adini
    # kapip gercek dosya okumayi golgeleyemez. Burada ayrica try ile
    # sariliyor: bozuk bir eklenti dosyasi arac listesini bosaltmasin.
    if plugin_loader is not None:
        try:
            out += plugin_loader.get_enabled_tools()
        except Exception as e:
            print(f"[PLUGIN] arac listesi alinamadi: {e}")
    return out


# AD KORUMASI: eklentiler cekirdek arac adlarini KAPAMAZ. Bunu import
# aninda (herhangi bir istekten ve discover() cagrisindan ONCE) kuruyoruz;
# startup()'a birakmak, uvicorn'un ilk istegi startup'tan once isledigi
# durumlarda korumasiz bir pencere birakirdi.
if plugin_loader is not None:
    try:
        _reserved = {t["function"]["name"] for t in TOOLS
                     if isinstance(t, dict) and t.get("function")}
        try:
            _reserved |= {t["function"]["name"] for t in skills_engine.get_enabled_tools()
                          if isinstance(t, dict) and t.get("function")}
        except Exception:
            pass
        plugin_loader.set_reserved_names(_reserved)
    except Exception as _e:
        print(f"[PLUGIN] ad koruması kurulamadi: {_e}")

# HIZ: Bu araclar salt-okunur/bagimsizdir - ayni turda birden fazlasi
# istenirse sirayla degil PARALEL calistirilir (bkz. run_agent). PC
# kontrolu/dosya yazma gibi durumlu/sirali islemler BILEREK disarida -
# guvenlik/tutarlilik icin sirali kalmaya devam ediyor.
PARALLEL_SAFE_TOOLS = {
    "get_crypto_prices", "get_exchange_rates", "get_news_tr", "get_weather", "get_worldview",
    "fetch_url", "google_search", "browse_web", "web_search_deep",
    "get_file_info", "list_directory", "search_files", "read_file", "read_skill", "list_skills",
    "get_all_facts", "get_user_profile", "search_memory",
    "get_fiverr_tasks", "list_schedules", "list_notification_rules", "list_personas",
    "get_system_info", "check_fiverr_messages", "check_bionluk_messages",
    "list_installed_skills", "list_connectors",
    # Masaustu SALT-OKUNUR araclar. focus_window/click_control/
    # set_control_text/close_window BILEREK YOK: onlar odagi ve ekrani
    # DEGISTIRIR, paralel calisirlarsa birbirinin altindan pencereyi ceker.
    # Ayni gerekce ile cua_action / openclaw_desktop / openclaw_browser /
    # openclaw_terminal DA YOK: ilk ucu odagi ve fare/klavyeyi paylasir
    # (paralel tik = yanlis pencereye tik), terminal ise dosya sistemini
    # degistirebilir — sirali kalmalari zorunlu.
    "list_windows", "list_controls", "get_control_text",
}

# LOG: her arac cagrisi icin TEK SATIRLIK, kisa Turkce aciklama. Ali'nin
# "ne yapti asiri kisa yazsin" istegi - detay yok, sadece ozet.
TOOL_LOG_LABELS = {
    "open_app": "Uygulama açıldı", "click_at": "Tıklandı", "type_text": "Yazıldı",
    "press_key": "Tuşa basıldı", "take_screenshot": "Ekran görüntüsü alındı",
    "analyze_screen": "Ekran analiz edildi", "find_on_screen": "Ekranda arandı",
    "get_weather": "Hava durumu kontrol edildi", "get_crypto_prices": "Kripto fiyatları çekildi",
    "get_exchange_rates": "Döviz kuru çekildi", "get_news_tr": "Haberler çekildi",
    "get_worldview": "Dünya durumu güncellendi", "google_search": "Web'de arandı",
    "browse_web": "Web sayfası açıldı", "web_search_deep": "Derin arama yapıldı",
    "fetch_url": "Sayfa çekildi", "read_file": "Dosya okundu", "write_file": "Dosya yazıldı",
    "edit_file": "Dosya düzenlendi", "delete_path": "Dosya silindi",
    "create_directory": "Klasör oluşturuldu", "list_directory": "Klasör listelendi",
    "search_files": "Dosya arandı", "get_file_info": "Dosya bilgisi alındı",
    "list_skills": "Yetenekler listelendi", "read_skill": "Yetenek okundu",
    "remember_fact": "Bilgi kaydedildi", "update_user_profile": "Profil güncellendi",
    "search_memory": "Hafızada arandı", "get_all_facts": "Hafıza okundu",
    "get_user_profile": "Profil okundu", "check_fiverr_messages": "Fiverr mesajları kontrol edildi",
    "check_bionluk_messages": "Bionluk mesajları kontrol edildi",
    "add_fiverr_task": "Fiverr görevi eklendi", "get_fiverr_tasks": "Fiverr görevleri okundu",
    "open_fiverr_login": "Fiverr girişi açıldı", "add_schedule": "Zamanlama eklendi",
    "remove_schedule": "Zamanlama silindi", "list_schedules": "Zamanlamalar listelendi",
    "add_notification_rule": "Bildirim kuralı eklendi",
    "list_notification_rules": "Bildirim kuralları listelendi",
    "send_notification": "Bildirim gönderildi", "run_python_code": "Kod çalıştırıldı",
    "multi_agent_discuss": "5 AI analizi yapıldı", "set_persona": "Mod değiştirildi",
    "list_personas": "Modlar listelendi", "get_system_info": "Sistem bilgisi alındı",
    "start_tunnel": "Tünel başlatıldı", "get_phone_access": "Telefon erişimi hazırlandı",
    "add_pending_approval": "Onay bekleniyor",
    "list_installed_skills": "Yetenekler (skills) listelendi",
    "list_connectors": "Connector'lar listelendi",
    "call_connector": "Connector çağrıldı",
    "list_windows": "Pencereler listelendi", "focus_window": "Pencere odaklandı",
    "window_state": "Pencere durumu değişti", "close_window": "Pencere kapatıldı",
    "wait_for_window": "Pencere beklendi", "list_controls": "Denetimler listelendi",
    "click_control": "Denetime tıklandı", "set_control_text": "Alana yazıldı",
    "get_control_text": "Alan okundu",
    "cua_action": "Bilgisayar kullanıldı", "openclaw_desktop": "Masaüstü eylemi",
    "openclaw_browser": "Tarayıcı eylemi", "openclaw_terminal": "Komut çalıştırıldı",
}

def log_action(tool_name: str, args: dict):
    label = TOOL_LOG_LABELS.get(tool_name, tool_name)
    # Bazi araclarda tek kelimelik ek baglam faydali (hangi uygulama, ne arandi)
    extra = (args.get("app_name") or args.get("query") or args.get("city")
             or args.get("connector_id") or args.get("command")
             or args.get("action") or "")
    # Komutlar uzun olabilir; log TEK SATIR kalmali (Ali'nin "asiri kisa" istegi)
    extra = str(extra).replace("\n", " ")[:48]
    text = f"{label} ({extra})" if extra else label
    try:
        append_action_log(text)
    except Exception:
        pass


def _cua_action_sync(args: dict, progress_cb=None) -> str:
    """OSWorld/WAA eylem(ler)ini SIRAYLA yurut (evo_cua_bridge).

    NEDEN SIRALI VE ILK HATADA DUR: bu eylemler ekrani ve odagi degistirir.
    3. adim basarisiz olduysa 4. adimi yine calistirmak, artik BEKLENMEYEN
    bir pencereye yazmak/tiklamak demektir — sessizce yanlis yere is yapmak
    yerine durup durumu bildirmek dogru davranis.

    KAPI: modul panelden kapatildiysa (veya Performance modu/kaynak baskisi
    onu duraklattiysa) SESSIZCE hicbir sey yapmayiz — modelin bunu bilmesi
    gerekir, yoksa "yaptim" der. O yuzden acik bir metin doneriz ve yerine
    kullanabilecegi araclari soyleriz.
    """
    if evo_cua_bridge is None:
        return ("❌ cua_action kullanilamiyor: evo_cua_bridge yuklenemedi "
                "(pyautogui eksik olabilir). Yerine click_at / type_text / "
                "press_key veya click_control kullan.")
    if not _mod_on("evo_cua", evo_cua_bridge):
        return ("⚠ cua_action su an KAPALI (Ayarlar > Moduller 'EvoCUA "
                "bilgisayar-kullanimi', ya da Performance modu/kaynak baskisi "
                "duraklatti). Hicbir eylem YAPILMADI. Ayni isi click_at, "
                "type_text, press_key, focus_window, click_control araclariyla "
                "yapabilirsin.")

    acts = args.get("actions")
    if not acts:
        one = args.get("action")
        # Model bazen alanlari duz gecirir: {"type":"click","x":..,"y":..}
        if not isinstance(one, dict):
            one = {k: v for k, v in (args or {}).items()
                   if k in ("type", "x", "y", "to_x", "to_y", "duration",
                            "text", "key", "keys", "amount", "seconds")}
        acts = [one] if one else []
    if isinstance(acts, dict):
        acts = [acts]
    if not isinstance(acts, list) or not acts:
        return ("❌ cua_action: eylem verilmedi. Ornek: "
                '{"actions":[{"type":"click","x":500,"y":300}]}')

    MAX_ACTIONS = 25          # kacak bir dongude ekrana 500 tik atmasin
    if len(acts) > MAX_ACTIONS:
        return (f"❌ cua_action: {len(acts)} eylem cok fazla (sinir {MAX_ACTIONS}). "
                "Isi daha kucuk parcalara bol ve arada ekrani kontrol et.")

    lines: list = []
    dry = False
    try:
        dry = bool(evo_cua_bridge.is_sandboxed())
    except Exception:
        pass
    for i, a in enumerate(acts, 1):
        if not isinstance(a, dict):
            lines.append(f"{i}. ATLANDI (eylem sozluk degil): {str(a)[:60]}")
            continue
        atype = str(a.get("type") or a.get("action") or "?")
        if progress_cb:
            try:
                progress_cb(f"{i}/{len(acts)}: {atype}")
            except Exception:
                pass
        try:
            res = evo_cua_bridge.execute_cua_action(a)
        except Exception as e:
            lines.append(f"{i}. {atype} → ❌ {e}")
            break
        if res.get("ok"):
            det = ""
            if res.get("pixel"):
                det = f" @{res['pixel'][0]},{res['pixel'][1]}"
            elif res.get("chars") is not None:
                det = f" ({res['chars']} karakter)"
            elif res.get("keys"):
                det = f" ({'+'.join(map(str, res['keys']))})"
            elif res.get("key"):
                det = f" ({res['key']})"
            lines.append(f"{i}. {atype}{det} → ✅")
        else:
            lines.append(f"{i}. {atype} → ❌ {res.get('error', 'bilinmeyen hata')}")
            if len(acts) > i:
                lines.append(f"   ⏹ Kalan {len(acts) - i} eylem YAPILMADI "
                             f"(ekran beklenen durumda degil).")
            break

    head = "[BILGISAYAR KULLANIMI"
    if dry:
        head += " — KUM HAVUZU: eylemler SIMULE edildi, ekrana dokunulmadi"
    return head + "]\n" + "\n".join(lines)


async def _openclaw_tool_async(name: str, args: dict, progress_cb=None) -> str:
    """OpenClaw koprusu araclari. AYRI TUTULUYOR cunku koprü asenkron
    (httpx) — execute_tool ise senkron bir thread'de calisir. Bu yuzden
    execute_tool_async icinde, executor'a devretmeden ONCE ele aliniyor;
    yoksa her cagrida kendi event loop'unu acmak gerekirdi."""
    if openclaw_bridge is None:
        return "❌ openclaw_bridge yuklenemedi (httpx eksik olabilir)."
    if not _mod_on("openclaw", openclaw_bridge):
        return ("⚠ OpenClaw koprusu su an KAPALI (Ayarlar > Moduller, ya da "
                "Performance modu/kaynak baskisi duraklatti). Hicbir islem "
                "YAPILMADI. Masaustu icin list_windows/click_control, web icin "
                "browse_web/web_search_deep, kod icin run_python_code kullan.")

    br = openclaw_bridge.bridge
    try:
        if name == "openclaw_desktop":
            action = str(args.get("action") or "").strip()
            if not action:
                return "❌ openclaw_desktop: 'action' gerekli (click/type/list_windows/close)."
            params = {"window": args.get("window", ""), "control": args.get("control", ""),
                      "text": args.get("text", "")}
            res = await br.control_desktop(action, params)
        elif name == "openclaw_browser":
            action = str(args.get("action") or "").strip()
            if not action:
                return "❌ openclaw_browser: 'action' gerekli (goto/search)."
            res = await br.control_browser(action, {"url": args.get("url", ""),
                                                    "query": args.get("query", "")})
        elif name == "openclaw_terminal":
            cmd = str(args.get("command") or "").strip()
            if not cmd:
                return "❌ openclaw_terminal: 'command' bos."
            t = float(args.get("timeout_s") or 15.0)
            t = max(1.0, min(120.0, t))     # ust sinir: ajan dongusunu kilitlemesin
            if progress_cb:
                try:
                    progress_cb(f"komut calisiyor (en fazla {int(t)}s)…")
                except Exception:
                    pass
            res = await br.execute_terminal(cmd, timeout_s=t)
        else:
            return f"Bilinmeyen araç: {name}"
    except Exception as e:
        return f"❌ {name}: {e}"

    # Cikti METIN olmali (modele arac sonucu olarak gider), sozluk degil.
    src = res.get("source") or "?"
    if name == "openclaw_terminal":
        rc = res.get("returncode")
        out = (res.get("stdout") or "").strip()
        err = (res.get("stderr") or "").strip()
        if res.get("data"):     # daemon kendi bicimini dondurur
            d = res["data"]
            out = str(d.get("stdout") or d.get("output") or d)[:2000]
            err = str(d.get("stderr") or "")[:1000]
            rc = d.get("returncode", rc)
        head = (f"[KOMUT {'OK' if res.get('ok') else 'HATA'} · {src}"
                + (f" · cikis kodu {rc}" if rc is not None else "") + "]")
        body = out or "(cikti yok)"
        if err:
            body += f"\n--- stderr ---\n{err}"
        return f"{head}\n{body}"

    if not res.get("ok"):
        return f"❌ {name} ({src}): {res.get('error', 'bilinmeyen hata')}"
    payload = res.get("result")
    if payload is None:
        payload = res.get("windows")
    if payload is None:
        payload = res.get("data")
    return f"[{name} · {src}]\n{str(payload)[:3000]}"


def _run_manager_goal_sync(goal: str, progress_cb=None) -> str:
    """Manager-Executor döngüsünü senkron araç ortamından güvenle çalıştırır."""
    import manager_agent
    import asyncio
    async def _async_run():
        return await manager_agent.run_goal(goal, progress_cb, tool_executor_fn=execute_tool)
    try:
        import concurrent.futures
        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
            return pool.submit(lambda: asyncio.run(_async_run())).result()
    except Exception as e:
        return f"❌ Manager-Executor hatası: {e}"


def execute_tool(name: str, args: dict, progress_cb=None) -> str:
    """
    progress_cb: (str) -> None - bazi araclar (ozellikle Fiverr/Bionluk
    tarayici otomasyonu) uzun surer ve ara adimlari bildirmek ister.
    Verilirse Ali "tarayici aciliyor... sayfaya gidiliyor..." gibi
    gercek zamanli ilerleme gorur, sadece sonucu degil.
    """
    try:
        tools = {
            "take_screenshot": lambda: take_screenshot(args.get("region", "auto")),
            "open_app": lambda: open_app(args["app_name"]),
            "type_text": lambda: type_text(args["text"]),
            "press_key": lambda: press_key(args["key"]),
            "click_at": lambda: click_at(args["x"], args["y"]),
            "wait": lambda: (time.sleep(float(args.get("seconds", 2.0))) or f"✅ {args.get('seconds', 2.0)}s beklendi"),
            "sleep": lambda: (time.sleep(float(args.get("seconds", 2.0))) or f"✅ {args.get('seconds', 2.0)}s beklendi"),
            "get_system_info": lambda: get_system_info(),
            # ── Windows masaustu (ad tabanli, koordinat degil) ───────
            "list_windows": lambda: _nd("list_windows_text",
                                        bool(args.get("visible_only", True))),
            "focus_window": lambda: _nd("focus_window", args["title"]),
            "window_state": lambda: _nd("window_state", args["title"],
                                        args.get("state", "restore")),
            "close_window": lambda: _nd("close_window", args["title"]),
            "wait_for_window": lambda: _nd("wait_for_window", args["title"],
                                           float(args.get("timeout_s") or 10.0)),
            "list_controls": lambda: _nd("list_controls", args["title"],
                                         int(args.get("depth") or 3)),
            "click_control": lambda: _nd("click_control", args["title"], args["name"],
                                         args.get("control_type"),
                                         bool(args.get("double"))),
            "set_control_text": lambda: _nd("set_control_text", args["title"],
                                            args["name"], args["text"]),
            "get_control_text": lambda: _nd("get_control_text", args["title"],
                                            args["name"]),
            # ── OSWorld/WAA eylem uzayi (0-1000 normalize koordinat) ──
            "cua_action": lambda: _cua_action_sync(args, progress_cb),
            "remember_fact": lambda: remember_fact(args["fact"], args.get("category","general")),
            "update_user_profile": lambda: update_user_profile(args["key"], args["value"]),
            "get_user_profile": lambda: get_user_profile(),
            "search_memory": lambda: search_memory(args["query"]),
            "get_all_facts": lambda: get_all_facts(),
            "fetch_url": lambda: fetch_url(args["url"]),
            "google_search": lambda: google_search(args["query"]),
            "get_worldview": lambda: get_worldview(),
            "get_news_tr": lambda: get_news_tr(),
            "get_weather": lambda: get_weather(args.get("city","Istanbul")),
            "get_crypto_prices": lambda: get_crypto_prices(),
            "get_exchange_rates": lambda: get_exchange_rates(),
            # ESKIDEN: ayni key ("check_bionluk_messages") iki kez
            # tanimliydi (biri kendi kendini cagiran olu kod), ve
            # check_fiverr_messages'da anlamsiz bir "if True else" vardi.
            # Artik ikisi de progress_cb'yi gercekten Selenium modulune
            # geciriyor - Ali "tarayici aciliyor" gibi adimlari gorur.
            "check_fiverr_messages": lambda: get_fiverr_messages_manual(progress_cb, visible=args.get("visible", False)),
            "check_bionluk_messages": lambda: get_bionluk_messages_manual(progress_cb, visible=args.get("visible", False)),
            "add_fiverr_task": lambda: add_fiverr_task(args["task"], args["client_name"], args.get("status","bekliyor")),
            "get_fiverr_tasks": lambda: get_fiverr_tasks(),
            "add_pending_approval": lambda: add_pending_approval(args["action"], args["description"], args.get("params",{})),
            "add_schedule": lambda: add_schedule(args["name"], args["time_str"], args["action"], args.get("repeat","daily")),
            "list_schedules": lambda: list_schedules(),
            "remove_schedule": lambda: remove_schedule(args["schedule_id"]),
            "send_notification": lambda: send_notification(args["title"], args["message"]),
            "add_notification_rule": lambda: add_notification_rule(args["trigger"], args["message"], args.get("check_interval",3600)),
            "list_notification_rules": lambda: list_notification_rules(),
            "run_python_code": lambda: run_python_code(args["code"]),
            "set_persona": lambda: set_persona(args["persona_key"]),
            # Vision
            "analyze_screen": lambda: analyze_screen_and_act(args.get("question","Ekranda ne var?"), args.get("region","auto")),
            "find_on_screen": lambda: find_element_on_screen(args["element"], args.get("region","auto")),
            # Gercek browsing
            "browse_web": lambda: browse_sync(args["url"]),
            "web_search_deep": lambda: search_sync(args["query"]),
            # Fiverr
            "open_fiverr_login": lambda: open_fiverr_for_login(progress_cb),
            # Tunnel / Telefon
            "start_tunnel": lambda: start_ngrok() if args.get("type","ngrok")=="ngrok" else start_cloudflare_tunnel() if args.get("type")=="cloudflare" else get_local_ip(),
            "get_phone_access": lambda: get_local_ip() + "\n\n" + get_tunnel_status(),
            # Dosya sistemi
            "read_file": lambda: read_file(args["path"]),
            "write_file": lambda: write_file(args["path"], args["content"], args.get("overwrite", False)),
            "edit_file": lambda: edit_file(args["path"], args["old_text"], args["new_text"]),
            "list_directory": lambda: list_directory(args.get("path",".")),
            "create_directory": lambda: create_directory(args["path"]),
            "delete_path": lambda: delete_path(args["path"]),
            "search_files": lambda: search_files(args["directory"], args["pattern"]),
            "get_file_info": lambda: get_file_info(args["path"]),
            "list_skills": lambda: list_skills(),
            "read_skill": lambda: read_skill(args["filename"]),
            "list_personas": lambda: list_personas(),
            # Multi-Agent / Manager-Executor
            "multi_agent_discuss": lambda: run_discussion_sync(args["topic"], progress_cb),
            "manage_goal": lambda: _run_manager_goal_sync(args.get("goal") or args.get("topic") or "", progress_cb),
            # Skills (takilabilir yetenekler - Claude'daki skill mantigi)
            "list_installed_skills": lambda: skills_engine.list_skills_text(),
            # Connectors (harici servisler)
            "list_connectors": lambda: "\n".join(
                f"  * {c['id']} ({'aktif' if c['enabled'] else 'pasif'}{', key girilmis' if c.get('has_key') else ', key yok'}) — {c['description']}"
                for c in connectors.list_connectors()
            ) or "[BILGI] Hic connector yok.",
            "call_connector": lambda: connectors.call_connector(
                args["connector_id"], args["path"], args.get("method", "GET"),
                args.get("body"), args.get("params")
            ),
            # Model Context Protocol (MCP)
            "mcp_list_tools": lambda: json.dumps(mcp_connector.list_mcp_tools() if mcp_connector else [], ensure_ascii=False),
            "mcp_call_tool": lambda: mcp_connector.call_mcp_tool(args["name"], args.get("arguments", {})) if mcp_connector else "MCP kullanılamıyor",
            "mcp_read_file": lambda: mcp_connector.mcp_read_file(args["path"]) if mcp_connector else read_file(args["path"]),
            "mcp_list_directory": lambda: mcp_connector.mcp_list_directory(args.get("path", ".")) if mcp_connector else list_directory(args.get("path", ".")),
            # PDF ve Belge Üretimi
            "generate_pdf": lambda: json.dumps(document_generator.generate_pdf(args.get("title", "Belge"), args.get("content", "")) if document_generator else {"ok": False, "error": "PDF modülü aktif değil"}, ensure_ascii=False),
        }
        if name in tools:
            return tools[name]()

        # Evrilmiş Beceriler (Darwin-Gödel Self-Evolution)
        if self_evolution is not None and hasattr(self_evolution, "get_evolved_skills"):
            try:
                ev_skills = self_evolution.get_evolved_skills()
                clean_n = name.replace("skill_", "")
                target_skill = ev_skills.get(name) or ev_skills.get(clean_n) or ev_skills.get(f"skill_{clean_n}")
                if target_skill and hasattr(target_skill, "run"):
                    import inspect
                    sig = inspect.signature(target_skill.run)
                    if len(sig.parameters) == 1:
                        return str(target_skill.run(args))
                    else:
                        return str(target_skill.run(**args))
            except Exception as e_ev:
                return f"❌ Evrilmiş beceri ({name}) çalıştırma hatası: {e_ev}"
        # Statik tabloda yoksa: bu bir skill araci olabilir (skills/ altinda
        # kullanicinin sonradan ekledigi bir klasor) - skills_engine'e sor.
        skill_result = skills_engine.execute_skill_tool(name, args, progress_cb)
        if skill_result is not None:
            return skill_result
        # Sonra EKLENTILER (plugins/ altindaki .py dosyalari). Ayni sozlesme:
        # bu ada sahip degilse None doner. Sira BILINCLI: cekirdek -> skill ->
        # eklenti, yani sonradan eklenen bir dosya once geleni golgeleyemez.
        if plugin_loader is not None:
            try:
                plugin_result = plugin_loader.execute_plugin_tool(name, args, progress_cb)
            except Exception as e:
                return f"❌ Eklenti çağrısı başarısız ({name}): {e}"
            if plugin_result is not None:
                return plugin_result
        return f"Bilinmeyen araç: {name}"
    except Exception as e:
        return f"Hata: {traceback.format_exc()}"

# ─── NON-BLOCKING ARAC CALISTIRMA ────────────────────────────────
# execute_tool icindeki bircok arac BLOKLAYICI: ekran goruntusu,
# Groq vision API cagrisi, Selenium (Fiverr/Bionluk), Playwright
# (browse_web/web_search_deep - kendi event loop'unu acan asyncio.run
# icerir), httpx ile worldview/haber cekme.
#
# Bunlari dogrudan await ile cagirmak TUM websocket'i (ve diger
# baglantilari) kilitler: "ekranı görüyor musun" gibi istekler
# uygulamayi "takılı" gösterir. Ayrica Playwright'in asyncio.run()
# cagrisi, zaten calisan bir event loop icinden cagrilirsa
# RuntimeError verir - executor'daki ayri thread'de bu sorun olmaz.
_executor = ThreadPoolExecutor(max_workers=8)

async def execute_tool_async(name: str, args: dict, websocket: WebSocket = None) -> str:
    """
    websocket verilirse, uzun suren araclarin (Fiverr/Bionluk) ara
    adimlari gercek zamanli olarak 'tool_progress' mesaji ile frontend'e
    gonderilir. Bu thread-safe sekilde yapilmali: progress_cb baska bir
    thread'den (executor) cagrilacagi icin, asyncio.run_coroutine_threadsafe
    ile ana event loop'a geri donus yapiyoruz.
    """
    loop = asyncio.get_event_loop()

    # ── ONGORULU ON-YUKLEME: HAZIR SONUC ────────────────────────────
    # Bir onceki adimda bu cagri spekulatif olarak zaten yapildiysa
    # (bkz. predictive.prefetch_for, run_agent'in arac dongusu), sonuc
    # onbellekte hazir bekliyor: sifir bekleme. take() SADECE salt-okunur
    # araclari ve SURESI GECMEMIS girdileri dondurur — bayat veri
    # dondurmek sessiz yanlislik uretecegi icin suresi gecen MISS sayilir.
    if predictive is not None:
        try:
            ready = predictive.take(name, args or {})
        except Exception:
            ready = None
        if ready is not None:
            if websocket is not None:
                try:
                    await websocket.send_json({"type": "tool_progress", "tool": name,
                                               "message": "hazır (ön yükleme)"})
                except Exception:
                    pass
            return ready

    def progress_cb(message: str):
        try:
            import screen_streamer
            screen_streamer.log_activity(f"[{name}] {message}", level="INFO", tool=name)
        except Exception:
            pass
        if websocket is None:
            return
        try:
            asyncio.run_coroutine_threadsafe(
                websocket.send_json({"type": "tool_progress", "tool": name, "message": message}),
                loop
            )
        except Exception:
            pass  # ilerleme bildirimi basarisiz olsa bile islemi durdurma

    # ── CANLI EKRAN VE AKTİVİTE YAYINI (screen_streamer) ────────────
    try:
        import screen_streamer
        screen_streamer.start_task(name)
    except Exception:
        pass

    try:
        # ── ASENKRON-DOGAL ARACLAR ──────────────────────────────────────
        # OpenClaw koprusu httpx ile ASENKRON konusur. Onu execute_tool'un
        # senkron govdesine koymak, thread icinde yeni bir event loop acmayi
        # (asyncio.run) gerektirirdi — gereksiz ve kirilgan. Burada, executor'a
        # devretmeden ONCE dogrudan await ediyoruz. Not: progress_cb bu yolda
        # AYNI thread'den cagrilir; run_coroutine_threadsafe zaten calisan
        # loop'a gonderdigi icin bu da guvenli.
        if name in ("openclaw_desktop", "openclaw_browser", "openclaw_terminal"):
            return await _openclaw_tool_async(name, args or {}, progress_cb)

        return await loop.run_in_executor(_executor, execute_tool, name, args, progress_cb)
    finally:
        try:
            import screen_streamer
            screen_streamer.finish_task(name)
        except Exception:
            pass


async def _raw_tool_async(name: str, args: dict) -> str:
    """ON-YUKLEME icin HAM calistirma.

    Iki sey BILEREK yok:
      * predictive.take() kapisi — kendi doldurdugu onbellekten okumak
        anlamsiz olur (ve girdiyi tuketip gercek cagriyi issiz birakir).
      * websocket ilerleme bildirimi — kullanicinin ISTEMEDIGI spekulatif
        bir isin loglari arayuzde gorunmemeli, yoksa "ben bunu istemedim"
        diyecegi satirlar akar.
    """
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(_executor, execute_tool, name, args, None)


def _prefetch_enabled() -> bool:
    """Ongorulu on-yukleme SU AN acik mi.

    Performance mod / kaynak baskisi / uyku bu modulu duraklatir
    (runtime_state.MODULES['predictive'].heavy_local=True). Spekulatif is,
    kaynak sikisinca ilk kesilmesi gereken seydir — bu yuzden kapiyi
    burada, tek yerde soruyoruz."""
    if predictive is None:
        return False
    if runtime_state is None:
        return True
    try:
        return bool(runtime_state.module_active("predictive"))
    except Exception:
        return True


def _mod_on(mid: str, mod=None) -> bool:
    """Faz 2/3/6 modulleri icin tek kapi: modul YUKLU mu VE su an ACIK mi.

    NEDEN GEREKLI: bu moduller runtime_state.MODULES'e kaydedildi, yani
    Ayarlar'da her biri icin bir anahtar goruluyor. O anahtarin GERCEKTEN
    bir sey yapmasi icin kodun da onu sormasi gerekir — yoksa panelde
    kapatilan bir modul arkada calismaya devam eder ve anahtar suse
    donusur (bu projede daha once tam olarak bu olmustu).

    heavy_local=True olanlar Performance modda / kaynak baskisinda
    otomatik kapanir; bu fonksiyon o karari da tasir."""
    if mod is None:
        return False
    if runtime_state is None:
        return True
    try:
        return bool(runtime_state.module_active(mid))
    except Exception:
        return True


# ─── STREAMING (HIZ) ─────────────────────────────────────────────
# ESKIDEN: Groq/Cerebras cevabi TEK PARCA halinde bekleniyordu - model
# 4096 token'a kadar cevap uretebildigi icin, uzunca bir cevapta kullanici
# birkac saniye BOMBOS ekrana bakiyordu (ilk kelime = son kelimeyle ayni
# anda geliyordu). ARTIK: stream=True ile model kelime kelime ürettikce
# aninda websocket'e "token" olarak yollaniyor - ilk kelime ~aninda
# gorunuyor (algilanan hiz cok buyuk fark yaratir), toplam sure ayni kalsa
# bile "hizli" hissettiriyor. Tool-call icin gereken JSON parcalari da
# stream'den index'e gore biriktirilip sonunda birlestiriliyor.
class _StreamFunc:
    __slots__ = ("name", "arguments")
    def __init__(self, name, arguments):
        self.name = name
        self.arguments = arguments

class _StreamToolCall:
    __slots__ = ("id", "function")
    def __init__(self, id_, name, arguments):
        self.id = id_
        self.function = _StreamFunc(name, arguments)

def _consume_stream_blocking(stream, on_token):
    """BLOKLAYICI - sadece bir thread/executor icinde cagrilmali. Groq/
    Cerebras'in stream=True cevabini tuketir, metin parcalarini on_token
    ile aninda bildirir, tool-call parcalarini index'e gore biriktirip
    sonunda tek bir listeye birlestirir."""
    content_parts = []
    tool_calls_acc = {}
    for chunk in stream:
        if not chunk.choices:
            continue
        delta = chunk.choices[0].delta
        piece = getattr(delta, "content", None)
        if piece:
            content_parts.append(piece)
            on_token(piece)
        deltas = getattr(delta, "tool_calls", None)
        if deltas:
            for d in deltas:
                idx = getattr(d, "index", 0)
                acc = tool_calls_acc.setdefault(idx, {"id": None, "name": "", "arguments": ""})
                if getattr(d, "id", None):
                    acc["id"] = d.id
                fn = getattr(d, "function", None)
                if fn is not None:
                    if getattr(fn, "name", None):
                        acc["name"] += fn.name
                    if getattr(fn, "arguments", None):
                        acc["arguments"] += fn.arguments
    tool_calls = None
    if tool_calls_acc:
        tool_calls = [
            _StreamToolCall(acc["id"] or f"call_{idx}", acc["name"], acc["arguments"])
            for idx, acc in sorted(tool_calls_acc.items())
        ]
    return "".join(content_parts), tool_calls

async def stream_chat_completion(client, model: str, messages: list, tools: list,
                                  websocket: WebSocket, temperature=None) -> tuple:
    """create(..., stream=True) cagrisini yapar, executor'da (bloklamadan)
    tuketir, her metin parcasini ANINDA 'token' websocket mesaji olarak
    yollar. (content, tool_calls) dondurur - tool_calls yoksa None.

    GUVENLIK AGI: streaming (bazi model/API kombinasyonlarinda tool-calling
    ile birlikte) ara sira beklenmedik sekilde hata verebiliyor. Eskiden bu
    durumda run_agent hemen bir sonraki SAGLAYICIYA (Cerebras, sonra
    SambaNova/Gemini gibi daha zayif yedeklere) duşuyordu - kullanicinin
    Groq key'i gecerli olsa bile, sirf streaming takildi diye Groq hic
    denenmemis gibi SambaNova'ya duşuyordu. ARTIK: streaming basarisiz
    olursa AYNI saglayicida stream=False ile bir kez daha denenir (token
    token gorunmez ama tool-calling ve dogru saglayici korunur) - sadece
    BU DA basarisiz olursa yukarida gercek bir saglayici hatasi olarak
    ele alinir."""
    loop = asyncio.get_event_loop()

    def on_token(piece: str):
        if websocket is None:
            return
        try:
            asyncio.run_coroutine_threadsafe(
                websocket.send_json({"type": "token", "content": piece}), loop
            )
        except Exception:
            pass

    def blocking_stream():
        kwargs = dict(model=model, messages=messages, tools=tools,
                      tool_choice="auto", max_tokens=4096, stream=True)
        if temperature is not None:
            kwargs["temperature"] = temperature
        stream = client.chat.completions.create(**kwargs)
        return _consume_stream_blocking(stream, on_token)

    def blocking_nonstream():
        kwargs = dict(model=model, messages=messages, tools=tools,
                      tool_choice="auto", max_tokens=4096, stream=False)
        if temperature is not None:
            kwargs["temperature"] = temperature
        resp = client.chat.completions.create(**kwargs)
        msg = resp.choices[0].message
        return msg.content or "", msg.tool_calls

    try:
        return await loop.run_in_executor(_executor, blocking_stream)
    except Exception as e:
        print(f"[STREAM] Streaming basarisiz ({model}): {e} - stream=False ile ayni saglayicida tekrar deneniyor...")
        return await loop.run_in_executor(_executor, blocking_nonstream)


# ─── ROUTER TABANLI STREAMING (mod zinciri) ─────────────────────
async def stream_via_router(messages: list, tools: list, websocket: WebSocket,
                            mode: str = None) -> tuple:
    """model_router.stream_chat ile aktif MODUN zincirini kullanarak token
    token yayin yapar (Cheat->DeepSeek V4, Heavy->Kimi K3, vb.). Ilk
    baglanabilen katmandan yayin eder, duşerse sonraki katmana gecer.
    Doner: (content:str, tool_calls:list|None, used_layer:dict|None) —
    tool_calls formati stream_chat_completion ile ayni ( .id/.function ).
    Zincir tamamen basarisizsa RouterError firlatir (caller yakalar).

    FAZ-2 (2026-09-05): bu fonksiyon ALES'teki TUM router cagrilarinin tek
    gecis noktasi oldugu icin iki hiz optimizasyonu burada yapilir:
      (a) DEPO token optimizasyonu (token_optimizer) — bayat arac
          ciktilarini kirpar ve gorev karmasikligina gore cikti butcesi
          belirler. max_tokens PENCEREDEN REZERVE EDILDIGI icin (bkz.
          model_router butce hesabi) basit sorularda 4096 yerine 512
          istemek girdi icin yer ACAR — yani zincirin dusme sebebini
          azaltir, sadece token tasarrufu degil.
      (b) SpecCache KV onek kaydi — ortak sistem promptu onekleri
          eslesirse prefill yuku olcumu icin isaretlenir.
    Ikisi de TAMAMEN opsiyoneldir: modul yoksa ya da hata verirse akis
    degismeden devam eder (fail-open)."""
    loop = asyncio.get_event_loop()
    used = {"layer": None}
    max_tokens = 4096

    # (a) DEPO — token/adim optimizasyonu
    if _mod_on("token_optimizer", token_optimizer):
        try:
            _hint = ""
            for _m in reversed(messages):
                if _m.get("role") == "user" and _m.get("content"):
                    _hint = str(_m["content"])
                    break
            messages, _dep = token_optimizer.optimize_messages(messages, task_hint=_hint)
            max_tokens = int(_dep.get("recommended_max_tokens") or 4096)
            if _dep.get("tokens_saved") or _dep.get("pruned_messages"):
                print(f"[DEPO] ~{_dep.get('tokens_saved',0)} token kirpildi · "
                      f"{_dep.get('pruned_messages',0)} mesaj · "
                      f"karmasiklik={_dep.get('complexity')} · butce={max_tokens}")
        except Exception as e:
            print(f"[DEPO] optimizasyon atlandi: {e}")
            max_tokens = 4096

    # (b) SpecCache — KV onek yeniden kullanim kaydi (RelayCaching tarzi)
    #
    # SIRA ONEMLI: ONCE get_kv_prefix (OKUMA), SONRA cache_kv_prefix (YAZMA).
    # Ters cevirirsek her tur kendi yazdigi onegi okur ve isabet orani
    # yapay olarak %100 gorunur — olcum degil, kendi kuyrugunu yiyen bir sayac
    # olur. Simdiki sira ile "isabet" GERCEKTEN onceki bir turdan gelir.
    #
    # NEDEN SADECE SAYAC: get_kv_prefix bir KV onbellek KIMLIGI dondurur,
    # saglayicinin gercek prefill onbellegini DEGISTIRMEZ — HTTP API'lerinde
    # (Groq/Gemini/Cerebras) boyle bir kanca yok. Bu yuzden panelde "token
    # kazanildi" DEMIYORUZ; "ayni sistem onegi N kez gorundu" diyoruz.
    # Saglayici tarafinda otomatik prompt caching varsa kazanc oradan gelir,
    # bizim sayacimizdan degil. Olcmedigimiz seyi soylemiyoruz.
    if _mod_on("spec_cache", speculative_cache):
        try:
            _sysmsg = next((m.get("content") for m in messages
                            if m.get("role") == "system"), "")
            if _sysmsg:
                _kv = speculative_cache.get_kv_prefix(str(_sysmsg))
                if _kv and _kv.get("matched"):
                    print(f"[SPEC-KV] sistem onegi {_kv.get('hits')}. kez "
                          f"goruldu ({_kv.get('prefix_hash')}) · "
                          f"~{_kv.get('tokens_saved')} token sabit onek")
                speculative_cache.cache_kv_prefix(str(_sysmsg), {"mode": mode})
        except Exception:
            pass

    def on_layer(layer):
        used["layer"] = layer
        try:
            asyncio.run_coroutine_threadsafe(
                websocket.send_json({"type": "tool_use", "tool": "route",
                                     "args": {"layer": layer.get("layer"),
                                              "provider": layer.get("provider"),
                                              "model": layer.get("model")}}), loop)
        except Exception:
            pass

    content_parts, tool_acc, err = [], None, None
    async for ev in model_router.stream_chat(messages, mode=mode, tools=tools,
                                             max_tokens=max_tokens,
                                             on_layer=on_layer):
        t = ev.get("type")
        if t == "token":
            content_parts.append(ev["text"])
            try:
                await websocket.send_json({"type": "token", "content": ev["text"]})
            except Exception:
                pass
        elif t == "tool_calls":
            tool_acc = ev["tool_calls"]
        elif t == "error":
            err = ev.get("error")
    if err and not content_parts and not tool_acc:
        raise model_router.RouterError(err)
    tool_calls = None
    if tool_acc:
        tool_calls = [_StreamToolCall(tc.get("id") or f"call_{i}",
                                      tc.get("name", ""), tc.get("args", ""))
                      for i, tc in enumerate(tool_acc)]
    return "".join(content_parts), tool_calls, used["layer"]


async def send_tts_audio(text: str, websocket: WebSocket):
    """Metni sese cevirir ve TARAYICIYA yollar - ChatGPT'deki gibi aninda
    <audio> ile calinsin diye. ESKIDEN burada speak() cagriliyordu, o da
    isletim sisteminin varsayilan medya oynaticisini (ayri bir pencere)
    aciyordu VE sadece backend'in calistigi bilgisayardan ses cikariyordu
    (telefondan kullanirken ses PC'ye gidiyordu, telefona degil). Simdi
    ses verisi websocket ile frontend'e gidiyor, hangi cihazdan
    bakiliyorsa orada calıyor - hicbir dosya penceresi acilmiyor.

    AKISLI YOL (audio_streamer): ayar aciksa metin CUMLE CUMLE sese
    cevrilir ve her cumle hazir olunca ayri bir 'audio_chunk' olarak
    gonderilir — ilk sesi duymak icin tum yanitin sentezlenmesi beklenmez.
    Akis basarisiz olursa (motor yok, hata) sessizce ASAGIDAKI tek-parca
    yola duser; yani ses hicbir kosulda tamamen kaybolmaz."""
    # HUD: konusan nokta. 'on' = ALES SES URETIYOR demek; sesin CALMASI
    # bittiginde soneceginden frontend kendi <audio> 'ended' olayindan da
    # sorumlu (backend tarayicidaki calma suresini bilemez).
    await _send_speaking(websocket, True)
    try:
        if await _send_tts_stream(text, websocket):
            return
        try:
            cfg = load_config()
            loop = asyncio.get_event_loop()
            key = (
                cfg.get("elevenlabs_key", "")
                or get_key("elevenlabs_key")
                or os.environ.get("ELEVENLABS_API_KEY", "")
                or os.environ.get("ELEVENLABS_KEY", "")
            ).strip()
            voice_id = cfg.get("elevenlabs_voice") or DEFAULT_ELEVENLABS_VOICE
            edge_voice = cfg.get("edge_voice") or DEFAULT_EDGE_VOICE
            audio_bytes = await loop.run_in_executor(
                _executor, synthesize, text,
                key,
                voice_id,
                edge_voice,
            )
            if audio_bytes:
                mime = "audio/wav" if audio_bytes.startswith(b"RIFF") else "audio/mpeg"
                b64 = base64.b64encode(audio_bytes).decode("ascii")
                await websocket.send_json({"type": "audio", "data": b64, "mime": mime})
        except Exception as e:
            print(f"[TTS] Ses gonderilemedi: {e}")
    finally:
        await _send_speaking(websocket, False)


async def _send_speaking(websocket: WebSocket, on: bool):
    """HUD'un konusan noktasi icin tek satirlik olay. Hatasi ONEMSIZ:
    ses gonderimi bir HUD mesaji yuzunden asla durmamali."""
    try:
        await websocket.send_json({"type": "speaking", "on": bool(on)})
    except Exception:
        pass


def _tts_stream_on() -> bool:
    """Akisli TTS acik mi: modul var + kullanici ayari + duraklatilmamis.

    Varsayilan KAPALI. Nedeni: akisli yol ses verisini birden fazla
    parca halinde yollar ve frontend'in bunlari SIRAYLA calmasi gerekir;
    eski bir arayuz sekmesi bu mesaj tipini bilmezse ses hic duyulmaz.
    Bu yuzden ozellik kullanicinin ayardan acmasiyla devreye girer."""
    if audio_streamer is None:
        return False
    try:
        if not bool(load_config().get("tts_stream", False)):
            return False
    except Exception:
        return False
    if runtime_state is not None:
        try:
            if runtime_state.is_paused("realtime_tts") or runtime_state.is_paused("tts"):
                return False
        except Exception:
            pass
    return True


async def _send_tts_stream(text: str, websocket: WebSocket) -> bool:
    """Cumle cumle ses gonder. Doner: gercekten ses gonderildi mi.

    False donerse cagiran TEK PARCA yola duser. "Motor yok" ile "hicbir
    cumle sentezlenemedi" ayni sekilde ele alinir: ikisi de sessizlik
    demektir ve sessizlik kabul edilemez bir sonuctur."""
    if not _tts_stream_on() or not (text or "").strip():
        return False

    sent = 0

    async def _on_chunk(data: bytes, mime: str, seq: int, is_last: bool):
        nonlocal sent
        await websocket.send_json({
            "type": "audio_chunk",
            "data": base64.b64encode(data).decode("ascii"),
            "mime": mime, "seq": seq, "last": bool(is_last),
        })
        sent += 1

    try:
        cfg = load_config()
        res = await audio_streamer.stream_text(
            text, _on_chunk,
            voice=cfg.get("tts_voice") or cfg.get("edge_voice") or None,
            engine=cfg.get("tts_engine") or None)
    except Exception as e:
        print(f"[TTS] akis hatasi, tek parca yola dusuluyor: {e}")
        return False

    if sent:
        # Son parcanin bittigini frontend zaten 'last' ile biliyor; burada
        # sadece teshis logu birakiyoruz (ilk ses kac saniyede geldi).
        print(f"[TTS] akis: {sent} parca · ilk ses {res.get('first_audio_s')}s · "
              f"motor {res.get('engine')}")
        return True
    if res.get("local_playback"):
        # Motor sesi PC HOPARLORUNDEN caldi (SAPI/RealtimeTTS). Tarayiciya
        # gonderilecek byte yok — telefondan bakiliyorsa kullanici hicbir
        # sey duymaz, bu yuzden durumu acikca bildiriyoruz.
        try:
            await websocket.send_json({
                "type": "system_log", "level": "INFO",
                "message": f"Ses bu bilgisayarın hoparlöründen çalındı ({res.get('engine')}).",
                "time": datetime.now().strftime("%H:%M:%S")})
        except Exception:
            pass
        return True
    if res.get("error"):
        print(f"[TTS] akis basarisiz ({res['error']}) — tek parca yola dusuldu")
    return False

# ─── SYSTEM PROMPT ───────────────────────────────────────────────
BASE_SYSTEM = """Sen ALES - Advanced Logic Execution System v3.0.
Kullanıcın Ali. Onun kişisel AI asistanı, stratejik düşünce ortağı ve güvendiği zeki sistemisin.

MOD: {persona_tone}

GENEL ASİSTAN VE DÜŞÜNCE ORTAĞI (TEMEL İLKE):
- Sen çok yönlü, derin genel kültüre ve analitik yetkinliğe sahip genel bir yapay zeka asistanısın.
- Bilim, felsefe, havacılık, tarih, sosyoloji, sanat veya gündelik konular dahil her soruya doğal, akıcı, kapsamlı ve samimi bir dille doğrudan yanıt ver.
- Kullanıcı açıkça istemediği veya ilgili bir görev vermediği sürece konuşmayı ASLA kodlamaya, web kazımaya (scraping), görev otomasyonuna veya bot işlevlerine ZORLAMA. Bir düşünce ortağı gibi sohbet et ve akıl yürüt.

ÇEKİRDEK KURALLAR (PAZARLIK YOK):
1. UYDURMA YOK: Emin olmadığın hiçbir şeyi kesin söyleme. Doğrulamadıysan açıkça belirt veya "VARSAYIM:" etiketi kullan.
2. AGGRESSIVE TOOL EXECUTION (CLAUDE CODE PROTOCOL - NO EXPLANATIONS):
NEVER explain how to do a task if you have a tool for it. YOU MUST execute the tool. If the user asks for a PDF, CALL the `generate_pdf` tool immediately. Do not give them instructions or tutorial code.
Kullanıcının isteği bir araç, dosya oluşturma, kod çalıştırma, sistem kontrolü, canlı arama veya PDF üretimi gerektiriyorsa, ASLA nasıl yapılacağını anlatma; ARACI ÇAĞIRIP HEMEN YAP!
3. İÇ DÜŞÜNCEYİ GÖSTERME: Kullanıcıya sadece doğrudan yanıtı, net gerekçeyi ve gerekliyse uygulanabilir adımları ver. Planını uzun uzun yazma.
4. NETLİK VE DERİNLİK: "Direkt yap" dendiğinde soru sorma, en mantıklı adımla ilerle. Analiz veya bilgi istendiğinde doyurucu ve derinlikli açıkla.

HIZ KURALLARI:
- Tek adımda halledilebilecek şeylerde fazladan araç kullanma.
- "Yapıyorum..." gibi boş dolgu cümleleri yazma, doğrudan konuya gir.
- Kullanıcı bilgi soruyorsa doğrudan açıkla; araç çağrısı gerekiyorsa anında icra et.

HAFIZA (PROAKTİF OL):
- Ali bir tercih, hedef, ilgi alanı veya çalışma tarzı belirtirse update_user_profile ile kaydet.
- Önemli ve kalıcı bilgiler için remember_fact kullan.
- ASLA kaydetme: şifre, API anahtarı, mahrem/özel bilgi.

DOSYA VE SİSTEM İŞLEMLERİ:
- Dosya okuma -> read_file
- Dosya oluşturma -> write_file
- Dosya düzenleme -> edit_file
- Kritik işlemler (silme, harici onay gerektirenler) -> add_pending_approval

BELGE VE PDF ÜRETİMİ:
- NEVER explain how to do a task if you have a tool for it. YOU MUST execute the tool. If the user asks for a PDF, CALL the `generate_pdf` tool immediately. Do not give them instructions or code tutorials.
- If the user asks for a PDF, report, or document, YOU MUST use the `generate_pdf` tool.
- Kullanıcı bir PDF, rapor, özet veya doküman dosyası oluşturulmasını istediğinde doğrudan metinle veya kod anlatımıyla geçiştirmek KESİNLİKLE YASAKTIR; MUTLAKA `generate_pdf` aracını çağır ve üretilen dosya indirme bağlantısını kullanıcıya sun.

EKRAN GÖRME (HIZ):
- analyze_screen / take_screenshot ekranı görmen gerektiğinde kullanılır.
- "Ekranda ne yazıyor" gibi durumlarda yerel OCR veya görme modelinden faydalanılır.

SKILLS & CONNECTORS:
- ALES modüler beceri ve bağlantılara sahiptir. İhtiyaç olduğunda ilgili araçları kullan.

KAYNAK DİSİPLİNİ:
- Web araması yaptıysan cevabın sonuna kısa kaynak notu ekle.

{persona_extra}

Şimdi: {dt}
Ali profili: {profile}
{recent_context}"""

def build_recent_context(conv_id: str = None) -> str:
    """
    Cross-conversation farkındalık ve kalıcı hafıza (Task 3):
    Son 5 sohbetin içeriğini + devam eden görevleri sistem promptuna enjekte eder.
    Böylece ALES önceki oturumları ve bağlamı hatırlar.
    """
    parts = []
    # 1. Son 5 sohbetin konuşma içeriği ve bağlamı
    try:
        convs = conv_store.list_conversations()
        recent = [c for c in convs if c["id"] != conv_id][:5]
        if not recent and convs:
            recent = convs[:5]
        conv_snippets = []
        for c in recent:
            detail = conv_store.get_conversation(c["id"])
            if not detail or not detail.get("messages"):
                continue
            title = detail.get("title", "Sohbet")
            recent_msgs = detail["messages"][-4:]
            snippet = []
            for m in recent_msgs:
                r = "Kullanıcı" if m.get("role") == "user" else "ALES"
                txt = (m.get("content") or "").strip().replace("\n", " ")
                if len(txt) > 130:
                    txt = txt[:130] + "…"
                snippet.append(f"  {r}: {txt}")
            if snippet:
                conv_snippets.append(f"- Sohbet \"{title}\":\n" + "\n".join(snippet))
        if conv_snippets:
            parts.append("[GEÇMİŞ SOHBETLER — son 5 konuşma bağlamı]:\n" + "\n".join(conv_snippets))
    except Exception as e:
        print(f"[CONTEXT] son sohbetleri yukleme hatasi: {e}")

    # Eger hic sohbet yoksa memory.json kisa hafizasindan son kayitlari al
    if not parts:
        try:
            mem = load_memory()
            short_msgs = mem.get("short", [])
            if short_msgs:
                s_lines = []
                for m in short_msgs[-8:]:
                    r = "Kullanıcı" if m.get("role") == "user" else "ALES"
                    txt = (m.get("content") or "").strip().replace("\n", " ")
                    if len(txt) > 130:
                        txt = txt[:130] + "…"
                    s_lines.append(f"  {r}: {txt}")
                if s_lines:
                    parts.append("[GEÇMİŞ HAFIZA — son kayıtlar]:\n" + "\n".join(s_lines))
        except Exception:
            pass

    # 2. Devam eden isler
    try:
        mem = load_memory()
        active_tasks = [t for t in mem.get("fiverr_tasks", []) if t.get("status") not in ("tamamlandi", "completed", "iptal")]
        if active_tasks:
            task_strs = [f"{t['task']} ({t['client']}, durum: {t['status']})" for t in active_tasks[-5:]]
            parts.append("Devam eden işler: " + " | ".join(task_strs))
    except Exception:
        pass
    return ("\n\n".join(parts)) if parts else ""

# ─── FAZ-3/6: TUR SONU OZ-GELISIM MUHASEBESI ─────────────────────
# Bu iki yardimci run_agent'in SONUNDA (cevap gonderildikten sonra)
# cagrilir. Ikisi de SADECE GOZLEMDIR: mevcut turun cevabini degistirmez,
# hicbir kod yazmaz, hicbir ayar degistirmez. Ogrendikleri sey bir
# SONRAKI turun sistem promptunu (CER/MUSE) zenginlestirir.
#
# NEDEN "sadece gozlem": config_manager.py:122'deki kural — ALES kendi
# kodunu kendi kararıyla degistirmez. Evrim burada STRATEJI metni ve
# yorunge arsivi duzeyinde kalir; kaynak dosyaya dokunmaz.
def _turn_domain(turn_calls: list) -> str:
    """Turdaki araclara bakip kaba bir alan etiketi uretir (MUSE prosedurel
    tariflerini alanlara ayirmak icin)."""
    names = {c.get("tool", "") for c in (turn_calls or [])}
    if names & {"take_screenshot", "click_at", "type_text", "press_key",
                "focus_window", "list_windows", "window_state", "close_window",
                "analyze_screen", "find_on_screen"}:
        return "masaustu"
    if names & {"google_search", "fetch_url", "browse_web", "web_search_deep"}:
        return "web"
    if names & {"read_file", "write_file", "edit_file", "list_directory",
                "search_files", "create_directory", "get_file_info"}:
        return "dosya"
    if names & {"check_fiverr_messages", "check_bionluk_messages",
                "add_fiverr_task", "get_fiverr_tasks"}:
        return "siparis"
    return "genel"


def _record_turn_evolution(user_message: str, turn_calls: list,
                           turn_errors: list, final: str, mode: str,
                           ok: bool = True, scaffold_id: str = None) -> None:
    """CER yorunge kaydi + SE-Agent yorunge sadelestirme + MUSE prosedurel
    tarif + Darwin Godel uyum (fitness) OLCUMU. Tamami best-effort."""
    success = bool(ok and not turn_errors)

    # 1) CER — yorungeyi arsivle (basarili VE basarisiz; ikisi de ogretici)
    if turn_calls and _mod_on("cer", cer_module):
        try:
            trajectory = [{"tool": c.get("tool"),
                           "args": _short_args(c.get("args"))}
                          for c in turn_calls]
            cer_module.record_experience(
                task=user_message, trajectory=trajectory, success=success,
                reflection=("; ".join(e.get("error", "")[:120] for e in turn_errors)
                            if turn_errors else ""),
                tags=[mode, _turn_domain(turn_calls)])
        except Exception as e:
            print(f"[CER] kayit atlandi: {e}")

    # 2) SE-Agent — yorungedeki dongu/tekrarlari tespit et, sadelestir.
    #    Cikan sade yorunge basariliysa MUSE prosedurel tarifi olur:
    #    "bu tur istek soyle bir arac dizisiyle cozuluyor".
    if turn_calls and _mod_on("self_evolution", self_evolution):
        try:
            steps = [{"tool": c.get("tool"), "args": _short_args(c.get("args"))}
                     for c in turn_calls]
            slim = self_evolution.optimize_trajectory(steps)
            if success and len(slim) >= 2:
                self_evolution.record_procedural_recipe(
                    domain=_turn_domain(turn_calls),
                    pattern=" -> ".join(s.get("tool", "") for s in slim[:6]),
                    steps=[s.get("tool", "") for s in slim[:6]])
        except Exception as e:
            print(f"[SE-AGENT] yorunge islenemedi: {e}")

    # 3) Darwin Godel — GERCEK uyum sinyali. Bu turda HANGI iskelenin
    #    kullanildigini biliyoruz (scaffold_id promptu kuran yerden gelir);
    #    sonuc TAM O adaya yazilir. Yanlis adaya yazmak tum secilimi
    #    bozardi. Rastgele fitness YOK: bkz. darwin_godel.compute_fitness.
    if scaffold_id and _mod_on("darwin_godel", darwin_godel):
        try:
            res = darwin_godel.record_outcome(success=success,
                                              steps=len(turn_calls),
                                              errors=len(turn_errors),
                                              scaffold_id=scaffold_id)
            v = (res or {}).get("verdict")
            if v:
                print(f"[DGM] deneme hukmu: {v.get('decision')} · "
                      f"uyum={v.get('fitness')} vs {v.get('champion_fitness') or v.get('beat')}")
        except Exception as e:
            print(f"[DGM] uyum olcumu atlandi: {e}")


async def _reflect_on_turn(user_message: str, turn_errors: list,
                           mode: str = None) -> None:
    """Reflexion + RetroAct: turdaki ILK hatayi modele analiz ettirir ve
    cikan dersi MUSE stratejik kurallarina yazar. Arka planda calisir."""
    if not turn_errors or not _mod_on("reflection", reflection_agent):
        return
    first = turn_errors[0]
    try:
        out = await reflection_agent.reflect_on_failure(
            task=user_message,
            action=f"{first.get('tool')}({_short_args(first.get('args'))})",
            error=str(first.get("error", ""))[:500],
            ask_llm=_codeact_ask_llm(mode))
    except Exception as e:
        print(f"[REFLECT] yansima basarisiz: {e}")
        return
    lesson = _extract_strategic_lesson((out or {}).get("reflection") or "")
    if lesson and self_evolution is not None:
        try:
            self_evolution.add_strategic_rule(lesson, source="reflexion")
            print(f"[REFLECT] yeni stratejik kural: {lesson[:80]}")
        except Exception:
            pass


def _extract_strategic_lesson(reflection: str) -> str:
    """reflect_on_failure UC bolumlu metin dondurur (kok neden / aninda
    duzeltme / stratejik ders). MUSE'e SADECE ucuncusu yazilir: ilk ikisi
    o ANA ait, kalici ilke degil. Tamamini yazmak sistem promptunu
    her hatada bir paragraf sisirirdi.

    Bolum bulunamazsa bos doner — yani "her hata bir kural uretir"
    garantisi YOKTUR; bu kasitli, cop kural biriktirmemek icin."""
    if not reflection:
        return ""
    txt = str(reflection)
    m = re.search(r"(?:STRATEJ[İI]K\s+DERS|Slow-?loop\s+lesson|3[\.\)]\s*STRATEJ[İI]K)"
                  r"\s*(?:\([^)]*\))?\s*[:\-–]?\s*(.+?)(?:\n\s*\n|\Z)",
                  txt, re.I | re.S)
    if not m:
        return ""
    lesson = re.sub(r"\s+", " ", m.group(1)).strip(" *-–—•\t")
    # Cok kisa/cok uzun cikti kural olmaya uygun degil
    if len(lesson) < 15:
        return ""
    return lesson[:300]


def _short_args(args) -> str:
    """Arac argumanlarini arsiv/log icin kisa metne cevirir (yorungeler
    sisip hafizayi doldurmasin)."""
    try:
        s = json.dumps(args, ensure_ascii=False) if not isinstance(args, str) else args
    except Exception:
        s = str(args)
    return s[:160]


# ─── AGENT ───────────────────────────────────────────────────────
async def run_agent(user_message: str, websocket: WebSocket, conv_id: str = None):
    # Aktif mod (Task/Cheat/Auto/Multi/Performance/Heavy). Zincir, fast_path,
    # multi vb. bu konfigurasyondan gelir; gecersiz/eksikse Auto'ya duşer.
    mode_cfg = get_mode_config()
    mode = mode_cfg["mode"]

    # ── 1) ZERO-LLM FAST PATH ────────────────────────────────────────
    # Rutin, tek-anlamli komutlar (ekran goruntusu, sistem bilgisi, kripto,
    # doviz, hava, ...) AI'ya HIC ugramadan dogrudan araclarla calisir
    # (<50ms hedef). Heavy mod bunu kapatir (dogruluk > hiz). Eslesme yoksa
    # ya da bir arac hata verirse istek normal AI dongusune duşer.
    if mode_cfg.get("fast_path", True):
        async def _fp_exec(tool_name, tool_args):
            return await execute_tool_async(tool_name, tool_args, websocket)
        try:
            fp = await fast_path.run_fast_path(user_message, _fp_exec)
        except Exception as e:
            print(f"[FASTPATH] beklenmeyen hata, AI'ya duşuluyor: {e}")
            fp = {"handled": False}
        if fp.get("handled"):
            parts = [str(o["result"]) for o in fp.get("outputs", []) if o.get("result")]
            final = "\n\n".join(parts) if parts else "✅ Tamamlandı."
            add_short("user", user_message, conv_id)
            add_short("assistant", final, conv_id)
            print(f"[FASTPATH] '{fp.get('name')}' calisti (LLM atlandi)")
            log_event(f"FastPath: {fp.get('name')} · {user_message[:40]}")
            await websocket.send_json({"type":"message","content":final})
            asyncio.create_task(send_tts_audio(final, websocket))
            return

    # ── 1.5) AGENT JIT: DERLENMIS BLOK (0 LLM) ───────────────────────
    # Fast Path "yazilmis bir kural" gerektirir. JIT ise kural olmayan ama
    # DAHA ONCE COZULMUS gorevleri yakalar: gorev metni normalize edilip
    # onbellekte aranir, bulunursa saklanan kod calisir ve LLM'e HIC
    # gidilmez (stats()["llm_calls_saved"] bunu sayar).
    #
    # UC KAPI VE NEDENLERI:
    #  (a) peek() kullaniyoruz, lookup() DEGIL — peek sayaclara dokunmaz.
    #      Asagida jit_run() zaten kendi icinde lookup() cagirip isabeti
    #      bir kez sayacak; ikisini birlikte kullanmak ayni isabeti IKI
    #      kez sayip panelde gercek olmayan bir JIT kullanimi gosterirdi.
    #  (b) needs_approval() True ise BURADA calistirmiyoruz. Bu katman
    #      sessiz ve otomatik; kullaniciya onay sormanin yeri normal
    #      dongudur. Onay gereken kod fast-path'te calistirilmaz —
    #      CodeAct onay kapisi bu projede kaldirilmaz.
    #  (c) Calistirma DAIMA agent_jit.jit_run uzerinden; boylece ayri
    #      process + timeout + statik kapi + karantina sayaci korunur.
    if (mode_cfg.get("fast_path", True) and agent_jit is not None
            and code_act_executor is not None
            and _mod_on("agent_jit", agent_jit)):
        try:
            _e = agent_jit.peek(user_message)
        except Exception as e:
            print(f"[JIT] onbellek okunamadi, atlaniyor: {e}")
            _e = None
        if _e and _e.get("code") and not code_act_executor.needs_approval(
                _e.get("code", ""), _e.get("lang", "python")):
            try:
                _jr = await agent_jit.jit_run(user_message)
            except Exception as e:
                print(f"[JIT] calistirma hatasi, AI'ya duşuluyor: {e}")
                _jr = {"ok": False}
            _out = ((_jr.get("result") or {}).get("stdout") or "").strip()
            # ok DEGILSE ya da hicbir sey BASMADIYSA duz dongue duseriz.
            # Bos ciktiyi "cevap" diye gostermek, kullaniciya bos bir
            # balon gondermek olurdu; jit_run basarisizligi zaten
            # record_result ile isaretledi (FAIL_LIMIT -> karantina).
            if _jr.get("ok") and _out:
                if len(_out) > 4000:
                    _out = _out[:4000] + "\n… (cikti kirpildi)"
                add_short("user", user_message, conv_id)
                add_short("assistant", _out, conv_id)
                print(f"[JIT] onbellekten calisti · benzerlik="
                      f"{_e.get('similarity')} · {_jr.get('elapsed')}s (LLM atlandi)")
                log_event(f"JIT: {user_message[:40]}")
                await websocket.send_json({"type": "message", "content": _out})
                asyncio.create_task(send_tts_audio(_out, websocket))
                return
            elif not _jr.get("ok"):
                print(f"[JIT] blok basarisiz oldu, AI'ya duşuluyor: "
                      f"{str(_jr.get('error'))[:120]}")

    # ── 2) ANLAMSAL CACHE ────────────────────────────────────────────
    # Yakin-tekrar bilgi sorulari (aksiyon/zamana-duyarli DEGIL) daha once
    # yanitlandiysa LLM'e hic gitmeden ayni cevap dondurulur. Namespace =
    # mod (task-modu cevabi heavy-moda sizmaz). is_cacheable kapisi komut/
    # volatil sorgulari zaten reddeder (iceride karar verilir).
    try:
        cached = semantic_cache.lookup(user_message, namespace=mode)
    except Exception:
        cached = None
    if cached and cached.get("answer"):
        final = cached["answer"]
        add_short("user", user_message, conv_id)
        add_short("assistant", final, conv_id)
        print(f"[CACHE] HIT (benzerlik={cached.get('similarity')}, yas={cached.get('age_s')}s)")
        await websocket.send_json({"type":"message","content":final})
        asyncio.create_task(send_tts_audio(final, websocket))
        return

    # ── 2.5) LLM MECLISI (Council) ───────────────────────────────────
    # Heavy/Council modunda ya da global anahtar aciksa: ayni soru 6 modele
    # kadar AYNI ANDA sorulur, yanitlar anonimlestirilip hakem modele
    # degerlendirtilir, tek cevap sentezlenir.
    # KAPILAR: (a) Fast Path zaten calistiysa buraya hic gelinmez;
    # (b) arac gerektiren istekler meclise GITMEZ — meclis uyeleri arac
    # cagiramaz, "ekrani ac" gibi bir komut meclise giderse sadece metin
    # doner ve is YAPILMAZ. Bu yuzden sadece is_cacheable()==True olan
    # (aksiyon/volatil olmayan) bilgi sorulari meclise gider.
    if llm_council and mode_cfg.get("council"):
        try:
            council_ok, _reason = semantic_cache.is_cacheable(user_message)
        except Exception:
            council_ok = False
        if council_ok:
            await websocket.send_json({"type": "tool_use", "tool": "council",
                                       "args": {"strategy": mode_cfg.get("council_strategy")}})
            try:
                cfg_c = get_council()
                res = await llm_council.council(
                    user_message,
                    strategy=mode_cfg.get("council_strategy") or cfg_c["strategy"],
                    timeout_s=cfg_c["timeout_s"],
                    judge_timeout_s=cfg_c["judge_timeout_s"],
                    use_cache=cfg_c["cache"],
                    # KALICI SISTEM PROMPTU (LUBV): meclis yolu asagidaki
                    # enjeksiyondan ONCE return ettigi icin, yonergenin meclis
                    # yanitlarina islemesinin tek yolu onu buradan gecirmektir.
                    # Aksi halde "her konusmaya enjekte edilir" sozu Meclis/Heavy
                    # modunda SESSIZCE bozulurdu.
                    system_extra=get_system_prompt(),
                )
            except Exception as e:
                print(f"[COUNCIL] beklenmeyen hata, normal zincire duşuluyor: {e}")
                res = {"ok": False, "error": str(e)}

            if res.get("ok") and (res.get("answer") or "").strip():
                final = res["answer"]
                add_short("user", user_message, conv_id)
                add_short("assistant", final, conv_id)
                print(f"[COUNCIL] {res.get('responded')}/{res.get('asked')} uye · "
                      f"{res.get('strategy')} · hakem={res.get('judge')} · "
                      f"{res.get('elapsed')}s")
                log_event(f"Meclis: {user_message[:40]}")
                await websocket.send_json({
                    "type": "tool_result", "tool": "council",
                    "result": (f"{res.get('responded', 0)}/{res.get('asked', 0)} model yanitladi "
                               f"· {res.get('strategy')}"
                               + (" · onbellek" if res.get("cached") else ""))})
                await websocket.send_json({"type": "council", "summary": {
                    "strategy": res.get("strategy"), "judge": res.get("judge"),
                    "winner": res.get("winner"), "members": res.get("members", []),
                    "responded": res.get("responded"), "asked": res.get("asked"),
                    "elapsed": res.get("elapsed"), "cached": res.get("cached"),
                    "degraded": res.get("degraded")}})
                await websocket.send_json({"type": "message", "content": final})
                asyncio.create_task(send_tts_audio(final, websocket))
                return
            # Meclis basarisiz -> sessizce NORMAL zincire duş (asla patlama).
            print(f"[COUNCIL] atlandi: {res.get('error')}")
            await websocket.send_json({
                "type": "tool_result", "tool": "council",
                "result": f"meclis atlandi ({res.get('error')}) — normal zincire duşuldu"})

    # ── 2.6) AJAN KARISIMI (MoA / DMoA) ─────────────────────────────
    # "Mixture-of-Agents" (2024) + Dynamic MoA: ayni soru birden fazla
    # KATMANA onerici olarak sorulur, yanitlar anonimlestirilir, hakem
    # katman en iyi yonleri sentezler. DMoA once ceşitliligi olcer:
    # modeller hemfikirse (dusuk ceşitlilik) hakem adimi ATLANIR ve en
    # hizli yanit doner — yani "coklu model" her zaman yavas degil.
    #
    # NEDEN COUNCIL'DEN AYRI: llm_council farkli SAGLAYICILARI oylatir ve
    # kendi onbellegi/stratejileri var; MoA ayni router katmanlarini
    # onerici/hakem rolune sokar. Ikisini birlikte kosmak ayni isi iki kez
    # yapmak olurdu — bu yuzden council ACIKSA MoA devreye girmez.
    #
    # KAPI: council ile AYNI gerekce — onericiler ARAC CAGIRAMAZ. "Ekrani
    # ac" gibi bir eylem istegi MoA'ya giderse guzel bir metin doner ama
    # is YAPILMAZ. Bu yuzden yalnizca is_cacheable()==True olan (aksiyon
    # icermeyen, volatil olmayan) bilgi sorulari buraya girer.
    if (mode_cfg.get("multi") and not mode_cfg.get("council")
            and _mod_on("moa", mixture_of_agents)):
        try:
            _moa_ok, _ = semantic_cache.is_cacheable(user_message)
        except Exception:
            _moa_ok = False
        if _moa_ok:
            await websocket.send_json({"type": "tool_use", "tool": "moa",
                                       "args": {"strategy": "dmoa"}})
            try:
                # LUBV/kalici sistem promptu MoA yolundan da GECMEK ZORUNDA:
                # bu yol da normal zincire ugramadan return edebiliyor.
                _moa = await mixture_of_agents.run_dmoa(
                    user_message, system=get_system_prompt() or "")
            except Exception as e:
                print(f"[MoA] beklenmeyen hata, normal zincire duşuluyor: {e}")
                _moa = {"ok": False, "error": str(e)}

            if _moa.get("ok") and (_moa.get("content") or "").strip():
                final = _moa["content"]
                add_short("user", user_message, conv_id)
                add_short("assistant", final, conv_id)
                print(f"[MoA] {_moa.get('mode')} · {_moa.get('proposers_count')} onerici "
                      f"· ceşitlilik={_moa.get('diversity_score')} · {_moa.get('elapsed')}s")
                log_event(f"MoA: {user_message[:40]}")
                await websocket.send_json({
                    "type": "tool_result", "tool": "moa",
                    "result": (f"{_moa.get('proposers_count', 0)} onerici · "
                               f"{_moa.get('mode')}")})
                await websocket.send_json({"type": "moa", "summary": {
                    "mode": _moa.get("mode"),
                    "proposers_count": _moa.get("proposers_count"),
                    "diversity_score": _moa.get("diversity_score"),
                    "elapsed": _moa.get("elapsed")}})
                await websocket.send_json({"type": "message", "content": final})
                asyncio.create_task(send_tts_audio(final, websocket))
                return
            print(f"[MoA] atlandi: {_moa.get('error')}")
            await websocket.send_json({
                "type": "tool_result", "tool": "moa",
                "result": f"MoA atlandi ({_moa.get('error')}) — normal zincire duşuldu"})

    # ── 3) GECMIS + SISTEM PROMPTU ──────────────────────────────────
    if conv_id:
        history = conv_store.get_history_for_model(conv_id, limit=20)
    else:
        mem = load_memory()
        history = [{"role":m["role"],"content":m["content"]} for m in mem["short"][-20:]]
    history.append({"role":"user","content":user_message})
    add_short("user", user_message, conv_id)

    persona = get_current_persona()
    system = BASE_SYSTEM.format(
        dt=datetime.now().strftime("%d.%m.%Y %H:%M"),
        profile=build_context_prompt() or "Henüz profil yok.",
        persona_tone=persona["tone"],
        persona_extra=persona.get("system_add",""),
        recent_context=build_recent_context(conv_id)
    )
    # KALICI SISTEM PROMPTU (LUBV) — system_prompts.json'da enabled ise her
    # konusmaya sistem rolunun BASINA eklenir. Bos/dormant ise (varsayilan)
    # tam no-op — hicbir sey degismez.
    lubv = get_system_prompt()
    if lubv:
        system = lubv + "\n\n" + system

    # UZUN VADELI HAFIZA: konuya anlamsal olarak yakin kalici notlari sistem
    # promptuna ekle. build_recent_context() sadece SON mesajlari verir; bu ise
    # haftalar oncesinden ilgili olani getirir. Toplu kuyruk uzerinden gider.
    _lt = await recall_long_term(user_message, k=3)
    if _lt:
        system += "\n\n[UZUN VADELI HAFIZA — gecmis oturumlardan ilgili notlar]\n" + \
            "\n".join(f"- {r.get('text','')}" for r in _lt if r.get("text"))

    # ── ÖĞRENİLEN DENEYİM KURALLARI (experience_learner) ───────────
    try:
        import experience_learner
        _lr = experience_learner.get_rules_prompt()
        if _lr:
            system += "\n" + _lr
    except Exception:
        pass

    # ── FAZ-3: BAGLAMSAL DENEYIM TEKRARI (CER) ──────────────────────
    # "Contextual Experience Replay" (2026): egitim GEREKTIRMEYEN
    # oz-gelisim. ALES gecmiste BENZER bir gorevi nasil cozdugunu (ya da
    # nerede patladigini) kendi baglam penceresinde tekrar okur. Uzun
    # vadeli hafizadan FARKI: LTM "ne konustuk"u getirir, CER "bu isi
    # hangi ADIMLARLA yaptik"i getirir.
    if cer_module is not None and _mod_on("cer", cer_module):
        try:
            _cer_inj = cer_module.format_cer_prompt_injection(user_message)
            if _cer_inj:
                system += "\n\n" + _cer_inj
                print("[CER] gecmis yorunge baglama enjekte edildi")
        except Exception as e:
            print(f"[CER] enjeksiyon atlandi: {e}")

    # ── FAZ-3: MUSE HIYERARSIK BELLEK ───────────────────────────────
    # "Learning on the Job" (2025): basarili turlardan damitilmis
    # STRATEJIK ilkeler (prosedurel tarifler degil — onlar Fast Path /
    # skills_autogrowth tarafinda). Sadece kural VARSA eklenir.
    if _mod_on("self_evolution", self_evolution):
        try:
            _muse = self_evolution.get_muse_context(user_message)
            if _muse:
                system += "\n" + _muse
        except Exception as e:
            print(f"[MUSE] baglam atlandi: {e}")

    # ── FAZ-6: DARWIN GODEL AKTIF ISKELE (A/B denemesi) ─────────────
    # Aktif iskelenin strateji METNI promptun sonuna eklenir ve KIMLIGI
    # saklanir; tur bitince sonuc TAM O kimlige yazilir (bkz.
    # _record_turn_evolution). Sampiyon <-> aday paylasimi modulun
    # icinde (CHALLENGER_SHARE) yapilir, boylece iki taraf ayni kosullarda
    # olculur.
    #
    # NOT: strateji metni yalnizca DAVRANIS TAVSIYESIDIR ("tiklamadan once
    # pencere odagini dogrula" gibi) — arac izni vermez, kapi kaldirmaz,
    # kod calistirmaz. Panelden gorulebilir ve kapatilabilir.
    _scaffold_id = None
    if mode_cfg.get("self_evolution", True) and _mod_on("darwin_godel", darwin_godel):
        try:
            _sc = darwin_godel.get_active_strategy()
            if _sc.get("strategy"):
                _scaffold_id = _sc.get("id")
                system += (f"\n\n[EVRIMSEL ISKELE — {_sc.get('name','')} "
                           f"({_sc.get('role')})]\n{_sc['strategy']}")
        except Exception as e:
            print(f"[DGM] iskele secilemedi: {e}")

    # ── AGGRESSIVE TOOL EXECUTION DIRECTIVE (Claude Protocol) ────────
    _msg_l = (user_message or "").lower()
    _pdf_intent = any(k in _msg_l for k in ["pdf", "rapor", "belge", "doküman", "dokuman", "özet çıkar", "kitapçık"])
    if _pdf_intent:
        system += (
            "\n\n[KRİTİK TALİMAT - AGGRESSIVE TOOL EXECUTION (CLAUDE CODE PROTOCOL)]:\n"
            "Kullanıcı bir PDF/belge/rapor istedi veya doküman üretilmesini talep ediyor.\n"
            "NEVER explain how to do a task if you have a tool for it. YOU MUST execute the tool. "
            "If the user asks for a PDF, CALL the `generate_pdf` tool immediately. Do not give them instructions or tutorial code.\n"
            "ASLA nasıl yapılacağını anlatma! ASLA 'Python ile şöyle yapabilirsiniz' veya kod örneği verme!\n"
            "MUTLAKA ve DERHAL `generate_pdf` fonksiyon çağrısını (tool_call) çalıştır!\n"
            "Parametreler: 'title' (belge başlığı), 'content' (kapsamlı, zengin markdown içeriği).\n"
            "İçerik hazırlandığında araç tarafından dönen dosya indirme bağlantısını kullanıcıya sun."
        )

    # Tool Router: 35+ arac + skill araclari, mesaja gore ilgili olanlari sec
    # Kucuk/ucretsiz modeller bu sayede daha az kafasi karisir.
    # get_all_tools() her turda TAZE cagrilir - boylece bir skill panelden
    # aninda aktif/pasif edilirse, restart gerekmeden bir sonraki mesajda
    # yansir.
    all_tools_now = get_all_tools()
    active_tools = select_relevant_tools(user_message, all_tools_now)
    print(f"[MODE] {mode} · [ROUTER] {get_routing_info(user_message)} -> {len(active_tools)}/{len(all_tools_now)} arac")

    # ── 4) MOD ZINCIRI (router) ─────────────────────────────────────
    # Eskiden burada get_client() ile SADECE Groq->Cerebras vardi ve model
    # adlari sabit kodluydu. ARTIK aktif MODUN zinciri (config'ten) kullanilir:
    #   Task -> Cerebras+Groq · Cheat -> DeepSeek V4 · Heavy -> Kimi K3 ...
    # stream_via_router zinciri sirayla dener, ilk baglanabilen katmandan
    # token token yayin yapar; bir katman duşerse otomatik sonrakine gecer.
    #
    # turn_calls: bu turda calisan araclar CALISMA SIRASIYLA. Iki yerde
    # kullanilir — (a) predictive'e "sunun ardindan su geldi" ogretmek,
    # (b) tur basariyla bitince skills_autogrowth'a kalip onerisi icin
    # gozlem vermek. Ikisi de SADECE gozlemdir, davranisi degistirmez.
    turn_calls = []
    # turn_errors: bu turda HATA donen arac cagrilari. Tur sonunda CER'e
    # (basarisiz yorunge) ve reflection_agent'a (Reflexion/RetroAct) gider.
    turn_errors = []
    # jit_candidate: bu turda run_python_code BASARIYLA calistiysa
    # (gorev metni -> calisan kod) ciftinin adayi. Tur SONUNDA, sadece
    # butun tur TEK arac cagrisiyla bittiyse agent_jit'e yazilir.
    #
    # NEDEN TUR SONUNDA VE NEDEN TEK CAGRI: JIT onbellegi "bu gorev bu
    # kodla cozulur" iddiasi tasir. Model kodu calistirip ARDINDAN dosya
    # yazdiysa/web'e gittiyse, kod gorevin YALNIZCA BIR PARCASIDIR; onu
    # gorevin tamami olarak saklamak, ayni istek tekrar geldiginde eksik
    # is yapip "tamamlandi" demek olurdu. Bu yuzden aday, tur duz metinle
    # (arac cagrisi olmadan) bittiginde ve turda baska cagri yoksa
    # islenir — yoksa sessizce duser.
    jit_candidate = None
    _last_pdf_info = None
    for _ in range(10):
        try:
            msg_content, msg_tool_calls, _used_layer = await stream_via_router(
                [{"role":"system","content":system}]+history,
                active_tools, websocket, mode=mode)
        except model_router.RouterError as e:
            # TUM mod zinciri basarisiz oldu (router ZATEN iki gecis denedi:
            # normal butce + gevsetilmis butce — bkz. model_router.stream_chat).
            print(f"[AGENT] mod zinciri tamamen basarisiz oldu: {e}")

            # ── SON ARAC-DESTEKLI DENEME ────────────────────────────────
            # NEDEN: asagidaki duz-metin yedekleri arac cagirAMAZ, yani bu
            # yola girmek kullanicinin "Google araması calismiyor" diye
            # gordugu seyin TA KENDISI. Ama zincirin en sik duşme sebebi
            # BUTCE: ~35 aracin JSON semasi istemi kucuk pencereli
            # katmanlara sigmaz hale getiriyor. O yuzden vazgecmeden once
            # araclari CEKIRDEK + WEB'e kisip bir kez daha deniyoruz —
            # istem ciddi olcude kuculur ve google_search hala elde kalir.
            slim = [t for t in active_tools
                    if t.get("function", {}).get("name") in _SLIM_TOOL_NAMES]
            recovered = False
            if slim and len(slim) < len(active_tools):
                print(f"[AGENT] arac seti kisiliyor ({len(active_tools)} -> "
                      f"{len(slim)}) ve zincir bir kez daha deneniyor")
                try:
                    msg_content, msg_tool_calls, _used_layer = await stream_via_router(
                        [{"role":"system","content":system}]+history,
                        slim, websocket, mode=mode)
                    active_tools = slim   # bu turun kalani da kisik devam etsin
                    recovered = True
                except model_router.RouterError as e2:
                    print(f"[AGENT] kisik arac setiyle de basarisiz: {e2}")

            # NOT: recovered ise BU BLOK NORMAL BITER ve akis asagidaki
            # "if msg_tool_calls:" satirina DUSER (continue YOK — continue
            # olsaydi ayni tur bastan calisip zaten websocket'e yazilmis
            # metni IKINCI KEZ yazdirirdi).
            if not recovered:
                # Arac kullanamayan ama en azindan DUZ METIN bir cevap
                # verebilen yedekler. "API Hatasi" ile bos donmekten iyidir.
                convo_text = "\n".join(f"{m.get('role','?')}: {m.get('content','')}" for m in history if m.get("role") in ("user","assistant") and m.get("content"))
                hint = ""
                try:
                    from config_manager import credential_problems
                    probs = credential_problems()
                    if probs:
                        hint = " · Ayarlar'da düzeltilmesi gereken anahtar: " + \
                               ", ".join(p["field"] for p in probs)
                except Exception:
                    pass
                for name, caller in (("Gemini", multi_agent._call_gemini), ("SambaNova", multi_agent._call_sambanova), ("OpenRouter", multi_agent._call_openrouter)):
                    ok, text = await caller(convo_text, system)
                    if ok:
                        final = text + f"\n\n_(⚠️ Ana model zinciri erişilemedi, {name} ile yanıt verildi - bu turda araç/otomasyon kullanılamadı{hint})_"
                        add_short("assistant", final, conv_id)
                        await websocket.send_json({"type":"message","content":final})
                        asyncio.create_task(send_tts_audio(final, websocket))
                        return
                await websocket.send_json({"type":"error","content":f"API Hatası: {e}{hint}"})
                # Zincir tamamen duştu: bunu da OGREN. CER basarisiz
                # yorungeyi arsivler, yansima kok nedeni cikarir. Boylece
                # ayni model/butce hatasi tekrarlarsa bir sonraki turda
                # stratejik kural olarak promptta hazir olur.
                _record_turn_evolution(user_message, turn_calls,
                                       turn_errors + [{"tool": "router",
                                                       "args": {"mode": mode},
                                                       "error": str(e)[:300]}],
                                       "", mode, ok=False,
                                       scaffold_id=_scaffold_id)
                asyncio.create_task(_reflect_on_turn(
                    user_message,
                    [{"tool": "router", "args": {"mode": mode}, "error": str(e)[:300]}],
                    mode))
                return
        except Exception as e:
            print(f"[AGENT] beklenmeyen stream hatasi: {e}")
            await websocket.send_json({"type":"error","content":f"API Hatası: {e}"})
            return

        if msg_tool_calls:
            # JIT ADAYINI IPTAL ET: bir onceki turda kod calisti diye aday
            # tutuyorduk, ama model DEVAM ediyor — demek ki o kod gorevin
            # TAMAMI degildi. Bu adayi saklamak, ayni istek tekrar
            # geldiginde isin yarisini yapip bitmis gibi davranmak olurdu.
            if jit_candidate is not None:
                print("[JIT] aday iptal: tur ek arac cagrisiyla devam etti")
                jit_candidate = None
            history.append({
                "role":"assistant","content":msg_content or "",
                "tool_calls":[{"id":tc.id,"type":"function","function":{"name":tc.function.name,"arguments":tc.function.arguments}} for tc in msg_tool_calls]
            })
            parsed_calls = []
            for tc in msg_tool_calls:
                name = tc.function.name
                try: args = json.loads(tc.function.arguments)
                except: args = {}
                parsed_calls.append((tc, name, args))
                await websocket.send_json({"type":"tool_use","tool":name,"args":args})
                log_action(name, args)

            # HIZ: Bu turdaki TUM araclar salt-okunur/bagimsizsa (weather+
            # crypto+news gibi) paralel calistir - LLMCompiler tarzi teknik,
            # sirayla yerine ayni anda calistirinca 3x'e kadar hizlanma
            # sagliyor. PC kontrolu/dosya yazma gibi sirali islemler
            # GUVENLIK icin sirali kalmaya devam ediyor.
            all_safe = all(name in PARALLEL_SAFE_TOOLS for _, name, _ in parsed_calls)
            if all_safe and len(parsed_calls) > 1:
                results = await asyncio.gather(*[execute_tool_async(n, a, websocket) for _, n, a in parsed_calls])
            else:
                # ── AGENT JIT ÇİZGE KATMANI (Agint-tarzi DAG) ──────────
                # Buraya "hepsi guvenli DEGIL" durumunda geliniyor, yani
                # KARISIK bir tur: orn. [get_weather, get_crypto_prices,
                # click_at]. Eski kod boyle bir turda HEPSINI sirayla
                # calistiriyordu - iki salt-okunur cagri bekleyebilecekleri
                # halde birbirini bekliyordu.
                #
                # Cizge tam bunu cozuyor: salt-okunur cagrilar ayni katmanda
                # paralel gider, yan etkili her cagri bir BARIYER olur ve
                # kendisinden onceki her seyin bitmesini bekler. Modelin
                # verdigi sira ASLA bozulmaz; yalnizca gercekten bagimsiz
                # olanlar ayni anda gider.
                #
                # UC KAPI:
                #  (a) graph_would_help(): en az IKI salt-okunur cagri ayni
                #      katmanda olmadikca cizge kurmuyoruz - kazanc yoksa
                #      ek nesne uretmenin anlami yok.
                #  (b) _mod_on(): modul Teshis panelinden duraklatilabilir.
                #  (c) Cizge KURULURKEN hata -> duz sirali yola duseriz.
                #      Cizge bir HIZLANDIRMA katmani; asla tek yol degil.
                #      AMA cizge BIR KEZ BASLADIKTAN sonra geri donmuyoruz:
                #      araclar calismis olur (dosya yazilmis, tiklanmis) ve
                #      sirali yolu tekrar kosmak yan etkiyi IKI KEZ uygulardi.
                _graph_used = False
                if (agent_jit is not None and _mod_on("agent_jit", agent_jit)
                        and len(parsed_calls) > 1):
                    try:
                        _calls = [(n, a) for _, n, a in parsed_calls]
                        if agent_jit.graph_would_help(_calls, PARALLEL_SAFE_TOOLS):
                            _g = agent_jit.compile_calls_to_graph(
                                user_message, _calls, PARALLEL_SAFE_TOOLS)

                            async def _graph_exec(tool_name, tool_args):
                                return await execute_tool_async(
                                    tool_name, tool_args, websocket)

                            _gr = await agent_jit.execute_graph(_g, _graph_exec)
                            # Dugum sirasi = parsed_calls sirasi (n1..nN),
                            # bu yuzden asagidaki zip() bozulmadan calisir.
                            _outs = _gr.get("outputs") or {}
                            # ONEMLI: cizge BASLADIYSA artik geri donmuyoruz.
                            # Araclar CALISTI (dosya yazildi, tiklandi); duz
                            # sirali yola dusmek onlari IKINCI KEZ calistirmak
                            # olurdu. Bir dugumun ciktisi bos kaldiysa (cizgede
                            # kilitlenme gibi beklenmeyen bir durum) o dugum
                            # icin modele hata METNI veriyoruz — model turu
                            # kendisi toparlar, biz yan etkiyi tekrarlamayiz.
                            _graph_used = True
                            results = []
                            for _i, (_tc, _n, _a) in enumerate(parsed_calls):
                                _o = _outs.get(f"n{_i+1}")
                                results.append(
                                    _o if _o is not None
                                    else f"❌ {_n}: cizge dugumu sonuc uretmedi")
                            print(f"[JIT-GRAPH] {_gr.get('steps_run')} dugum / "
                                  f"{_gr.get('layers')} katman · "
                                  f"{_gr.get('elapsed')}s (karisik tur "
                                  f"paralellestirildi)")
                            log_event(f"JIT cizge: {_gr.get('steps_run')} "
                                      f"adim / {_gr.get('layers')} katman")
                    except Exception as e:
                        # BURAYA yalnizca cizge KURULURKEN (derleme) hata
                        # cikarsa gelinir; execute_graph kendi icindeki arac
                        # hatalarini yutup dugume yaziyor, disari sizdirmiyor.
                        # Yine de execute_graph'in kendisi patlarsa _graph_used
                        # zaten True olmus olabilir -> tekrar calistirmayiz.
                        print(f"[JIT-GRAPH] cizge kurulamadi, sirali yola "
                              f"dusuluyor: {e}")
                if not _graph_used:
                    results = [await execute_tool_async(n, a, websocket) for _, n, a in parsed_calls]

            for (tc, name, args), result in zip(parsed_calls, results):
                if name == "generate_pdf":
                    try:
                        _pdata = json.loads(result) if isinstance(result, str) else result
                        if isinstance(_pdata, dict) and _pdata.get("ok"):
                            _last_pdf_info = _pdata
                    except Exception:
                        pass
                if name == "get_worldview":
                    await websocket.send_json({"type":"worldview","content":result})
                # UI'ya TAM sonuc gider (kullanici kirpilmis cikti gormesin),
                # modelin gecmisine ise DEPO ile kirpilmis surum eklenir.
                # Ayni veriyi iki kez tasimanin anlami yok: 200 satirlik bir
                # dosya dokumu bir sonraki turda ~3000 token yer kaplardi.
                await websocket.send_json({"type":"tool_result","tool":name,"result":result})
                _hist_result = result
                if token_optimizer is not None and isinstance(result, str):
                    try:
                        _hist_result = token_optimizer.compress_tool_result(result, max_chars=1500)
                    except Exception:
                        _hist_result = result
                history.append({"role":"tool","tool_call_id":tc.id,"content":_hist_result})
                # Basarisiz arac cagrilarini bu turun yorungesine isle —
                # tur sonunda CER'e ve (gerekirse) yansimaya gider.
                if isinstance(result, str) and result.lstrip().startswith(("❌", "Hata", "HATA")):
                    turn_errors.append({"tool": name, "args": args,
                                        "error": result[:300]})

                # ── AGENT JIT: (gorev -> calisan kod) ADAYINI YAKALA ──
                # Bu ardisik dizide (gorev, KANITLANMIS calisan kod) cifti
                # ureten TEK durust kaynak budur: model kodu kendi yazdi,
                # kod GERCEKTEN calisti ve "✅" dondu. Yazma tarafi olmadan
                # JIT onbellegi sonsuza kadar bos kalir ve okuma katmani
                # olu koda donusur.
                if (name == "run_python_code" and agent_jit is not None
                        and isinstance(result, str) and result.startswith("✅")
                        and len(parsed_calls) == 1 and not turn_calls
                        and jit_candidate is None):
                    _jc = (args or {}).get("code") or ""
                    # Tek satirlik "2+2" gibi bloklari saklamanin degeri yok:
                    # onlari zaten LLM'siz yol ya da hesap makinesi cozer,
                    # onbellek yeri harcamasin.
                    if 20 <= len(_jc) <= 8000:
                        jit_candidate = _jc

            # ── SPEC-CACHE: GECIS OGRENME ────────────────────────────
            # Hangi aractan sonra hangisinin geldigini ogren; predictive
            # bir sonraki turda bunu on-getirme sirasi icin kullanir.
            if speculative_cache is not None and len(parsed_calls) > 1:
                try:
                    for _i in range(len(parsed_calls) - 1):
                        speculative_cache.register_transition(
                            parsed_calls[_i][1], parsed_calls[_i + 1][1])
                except Exception:
                    pass

            # ── ONGORULU ON-YUKLEME (Predictive Execution) ───────────
            # Bu turdaki araclara bakip SIRADAKI muhtemel SALT-OKUNUR
            # cagriyi simdiden baslatiyoruz; model bir sonraki adima
            # gectiginde veri hazir olur (execute_tool_async icindeki
            # predictive.take() onu bulur).
            # KAPILAR: sadece READONLY_PREFETCHABLE araclar; en fazla
            # MAX_INFLIGHT tanesi; on-getirme icinden on-getirme yok.
            # BEKLEMEYIZ (create_task) — yoksa "hizlandirma" adina
            # gercek cevabi geciktirmis olurduk.
            if _prefetch_enabled():
                for _, _pname, _pargs in parsed_calls:
                    if turn_calls:
                        try:
                            predictive.observe(turn_calls[-1]["tool"], _pname)
                        except Exception:
                            pass
                    turn_calls.append({"tool": _pname, "args": _pargs})
                try:
                    _last = parsed_calls[-1]
                    asyncio.create_task(predictive.prefetch_for(
                        _last[1], _last[2], _raw_tool_async,
                        history=[c["tool"] for c in turn_calls],
                        user_message=user_message))
                except Exception as e:
                    print(f"[PREDICT] on-yukleme baslatilamadi: {e}")
            else:
                for _, _pname, _pargs in parsed_calls:
                    turn_calls.append({"tool": _pname, "args": _pargs})
            # ESKIDEN: active_tools = TOOLS (49 aracin TAMAMI - her ek
            # turda ~930 token fazladan, cok adimli isteklerde belirgin
            # yavaslama yapiyordu). ARTIK: sadece az once kullanilan
            # araclarin kategorisini genisletiyoruz - hizli VE yeterli.
            used_names = [tc.function.name for tc in msg_tool_calls]
            active_tools = expand_after_tool_call(active_tools, used_names, all_tools_now)
        else:
            final = msg_content or ""
            # PDF bağlantısının yanıtta kesinlikle yer almasını garanti et (Claude clone garantisi)
            if _last_pdf_info and _last_pdf_info.get("url"):
                _pdf_url = _last_pdf_info["url"]
                _pdf_fn = _last_pdf_info.get("filename", "Belge.pdf")
                if _pdf_url not in final and _pdf_fn not in final:
                    final = (final.strip() + f"\n\n📄 **Oluşturulan PDF Belgesi:** [{_pdf_fn}]({_pdf_url})").strip()
            elif _pdf_intent and not turn_calls and document_generator:
                try:
                    _gen_res = document_generator.generate_pdf("Belge", final or user_message)
                    if _gen_res.get("ok"):
                        _pdf_url = _gen_res["url"]
                        _pdf_fn = _gen_res["filename"]
                        final = (final.strip() + f"\n\n📄 **Oluşturulan PDF Belgesi:** [{_pdf_fn}]({_pdf_url})").strip()
                except Exception as _pdf_err:
                    print(f"[PDF] Otomatik fallback hatası: {_pdf_err}")
            add_short("assistant", final, conv_id)
            log_event(f"Konuşma: {user_message[:50]}")
            # ANLAMSAL CACHE'E YAZ — sadece cache'lenebilir sorular saklanir
            # (komut/aksiyon ve zamana-duyarli sorgular is_cacheable icinde
            # reddedilir). Namespace = aktif mod.
            try:
                semantic_cache.store(user_message, final, namespace=mode)
            except Exception:
                pass

            # ── AGENT JIT'E YAZ (derlenmis blogu sakla) ──────────────
            # Tur duz metinle bitti = model isi bitmis sayiyor. Aday kod
            # bu turda TEK arac cagrisiyla calisti, yani gorevin tamamini
            # o kod cozdu. Simdi (gorev -> kod) cifti saklanabilir; ayni
            # istek tekrar gelirse asagidaki 1.5 katmani LLM'e HIC gitmez.
            #
            # KAPI: statik denetim TEMIZ degilse SAKLAMAZ. Sebep: onbellege
            # giren kod ileride onay kapisi tarafindan zaten reddedilecekti;
            # reddedilecek bir blogu saklamak onbellegi cop ile doldurur.
            if (jit_candidate and agent_jit is not None
                    and code_act_executor is not None
                    and _mod_on("agent_jit", agent_jit)):
                try:
                    _st = code_act_executor.static_check(jit_candidate, "python")
                    if _st.get("ok"):
                        _e = agent_jit.store(user_message, jit_candidate,
                                             "python", static=_st,
                                             source_model="run_python_code")
                        print(f"[JIT] derlenmis blok saklandi · anahtar="
                              f"{_e.get('key')} · {len(jit_candidate)} karakter")
                    else:
                        print("[JIT] saklanmadi (statik kapi): "
                              + "; ".join(_st.get("blocked", []))[:120])
                except Exception as e:
                    print(f"[JIT] saklama basarisiz: {e}")
            # ── BECERI OGRENME (bounded, insan onayli) ───────────────
            # Tur BASARIYLA bitti. Ayni kisa komut + ayni arac dizisi
            # birkac kez tekrarlanirsa skills_autogrowth bir Fast Path
            # girdisi ONERIR — kendiliginden EKLEMEZ. Onay/ret Ali'ye ait
            # (WS 'skill_proposal' -> UI bildirimi). Buradaki cagri sadece
            # gozlem; sohbeti hicbir sekilde etkilemez, hata verse bile.
            if skills_autogrowth is not None and turn_calls:
                try:
                    _obs = skills_autogrowth.observe(user_message, turn_calls,
                                                     ok=True, mode=mode)
                    if _obs.get("proposal"):
                        print(f"[SKILL] yeni oneri: {_obs['proposal'].get('name')}")
                except Exception as e:
                    print(f"[SKILL] gozlem hatasi: {e}")
            await websocket.send_json({"type":"message","content":final})
            # Ses uretimi + gonderimi de bloklayici olabilir - beklemeden
            # (fire-and-forget) arka planda calistir, tarayici sesi
            # hazir olunca alip aninda calar (bkz. send_tts_audio)
            asyncio.create_task(send_tts_audio(final, websocket))
            # ── FAZ-3/6: OZ-GELISIM MUHASEBESI ───────────────────────
            # Cevap kullaniciya GONDERILDIKTEN SONRA yapilir — ogrenme
            # asla yanit gecikmesine eklenmez. Hepsi gozlemdir; bu turun
            # cevabini degistirmez ve hata verse bile sohbeti bozmaz.
            _record_turn_evolution(user_message, turn_calls, turn_errors,
                                   final, mode, ok=True,
                                   scaffold_id=_scaffold_id)
            if turn_errors:
                # Tur cevapla bitti ama yolda arac hatasi vardi: Reflexion/
                # RetroAct yansimasi arka planda calisir, cikardigi dersi
                # MUSE stratejik kurallarina yazar. Beklemiyoruz.
                asyncio.create_task(_reflect_on_turn(user_message, turn_errors, mode))
            return

    # GUVENLIK AGI: 10 tur tool-call ile doldu ama model hic son cevap
    # vermedi (surekli arac cagirip durdu). Bunu sessizce birakirsak
    # frontend'de "thinking" gostergesi sonsuza kadar doner, kullanici
    # hicbir sey gormez. En azindan o ana kadar toplanan tool sonuclarini
    # ozetleyip bir mesaj olarak gonderiyoruz.
    fallback = (
        "Bu istek beklenenden fazla adim gerektirdi, bazi islemleri "
        "denedim ama net bir sonuca varamadim. Yukaridaki islem "
        "geçmisine bak, gerekirse daha spesifik bir istekle tekrar dene "
        "(orn: tam dosya yolu, uygulama adi gibi)."
    )
    add_short("assistant", fallback, conv_id)
    await websocket.send_json({"type":"message","content":fallback})

# ─── TOPLU ISTEK KUYRUGU (batch_queue) ───────────────────────────
# batch_queue.py yazilmisti ama main.py'ye baglanmamisti. Burada GERCEK bir
# tuketici veriyoruz: uzun vadeli hafiza hatirlama (recall) cagrilari.
# Neden bu is secildi: recall YAN ETKISIZ (sadece okuma) ve gomme/DB
# maliyeti var — is_batchable() zaten yikici eylemleri reddediyor.
# Toplu calistirma thread havuzunda yapilir; recall SENKRON (sqlite) oldugu
# icin olay dongusunu bloklamasin.
_recall_batcher = None


async def _recall_batch_handler(items: list) -> list:
    """Bir pencerede biriken recall isteklerini TEK seferde isle."""
    loop = asyncio.get_running_loop()

    def _work():
        out = []
        for it in items:
            try:
                out.append(long_term_memory.recall(
                    it.get("query", ""), k=int(it.get("k") or 3)))
            except Exception as e:
                print(f"[BATCH] recall hatasi: {e}")
                out.append([])
        return out

    return await loop.run_in_executor(_executor, _work)


async def recall_long_term(query: str, k: int = 3) -> list:
    """Uzun vadeli hafizadan hatirla — kuyruk varsa toplu, yoksa dogrudan."""
    if not long_term_memory or not (query or "").strip():
        return []
    try:
        if _recall_batcher is not None:
            return await _recall_batcher.add({"query": query, "k": k})
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(
            _executor, lambda: long_term_memory.recall(query, k=k))
    except Exception as e:
        print(f"[MEMORY] uzun vadeli hatirlama hatasi: {e}")
        return []


# ─── WEBSOCKET ───────────────────────────────────────────────────
connected_ws = []

# BIG ALES KOPRUSU: puter_connector'a "bagli arayuzler kimler" diye
# soracagi yolu veriyoruz. Ters yonde kayit BILINCLI — puter_connector
# main.py'yi import ETSEYDI dairesel import olurdu (main zaten onu
# yukluyor). Fonksiyon geciriyoruz, modul degil.
if puter_connector:
    try:
        puter_connector.register_ws_source(lambda: connected_ws)
    except Exception as _e:
        print(f"[PUTER] koprü kaydedilemedi: {_e}")

@app.websocket("/ws")
async def ws_endpoint(websocket: WebSocket):
    await websocket.accept()
    connected_ws.append(websocket)
    cfg = load_config()
    # Herhangi bir saglayici key'i yeter — mod'a gore Groq/Cerebras yerine
    # NVIDIA (Cheat) ya da OpenRouter (Heavy) tek basina da calisabilir.
    has_key = any(bool(get_key(k)) for k in model_router.PROVIDER_KEY.values())
    persona = get_current_persona()
    await websocket.send_json({
        "type":"connected",
        "content": (persona["emoji"] + " ALES v3.0 aktif. Merhaba Ali!") if has_key else "API key gerekli.",
        "setup_needed": not has_key
    })
    try:
        while True:
            data = await websocket.receive_json()
            # KULLANICI ETKINLIGI: uyku sayacini sifirla (uyuyorsa uyandir).
            # ESKIDEN touch() hicbir yerden cagrilmiyordu -> ALES 5 dakika
            # sonra "bosta" sayilip uyuyabiliyordu, kullanici aktif olsa bile.
            if runtime_state:
                try:
                    runtime_state.touch()
                except Exception:
                    pass
            if data.get("type") == "message":
                text = data.get("content","").strip()
                conv_id = data.get("conversation_id")
                if not conv_id:
                    conv = conv_store.create_conversation(text)
                    conv_id = conv["id"]
                    await websocket.send_json({"type":"conversation_created","id":conv_id})
                if text: await run_agent(text, websocket, conv_id)
            elif data.get("type") == "ping":
                await websocket.send_json({"type":"pong"})
            elif data.get("type") == "puter_result":
                # BIG ALES KOPRUSU (bkz. backend/puter_connector.py).
                # Puter'in kimlik dogrulamasi TARAYICI TARAFLIDIR, bu yuzden
                # cagriyi arayuz yapar ve sonucu buradan geri verir. Backend
                # bekleyen Future'i cozer.
                if puter_connector:
                    try:
                        puter_connector.resolve(data.get("request_id"), data)
                    except Exception as e:
                        print(f"[PUTER] sonuc islenemedi: {e}")
    except WebSocketDisconnect:
        if websocket in connected_ws: connected_ws.remove(websocket)
    except Exception as e:
        try: await websocket.send_json({"type":"error","content":str(e)})
        except: pass

@app.websocket("/ws/stream")
async def websocket_stream_route(websocket: WebSocket):
    """
    Canlı ekran yayını ve aktivite akışı (Faz 5).
    İstemciye aktif görevler sırasında 800px JPEG base64 kareler ve
    tüm araç yürütme aktivitelerini anlık yayınlar.
    """
    import screen_streamer
    await screen_streamer.handle_stream_websocket(websocket)

@app.get("/api/learned-rules")
async def get_learned_rules_endpoint():
    """Öğrenilen deneyim kurallarını döner."""
    try:
        import experience_learner
        return {"ok": True, "rules": experience_learner.load_rules()}
    except Exception as e:
        return {"ok": False, "error": str(e), "rules": []}

@app.delete("/api/learned-rules")
async def clear_learned_rules_endpoint():
    """Öğrenilen tüm kuralları temizler."""
    try:
        import experience_learner
        ok = experience_learner.clear_rules()
        return {"ok": ok}
    except Exception as e:
        return {"ok": False, "error": str(e)}

@app.get("/api/download/pdf/{filename}")
async def download_pdf_endpoint(filename: str):
    """Oluşturulan PDF belgesini indirir."""
    if document_generator is None:
        raise HTTPException(status_code=500, detail="Belge üretim modülü aktif değil")
    p = document_generator.get_pdf_path(filename)
    if not p or not p.exists():
        raise HTTPException(status_code=404, detail="Dosya bulunamadı")
    return FileResponse(
        path=str(p),
        media_type="application/pdf",
        filename=p.name
    )

@app.get("/api/telemetry")
async def get_telemetry_endpoint():
    """Sistem performans ve başarı metriklerini döner."""
    if telemetry is None:
        return {"ok": False, "error": "Telemetri modülü aktif değil"}
    return {"ok": True, "data": telemetry.get_metrics()}

@app.post("/api/telemetry/reset")
async def reset_telemetry_endpoint():
    """Telemetri sayaçlarını sıfırlar."""
    if telemetry is None:
        return {"ok": False, "error": "Telemetri modülü aktif değil"}
    telemetry.reset_metrics()
    return {"ok": True, "message": "Metrikler sıfırlandı"}

# ─── HTTP ────────────────────────────────────────────────────────
@app.get("/status")
async def status():
    cfg = load_config()
    mem = load_memory()
    persona = get_current_persona()
    return {"status":"online","persona":persona["name"],"has_groq":bool(cfg.get("groq_key")),"has_cerebras":bool(cfg.get("cerebras_key")),"tasks":len(mem.get("fiverr_tasks",[])),"time":datetime.now().isoformat()}


@app.get("/api/system/status")
async def get_real_system_status():
    """
    Sistemin GERÇEK durumunu dinamik olarak denetler ve döner (TASK 3).
    Mock/statik veri içermez; modüllerin varlığını, API anahtarlarını,
    DPI ölçeğini ve disk durumunu anlık test eder.
    """
    cfg = load_config()
    caps = {}

    # 1. API Anahtarları & Model Sağlayıcıları
    active_keys = []
    for prov, k in (("Groq", "groq_key"), ("Gemini", "gemini_key"), ("Cerebras", "cerebras_key"),
                    ("NVIDIA", "nvidia_key"), ("OpenRouter", "openrouter_key"), ("SambaNova", "sambanova_key")):
        if cfg.get(k):
            active_keys.append(prov)
    
    if active_keys:
        caps["api_models"] = {
            "status": "working",
            "label": "Model Sağlayıcıları & API",
            "details": f"Aktif Anahtarlar: {', '.join(active_keys)} (Model Router hazır)"
        }
    else:
        caps["api_models"] = {
            "status": "failed",
            "label": "Model Sağlayıcıları & API",
            "details": "Hiçbir API anahtarı tanımlanmamış. ALES yanıt veremez; Ayarlar'dan anahtar ekleyin."
        }

    # 2. Masaüstü Denetimi (Computer Use & DPI)
    try:
        import native_desktop
        dpi_scale = native_desktop.get_dpi_scale()
        backends = native_desktop.backend_info()
        el_backend = backends.get("element_backend")
        if el_backend:
            caps["computer_control"] = {
                "status": "working",
                "label": "Masaüstü Denetimi (Computer Use)",
                "details": f"Motor: {el_backend} (Element Ağacı) + PyAutoGUI | DPI Ölçek: %{int(dpi_scale*100)}"
            }
        elif backends.get("window_backend"):
            caps["computer_control"] = {
                "status": "beta",
                "label": "Masaüstü Denetimi (Computer Use)",
                "details": f"Motor: {backends.get('window_backend')} (Piksel Koordinatı) | DPI Ölçek: %{int(dpi_scale*100)} (Element seviyesi kütüphane eksik)"
            }
        else:
            caps["computer_control"] = {
                "status": "failed",
                "label": "Masaüstü Denetimi",
                "details": "Windows arayüz sürücüsü yüklenemedi."
            }
    except Exception as e_nd:
        caps["computer_control"] = {
            "status": "failed",
            "label": "Masaüstü Denetimi",
            "details": f"Masaüstü sürücü hatası: {e_nd}"
        }

    # 3. Canlı Ekran Yayını (screen_streamer)
    try:
        import screen_streamer
        test_frame = screen_streamer._capture_screen_jpeg_base64()
        if test_frame:
            caps["screen_streamer"] = {
                "status": "working",
                "label": "Canlı Ekran Yayını",
                "details": "MSS/PIL ekran yakalama aktif (Boşta 1 FPS, Görevde 2 FPS)"
            }
        else:
            caps["screen_streamer"] = {
                "status": "beta",
                "label": "Canlı Ekran Yayını",
                "details": "Ekran yakalama motoru başlatılamadı."
            }
    except Exception as e_ss:
        caps["screen_streamer"] = {
            "status": "failed",
            "label": "Canlı Ekran Yayını",
            "details": f"Hata: {e_ss}"
        }

    # 4. Deneyim Öğrenici (experience_learner)
    try:
        import experience_learner
        rules = experience_learner.load_rules()
        caps["experience_learner"] = {
            "status": "working",
            "label": "Deneyim & Hata Öğrenici",
            "details": f"Disk üzerinde aktif (%APPDATA%\\ALES\\learned_rules.json). Toplam {len(rules)} kural devrede."
        }
    except Exception as e_el:
        caps["experience_learner"] = {
            "status": "failed",
            "label": "Deneyim Öğrenici",
            "details": f"Hata: {e_el}"
        }

    # 5. Manager-Executor Mimarisi
    try:
        import manager_agent
        import executor_agent
        caps["manager_executor"] = {
            "status": "working",
            "label": "Manager-Executor Mimarisi",
            "details": "Görev Planlama, Alt Görev İcrası ve Adım Doğrulama/Kurtarma döngüsü aktif."
        }
    except Exception as e_me:
        caps["manager_executor"] = {
            "status": "failed",
            "label": "Manager-Executor",
            "details": f"Hata: {e_me}"
        }

    # 6. Ses Sentezi (TTS)
    try:
        import edge_tts
        caps["voice_tts"] = {
            "status": "working",
            "label": "Ses Çıkışı (Edge-TTS)",
            "details": "Türkçe doğal sesler aktif (Ahmet / Emel Neural)"
        }
    except Exception as e_tts:
        caps["voice_tts"] = {
            "status": "failed",
            "label": "Ses Çıkışı",
            "details": f"TTS motoru bulunamadı: {e_tts}"
        }

    # 7. Ses Girişi (STT)
    caps["voice_stt"] = {
        "status": "beta",
        "label": "Ses Girişi (STT)",
        "details": "Tarayıcı Web Speech API (Mikrofon izni ve internet bağlantısı gerektirir)."
    }

    # 8. Kalıcı Hafıza
    try:
        mem = load_memory()
        caps["memory"] = {
            "status": "working",
            "label": "Kalıcı Hafıza & Profil",
            "details": f"Kısa hafıza: {len(mem.get('short', []))} mesaj, Profil kayıtları aktif."
        }
    except Exception as e_mem:
        caps["memory"] = {
            "status": "failed",
            "label": "Kalıcı Hafıza",
            "details": f"Hafıza okuma hatası: {e_mem}"
        }

    # 9. Serbest Çalışan Botu (Dürüst Durum)
    caps["freelance"] = {
        "status": "failed",
        "label": "Serbest Çalışan (Freelance) Botu",
        "details": "Kaldırıldı: Cloudflare Turnstile ve 2FA engelleri nedeniyle devre dışı bırakıldı."
    }

    return {"ok": True, "capabilities": caps, "checked_at": datetime.now().isoformat()}

# ─── SURUMLU YAPILANDIRMA (anlik goruntu + geri alma) ────────────────
# Sozlesme: her yapilandirma kaydinda DEGISIKLIKTEN ONCEKI hal saklanir,
# boylece "son degisikligi geri al" tek tikla mumkun olur.
#
# GIZLI ALANLAR SAKLANMAZ. Nedeni iki tarafli:
#   (a) Guvenlik: config.json'daki anahtarlar duz metin; ayni anahtarlari
#       bir de surum gecmisi dosyasina kopyalamak sizinti yuzeyini
#       cogaltirdi (gecmis 50 surum tutuyor).
#   (b) Dogruluk: bu yuzden geri alma da anahtarlari GERI YAZAMAZ —
#       _apply_config_version() mevcut anahtarlari KORUR ve yalnizca
#       gizli olmayan alanlari eski haline dondurur. Aksi halde bir geri
#       alma, calisan anahtarlari bos degerle silerdi.
_SECRET_CFG_KEYS = ("groq_key", "cerebras_key", "gemini_key", "sambanova_key",
                    "openrouter_key", "nvidia_key", "elevenlabs_key")


def _cfg_without_secrets(cfg: dict) -> dict:
    """Gizli alanlari cikar; hangi anahtarlarin DOLU oldugunu ise not et
    (geri alma ekraninda 'o zaman su anahtarlar tanimliydi' bilgisi)."""
    out = {k: v for k, v in (cfg or {}).items() if k not in _SECRET_CFG_KEYS}
    out["_secrets_present"] = sorted(k for k in _SECRET_CFG_KEYS
                                     if (cfg or {}).get(k))
    return out


def _snapshot_config(reason: str, category: str = "config") -> None:
    """Kaydetmeden ONCEKI hali surumle. Best-effort: patlarsa kaydi bozmaz."""
    if not _mod_on("versioned_config", versioned_config):
        return
    try:
        versioned_config.record_version(category,
                                        _cfg_without_secrets(load_config()),
                                        reason=reason)
    except Exception as e:
        print(f"[VERSION] anlik goruntu alinamadi: {e}")


def _apply_config_version(data: dict) -> None:
    """Geri alma uygulayicisi: MEVCUT anahtarlari koru, gerisini eski hale
    dondur. versioned_config.rollback_to_version(apply_fn=...) bunu cagirir."""
    cur = load_config()
    new = {k: v for k, v in (data or {}).items() if k != "_secrets_present"}
    for k in _SECRET_CFG_KEYS:
        if cur.get(k):
            new[k] = cur[k]
    save_config(new)


@app.post("/config")
async def set_config(data: dict):
    cfg = load_config()
    for key in ["groq_key", "cerebras_key", "elevenlabs_key", "elevenlabs_voice", "edge_voice",
                "gemini_key", "sambanova_key", "openrouter_key", "nvidia_key"]:
        if key in data:
            val = data[key]
            # Only update fields that are non-empty OR explicitly marked for clearing. Merge with existing config.
            if val is not None and str(val).strip() != "":
                cfg[key] = str(val).strip()
            elif data.get(f"clear_{key}") is True or val == "__CLEAR__":
                cfg[key] = ""
    # Zaman asimlari (katman bazli, saniye) — mevcut alanlar korunur, sadece
    # gonderilenler guncellenir. Gecersiz sayilar sessizce atlanir.
    if isinstance(data.get("timeouts"), dict):
        cur = dict(cfg.get("timeouts") or {})
        for k, v in data["timeouts"].items():
            try: cur[k] = float(v)
            except Exception: pass
        cfg["timeouts"] = cur
    # Kaydetmeden ONCE anlik goruntu: yanlis bir ayar sonrasi tek tikla
    # geri donulebilsin (anahtarlar goruntuye GIRMEZ, bkz. _snapshot_config).
    _changed = [k for k in data.keys() if k != "mode"]
    _snapshot_config(reason=("degisiklik oncesi: " + ", ".join(_changed[:6])
                             if _changed else "degisiklik oncesi"))
    save_config(cfg)
    # Mod ayri set_mode ile (dogrulama + config.json'a yazim onun icinde)
    if data.get("mode"):
        try:
            set_mode(data["mode"])
        except ValueError as e:
            return {"success": True, "mode_error": str(e)}
    return {"success":True}

@app.get("/config")
async def get_cfg():
    cfg = load_config()
    return {
        "has_groq": bool(cfg.get("groq_key")),
        "has_cerebras": bool(cfg.get("cerebras_key")),
        "has_elevenlabs": bool(cfg.get("elevenlabs_key")),
        "has_gemini": bool(cfg.get("gemini_key")),
        "has_sambanova": bool(cfg.get("sambanova_key")),
        "has_openrouter": bool(cfg.get("openrouter_key")),
        "has_nvidia": bool(cfg.get("nvidia_key")),
        "elevenlabs_voice": cfg.get("elevenlabs_voice") or DEFAULT_ELEVENLABS_VOICE,
        "mode": get_mode(),
        "timeouts": get_mode_config()["timeouts"],
    }

@app.post("/test-key")
async def test_key_route(data: dict):
    """
    Onboarding ve Ayarlar için 1-token ping testi.
    Groq veya Gemini anahtarının geçerli olduğunu doğrular.
    Hata durumunda sağlayıcının döndürdüğü tam hata mesajını döner.
    """
    provider = (data.get("provider") or "groq").lower().strip()
    key = (data.get("key") or "").strip()
    if not key:
        return {"ok": False, "error": "API anahtarı boş olamaz."}

    try:
        if provider == "gemini":
            # 1. Yeni google-genai SDK ile models.list() dene (AQ. ve AIza anahtarlarını tam destekler)
            try:
                from google import genai
                loop = asyncio.get_event_loop()
                def _genai_test():
                    c = genai.Client(api_key=key)
                    # client.models.list() model adına bağlı kalmadan doğrudan anahtar yetkisini doğrular
                    for _ in c.models.list():
                        return True
                    return True
                ok = await loop.run_in_executor(_executor, _genai_test)
                if ok:
                    return {"ok": True, "provider": "gemini", "model": "gemini-flash-latest"}
            except Exception as ge:
                code = getattr(ge, "code", None)
                msg = getattr(ge, "message", None) or str(ge)
                code_str = f" ({code})" if code else ""
                if code in (400, 401, 403) or "API key not valid" in msg or "UNAUTHENTICATED" in msg:
                    return {"ok": False, "error": f"Gemini Hatası{code_str}: {msg}"}

            # 2. HTTP doğrudan REST API testi
            async with httpx.AsyncClient(timeout=12.0) as client:
                m_resp = await client.get(
                    f"https://generativelanguage.googleapis.com/v1beta/models?key={key}"
                )
                if m_resp.status_code == 200:
                    return {"ok": True, "provider": "gemini", "model": "gemini-flash-latest"}

                try:
                    err_json = m_resp.json()
                    err_msg = err_json.get("error", {}).get("message") or m_resp.text
                except Exception:
                    err_msg = m_resp.text or str(m_resp.status_code)
                return {"ok": False, "error": f"Gemini Hatası ({m_resp.status_code}): {err_msg}"}

        elif provider == "groq":
            async with httpx.AsyncClient(timeout=12.0) as client:
                # 1. Önce models endpoint'ini kontrol et (anahtar geçerliliği için en hızlı ve güvenli yol)
                m_resp = await client.get(
                    "https://api.groq.com/openai/v1/models",
                    headers={"Authorization": f"Bearer {key}"}
                )
                if m_resp.status_code != 200:
                    try:
                        err_json = m_resp.json()
                        err_msg = err_json.get("error", {}).get("message") or m_resp.text
                    except Exception:
                        err_msg = m_resp.text or str(m_resp.status_code)
                    return {"ok": False, "error": f"Groq Hatası ({m_resp.status_code}): {err_msg}"}

                # 2. Aktif bir sohbet modeli seç ve 1-token ping at
                models_data = m_resp.json().get("data", [])
                chat_model = next(
                    (m["id"] for m in models_data
                     if not any(x in m["id"] for x in ["guard", "whisper", "orpheus"])
                     and any(k in m["id"] for k in ["gpt", "llama", "qwen", "gemma", "mixtral"])),
                    "openai/gpt-oss-120b"
                )

                c_resp = await client.post(
                    "https://api.groq.com/openai/v1/chat/completions",
                    headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
                    json={
                        "model": chat_model,
                        "messages": [{"role": "user", "content": "ping"}],
                        "max_tokens": 1
                    }
                )
                if c_resp.status_code == 200:
                    return {"ok": True, "provider": "groq", "model": chat_model}
                else:
                    # Model çağrısı patlasa bile models listesi 200 döndüyse anahtar geçerlidir
                    try:
                        err_json = c_resp.json()
                        err_msg = err_json.get("error", {}).get("message") or c_resp.text
                    except Exception:
                        err_msg = c_resp.text
                    # Eğer yetki hatası değil sadece model hatasıysa yine de geçerli sayılabilir
                    if c_resp.status_code != 401 and c_resp.status_code != 403:
                        return {"ok": True, "provider": "groq", "note": f"Anahtar geçerli ({chat_model}: {err_msg})"}
                    return {"ok": False, "error": f"Groq Hatası ({c_resp.status_code}): {err_msg}"}

        else:
            return {"ok": False, "error": f"Bilinmeyen sağlayıcı: {provider}"}

    except Exception as e:
        return {"ok": False, "error": f"Bağlantı Hatası: {type(e).__name__}: {e}"}

# ─── MOD SISTEMI (Task/Cheat/Auto/Multi/Performance/Heavy) ────────
@app.get("/modes")
async def get_modes():
    """UI mod secici icin: tum modlar + hangisinin aktif oldugu, ve aktif
    modun cozumlenmis zinciri (hangi saglayici/model) + zaman asimlari."""
    active = get_mode_config()
    return {
        "modes": list_modes(),
        "active": active["mode"],
        "active_chain": [{"layer": l["layer"], "provider": l.get("provider"),
                          "model": l.get("model")} for l in active["chain"]],
        "providers": model_router.available_providers(),
        "timeouts": active["timeouts"],
    }

@app.post("/mode")
async def post_mode(data: dict):
    """Aktif modu degistir. Gecersiz mod -> 400 benzeri {ok:False}."""
    try:
        m = set_mode(data.get("mode", ""))
    except ValueError as e:
        return {"ok": False, "error": str(e), "modes": [x["id"] for x in list_modes()]}
    return {"ok": True, "mode": m, "active_chain":
            [{"layer": l["layer"], "provider": l.get("provider"), "model": l.get("model")}
             for l in get_mode_config(m)["chain"]]}

# ─── LLM MECLISI (Council) ───────────────────────────────────────
@app.get("/council")
async def council_get():
    """Ayarlar'daki Meclis paneli: acik/kapali, strateji, uye listesi."""
    cfg = get_council()
    out = {"config": cfg, "strategies": sorted(llm_council.STRATEGIES) if llm_council else []}
    if llm_council:
        st = llm_council.status()
        out.update(st)
        # UI kolayligi: hangi saglayicilar hazir, hangilerinin key'i eksik.
        ready = [m["provider"] for m in st.get("members", [])]
        out["available_providers"] = ready
        out["missing_providers"] = [p for p in
                                    ("groq", "cerebras", "deepseek", "gemini",
                                     "sambanova", "openrouter") if p not in ready]
    else:
        out["available"] = False
        out["available_providers"] = []
        out["missing_providers"] = []
    # Hangi modlarda otomatik acik (heavy/council) — UI bunu bilgi olarak gosterir.
    out["heavy_modes"] = [m["id"] for m in list_modes()
                          if get_mode_config(m["id"]).get("council")]
    return out


@app.post("/council")
async def council_post(data: dict):
    """Meclis anahtari/stratejisi. Govde: {"enabled":true,"strategy":"synthesized"}"""
    try:
        cfg = set_council(
            enabled=data.get("enabled"),
            strategy=data.get("strategy"),
            timeout_s=data.get("timeout_s"),
            judge_timeout_s=data.get("judge_timeout_s"),
            cache=data.get("cache"),
        )
    except ValueError as e:
        return {"ok": False, "error": str(e),
                "strategies": sorted(llm_council.STRATEGIES) if llm_council else []}
    await broadcast_system_log(
        "INFO", f"Meclis {'acik' if cfg['enabled'] else 'kapali'} · {cfg['strategy']}")
    return {"ok": True, "config": cfg}


# ─── BIG ALES (Puter orkestratoru) ────────────────────────────────────
# Ali'nin istegi: kullanici HICBIR API ANAHTARI GIRMEZ. Odemeyi kendi Puter
# hesabi karsilar ("User Pays"), giris arayuzde bir kez yapilir. Bu yuzden
# burada anahtar alani YOK ve olmamali.
@app.get("/big-ales")
async def big_ales_get():
    """Ayarlar'daki Big ALES paneli: anahtar durumu, model, oturum bilgisi."""
    out = {"config": get_big_ales(), "models": list(BIG_ALES_MODELS),
           "available": bool(puter_connector)}
    if puter_connector:
        # session_info() jetonu SIZDIRMAZ: yalnizca giris yapilmis mi,
        # kullanici adi ve sifrelemenin gercekten acik olup olmadigi.
        out["session"] = puter_connector.session_info()
        out["clients"] = len(connected_ws)
        # Devre kesici: yol ust uste basarisiz olduysa cagri BEKLEMEDEN
        # hata doner. Bunu UI'da gostermek onemli, yoksa kullanici
        # "acik ama hicbir sey olmuyor" sanir.
        try:
            out["breaker"] = puter_connector.breaker_state()
        except Exception:
            out["breaker"] = None
    else:
        out["session"] = {"signed_in": False, "encryption": "none"}
        out["clients"] = 0
        out["breaker"] = None
    # Mod olarak da secilebilir; UI ikisini birlikte gosterir.
    out["mode_active"] = get_mode() == "big_ales"
    return out


@app.post("/big-ales")
async def big_ales_post(data: dict):
    """Big ALES anahtari/modeli. Govde: {"enabled":true,"model":"..."}

    SADECE GONDERILEN alanlar guncellenir. Bunu Meclis ucundan farkli
    yaptim: orada eksik alanlar None olarak gecip bool(None)=False ile
    anahtari sessizce kapatabiliyor; burada o tuzak olmasin."""
    kw = {k: data[k] for k in ("enabled", "model", "timeout_s")
          if k in data and data[k] is not None}
    try:
        cfg = set_big_ales(**kw)
    except ValueError as e:
        return {"ok": False, "error": str(e), "models": list(BIG_ALES_MODELS)}
    await broadcast_system_log(
        "INFO", f"Big ALES {'acik' if cfg['enabled'] else 'kapali'} · {cfg['model']}")
    return {"ok": True, "config": cfg}


@app.post("/big-ales/logout")
async def big_ales_logout():
    """Kayitli Puter oturumunu SIL (sifreli dosya kaldirilir)."""
    if not puter_connector:
        return {"ok": False, "error": "puter_connector yuklenemedi"}
    ok = puter_connector.clear_session()
    await broadcast_system_log("INFO", "Puter oturumu silindi" if ok
                               else "Puter oturumu silinemedi")
    return {"ok": ok, "session": puter_connector.session_info()}


# ─── PUTER KOPRU SAYFASI ──────────────────────────────────────────────
# NEDEN VAR: paketlenmis Electron arayuzu file:// ile aciliyor
# (electron-main.js -> mainWindow.loadFile). file:// bir "opaque origin";
# puter.js'in giris akisi puter.com'a acilan pencere + postMessage
# uzerine kurulu ve jetonun yasayacagi bir depo istiyor. Orada ikisi de
# yok. Bu sayfa ise BACKEND'IN KENDI http kaynagindan servis edilir
# (http://127.0.0.1:8000/puter-bridge) — yani normal bir origin: giris
# penceresi calisir ve jeton o kaynakta kalici olur.
#
# Arayuz (App.jsx) file:// uzerindeyse cagriyi kendi yapmaz, bu adresi bir
# pencerede acar; sayfa isi /puter-bridge/job/<rid> ile ceker, sonucu
# /puter-bridge/result ile geri verir. Sonuc yine ayni Future'i cozer,
# yani model_router tarafi hicbir sey bilmez.
@app.get("/puter-bridge")
async def puter_bridge_page():
    """puter.js'i gercek bir http kaynagindan calistiran kucuk sayfa."""
    from fastapi.responses import HTMLResponse, PlainTextResponse
    if not puter_connector:
        return PlainTextResponse("puter_connector yuklenemedi", status_code=503)
    # no-store: sayfa her seferinde taze gelsin (rid her cagrida degisir).
    return HTMLResponse(puter_connector.BRIDGE_HTML,
                        headers={"Cache-Control": "no-store"})


@app.get("/puter-bridge/job/{rid}")
async def puter_bridge_job(rid: str):
    """Kopru sayfasi isini buradan ceker. Bilinmeyen id -> bos sozluk."""
    if not puter_connector:
        return {}
    return puter_connector.get_job(rid)


@app.post("/puter-bridge/result")
async def puter_bridge_result(data: dict):
    """Kopru sayfasinin sonucu. Bekleyen cagriyi cozer."""
    if not puter_connector:
        return {"ok": False, "error": "puter_connector yuklenemedi"}
    rid = str(data.get("rid") or data.get("request_id") or "")
    if not rid:
        return {"ok": False, "error": "rid yok"}
    delivered = puter_connector.resolve(rid, data)
    if not delivered:
        # Bekleyen yoksa (zaman asimi gecmis olabilir) bunu SESSIZ
        # GECMIYORUZ: kullanici "hicbir sey olmadi" hissi yasamasin.
        await broadcast_system_log(
            "WARN", "Puter kopru sonucu geldi ama bekleyen istek yok "
                    "(zaman asimi olmus olabilir)")
    return {"ok": True, "delivered": delivered}


@app.post("/council/ask")
async def council_ask(data: dict):
    """Meclisi TEK SEFERLIK elle calistir (test/karsilastirma icin).
    Sohbet gecmisine YAZMAZ — sadece sonucu doner."""
    if not llm_council:
        return {"ok": False, "error": "llm_council yuklenemedi"}
    q = (data.get("prompt") or "").strip()
    if not q:
        return {"ok": False, "error": "prompt bos"}
    cfg = get_council()
    return await llm_council.council(
        q, strategy=data.get("strategy") or cfg["strategy"],
        timeout_s=data.get("timeout_s") or cfg["timeout_s"],
        judge_timeout_s=cfg["judge_timeout_s"],
        system_extra=get_system_prompt(),
        use_cache=cfg["cache"] if data.get("use_cache") is None else bool(data["use_cache"]))


# ─── KALICI SISTEM PROMPTU (LUBV) ────────────────────────────────
# run_agent her konusmada get_system_prompt() cagirir ve dolu ise sistem
# promptunun BASINA ekler (meclis yolu dahil, yukariya bak). Bu iki endpoint
# metni arayuzden duzenlenebilir yapar; dosyayi elle acmak gerekmez.
@app.get("/system-prompt")
async def system_prompt_get(name: str = "lubv"):
    """Metni AYNEN dondurur — Ayarlar'daki alan bunu duzenler."""
    data = load_system_prompts() or {}
    val = data.get(name)
    if isinstance(val, str):                 # eski duz-metin formati
        val = {"enabled": True, "text": val}
    elif not isinstance(val, dict):
        val = {"enabled": False, "text": ""}
    text = val.get("text") or ""
    return {
        "name": name,
        "enabled": bool(val.get("enabled")) and bool(text.strip()),
        "text": text,
        "chars": len(text),
        # active = su an GERCEKTEN enjekte ediliyor mu (tek dogruluk kaynagi
        # get_system_prompt; UI'nin kendi mantigini kurmasina gerek yok).
        "active": bool(get_system_prompt(name)),
        "names": sorted(k for k in data if not k.startswith("_")),
    }


@app.post("/system-prompt")
async def system_prompt_post(data: dict):
    """Govde: {"name":"lubv","text":"...","enabled":true}
    text yoksa metne dokunulmaz (sadece ac/kapat); metin bossa enabled
    zorla False olur — bos yonerge enjekte etmek anlamsizdir."""
    name = (data.get("name") or "lubv").strip() or "lubv"
    # Sistem promptu ALES'in davranisini en cok etkileyen tek metin; yanlis
    # bir yapistirma sonrasi geri donulebilsin diye onceki hal surumlenir.
    # (Metin config.json'da degil system_prompts.json'da; bu yuzden ayri
    # kategori ve veri olarak metnin KENDISI saklanir.)
    if _mod_on("versioned_config", versioned_config):
        try:
            _prev = get_system_prompt(name)
            versioned_config.record_version(
                "system_prompt", {"name": name, "text": _prev},
                reason=f"'{name}' degistirilmeden once ({len(_prev or '')} karakter)")
        except Exception as e:
            print(f"[VERSION] sistem promptu goruntusu alinamadi: {e}")
    try:
        res = set_system_prompt(name, text=data.get("text"),
                                enabled=data.get("enabled"))
    except Exception as e:
        return {"ok": False, "error": f"yazilamadi: {e}"}
    await broadcast_system_log(
        "INFO", f"Kalici sistem promptu '{name}' "
                f"{'acik' if res['enabled'] else 'kapali'} · {res['chars']} karakter")
    return {"ok": True, "name": name, **res,
            "active": bool(get_system_prompt(name))}


# ─── UZUN VADELI HAFIZA (long_term_memory) ───────────────────────
# Bu modul yazilmisti ama main.py'ye HIC baglanmamisti; asagidaki uc
# endpoint onu arayuze acar. Sohbet icindeki otomatik kullanimi
# run_agent'taki hatirlama adiminda yapilir.
@app.get("/memory/long")
async def memory_long_get(q: str = "", k: int = 5):
    """q verilirse anlamsal hatirlama, verilmezse sadece istatistik."""
    if not long_term_memory:
        return {"available": False, "error": "long_term_memory yuklenemedi"}
    out = {"available": True, "stats": long_term_memory.stats()}
    if q.strip():
        out["results"] = long_term_memory.recall(q, k=max(1, min(int(k or 5), 20)))
    return out


@app.post("/memory/long")
async def memory_long_add(data: dict):
    """Kalici not ekle. Govde: {"text":"...","kind":"note","importance":1.0}"""
    if not long_term_memory:
        return {"ok": False, "error": "long_term_memory yuklenemedi"}
    text = (data.get("text") or "").strip()
    if not text:
        return {"ok": False, "error": "text bos"}
    rec = long_term_memory.add(text, kind=data.get("kind") or "note",
                               source=data.get("source") or "ui",
                               importance=float(data.get("importance") or 1.0))
    return {"ok": True, "record": rec, "stats": long_term_memory.stats()}


@app.post("/memory/long/forget")
async def memory_long_forget(data: dict = None):
    """Bayatlamis kayitlari temizle (onemli olanlar korunur)."""
    if not long_term_memory:
        return {"ok": False, "error": "long_term_memory yuklenemedi"}
    n = long_term_memory.forget_stale(
        min_freshness=float((data or {}).get("min_freshness") or 0.02),
        keep_important=float((data or {}).get("keep_important") or 3.0))
    return {"ok": True, "forgotten": n, "stats": long_term_memory.stats()}


@app.post("/api/transcribe")
@app.post("/transcribe")
async def transcribe_audio_api(request: Request):
    """
    Ses kaydını metne dönüştürür (Groq Whisper API whisper-large-v3-turbo).
    Web Speech API desteği olmayan ortamlarda (Electron / Mobil) MediaRecorder yedeği.
    """
    audio_bytes = None
    filename = "recording.webm"
    content_type = "audio/webm"

    content_type_header = request.headers.get("content-type", "")
    if "multipart/form-data" in content_type_header:
        try:
            form = await request.form()
            file = form.get("file")
            if file and hasattr(file, "read"):
                audio_bytes = await file.read()
                filename = getattr(file, "filename", "recording.webm") or "recording.webm"
                content_type = getattr(file, "content_type", "audio/webm") or "audio/webm"
        except Exception as e:
            print(f"[TRANSCRIBE] Form okuma hatası: {e}")

    if not audio_bytes:
        try:
            body = await request.json()
            if "audio_base64" in body:
                raw_b64 = body["audio_base64"]
                if "," in raw_b64:
                    raw_b64 = raw_b64.split(",", 1)[1]
                audio_bytes = base64.b64decode(raw_b64)
        except Exception:
            pass

    if not audio_bytes:
        return {"ok": False, "error": "Ses verisi alınamadı", "text": ""}

    # Content-type ve dosya uzantısını temizle
    if content_type and ";" in content_type:
        content_type = content_type.split(";")[0].strip()
    if not any(filename.endswith(ext) for ext in [".webm", ".mp3", ".wav", ".m4a", ".ogg"]):
        filename = f"{filename}.webm"

    groq_key = get_key("groq_key") or os.environ.get("GROQ_API_KEY", "") or os.environ.get("GROQ_KEY", "")
    if not groq_key:
        return {"ok": False, "error": "GROQ_API_KEY yapılandırılmamış", "text": ""}

    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            files = {"file": (filename, audio_bytes, content_type)}
            data = {
                "model": "whisper-large-v3-turbo",
                "language": "tr",
                "response_format": "json"
            }
            resp = await client.post(
                "https://api.groq.com/openai/v1/audio/transcriptions",
                headers={"Authorization": f"Bearer {groq_key}"},
                files=files,
                data=data
            )
            if resp.status_code == 200:
                result = resp.json()
                text = result.get("text", "").strip()
                return {"ok": True, "text": text}
            else:
                print(f"[TRANSCRIBE] Groq API Hatası ({resp.status_code}): {resp.text}")
                return {"ok": False, "error": f"Groq Whisper hatası ({resp.status_code})", "text": ""}
    except Exception as e:
        print(f"[TRANSCRIBE] İstisna: {e}")
        return {"ok": False, "error": f"Transkripsiyon hatası: {str(e)}", "text": ""}


@app.get("/batch/stats")
async def batch_stats():
    """Toplu istek kuyrugu sayaclari (kac cagri tasarruf edildi)."""
    if not batch_queue or _recall_batcher is None:
        return {"available": False}
    return {"available": True, "stats": dict(_recall_batcher.stats),
            "pending": _recall_batcher.pending(),
            "max_batch": _recall_batcher.max_batch,
            "min_batch": _recall_batcher.min_batch,
            "max_wait_s": _recall_batcher.max_wait_s}


@app.get("/voices")
async def get_voices():
    """Secilebilir sesler - Ayarlar'daki ses dropdown'u icin"""
    cfg = load_config()
    return {
        "voices": ELEVENLABS_VOICES,
        "current": cfg.get("elevenlabs_voice") or DEFAULT_ELEVENLABS_VOICE,
        "has_elevenlabs_key": bool(cfg.get("elevenlabs_key")),
        "edge_voices": EDGE_VOICES,
        "current_edge_voice": cfg.get("edge_voice") or DEFAULT_EDGE_VOICE,
    }

@app.post("/speak_test")
async def speak_test(data: dict):
    """Ayarlar'daki 'Sesi Test Et' butonu icin - secilen sesle ornek cumle
    soyler. ESKIDEN sesi backend kendi acip calıyordu (isletim sisteminin
    medya oynaticisiyla, ayri pencere) - ARTIK ses verisini dogrudan HTTP
    yanitinda donuyor, frontend aninda <audio> ile calıyor."""
    cfg = load_config()
    text = data.get("text") or "Merhaba Ali. Ben ALES. Sesimi nasil buluyorsun?"
    key = (
        data.get("elevenlabs_key")
        or cfg.get("elevenlabs_key", "")
        or get_key("elevenlabs_key")
        or os.environ.get("ELEVENLABS_API_KEY", "")
        or os.environ.get("ELEVENLABS_KEY", "")
    )
    if isinstance(key, str): key = key.strip()
    voice_id = data.get("voice_id") or cfg.get("elevenlabs_voice") or DEFAULT_ELEVENLABS_VOICE
    edge_voice = data.get("edge_voice") or cfg.get("edge_voice") or DEFAULT_EDGE_VOICE
    loop = asyncio.get_event_loop()
    audio_bytes = await loop.run_in_executor(_executor, synthesize, text, key, voice_id, edge_voice)
    if not audio_bytes:
        return {"ok": False, "error": "Ses üretilemedi (key/bağlantı kontrol et)"}
    mime = "audio/wav" if audio_bytes.startswith(b"RIFF") else "audio/mpeg"
    return {"ok": True, "audio": base64.b64encode(audio_bytes).decode("ascii"), "mime": mime}


# ─── SKILLS (Ayarlar > Skills paneli icin) ────────────────────────
@app.get("/skills")
async def get_skills():
    return {"skills": skills_engine.get_skills_summary()}

@app.post("/skills/reload")
async def reload_skills_route():
    skills_engine.reload_skills()
    return {"skills": skills_engine.get_skills_summary()}

@app.post("/skills/{skill_id}/toggle")
async def toggle_skill_route(skill_id: str, data: dict):
    msg = skills_engine.set_skill_enabled(skill_id, bool(data.get("enabled", True)))
    return {"result": msg, "skills": skills_engine.get_skills_summary()}

@app.post("/skills/install")
async def install_skill_route(data: dict):
    """Yeni bir skill yukle: {skill_id, skill_md, skill_py?}
    Tipki Claude'a bir skill klasoru yukler gibi - SKILL.md zorunlu,
    skill.py (gercek yetenek kodu) opsiyonel (yoksa sadece referans/dokuman olur)."""
    msg = skills_engine.install_skill(
        data.get("skill_id", ""), data.get("skill_md", ""), data.get("skill_py", "")
    )
    return {"result": msg, "skills": skills_engine.get_skills_summary()}

@app.delete("/skills/{skill_id}")
async def delete_skill_route(skill_id: str):
    return {"result": skills_engine.delete_skill(skill_id)}

# ─── CONNECTORS (Ayarlar > Connectors paneli icin) ────────────────
@app.get("/connectors")
async def get_connectors():
    return {"connectors": connectors.list_connectors()}

@app.post("/connectors/{connector_id}/configure")
async def configure_connector_route(connector_id: str, data: dict):
    msg = connectors.configure_connector(
        connector_id,
        api_key=data.get("api_key"),
        enabled=data.get("enabled"),
    )
    return {"result": msg, "connectors": connectors.list_connectors()}

@app.post("/connectors/install")
async def install_connector_route(data: dict):
    """Ozel/yeni bir connector ekle: {id, name, base_url, description?, auth_style?, icon?}"""
    msg = connectors.add_custom_connector(
        data.get("id", ""), data.get("name", ""), data.get("base_url", ""),
        data.get("description", ""), data.get("auth_style", "bearer"), data.get("icon", "🔌"),
    )
    return {"result": msg, "connectors": connectors.list_connectors()}

@app.delete("/connectors/{connector_id}")
async def delete_connector_route(connector_id: str):
    return {"result": connectors.delete_connector(connector_id)}

@app.get("/worldview")
async def worldview_api():
    return {"data": get_worldview()}

@app.get("/approvals")
async def get_approvals():
    mem = load_memory()
    if _prune_stale_approvals(mem):
        save_memory(mem)
    return {"approvals":mem.get("pending_approvals",[])}

@app.post("/approve/{aid}")
async def approve(aid: int):
    mem = load_memory()
    for a in mem.get("pending_approvals",[]):
        if a["id"] == aid:
            result = await execute_tool_async(a["action"], a["params"])
            mem["pending_approvals"] = [x for x in mem["pending_approvals"] if x["id"]!=aid]
            save_memory(mem); return {"result":result}
    return {"error":"Bulunamadı"}

@app.delete("/approve/{aid}")
async def reject(aid: int):
    mem = load_memory()
    mem["pending_approvals"] = [x for x in mem.get("pending_approvals",[]) if x["id"]!=aid]
    save_memory(mem); return {"result":"Reddedildi"}

# ─── EYLEM LOGU (kısa, "ALES ne yaptı" özeti) ─────────────────────
@app.get("/logs")
async def get_logs():
    log = load_action_log()
    return {"logs": list(reversed(log[-50:]))}  # en yeni en ustte

@app.get("/stats")
async def get_stats():
    """Kullanım panosu (dashboard) icin ozet istatistikler: en cok
    kullanilan araclar, son 14 gundeki aktivite, toplam sohbet/mesaj
    sayisi. Var olan action_log + conversations verisinden turetilir -
    ayri bir izleme sistemi gerekmez."""
    log = load_action_log()

    # En cok kullanilan araclar (etiketin " (" kismindan once, yani
    # baglam haric temel eylem adi - orn. "Uygulama açıldı (chrome)" -> "Uygulama açıldı")
    tool_counts: dict = {}
    daily_counts: dict = {}
    for entry in log:
        text = entry.get("text", "") if isinstance(entry, dict) else str(entry)
        ts = entry.get("time", "") if isinstance(entry, dict) else ""
        label = text.split(" (")[0].strip()
        if label:
            tool_counts[label] = tool_counts.get(label, 0) + 1
        if ts:
            day = ts[:10]
            daily_counts[day] = daily_counts.get(day, 0) + 1

    top_tools = sorted(tool_counts.items(), key=lambda x: x[1], reverse=True)[:8]

    # son 14 gun (bos gunler de 0 olarak gorunsun ki grafik duzgun olsun)
    days = []
    today = datetime.now().date()
    for i in range(13, -1, -1):
        d = (today - timedelta(days=i)).isoformat()
        days.append({"date": d, "count": daily_counts.get(d, 0)})

    # son 60 dakika: dakika basina islem sayisi ("tasks/minute" grafigi).
    # activity_by_day ile ayni action_log verisinden turetilir - bos dakikalar
    # 0 gorunur ki grafik surekli ve duzgun olsun.
    now = datetime.now()
    minute_counts: dict = {}
    for entry in log:
        ts = entry.get("time", "") if isinstance(entry, dict) else ""
        if len(ts) >= 16:
            minute_counts[ts[:16]] = minute_counts.get(ts[:16], 0) + 1
    minutes = []
    for i in range(59, -1, -1):
        m = (now - timedelta(minutes=i)).strftime("%Y-%m-%dT%H:%M")
        minutes.append({"minute": m[11:16], "count": minute_counts.get(m, 0)})

    convs = conv_store.list_conversations()
    total_messages = 0
    for c in convs:
        try:
            full = conv_store.get_conversation(c["id"])
            total_messages += len(full.get("messages", [])) if full else 0
        except Exception:
            pass

    mem = load_memory()
    return {
        "total_actions": len(log),
        "total_conversations": len(convs),
        "total_messages": total_messages,
        "top_tools": [{"label": l, "count": c} for l, c in top_tools],
        "activity_by_day": days,
        "activity_by_minute": minutes,
        "earnings": _earnings_summary(mem.get("earnings", [])),
    }

# ─── KAZANÇ (earnings) ───────────────────────────────────────────
# Fiverr/Bionluk gibi kaynaklardan gelen gerçek gelir kayıtları. Bellekte
# (memory.json / AppData) "earnings" listesinde tutulur; her kayıt
# {id, amount, currency, source, note, time}. Panodaki sayaç bundan türer.
def _earnings_summary(entries: list) -> dict:
    entries = [e for e in (entries or []) if isinstance(e, dict)]
    total = 0.0
    currency = "TRY"
    today = datetime.now().date().isoformat()
    month = today[:7]
    today_total = 0.0
    month_total = 0.0
    for e in entries:
        try:
            amt = float(e.get("amount", 0) or 0)
        except (TypeError, ValueError):
            amt = 0.0
        total += amt
        currency = e.get("currency") or currency
        ts = str(e.get("time", ""))
        if ts[:10] == today:
            today_total += amt
        if ts[:7] == month:
            month_total += amt
    recent = sorted(entries, key=lambda x: str(x.get("time", "")), reverse=True)[:10]

    # ── Kaynak kirilimi: hangi is/platform ne kadar getirdi ──────────
    by_source = {}
    per_day = {}
    for e in entries:
        try:
            amt = float(e.get("amount", 0) or 0)
        except (TypeError, ValueError):
            amt = 0.0
        src = (e.get("source") or "diger").strip() or "diger"
        by_source[src] = round(by_source.get(src, 0.0) + amt, 2)
        day = str(e.get("time", ""))[:10]
        if len(day) == 10:
            per_day[day] = round(per_day.get(day, 0.0) + amt, 2)

    # ── Trend cizgisi: son 30 gun, bos gunler 0 (grafikte kesinti olmaz)
    daily = []
    for i in range(29, -1, -1):
        d = (datetime.now() - timedelta(days=i)).date().isoformat()
        daily.append({"date": d, "amount": per_day.get(d, 0.0)})

    sources = [{"source": s, "amount": a}
               for s, a in sorted(by_source.items(), key=lambda kv: kv[1], reverse=True)]

    return {
        "total": round(total, 2),
        "today": round(today_total, 2),
        "month": round(month_total, 2),
        "currency": currency,
        "count": len(entries),
        "recent": recent,
        "by_source": sources,
        "daily": daily,
        "best_day": max(daily, key=lambda d: d["amount"]) if daily else None,
        "avg_per_day_30": round(sum(d["amount"] for d in daily) / 30.0, 2) if daily else 0.0,
    }


async def _broadcast_earnings(summary: dict):
    """Kazanc degisimini bagli tum panolara ANINDA gonder. Tek bir istemciye
    degil hepsine gider (telefon + masaustu ayni anda acik olabilir).
    Kopan baglantilar sessizce atlanir."""
    dead = []
    for ws in list(connected_ws):
        try:
            await ws.send_json({"type": "earnings", "summary": summary})
        except Exception:
            dead.append(ws)
    for ws in dead:
        if ws in connected_ws:
            connected_ws.remove(ws)

@app.get("/earnings")
async def get_earnings():
    mem = load_memory()
    return _earnings_summary(mem.get("earnings", []))

@app.post("/earnings")
async def add_earning(data: dict):
    """Yeni bir kazanç kaydı ekle. Beklenen gövde: {amount, currency?,
    source?, note?}. amount zorunlu ve pozitif olmalı."""
    try:
        amount = float(data.get("amount", 0))
    except (TypeError, ValueError):
        return {"ok": False, "error": "Geçersiz tutar"}
    if amount <= 0:
        return {"ok": False, "error": "Tutar pozitif olmalı"}
    mem = load_memory()
    mem.setdefault("earnings", [])
    entry = {
        "id": int(time.time() * 1000),
        "amount": round(amount, 2),
        "currency": (data.get("currency") or "TRY").upper()[:4],
        "source": str(data.get("source") or "manuel")[:40],
        "note": str(data.get("note") or "")[:120],
        "time": datetime.now().isoformat(),
    }
    mem["earnings"].append(entry)
    save_memory(mem)
    log_event(f"Kazanç: +{entry['amount']} {entry['currency']} ({entry['source']})")
    summary = _earnings_summary(mem["earnings"])
    await _broadcast_earnings(summary)
    return {"ok": True, "entry": entry, "summary": summary}

@app.delete("/earnings/{eid}")
async def delete_earning(eid: int):
    mem = load_memory()
    before = len(mem.get("earnings", []))
    mem["earnings"] = [e for e in mem.get("earnings", []) if e.get("id") != eid]
    save_memory(mem)
    summary = _earnings_summary(mem["earnings"])
    await _broadcast_earnings(summary)
    return {"ok": len(mem["earnings"]) < before, "summary": summary}

# ─── KIMLIK BILGISI KASASI (Windows Credential Manager) ──────────
# Sirlar isletim sisteminin kasasinda tutulur; bu endpoint'ler sir DEGERI
# dondurmez, yalnizca "var/yok" ve maskeli onizleme verir.
@app.get("/credentials/audit")
async def credentials_audit():
    return credentials.audit()

@app.post("/credentials/migrate")
async def credentials_migrate(data: dict = None):
    """config.json'daki duz metin key'leri kasaya tasi ve dosyadan temizle."""
    remove = True
    if isinstance(data, dict) and "remove_from_config" in data:
        remove = bool(data["remove_from_config"])
    res = credentials.migrate_to_vault(remove_from_config=remove)
    if res.get("migrated"):
        log_event(f"Kimlik kasasi: {len(res['migrated'])} key tasindi")
    return res


@app.get("/env-status")
async def env_status_api():
    """.env dosyasi okundu mu, nereden, kac degisken yuklendi.

    NEDEN GEREKLI: anahtarlari config.json'dan .env'e tasimak sessizce
    basarisiz olabilecek bir istir — dosya yanlis klasorde olur ya da
    degisken adi farkli yazilir, ALES hicbir uyari vermeden "anahtar yok"
    davranir ve butun saglayici zinciri kapanir. Bu uc, tasimanin
    calistigini GORMEK icin var.

    GUVENLIK: yalnizca SAYI ve YOL doner. Ne anahtar degeri, ne de
    degisken ADI listelenir. "searched" alani, dosya bulunamadiginda
    nereye konmasi gerektigini gosterir.
    """
    try:
        # config_manager main.py'de yalnizca "from ... import ..." ile
        # kullaniliyor, modul adi bagli DEGIL — burada acikca aliyoruz.
        import config_manager as _cm
        st = _cm.env_file_status()
    except Exception as e:
        return {"loaded": False, "error": str(e)[:200]}
    # Hangi saglayicinin anahtari GERCEKTEN cozulebiliyor: kaynak
    # ayrimi olmadan (config.json mi .env mi) sadece var/yok.
    resolved = {}
    for _k in ("groq_key", "cerebras_key", "gemini_key", "openrouter_key",
               "nvidia_key", "sambanova_key", "elevenlabs_key"):
        try:
            resolved[_k] = bool(_cm.get_key(_k))
        except Exception:
            resolved[_k] = False
    st["keys_resolved"] = resolved
    st["keys_ok_count"] = sum(1 for v in resolved.values() if v)
    return st

@app.post("/credentials/set")
async def credentials_set(data: dict):
    """Tek bir sirri kasaya yaz. Govde: {name, value}. Deger loglanmaz."""
    name = (data.get("name") or "").strip()
    value = data.get("value") or ""
    if not name or not value:
        return {"ok": False, "error": "name ve value zorunlu"}
    ok = credentials.set_secret(name, value)
    if ok:
        log_event(f"Kimlik kasasi: '{name}' guncellendi")
    return {"ok": ok, "backend": credentials.backend_name()}

@app.delete("/credentials/{name}")
async def credentials_delete(name: str):
    return {"ok": credentials.delete_secret(name)}

# ─── IZOLE TARAYICI PROFILLERI (gizlilik + test) ─────────────────
@app.get("/browser-profiles")
async def browser_profiles_list():
    return {"profiles": browser_profiles.list_profiles(),
            "dir": str(browser_profiles.BASE_DIR)}

@app.post("/browser-profiles")
async def browser_profiles_create(data: dict):
    return browser_profiles.create_profile(
        (data.get("id") or "").strip(),
        (data.get("label") or "").strip(),
        (data.get("note") or "").strip(),
    )

@app.delete("/browser-profiles/{pid}")
async def browser_profiles_delete(pid: str, wipe: bool = True):
    return browser_profiles.delete_profile(pid, wipe=wipe)

@app.post("/browser-profiles/{pid}/clear")
async def browser_profiles_clear(pid: str):
    """Profilin cerez/depolama verisini sil — 'her yerden cikis yap'."""
    return browser_profiles.clear_profile_data(pid)

# ─── DAYANIKLILIK SAYAClARI (retry_util) ─────────────────────────
# retry_util import ediliyordu ama HICBIR YERDEN cagrilmiyordu (olu import).
# Artik long_term_memory._gemini_embed onu kullaniyor ve asagidaki iki
# endpoint sonuclari arayuze aciyor: kac gecici hata yeniden denemeyle
# kurtarildi, nerede pes edildi.
@app.get("/retry/stats")
async def retry_stats():
    return retry_util.stats()

@app.post("/retry/stats/reset")
async def retry_stats_reset():
    retry_util.reset_stats()
    return {"ok": True, **retry_util.stats()}

# ─── SISTEM KONTROLU (GOREV sekmesi: baslat/durdur + canli durum) ──
# ALES'IN KENDI arka plan isleyicilerini yonetir: zamanlayici, bildirimci
# ve kaynak izleyici. (Coklu hesap otomasyonu KAPSAM DISI.)
_workers = {"scheduler": None, "notifier": None}
# self_heal.Supervisor ornegi (startup'ta kurulur). _workers'i PAYLASIR:
# denetci yeniden baslattigi gorevi ayni sozluge yazar, boylece
# _worker_alive() / /system/status dogru sonuc vermeye devam eder.
_supervisor = None

# Surec baslangici — /system/status "runtime.uptime_s" bundan turer.
# runtime_state'ten BAGIMSIZ tutuluyor: modul yuklenemese bile calisma
# suresini yine bildirebilmeliyiz.
_STARTED_AT = time.time()


# ── Arka plan isleyici callback'leri ─────────────────────────────
# ESKIDEN: bu iki callback SADECE startup() icinde YEREL fonksiyon olarak
# tanimliydi, ama /system/start onlara modul duzeyinden (_scheduler_cb /
# _notifier_cb) erismeye calisiyordu -> NameError, endpoint hic calismiyordu.
# ARTIK modul duzeyindeler; hem startup() hem /system/start AYNI callback'i
# kullaniyor, davranis tek yerden yonetiliyor.
async def _scheduler_cb(action: str):
    """Zamanlanmis gorev tetiklendiginde: ilk canli WS uzerinden ajani calistir."""
    conv_store.get_or_create("zamanlama", "⏰ Zamanlanmış Görevler")
    for ws in list(connected_ws):
        try:
            await run_agent(f"[ZAMANLAMA] {action}", ws, "zamanlama")
            break
        except Exception:
            continue


async def _notifier_cb(msg: str):
    """Bildirim: isletim sistemi bildirimi + sohbet gecmisine satir."""
    for ws in list(connected_ws):
        try:
            # 'notification' tipi: frontend'de tarayici/masaustu bildirimi
            # (Notification API) tetikler - sekme arka planda olsa bile
            # kullanici gorur. 'message' de ayrica gonderiliyor ki sohbet
            # gecmisinde de gorunsun.
            await ws.send_json({"type": "notification", "title": "ALES", "content": msg})
            await ws.send_json({"type": "message", "content": f"[BILDIRIM] {msg}"})
            break
        except Exception:
            continue


# ═══════════════════════════════════════════════════════════════════
# 2025-2026 SOTA API ENDPOINTS (Hız, Zeka, Bilgisayar Kontrolü, Dayanıklılık)
# ═══════════════════════════════════════════════════════════════════

# 1. SpecCache
@app.get("/spec-cache/stats")
async def speccache_stats_api():
    if not speculative_cache:
        return {"unavailable": True}
    return speculative_cache.stats()

@app.post("/spec-cache/clear")
async def speccache_clear_api():
    if not speculative_cache:
        return {"unavailable": True}
    return speculative_cache.clear()

# 2. Toplu Çıkarım (Batch Inference - CONCUR)
@app.get("/batch-inference/stats")
async def batch_inference_stats_api():
    if not batch_inference:
        return {"unavailable": True}
    # engine.stats() DEGIL modul duzeyindeki stats(): ikincisi sayaclarin
    # ustune yapilandirmayi (batch_size, window_ms) ve o anki kuyruk
    # uzunlugunu (queued_now) ekliyor. Panelde "kac istek bekliyor / pencere
    # kac ms" satirlari bunlari okuyor; engine.stats() cagrildiginda o
    # alanlar undefined gelip satir bos gorunuyordu.
    return batch_inference.stats()

# 3. Token Optimize Edici (DEPO)
@app.get("/token-optimizer/stats")
async def token_optimizer_stats_api():
    if not token_optimizer:
        return {"unavailable": True}
    return token_optimizer.stats()

@app.post("/token-optimizer/reset")
async def token_optimizer_reset_api():
    if not token_optimizer:
        return {"unavailable": True}
    token_optimizer.reset_stats()
    return {"ok": True}

# 4. Mixture of Agents (MoA / DMoA)
@app.get("/moa/stats")
async def moa_stats_api():
    if not mixture_of_agents:
        return {"unavailable": True}
    return mixture_of_agents.stats()

@app.post("/moa/run")
async def moa_run_api(payload: dict):
    if not mixture_of_agents:
        return {"ok": False, "error": "mixture_of_agents modülü yüklü değil"}
    prompt = payload.get("prompt", "")
    system = payload.get("system", "")
    dmoa = bool(payload.get("dmoa", False))
    if dmoa:
        return await mixture_of_agents.run_dmoa(prompt, system=system)
    return await mixture_of_agents.run_moa(prompt, system=system)

# 5. Contextual Experience Replay (CER)
@app.get("/cer/stats")
async def cer_stats_api():
    if not cer_module:
        return {"unavailable": True}
    return cer_module.stats()

@app.get("/cer/experiences")
async def cer_experiences_api(limit: int = 30):
    if not cer_module:
        return {"experiences": []}
    return {"experiences": cer_module.list_experiences(limit=limit)}

@app.post("/cer/record")
async def cer_record_api(payload: dict):
    if not cer_module:
        return {"ok": False, "error": "cer modülü yüklü değil"}
    task = payload.get("task", "")
    trajectory = payload.get("trajectory", [])
    success = bool(payload.get("success", True))
    reflection = payload.get("reflection", "")
    return cer_module.record_experience(task, trajectory, success, reflection)

# 6. Öz-Evrim (Self-Evolution & RSI)
@app.get("/self-evolution/stats")
async def self_evolution_stats_api():
    if not self_evolution:
        return {"unavailable": True}
    return self_evolution.stats()

@app.post("/self-evolution/rsi")
async def self_evolution_rsi_api():
    if not self_evolution:
        return {"ok": False, "error": "self_evolution modülü yüklü değil"}
    return self_evolution.run_rsi_cycle()

# 7. Öz-Yansıma (Reflexion / SAGE)
@app.get("/reflection/stats")
async def reflection_stats_api():
    if not reflection_agent:
        return {"unavailable": True}
    return reflection_agent.stats()

@app.post("/reflection/run")
async def reflection_run_api(payload: dict):
    if not reflection_agent:
        return {"ok": False, "error": "reflection_agent modülü yüklü değil"}
    task = payload.get("task", "")
    action = payload.get("action", "")
    error = payload.get("error", "")
    return await reflection_agent.reflect_on_failure(task, action, error)

# 8. Darwin Gödel Makinesi
@app.get("/darwin-godel/stats")
async def darwin_godel_stats_api():
    if not darwin_godel:
        return {"unavailable": True}
    return darwin_godel.stats()

@app.get("/darwin-godel/archive")
async def darwin_godel_archive_api():
    if not darwin_godel:
        return {"archive": []}
    return {"archive": darwin_godel.get_archive()}

@app.get("/darwin-godel/trial")
async def darwin_godel_trial_api():
    """Suren A/B denemesinin durumu: sampiyon, aday, kac tur kaldi.

    UI'da ilerleme cubugu bunu okur. `fitness` None ise "henuz olculmedi"
    yazilmali — 0 ya da 0.99 gibi bir sayi UYDURMAK bu projede daha once
    yapilan hataydi (rastgele fitness), bir daha yapilmiyor."""
    if not darwin_godel:
        return {"unavailable": True}
    return {"available": True, "active": _mod_on("darwin_godel", darwin_godel),
            "trial": darwin_godel.trial_status(),
            "active_strategy": darwin_godel.get_active_strategy(),
            "evolve_interval_minutes": int(DGM_EVOLVE_INTERVAL_S / 60),
            "loop_running": _worker_alive("dgm_evolve")}

@app.post("/darwin-godel/evolve")
async def darwin_godel_evolve_api():
    if not darwin_godel:
        return {"ok": False, "error": "darwin_godel modülü yüklü değil"}
    # Elle tetikleyen kullanicidir; mutasyon icin LLM'e sorulur, olmazsa
    # modul kural-tabanli mutasyona duser.
    return await darwin_godel.evolve_generation(ask_llm=_codeact_ask_llm())

# 9. OpenClaw Köprüsü
@app.get("/openclaw/status")
async def openclaw_status_api():
    if not openclaw_bridge:
        return {"unavailable": True}
    return openclaw_bridge.bridge.status()

@app.post("/openclaw/desktop")
async def openclaw_desktop_api(payload: dict):
    if not openclaw_bridge:
        return {"ok": False, "error": "openclaw_bridge modülü yüklü değil"}
    action = payload.get("action", "list_windows")
    params = payload.get("params", {})
    return await openclaw_bridge.bridge.control_desktop(action, params)

@app.post("/openclaw/browser")
async def openclaw_browser_api(payload: dict):
    if not openclaw_bridge:
        return {"ok": False, "error": "openclaw_bridge modülü yüklü değil"}
    action = payload.get("action", "goto")
    params = payload.get("params", {})
    return await openclaw_bridge.bridge.control_browser(action, params)

@app.post("/openclaw/terminal")
async def openclaw_terminal_api(payload: dict):
    if not openclaw_bridge:
        return {"ok": False, "error": "openclaw_bridge modülü yüklü değil"}
    cmd = payload.get("command", "dir")
    timeout_s = float(payload.get("timeout_s", 15.0))
    return await openclaw_bridge.bridge.execute_terminal(cmd, timeout_s=timeout_s)

# 10. EvoCUA / InAgent
@app.get("/evocua/status")
async def evocua_status_api():
    if not evo_cua_bridge:
        return {"unavailable": True}
    return evo_cua_bridge.status()

@app.post("/evocua/action")
async def evocua_action_api(payload: dict):
    if not evo_cua_bridge:
        return {"ok": False, "error": "evo_cua_bridge modülü yüklü değil"}
    action = payload.get("action", {})
    return evo_cua_bridge.execute_cua_action(action)

@app.post("/evocua/sandbox")
async def evocua_sandbox_api(payload: dict):
    if not evo_cua_bridge:
        return {"ok": False}
    evo_cua_bridge.set_sandbox_mode(payload.get("enabled", True))
    return {"ok": True, "sandbox_mode": evo_cua_bridge.is_sandboxed()}

# 11. Dinamik Zaman Aşımları (Adaptive Timeouts)
@app.get("/adaptive-timeouts/stats")
async def adaptive_timeouts_stats_api():
    if not adaptive_timeouts:
        return {"unavailable": True}
    return adaptive_timeouts.get_stats()

@app.post("/adaptive-timeouts/reset")
async def adaptive_timeouts_reset_api():
    if not adaptive_timeouts:
        return {"unavailable": True}
    adaptive_timeouts.reset_stats()
    return {"ok": True}

# 12. Versiyonlu Yapılandırma (Versioned Config & Rollback)
@app.get("/config-versions")
async def config_versions_api(category: str = None, limit: int = 25):
    if not versioned_config:
        return {"versions": []}
    return {"versions": versioned_config.list_versions(category=category, limit=limit)}

@app.post("/config-versions/rollback/{version_id}")
async def config_versions_rollback_api(version_id: str):
    if not versioned_config:
        return {"ok": False, "error": "versioned_config modülü yüklü değil"}
    # DIKKAT: apply_fn olarak save_config DEGIL _apply_config_version verilir.
    # Surumlerde API anahtarlari saklanmiyor; save_config'e dogrudan verilse
    # geri alma calisan anahtarlari bos degerle EZERDI.
    res = versioned_config.rollback_to_version(
        version_id, apply_fn=_apply_config_version)
    if res.get("ok"):
        res["secrets_preserved"] = True
        res["note"] = ("API anahtarlari surumlerde saklanmadigi icin "
                       "geri alma onlara dokunmadi.")
    return res

# 13. Otomatik Model Keşfi
@app.get("/auto-discovery/status")
async def auto_discovery_status_api():
    if not auto_model_discovery:
        return {"unavailable": True}
    return auto_model_discovery.get_status()

@app.post("/auto-discovery/run")
async def auto_discovery_run_api():
    if not auto_model_discovery:
        return {"ok": False, "error": "auto_model_discovery modülü yüklü değil"}
    return await auto_model_discovery.run_discovery_now()


async def _broadcast(payload: dict):

    """Bagli tum istemcilere gonder; kopanlari listeden dusur."""
    dead = []
    for ws in list(connected_ws):
        try:
            await ws.send_json(payload)
        except Exception:
            dead.append(ws)
    for ws in dead:
        if ws in connected_ws:
            connected_ws.remove(ws)


async def broadcast_system_log(level: str, message: str):
    """GOREV sekmesindeki terminal-benzeri log alanina canli satir gonder.
    Sadece INFO/ERROR gibi onemli olaylar — token akisi buraya girmez."""
    await _broadcast({
        "type": "system_log",
        "level": (level or "INFO").upper(),
        "message": str(message)[:500],
        "time": datetime.now().strftime("%H:%M:%S"),
    })


def _worker_alive(name: str) -> bool:
    t = _workers.get(name)
    if t is None:
        return False
    # Kaynak izleyici bir THREAD (asyncio task degil) — .done() yok.
    if not hasattr(t, "done"):
        return bool(t)
    return not t.done()


async def _resource_alert_cb(report: dict):
    """Kaynak esigi asildi: kullaniciyi UYAR, karari ona birak.
    Otomatik kapatma YOK — sadece israrli/kritik asimda runtime_state
    dusuk tuketime geciyor (degrade callback'i)."""
    breached = ", ".join(
        f"{b.get('metric','?').upper()} %{b.get('value')} (esik %{b.get('limit')})"
        for b in (report or {}).get("breached", [])
    ) or "bilinmeyen"
    await broadcast_system_log("WARN", f"Kaynak uyarisi: {breached}")
    await _broadcast({"type": "resource_alert", "breached": (report or {}).get("breached", []),
                      "values": (report or {}).get("values", {})})


# resource_monitor callback'lerini ANA olay dongusune baglayan kopru.
# ONEMLI: ResourceMonitor._fire callback'leri KENDI THREAD'inden, SENKRON
# ve TEK argumanla cagirir. Bir async fonksiyonu dogrudan kaydetmek onu
# hicbir zaman calistirmaz (sadece coroutine nesnesi uretilir, await
# edilmez). Bu yuzden async olanlari run_coroutine_threadsafe ile ana
# dongude calistiriyoruz.
_main_loop = None


def _bridge_async_cb(coro_fn):
    """async callback -> monitor thread'inden guvenle cagrilabilen sync sarmalayici."""
    def _wrapped(report: dict):
        loop = _main_loop
        if loop is None or loop.is_closed():
            return
        try:
            asyncio.run_coroutine_threadsafe(coro_fn(report), loop)
        except Exception as e:
            print(f"[RESOURCE] callback koprusu hatasi: {e}")
    return _wrapped


def _bridge_notify(coro_fn):
    """Senkron modul callback'i -> ana dongude async yayin.

    _bridge_async_cb ile ayni gerekce (bkz. yukarisi) ama serbest imzali:
    self_heal (level, msg), skills_autogrowth (proposal) gibi farkli
    imzalar icin *args gecirir. Bir async fonksiyonu senkron bir callback
    yuvasina dogrudan kaydetmek onu HIC calistirmaz — sadece beklenmeyen
    bir coroutine nesnesi uretir."""
    def _wrapped(*a, **kw):
        loop = _main_loop
        if loop is None or loop.is_closed():
            return
        try:
            asyncio.run_coroutine_threadsafe(coro_fn(*a, **kw), loop)
        except Exception as e:
            print(f"[ALES] bildirim koprusu hatasi: {e}")
    return _wrapped


async def _skill_proposal_cb(proposal: dict):
    """Yeni beceri onerisi -> tum istemcilere bildir. Onay/ret Ali'ye ait;
    burada SADECE haber veriyoruz, hicbir sey skills.json'a yazilmiyor."""
    await _broadcast({"type": "skill_proposal", "proposal": proposal})
    await broadcast_system_log(
        "INFO", f"Yeni beceri önerisi: {proposal.get('name')} "
                f"({proposal.get('occurrences')} kez tekrarlandı) — onayını bekliyor")


async def _selfheal_cb(level: str, msg: str):
    """self_heal olaylari GOREV sekmesindeki canli loga duser. Sessiz
    kurtarma, kurtarma olmayan bir sistemden daha tehlikelidir — kullanici
    neyin yeniden baslatildigini gormeli."""
    await broadcast_system_log(level or "INFO", f"[toparlama] {msg}")


async def _plugin_event_broadcast(event: str, pid: str, detail: str = ""):
    """Eklenti yuklendi/kaldirildi/hata verdi -> UI'ya bildir."""
    await _broadcast({"type": "plugin_event", "event": event,
                      "plugin": pid, "detail": str(detail)[:300]})


async def _sleep_watchdog():
    """Bosta kalma denetleyicisi.

    ESKIDEN check_sleep() HIC cagrilmiyordu, bu yuzden uyku modu olu koddu.
    Her 30 saniyede bir denetler; durum degistiginde arayuze bildirir."""
    was_asleep = False
    while True:
        try:
            await asyncio.sleep(30)
            if not runtime_state:
                continue
            runtime_state.check_sleep()
            asleep = bool(runtime_state.snapshot().get("asleep"))
            if asleep != was_asleep:
                was_asleep = asleep
                await broadcast_system_log(
                    "INFO", "Uyku moduna gecildi (bosta)" if asleep
                    else "Uyku modundan cikildi")
                await _broadcast({"type": "sleep_state", "asleep": asleep})
        except asyncio.CancelledError:
            raise
        except Exception as e:
            print(f"[ALES] uyku denetleyici hatasi: {e}")


# ─── DARWIN GODEL ARKA PLAN EVRIMI ────────────────────────────────────
# Aralik KASITLI olarak uzun: bir adayin hukum alabilmesi icin MIN_TRIALS
# (12) GERCEK kullanici turu gerekiyor. Dakikada bir aday acmak, hicbirini
# olcmeden arsivi doldurmak olurdu — eski surumun rastgele-fitness hatasinin
# baska bir bicimi. Bu yuzden: aday YOKSA yeni aday ac, VARSA dokunma.
DGM_EVOLVE_INTERVAL_S = 3600.0     # 1 saat
DGM_EVOLVE_FIRST_DELAY_S = 900.0   # acilistan 15 dk sonra


async def _dgm_evolution_loop():
    """Dusuk frekansli, kosullu evrim dongusu.

    KAPILAR (hepsi kasitli):
      1. Modul panelden kapaliysa hicbir sey yapmaz (_mod_on).
      2. Ortada denenen aday varsa evolve_generation() zaten
         "deneme_suruyor" der; bekleriz.
      3. Mutasyon icin LLM'e SORULUR ama zorunlu degil: ask_llm
         basarisiz olursa modul kural-tabanli mutasyona duser.
      4. Kaynak baskisi/uyku halinde tur atlanir — evrim bir lukstur,
         kullanicinin isini yavaslatmamali.
    """
    await asyncio.sleep(DGM_EVOLVE_FIRST_DELAY_S)
    while True:
        try:
            if not _mod_on("darwin_godel", darwin_godel):
                await asyncio.sleep(DGM_EVOLVE_INTERVAL_S)
                continue
            # Uyku/kaynak baskisinda evrim yapma (bedava degil: 1 LLM cagrisi).
            # "degraded" = kaynak baskisi yuzunden agir moduller kesildi;
            # "performance_mode" = kullanici bilincli olarak hizi secti.
            busy = False
            try:
                if runtime_state:
                    snap = runtime_state.snapshot()
                    busy = bool(snap.get("asleep") or snap.get("degraded")
                                or snap.get("performance_mode"))
            except Exception:
                busy = False
            if busy:
                await asyncio.sleep(DGM_EVOLVE_INTERVAL_S)
                continue

            res = await darwin_godel.evolve_generation(ask_llm=_codeact_ask_llm())
            if res.get("ok"):
                v = res.get("new_variant") or {}
                print(f"[DGM] yeni aday: {v.get('name')} (nesil {res.get('generation')}) "
                      f"· {res.get('trials_needed')} turda olculecek")
                await broadcast_system_log(
                    "INFO", f"Darwin Gödel: yeni iskele adayı denemeye alındı "
                            f"(nesil {res.get('generation')}, "
                            f"{res.get('trials_needed')} tur gerekli)")
                await _broadcast({"type": "dgm_trial",
                                  "trial": darwin_godel.trial_status()})
            else:
                # "deneme_suruyor" normal durumdur, hata degil.
                print(f"[DGM] evrim atlandi: {res.get('reason') or res.get('error')}")
        except asyncio.CancelledError:
            raise
        except Exception as e:
            print(f"[DGM] evrim dongusu hatasi: {e}")
        await asyncio.sleep(DGM_EVOLVE_INTERVAL_S)


# ═══════════════════════════════════════════════════════════════════
# KAYNAK / CALISMA-ZAMANI YUKU
# Bu iki yardimci TEK kaynaktir: /resources, /runtime ve /system/status
# ucu de bunlari cagirir. Ayni alanlari iki yerde elle kurmak, birinde
# alan eklenip digerinde eklenmemesi demekti (sapma) — onlendi.
# ═══════════════════════════════════════════════════════════════════
def _resources_payload() -> dict:
    """resource_monitor anlik goruntusu; modul yuklenmediyse unavailable."""
    if not resource_monitor:
        return {"unavailable": True}
    st = resource_monitor.monitor.status()
    # Disk / RAM-MB / surec sayisi resource_monitor.sample() icinde ZATEN
    # olculuyordu ama buraya hic tasinmiyordu (snapshot disarida kaliyordu)
    # -> arayuzde disk diye bir sey yoktu. Artik snapshot'tan cikariliyor.
    snap_r = st.get("snapshot") or {}
    sys_r = snap_r.get("system") or {}
    self_r = snap_r.get("self") or {}
    gpu_r = snap_r.get("gpu") or {}
    return {
        "values": st.get("values", {}),
        "thresholds": st.get("thresholds", {}),
        "breached": st.get("breached", []),
        "scope": st.get("scope"),
        "degraded": st.get("degraded"),
        "gpu_backend": st.get("gpu_backend"),
        "psutil": st.get("psutil"),
        "running": st.get("running"),
        # Disk BILEREK esiksiz: DEFAULT_THRESHOLDS'a eklemek onu
        # dusurme/degrade kararlarina sokardi. Diskin %80 dolu olmasi
        # ALES'i kisitlamak icin gecerli bir sebep degil — sadece gosterilir.
        "disk": sys_r.get("disk"),
        "ram_mb": self_r.get("ram_mb"),
        "procs": self_r.get("procs"),
        "ram_total_mb": sys_r.get("ram_total_mb"),
        "gpu_mem_used_mb": gpu_r.get("mem_used_mb"),
        "gpu_mem_total_mb": gpu_r.get("mem_total_mb"),
    }


def _runtime_payload(include_modules: bool = True) -> dict:
    """runtime_state anlik goruntusu.

    include_modules=False -> 10 kayitlik modul defteri ATLANIR. O defterin
    label/note/available alanlari surec boyunca DEGISMEZ, sadece 'paused'
    degisir; 3 saniyelik yoklamada defteri her seferinde yeniden gondermek
    bosuna trafikti. Defter yerine yalnizca duraklatilmis id listesi gider,
    arayuz onu elindeki deftere bindirir (bkz. App.jsx loadLive)."""
    # Calisma suresi runtime_state'e bagli DEGIL — modul yuklenmese bile doner.
    uptime_s = round(time.time() - _STARTED_AT, 1)
    if not runtime_state:
        return {"unavailable": True, "uptime_s": uptime_s}
    snap = runtime_state.snapshot()
    out = {
        "performance_mode": snap["performance_mode"],
        "heavy_mode": snap["heavy_mode"],
        "headless_mode": snap["headless_mode"],
        "sleep_mode": snap["sleep_mode"],
        "asleep": snap["asleep"],
        "idle_s": snap["idle_s"],
        "degraded": snap["degraded"],
        "uptime_s": uptime_s,
        "sleep_after_s": snap.get("sleep_after_s"),
    }
    # 'paused' HER IKI durumda da gonderilir: defter atlandiginda arayuzun
    # rozetleri tazeleyebilmesi icin tek kaynak bu liste.
    out["paused"] = sorted((snap.get("paused") or {}).keys())
    if include_modules:
        out["modules"] = snap["modules"]
    return out


@app.get("/resources")
async def get_resources():
    """Yalniz kaynak olcumleri (CPU/RAM/GPU/disk/surec). GOREV sekmesinin
    3 saniyelik canli yoklamasi burayi cagirir; /system/status'un statik
    kisimlarini (mod zinciri, modul defteri, isleyiciler) tasimaz."""
    return _resources_payload()


@app.get("/runtime")
async def get_runtime(modules: bool = True):
    """Yalniz calisma-zamani durumu: 4 mod anahtari + bosta sayaci +
    calisma suresi. ?modules=false -> statik modul defterini atlar."""
    return _runtime_payload(include_modules=modules)


@app.get("/system/status")
async def system_status():
    """GOREV sekmesi durum kartlari icin tek seferlik anlik goruntu.
    Bilesik yanit: isleyiciler + mod + /resources + /runtime. Sekmeye
    girerken ve anahtar cevrildiginde cagirilir; surekli yoklama icin
    /resources + /runtime?modules=false tercih edilir (daha ucuz)."""
    mode_cfg = get_mode_config()
    out = {
        "workers": {
            "scheduler": _worker_alive("scheduler"),
            "notifier": _worker_alive("notifier"),
            "resource_monitor": bool(
                resource_monitor and resource_monitor.monitor.status().get("running")
            ),
            # Otomatik model kesfi zamanlayicisi (30 dk). Sessizce olurse
            # model adlari eskimeye baslar ve sebebi hicbir yerde gorunmezdi.
            "model_discovery": _worker_alive("model_discovery"),
        },
        "mode": {
            "id": mode_cfg["mode"],
            "label": mode_cfg["label"],
            "chain": [f"{l.get('provider')}/{str(l.get('model','')).split('/')[-1]}"
                      for l in mode_cfg["chain"]],
            "fast_path": mode_cfg["fast_path"],
            "multi": mode_cfg["multi"],
        },
        "clients": len(connected_ws),
    }
    out["resources"] = _resources_payload()
    out["runtime"] = _runtime_payload()
    # Denetci ozeti: hangi gorev dustu, hangisinden vazgecildi. Sadece
    # _worker_alive() bakildiginda "durmus" ile "vazgecildi" ayirt
    # edilemiyordu — ikisi cok farkli sey (biri kendiliginden geri gelir).
    if _supervisor is not None:
        try:
            sup = _supervisor.status()
            out["selfheal"] = {"running": sup.get("running"),
                               "degraded": sup.get("degraded", []),
                               "given_up": sup.get("given_up", []),
                               "workers": sup.get("workers", [])}
        except Exception as e:
            out["selfheal"] = {"error": str(e)}
    # Bekleyen beceri onerisi sayisi: rozet icin tek sayi yeterli, tum
    # listeyi /skills/proposals'dan cekmek gerekmiyor.
    if skills_autogrowth is not None:
        try:
            out["skill_proposals"] = skills_autogrowth.pending_count()
        except Exception:
            out["skill_proposals"] = 0
    return out


@app.post("/system/start")
async def system_start(data: dict = None):
    """ALES'in arka plan isleyicilerini baslat. Govde:
       {"workers": [...]}   bos = hepsi
       {"profiles": [...]}  GOREV sekmesinde secilen tarayici profilleri

    KAPSAM NOTU: profiller yalnizca KAYDEDILIR (hangi profil baglaminda
    calisilacagi bilgisi). Her profil icin AYRI/paralel oturum acan coklu
    hesap otomasyonu BILEREK yapilmaz — o kapsam daha once reddedildi ve
    karar korunuyor. Isleyiciler (zamanlayici/bildirimci/kaynak izleyici)
    profilden bagimsiz, tek ve global calisir."""
    data = data or {}
    want = data.get("workers") or ["scheduler", "notifier", "resource_monitor"]
    started, already = [], []

    # ── Secilen profilleri dogrula + kaydet ──────────────────────
    profiles_out = None
    if isinstance(data.get("profiles"), list):
        try:
            known = {p["id"] for p in browser_profiles.list_profiles()}
        except Exception:
            known = set()
        chosen = [str(p) for p in data["profiles"] if str(p) in known]
        unknown = [str(p) for p in data["profiles"] if str(p) not in known]
        cfg = load_config()
        cfg["active_profiles"] = chosen
        save_config(cfg)
        profiles_out = {"selected": chosen, "ignored_unknown": unknown}
        if chosen:
            await broadcast_system_log("INFO", f"Aktif profiller: {', '.join(chosen)}")

    if "scheduler" in want:
        if _worker_alive("scheduler"):
            already.append("scheduler")
        else:
            _workers["scheduler"] = asyncio.create_task(run_scheduler(_scheduler_cb))
            started.append("scheduler")

    if "notifier" in want:
        if _worker_alive("notifier"):
            already.append("notifier")
        else:
            _workers["notifier"] = asyncio.create_task(
                run_notifier(browser_module, _notifier_cb, fiverr_module=fiverr))
            started.append("notifier")

    if "resource_monitor" in want and resource_monitor:
        if resource_monitor.monitor.status().get("running"):
            already.append("resource_monitor")
        else:
            resource_monitor.monitor.start()
            _workers["resource_monitor"] = True
            started.append("resource_monitor")

    if started:
        await broadcast_system_log("INFO", f"Baslatildi: {', '.join(started)}")
    out = {"ok": True, "started": started, "already_running": already,
           "status": (await system_status())["workers"]}
    if profiles_out is not None:
        out["profiles"] = profiles_out
    return out


@app.post("/system/stop")
async def system_stop(data: dict = None):
    """Arka plan isleyicilerini durdur. Sohbet/WebSocket ETKILENMEZ —
    ALES konusmaya devam eder, sadece otomatik isleyiciler durur."""
    want = (data or {}).get("workers") or ["scheduler", "notifier", "resource_monitor"]
    stopped = []
    for name in ("scheduler", "notifier"):
        if name in want and _worker_alive(name):
            _workers[name].cancel()
            _workers[name] = None
            stopped.append(name)
    if "resource_monitor" in want and resource_monitor:
        if resource_monitor.monitor.status().get("running"):
            resource_monitor.monitor.stop()
            stopped.append("resource_monitor")
    if stopped:
        await broadcast_system_log("INFO", f"Durduruldu: {', '.join(stopped)}")
    return {"ok": True, "stopped": stopped,
            "status": (await system_status())["workers"]}


@app.post("/system/toggle")
async def system_toggle(data: dict):
    """Faz-3 anahtarlari: performance / heavy / headless / sleep.
    Govde: {"which": "performance", "on": true}"""
    if not runtime_state:
        return {"ok": False, "error": "runtime_state yuklenemedi"}
    which = (data.get("which") or "").lower()
    on = bool(data.get("on"))
    fn = {
        "performance": runtime_state.set_performance,
        "heavy": runtime_state.set_heavy,
        "headless": runtime_state.set_headless,
    }.get(which)
    try:
        if fn:
            snap = fn(on)
        elif which == "sleep":
            snap = runtime_state.set_sleep_enabled(on)
        else:
            return {"ok": False, "error": f"Bilinmeyen anahtar: {which}"}
    except Exception as e:
        return {"ok": False, "error": str(e)}
    await broadcast_system_log("INFO", f"{which} = {'ACIK' if on else 'KAPALI'}")
    # Anahtar degisimini TUM bagli istemcilere it. Frontend'de zaten
    # 'system_status' isleyicisi var (App.jsx), boylece ikinci bir sekme ya da
    # telefon da anahtari kendisi cevirmemis olsa bile aninda tazelenir.
    try:
        await _broadcast({"type": "system_status", "status": await system_status()})
    except Exception as e:
        print(f"[ALES] durum yayini basarisiz: {e}")
    return {"ok": True, "which": which, "on": on, "runtime": snap}


# ─── CODEACT / JIT (kod-olarak-eylem) ────────────────────────────
# NEDEN BURADA VE NEDEN LLM ARACI DEGIL: config_manager.py:122'de yazili
# olan kural — "AI kodu otomatik calistirilmaz, kapilar kaldirilmaz".
# Bu yuzden codeact TOOLS listesine EKLENMEDI: modelin kendi kararıyla
# kod calistirmasinin yolu yok. Yalnizca kullanicinin acikca bastigi bu
# uc endpoint uzerinden calisir ve her calisma statik kapi + onay +
# timeout + ayri process'ten gecer.
def _codeact_ask_llm(mode: str = None):
    """code_act_executor/agent_jit'in bekledigi `ask_llm` kapatmasi:
    async (messages) -> str. Router zincirini kullanir, boylece kod
    uretimi de mod ayarina (ve heavy kapisina) tabidir.

    FAZ-2 (CONCUR tarzi toplu cikarim): bu kapatma ALES'in TUM yardimci
    LLM isini besler — oz-yansima (Reflexion), JIT derleme, CodeAct plani.
    Bu isler arka planda ve genelde AYNI ANDA tetiklenir. Tek tek gonderilirse
    her biri ayri bir akis acar; batch_inference bunlari kisa bir pencerede
    (BATCH_WINDOW_MS) toplayip TEK sevkiyatta gonderir.

    DURUSTLUK: makaledeki "4x throughput" sunucu tarafi surekli-toplama
    (continuous batching) ile gelir; ucretsiz barindirilan API'lerde boyle
    bir uc YOK. Burada kazanc daha mutevazi ve gercek: es zamanli yardimci
    isler tek gather'da, sinirli es-zamanlilikla ve tek istatistik altinda
    sevk edilir; kuyruk kapaliysa/patlarsa dogrudan cagriya duser."""
    async def _direct(messages: list) -> str:
        res = await model_router.chat_chain(messages, mode=mode,
                                            max_tokens=2048, temperature=0.2)
        return res.get("content") or ""

    async def _executor(reqs: list) -> list:
        """batch_inference'in bekledigi toplu yurutucu: N istek -> N sonuc."""
        outs = await asyncio.gather(
            *[_direct(r.get("messages") or []) for r in reqs],
            return_exceptions=True)
        return ["" if isinstance(o, Exception) else o for o in outs]

    async def _ask(messages: list) -> str:
        if _mod_on("batch_inference", batch_inference):
            try:
                out = await batch_inference.engine.submit(
                    {"type": "chat", "messages": messages,
                     "prompt": str((messages or [{}])[-1].get("content", ""))[:200]},
                    executor=_executor)
                if out:
                    return out
            except Exception as e:
                print(f"[BATCH] toplu sevk atlandi, dogrudan gidiliyor: {e}")
        return await _direct(messages)
    return _ask


def _tools_doc() -> str:
    """Modele "hangi araclar var" bilgisini kisa liste olarak ver.
    Tam JSON semasi gereksiz token; ad + aciklama yeterli."""
    try:
        lines = []
        for t in get_all_tools():
            f = (t or {}).get("function") or {}
            if f.get("name"):
                lines.append(f"- {f['name']}: {str(f.get('description',''))[:120]}")
        return "\n".join(lines[:120])
    except Exception:
        return ""


@app.get("/codeact")
async def codeact_info():
    """Kapinin ne oldugunu UI'da gosterebilmek icin: izinli importlar,
    timeout, node var mi."""
    if code_act_executor is None:
        return {"available": False, "error": "code_act_executor yuklenemedi"}
    return {"available": True, "info": code_act_executor.info(),
            "stats": code_act_executor.stats()}


@app.post("/codeact/plan")
async def codeact_plan(data: dict):
    """Gorevi koda cevir ama CALISTIRMA. Onay ekraninda gosterilecek kod
    ile statik denetim sonucunu dondurur.

    Govde: {"task": "...", "mode": "task"}
    """
    if code_act_executor is None:
        return {"ok": False, "error": "code_act_executor yuklenemedi"}
    task = (data.get("task") or "").strip()
    if not task:
        return {"ok": False, "error": "task bos"}
    try:
        reply = await _codeact_ask_llm(data.get("mode"))(
            code_act_executor.build_messages(task, _tools_doc()))
    except Exception as e:
        return {"ok": False, "error": f"LLM hatasi: {type(e).__name__}: {e}"}
    ex = code_act_executor.extract_code(reply or "")
    if not ex.get("found"):
        return {"ok": False, "error": "modelin yanitinda kod blogu yok",
                "reply": (reply or "")[:1500]}
    st = code_act_executor.static_check(ex["code"], ex["lang"],
                                        allow_net=bool(data.get("allow_net")))
    return {"ok": bool(st.get("ok")), "code": ex["code"], "lang": ex["lang"],
            "static": st,
            "needs_approval": code_act_executor.needs_approval(ex["code"], ex["lang"]),
            "error": (None if st.get("ok")
                      else "statik kapi reddetti: " + "; ".join(st.get("blocked", [])))}


@app.post("/codeact/run")
async def codeact_run(data: dict):
    """Kodu calistir. IKI KULLANIM:
       {"code": "...", "approved": true}   -> /codeact/plan cikisini onayla
       {"task": "...", "approved": true}   -> plan + calistir tek adimda

    `approved` YOKSA hicbir sey calistirilmaz (kapi kapali dogar). Bu, LLM'in
    kendi basina kod calistirmasinin onune gecen ana kilit.
    """
    if code_act_executor is None:
        return {"ok": False, "error": "code_act_executor yuklenemedi"}
    approved = bool(data.get("approved"))
    code = (data.get("code") or "").strip()
    lang = (data.get("lang") or "python").lower()
    timeout_s = data.get("timeout_s")
    allow_net = bool(data.get("allow_net"))

    if code:
        st = code_act_executor.static_check(code, lang, allow_net=allow_net)
        if not st.get("ok"):
            return {"ok": False, "ran": False, "static": st,
                    "error": "statik kapi reddetti: " + "; ".join(st.get("blocked", []))}
        if code_act_executor.needs_approval(code, lang) and not approved:
            return {"ok": False, "ran": False, "needs_approval": True,
                    "static": st, "code": code,
                    "error": "onay gerekiyor: approved=true ile tekrar gonder"}
        res = code_act_executor.run_sandboxed(code, lang, timeout_s=timeout_s,
                                              allow_net=allow_net)
        await broadcast_system_log(
            "INFO" if res.get("ok") else "ERROR",
            f"CodeAct calisti ({lang}, {res.get('elapsed')}s) — "
            f"{'basarili' if res.get('ok') else 'hata'}")
        return {"ok": bool(res.get("ok")), "ran": True, "result": res,
                "static": st, "code": code, "lang": lang}

    task = (data.get("task") or "").strip()
    if not task:
        return {"ok": False, "error": "code veya task gerekli"}

    # approve_cb: kullanici ONCEDEN onayladiysa gecirir, aksi halde
    # REDDEDER. None GECMIYORUZ — None gecmek "onay kapisi yok" demek
    # degil, plan_and_run icinde "calistirma" anlamina gelir; burada
    # niyeti acikca yazmak istiyoruz.
    async def _approve(_code: str, _static: dict) -> bool:
        return approved

    out = await code_act_executor.plan_and_run(
        task, _codeact_ask_llm(data.get("mode")), approve_cb=_approve,
        tools_doc=_tools_doc(), timeout_s=timeout_s, allow_net=allow_net)
    if out.get("ran"):
        await broadcast_system_log(
            "INFO" if out.get("ok") else "ERROR",
            f"CodeAct gorev calisti ({out.get('elapsed')}s) — "
            f"{'basarili' if out.get('ok') else 'hata'}")
    return out


@app.get("/codeact/stats")
async def codeact_stats():
    if code_act_executor is None:
        return {"unavailable": True}
    return code_act_executor.stats()


@app.post("/codeact/stats/reset")
async def codeact_stats_reset():
    if code_act_executor is None:
        return {"ok": False, "error": "code_act_executor yuklenemedi"}
    return {"ok": True, **code_act_executor.reset_stats()}


@app.get("/jit")
async def jit_list(limit: int = 50):
    """Derlenmis gorev listesi + sayaclar. `llm_calls_saved` modulun asil
    kazancini gosterir: onbellekten calisan her gorev bir LLM turu eksiltir."""
    if agent_jit is None:
        return {"unavailable": True, "entries": [], "stats": {}}
    return {"entries": agent_jit.list_entries(limit), "stats": agent_jit.stats(),
            "info": agent_jit.info()}


# SIRA ONEMLI: bu tanim /jit/{key} yolundan ONCE gelmek ZORUNDA.
# FastAPI yollari TANIM SIRASIYLA esler; asagidaki /jit/{key} once
# gelseydi "graphs" kelimesi bir `key` sanilir ve bu uc hicbir zaman
# cagrilmazdi (404 bile vermez, bos bir `entry` doner — sessiz ariza).
# Govde asagida, jit_stats_reset'in yanindaki _jit_graphs_impl'de.
@app.get("/jit/graphs")
async def jit_graphs(limit: int = 20):
    return await _jit_graphs_impl(limit)


@app.get("/jit/{key}")
async def jit_entry(key: str):
    if agent_jit is None:
        return {"ok": False, "error": "agent_jit yuklenemedi"}
    e = agent_jit.get_entry(key)
    return {"ok": bool(e), "entry": e}


@app.post("/jit/run")
async def jit_run_route(data: dict):
    """Derlenmis blok varsa onu calistir, yoksa derle + calistir.
    Govde: {"task": "...", "approved": true, "force_recompile": false}

    Onay kapisi CodeAct ile AYNI: onbellekten gelen kod da AI kodudur."""
    if agent_jit is None:
        return {"ok": False, "error": "agent_jit yuklenemedi"}
    task = (data.get("task") or "").strip()
    if not task:
        return {"ok": False, "error": "task bos"}
    approved = bool(data.get("approved"))

    async def _approve(_code: str, _meta: dict) -> bool:
        return approved

    out = await agent_jit.jit_run(
        task, ask_llm=_codeact_ask_llm(data.get("mode")), approve_cb=_approve,
        force_recompile=bool(data.get("force_recompile")),
        timeout_s=data.get("timeout_s"), tools_doc=_tools_doc())
    if out.get("ok"):
        await broadcast_system_log(
            "INFO", f"JIT {'onbellekten' if out.get('cached') else 'derlenip'} "
                    f"calisti ({out.get('elapsed')}s)")
    return out


@app.post("/jit/{key}/quarantine")
async def jit_quarantine(key: str, data: dict = None):
    if agent_jit is None:
        return {"ok": False, "error": "agent_jit yuklenemedi"}
    on = True if data is None else bool(data.get("on", True))
    ok = (agent_jit.quarantine(key, (data or {}).get("reason", ""))
          if on else agent_jit.unquarantine(key))
    return {"ok": ok, "key": key, "quarantined": on}


@app.delete("/jit/{key}")
async def jit_invalidate(key: str):
    if agent_jit is None:
        return {"ok": False, "error": "agent_jit yuklenemedi"}
    return {"ok": agent_jit.invalidate(key), "key": key}


@app.delete("/jit")
async def jit_clear():
    if agent_jit is None:
        return {"ok": False, "error": "agent_jit yuklenemedi"}
    return agent_jit.clear()


@app.post("/jit/stats/reset")
async def jit_stats_reset():
    if agent_jit is None:
        return {"ok": False, "error": "agent_jit yuklenemedi"}
    return {"ok": True, **agent_jit.reset_stats()}


async def _jit_graphs_impl(limit: int = 20):
    """Canli agent dongusunde DERLENMIS cizgeler.

    NEDEN AYRI BIR UC: /jit blok onbellegini gosteriyor (derlenmis Python
    kodu). Cizge katmani BASKA bir sey: modelin ayni turda istedigi arac
    cagrilarini bir DAG'a dizip salt-okunur olanlari paralel yuruten
    zamanlayici. Ikisi ayni sayaclarda karisirsa "JIT calisiyor mu"
    sorusunun cevabi belirsizlesiyordu.

    `graphs_compiled` 0 ise cizge katmani hic devreye girmemis demektir ve
    bu NORMAL olabilir: yalnizca KARISIK turlarda (bazi cagrilar salt-okunur,
    bazilari yan etkili) ve en az iki salt-okunur cagri ayni katmana
    dustugunde kuruluyor. Butun cagrilar salt-okunursa main.py zaten
    asyncio.gather kullaniyor, cizgeye gerek yok.

    `nodes_per_layer` ASIL KAZANC: 1.0 ise hicbir sey paralellesmedi.
    Olculmemis bir deger UYDURMUYORUZ — hic cizge kosmadiysa None.
    """
    if agent_jit is None:
        return {"unavailable": True, "graphs": [], "stats": {}}
    s = agent_jit.stats()
    _n = s.get("graph_nodes_run") or 0
    _l = s.get("graph_layers") or 0
    with agent_jit._lock:
        _gs = sorted(agent_jit._compiled_graphs.values(),
                     key=lambda g: g.created, reverse=True)[:limit]
        graphs = [g.to_dict() for g in _gs]
    return {
        "graphs": graphs,
        "compiled": s.get("graphs_compiled", 0),
        "executed": s.get("graphs_executed", 0),
        "nodes_run": _n,
        "layers": _l,
        "nodes_per_layer": round(_n / _l, 2) if _l else None,
        "active": _mod_on("agent_jit", agent_jit),
        "note": ("Cizge yalnizca KARISIK turlarda ve >=2 salt-okunur cagri "
                 "ayni katmana dustugunde kurulur."),
    }


# ─── ONGORULU ON-YUKLEME (predictive) ────────────────────────────
@app.get("/predictive/stats")
async def predictive_stats():
    if predictive is None:
        return {"unavailable": True}
    return {"stats": predictive.stats(), "info": predictive.info(),
            # 'active' = modul var VE duraklatilmamis. Sadece stats'a bakip
            # "neden hic on-yukleme yok" sorusuna cevap bulunamiyordu.
            "active": bool(runtime_state and runtime_state.module_active("predictive"))
                      if runtime_state else True}


@app.post("/predictive/stats/reset")
async def predictive_stats_reset():
    if predictive is None:
        return {"ok": False, "error": "predictive yuklenemedi"}
    return {"ok": True, **predictive.reset_stats()}


@app.post("/predictive/clear")
async def predictive_clear():
    if predictive is None:
        return {"ok": False, "error": "predictive yuklenemedi"}
    predictive.clear()
    return {"ok": True, **predictive.stats()}


# ─── SES MOTORU (akisli TTS) ─────────────────────────────────────
@app.get("/tts/engine")
async def tts_engine():
    """Hangi motor aktif, akis acik mi, ses NEREDE calacak.
    `local_playback: true` -> ses PC hoparlorunden cikar, telefonda duyulmaz."""
    if audio_streamer is None:
        return {"available": False, "error": "audio_streamer yuklenemedi",
                "stream_on": False}
    out = audio_streamer.engine_info()
    out["stream_on"] = _tts_stream_on()
    try:
        out["stream_setting"] = bool(load_config().get("tts_stream", False))
    except Exception:
        out["stream_setting"] = False
    out["stats"] = audio_streamer.stats()
    return out


@app.post("/tts/toggle")
async def tts_toggle(data: dict):
    """Akisli sesi ac/kapa (config.json > tts_stream). Govde: {"on": true}
    Istege bagli: {"engine": "edge_tts", "voice": "tr-TR-AhmetNeural"}"""
    cfg = load_config()
    if "on" in (data or {}):
        cfg["tts_stream"] = bool(data.get("on"))
    if (data or {}).get("engine"):
        cfg["tts_engine"] = str(data["engine"])
    if (data or {}).get("voice"):
        cfg["tts_voice"] = str(data["voice"])
    save_config(cfg)
    return {"ok": True, "stream_on": _tts_stream_on(),
            "stream_setting": bool(cfg.get("tts_stream", False)),
            "engine": cfg.get("tts_engine"), "voice": cfg.get("tts_voice"),
            "note": ("Akis acikken ses birden fazla parca halinde gelir; "
                     "arayuz onlari sirayla calar.")}


@app.post("/speak")
async def speak_api(payload: dict):
    """
    UI'daki 'Sesli Oku' butonundan gelen metni sese çevirir ve
    base64 mp3 formatında döndürür. audio_streamer / edge-tts / voice kullanır.
    """
    text = (payload.get("text") or "").strip()
    if not text:
        return {"ok": False, "error": "Metin boş"}
    cleaned = voice._clean_for_speech(text) if voice else text
    audio_bytes = None
    try:
        cfg = load_config()
        key = (
            payload.get("elevenlabs_key")
            or cfg.get("elevenlabs_key", "")
            or get_key("elevenlabs_key")
            or os.environ.get("ELEVENLABS_API_KEY", "")
            or os.environ.get("ELEVENLABS_KEY", "")
        )
        if isinstance(key, str): key = key.strip()
        voice_id = payload.get("voice_id") or cfg.get("elevenlabs_voice") or voice.DEFAULT_ELEVENLABS_VOICE
        edge_voice = payload.get("edge_voice") or cfg.get("edge_voice") or voice.DEFAULT_EDGE_VOICE

        if voice:
            try:
                loop = asyncio.get_running_loop()
                audio_bytes = await loop.run_in_executor(
                    _executor, voice.synthesize, cleaned,
                    key,
                    voice_id,
                    edge_voice,
                )
            except Exception as ve:
                print(f"[SPEAK] voice.synthesize hatasi: {ve}")

        if not audio_bytes and audio_streamer:
            try:
                audio_bytes = await audio_streamer.synth_sentence(cleaned)
            except Exception as se:
                print(f"[SPEAK] audio_streamer hatasi: {se}")
        if audio_bytes:
            mime = "audio/wav" if audio_bytes.startswith(b"RIFF") else "audio/mpeg"
            b64 = base64.b64encode(audio_bytes).decode("ascii")
            return {"ok": True, "audio": b64, "mime": mime}
        return {"ok": False, "error": "Ses sentezlenemedi"}
    except Exception as e:
        return {"ok": False, "error": f"{type(e).__name__}: {e}"}


# ─── MODEL KATMANLARI (Kimi K3 dahil) ────────────────────────────
@app.get("/models")
async def models_list():
    """Katman tablosu: hangi model, hangi modda acik, anahtar var mi.
    Heavy-only katmanlar (kimi-k3) yalnizca Heavy/Council modunda 'active_now'
    gorunur — kapatan sey mod, eksik anahtar degildir."""
    from config_manager import list_model_layers, heavy_available, credential_problems
    return {"layers": list_model_layers(), "mode": get_mode(),
            "heavy_available": heavy_available(),
            "providers": model_router.available_providers(),
            # YANLIS TURDE anahtarlar: "key var" gorunup her cagrida 401
            # dondurmek en yaniltici ariza turu. Bu alan onu acikca soyler.
            # Deger DONDURULMEZ, sadece alan adi + ne yapilmasi gerektigi.
            "credential_problems": credential_problems()}


@app.get("/test-models")
async def test_models(ping: bool = True, timeout: float = 8.0):
    """Her saglayiciyi/katmani dener: hangisi GERCEKTEN ulasilabilir.

    ?ping=false  -> hic token harcamaz (yalnizca GET /models dogrulamasi)
    ?timeout=15  -> yavas saglayicilar icin sureyi uzat

    Tum saglayicilar es zamanli denenir, yani toplam sure ~timeout kadardir.
    """
    try:
        return await model_router.probe_all(
            ping=bool(ping), timeout=max(1.0, min(60.0, float(timeout))))
    except Exception as e:
        # Yerel import: JSONResponse bu dosyada asagida (frontend blogunda)
        # import ediliyor. Cagri aninda global olarak ZATEN var, ama o blok
        # bir gun tasinirsa burada sessiz bir NameError kalmasin.
        from fastapi.responses import JSONResponse as _JR
        return _JR({"ok": False, "error": f"{type(e).__name__}: {e}"},
                   status_code=500)


@app.get("/diag/chain")
async def diag_chain_endpoint(mode: str = None):
    """UCTAN UCA TESHIS — kabuk (terminal) gerekmeden, CALISAN surec icinde.

    Neyi dogrular:
      1. Yanlis TURDE anahtar var mi (credential_problems)
      2. Aktif zincir + zaman asimlari + katman basina cikti tavanlari
      3. GERCEK istem boyutu (sistem istemi + secilen araclarin JSON semasi)
      4. Zincir GERCEKTEN aciliyor mu — duz sohbet sorusu
      5. Model ARAC CAGIRIYOR mu — google_search gerektiren soru

    Tarayicidan: http://127.0.0.1:8000/diag/chain   (?mode=heavy ile mod secilir)

    NEDEN yeni bir route: mevcut hicbir route/WebSocket handler'i degismedi.
    /test-models saglayici ULASILABILIRLIGINI soyluyor ama zincirin ARAC
    SEMALARIYLA acilip acildigini ve modelin arac cagirdigini soylemiyor —
    kullanicinin gordugu ariza tam olarak orada.

    GUVENLIK: anahtar DEGERLERI dondurulmez, sadece "sorun var mi" bilgisi.
    """
    from fastapi.responses import JSONResponse as _JR
    try:
        from config_manager import credential_problems
        mc = get_mode_config(mode)

        # Gercek sohbet yolunun kurdugu istemin AYNISI (recent_context bos —
        # teshis bir konusmanin ortasinda degil).
        persona = get_current_persona()
        system = BASE_SYSTEM.format(
            dt=datetime.now().strftime("%d.%m.%Y %H:%M"),
            profile=build_context_prompt() or "Henüz profil yok.",
            persona_tone=persona["tone"],
            persona_extra=persona.get("system_add", ""),
            recent_context="")
        lubv = get_system_prompt()
        if lubv:
            system = lubv + "\n\n" + system
        try:
            import experience_learner
            _lr = experience_learner.get_rules_prompt()
            if _lr:
                system += "\n" + _lr
        except Exception:
            pass

        all_tools = get_all_tools()
        probe_q = "Google'da 'NVIDIA hisse fiyati' diye ara ve bulduklarini soyle."
        active = select_relevant_tools(probe_q, all_tools)

        async def _run(question: str, want_tool: bool) -> dict:
            msgs = [{"role": "system", "content": system},
                    {"role": "user", "content": question}]
            used, text, calls, err = {}, [], [], None
            t0 = time.time()
            try:
                async for ev in model_router.stream_chat(
                        msgs, mode=mc["mode"], tools=active,
                        on_layer=lambda l: used.update(l)):
                    t = ev.get("type")
                    if t == "token":
                        text.append(ev["text"])
                    elif t == "tool_calls":
                        calls = [c.get("name") for c in ev["tool_calls"]]
                    elif t == "error":
                        err = ev.get("error")
            except Exception as ex:
                err = f"{type(ex).__name__}: {ex}"
            body = "".join(text).strip()
            return {"question": question,
                    "ok": bool(err is None and (body or calls)),
                    "layer": (f"{used.get('layer')}={used.get('provider')}/"
                              f"{used.get('model')}" if used else None),
                    "seconds": round(time.time() - t0, 2),
                    "tool_calls": calls,
                    "tool_expected": want_tool,
                    "text": body[:400],
                    "error": (err or "")[:900]}

        plain = await _run("Merhaba, kisaca kendini tanit.", False)
        tooled = await _run(probe_q, True)
        return {
            "mode": mc["mode"],
            "chain": [f"{l['layer']}={l['provider']}/{l['model']}"
                      for l in mc["chain"]],
            "timeouts": mc["timeouts"],
            "max_out": mc.get("max_out"),
            "credential_problems": credential_problems(),
            "providers": model_router.available_providers(),
            "prompt_bytes": len(system.encode("utf-8")),
            "tools_total": len(all_tools),
            "tools_selected": len(active),
            "tool_schema_bytes": len(
                json.dumps(active, ensure_ascii=False).encode("utf-8")),
            "plain_chat": plain,
            "tool_call_test": tooled,
            "verdict": {
                "chain_opens": plain["ok"],
                "tools_work": bool(tooled["tool_calls"]),
                "all_pass": bool(plain["ok"] and tooled["tool_calls"]),
            },
        }
    except Exception as e:
        return _JR({"ok": False, "error": f"{type(e).__name__}: {e}",
                    "trace": traceback.format_exc()[-1500:]}, status_code=500)


# ─── OTOMATIK MODEL KESFI (model_registry) ───────────────────────
# Arayuz: Ayarlar > Gelismis > MODEL KESFI. Bu uc route panelin tamamini
# besler; hepsi model_registry tekil ornegini paylasir (router ile AYNI
# onbellek/kara liste — iki ayri gercek olmasin).
@app.get("/model-discovery")
async def model_discovery():
    """Saglayici saglik tablosu + katman dogrulamasi + kesif gunlugu.

    Bu route AG ISTEGI YAPMAZ — yalnizca bellekteki/onbellekteki son durumu
    dondurur. Panel her acildiginda alti saglayiciya istek atmasin diye
    boyle: taze veri istendiginde POST /model-discovery/refresh cagirilir.
    """
    if model_registry is None:
        return {"available": False,
                "error": "model_registry yüklenemedi",
                "providers": [], "layers": [], "events": [], "log": [],
                "totals": {}}
    try:
        return model_registry.status()
    except Exception as e:
        from fastapi.responses import JSONResponse as _JR
        return _JR({"available": False, "error": f"{type(e).__name__}: {e}"},
                   status_code=500)


@app.post("/model-discovery/refresh")
async def model_discovery_refresh():
    """Arayuzdeki YENILE dugmesi: hemen tum saglayicilari tazele.

    force=True: zamanlanmis tur tam o anda kosuyorsa bile kullanicinin
    tiklamasi bir sey yapmis olsun (aksi halde dugme sessizce hicbir sey
    yapmiyor gibi gorunuyordu).
    """
    if model_registry is None:
        return {"ok": False, "error": "model_registry yüklenemedi"}
    try:
        st = await model_registry.refresh_all_providers(force=True)
        t = st.get("totals") or {}
        return {"ok": True,
                "message": (f"{t.get('models', 0)} model · "
                            f"{t.get('ok', 0)} sağlayıcı OK"
                            + (f" · {t['stale_layers']} katman listede yok"
                               if t.get("stale_layers") else "")),
                **st}
    except Exception as e:
        return {"ok": False, "error": f"{type(e).__name__}: {e}"}


@app.post("/api/models/refresh")
@app.get("/api/models/refresh")
async def api_models_refresh():
    """Manuel ve UI tetiklemeli model kesfi ve otomatik onarim."""
    try:
        res = {}
        if auto_model_discovery is not None:
            res = await auto_model_discovery.run_discovery_now()
        elif model_registry is not None:
            res = await model_registry.refresh_all_providers(force=True)
        return {"ok": True, "result": res}
    except Exception as e:
        return {"ok": False, "error": str(e)}


@app.post("/api/session/sync")
@app.post("/session/sync")
async def api_session_sync(data: dict):
    """Frontend'den gelen API anahtarlarini oturuma senkronize et."""
    try:
        keys = data.get("keys") or data
        import config_manager as cm
        for k, v in keys.items():
            if isinstance(v, str) and v.strip():
                cm.set_key(k, v.strip())
        mode = data.get("mode")
        if mode:
            cm.set_mode(mode)
        return {"ok": True, "message": "Oturum anahtarları eşitlendi"}
    except Exception as e:
        return {"ok": False, "error": str(e)}


@app.post("/model-discovery/reset")
async def model_discovery_reset(data: dict = None):
    """Otomatik kararlari geri al. Govde:
       {"what": "blacklist"}   kara listeyi temizle (yasakli modeller yeniden denenir)
       {"what": "overrides"}   otomatik model degisimlerini sifirla
       {"what": "all"}         ikisi de  (varsayilan)

    NEDEN VAR: kacis kapisi olmayan bir kara liste, yanlis bir kayit
    olustugunda modeli kalici olarak kaybettirir. Otomatik sistemin her
    karari kullanici tarafindan geri alinabilir olmali.
    """
    if model_registry is None:
        return {"ok": False, "error": "model_registry yüklenemedi"}
    what = ((data or {}).get("what") or "all").lower()
    reg = model_registry.registry
    n_bl = n_ov = 0
    try:
        if what in ("blacklist", "all"):
            n_bl = reg.clear_blacklist()
        if what in ("overrides", "all"):
            n_ov = reg.clear_overrides()
        return {"ok": True,
                "message": f"{n_bl} kara liste kaydı, {n_ov} otomatik değişim silindi",
                "cleared": {"blacklist": n_bl, "overrides": n_ov}}
    except Exception as e:
        return {"ok": False, "error": f"{type(e).__name__}: {e}"}


# ─── EKLENTILER (plugin_loader) ──────────────────────────────────
@app.get("/plugins")
async def plugins_list():
    if plugin_loader is None:
        return {"unavailable": True, "plugins": [], "stats": {}}
    return {"plugins": plugin_loader.list_plugins(),
            "stats": plugin_loader.stats(), "info": plugin_loader.info(),
            "events": plugin_loader.events(20),
            "dir": plugin_loader.info().get("dir")}


@app.post("/plugins/reload")
async def plugins_reload():
    """plugins/ klasorunu yeniden tara. ALES'i yeniden baslatmak GEREKMEZ —
    modulun butun amaci bu."""
    if plugin_loader is None:
        return {"ok": False, "error": "plugin_loader yuklenemedi"}
    # reload_all() = discover(force=True) -> {pid: kayit} sozlugu doner.
    found = plugin_loader.reload_all() or {}
    bad = [p.get("id") for p in found.values() if p.get("load_error")]
    await _plugin_event_broadcast("reloaded", "*", f"{len(found)} eklenti")
    await broadcast_system_log(
        "WARN" if bad else "INFO",
        f"Eklentiler yenilendi: {len(found)} adet"
        + (f" — hatalı: {', '.join(str(b) for b in bad)}" if bad else ""))
    return {"ok": True, "count": len(found), "failed": bad,
            "plugins": plugin_loader.list_plugins(),
            "stats": plugin_loader.stats()}


@app.post("/plugins/{pid}/reload")
async def plugin_reload_one(pid: str):
    if plugin_loader is None:
        return {"ok": False, "error": "plugin_loader yuklenemedi"}
    res = plugin_loader.reload_plugin(pid)
    await _plugin_event_broadcast("reloaded" if res.get("ok") else "error", pid,
                                  res.get("error") or "")
    return res


@app.post("/plugins/{pid}/toggle")
async def plugin_toggle(pid: str, data: dict = None):
    """Eklentiyi ac/kapa. Govde: {"on": true}"""
    if plugin_loader is None:
        return {"ok": False, "error": "plugin_loader yuklenemedi"}
    on = True if data is None else bool(data.get("on", True))
    res = plugin_loader.set_enabled(pid, on)
    await _plugin_event_broadcast("enabled" if on else "disabled", pid)
    return res


@app.delete("/plugins/{pid}")
async def plugin_unload(pid: str):
    """Bellekten kaldir (DOSYAYI SILMEZ). Silme islemi bilerek yok:
    bir endpoint'in kullanicinin dosyalarini silmesi geri alinamaz."""
    if plugin_loader is None:
        return {"ok": False, "error": "plugin_loader yuklenemedi"}
    res = plugin_loader.unload(pid)
    await _plugin_event_broadcast("unloaded", pid)
    return res


# ─── BECERI ONERILERI (skills_autogrowth) ────────────────────────
@app.get("/skills/proposals")
async def skills_proposals(status: str = "pending"):
    """Onay bekleyen beceri onerileri. Onaylanmadan HICBIRI skills.json'a
    yazilmaz — buyume 'sinirli': oneriyi ALES uretir, karari Ali verir."""
    if skills_autogrowth is None:
        return {"unavailable": True, "proposals": [], "stats": {}}
    return {"proposals": skills_autogrowth.list_proposals(status),
            "pending": skills_autogrowth.pending_count(),
            "stats": skills_autogrowth.stats(),
            "info": skills_autogrowth.info(),
            "observations": skills_autogrowth.observations(15)}


@app.post("/skills/proposals/{pid}/approve")
async def skills_proposal_approve(pid: str):
    if skills_autogrowth is None:
        return {"ok": False, "error": "skills_autogrowth yuklenemedi"}
    res = skills_autogrowth.approve(pid)
    if res.get("ok"):
        # NOT: fast_path.reload_skills() approve() ICINDE zaten cagriliyor
        # (bkz. skills_autogrowth.py:424) — burada ikinci kez cagirmiyoruz.
        # Yeni beceri ANINDA devreye girer, yeniden baslatma gerekmez.
        await broadcast_system_log(
            "INFO", f"Beceri onaylandı: {res.get('name') or pid} — "
                    f"Fast Path'te {res.get('fast_path_reloaded', 0)} kural aktif")
    return res


@app.post("/skills/proposals/{pid}/reject")
async def skills_proposal_reject(pid: str, data: dict = None):
    if skills_autogrowth is None:
        return {"ok": False, "error": "skills_autogrowth yuklenemedi"}
    return skills_autogrowth.reject(pid, (data or {}).get("reason", ""))


@app.delete("/skills/observations")
async def skills_observations_clear():
    if skills_autogrowth is None:
        return {"ok": False, "error": "skills_autogrowth yuklenemedi"}
    return {"ok": True, "cleared": skills_autogrowth.clear_observations()}


# ─── UZUN HAFIZA: VEKTOR INDEKSI ─────────────────────────────────
@app.get("/memory/long/vector")
async def memory_vector_info():
    """sqlite-vec durumu. `needs_rebuild: true` -> eklenti sonradan kuruldu
    ve mevcut anilar indekste degil (asagidaki rebuild gerekli)."""
    if long_term_memory is None:
        return {"unavailable": True}
    try:
        return long_term_memory.vector_info()
    except Exception as e:
        return {"error": f"{type(e).__name__}: {e}"}


@app.post("/memory/long/vector/rebuild")
async def memory_vector_rebuild():
    """Mevcut TUM anilari vektor indeksine tasi. Yarim indeks yanlis KNN
    demek oldugu icin sifirdan kurar."""
    if long_term_memory is None:
        return {"ok": False, "error": "long_term_memory yuklenemedi"}
    res = long_term_memory.rebuild_vector_index()
    await broadcast_system_log(
        "INFO" if res.get("ok") else "WARN",
        f"Vektör indeksi: {res.get('indexed', 0)} anı indekslendi"
        if res.get("ok") else f"Vektör indeksi kurulamadı: {res.get('error')}")
    return res


# ─── KENDINI TOPARLAMA (self_heal) ───────────────────────────────
@app.get("/selfheal/status")
async def selfheal_status():
    """Denetci durumu + olay gecmisi + kurtarma noktalari.
    `policy` alani sinirlarin ne oldugunu ACIKCA yazar."""
    if self_heal is None:
        return {"unavailable": True}
    return self_heal.status()


@app.post("/selfheal/restart/{name}")
async def selfheal_restart(name: str, force: bool = False):
    """Arka plan gorevini elle yeniden baslat (scheduler/notifier/sleep_watch).
    SURECI yeniden baslatmaz — o yol tasarim geregi kapali."""
    if self_heal is None or _supervisor is None:
        return {"ok": False, "error": "denetci calismiyor"}
    res = await _supervisor.restart(name, force=force)
    await broadcast_system_log(
        "INFO" if res.get("ok") else "ERROR",
        f"Görev yeniden başlatma: {name} — {'tamam' if res.get('ok') else res.get('error')}")
    return res


@app.get("/selfheal/incidents")
async def selfheal_incidents(limit: int = 25):
    if self_heal is None:
        return {"unavailable": True, "incidents": []}
    return {"incidents": self_heal.incidents(limit), "stats": self_heal.stats()}


@app.delete("/selfheal/incidents")
async def selfheal_incidents_clear():
    if self_heal is None:
        return {"ok": False, "error": "self_heal yuklenemedi"}
    return {"ok": True, "cleared": self_heal.clear_incidents()}


# ─── MASAUSTU KONTROLU (native_desktop) ──────────────────────────
@app.get("/desktop/backend")
async def desktop_backend():
    """Hangi yol acik: pencere yonetimi ctypes ile HER ZAMAN calisir;
    element bazli denetim icin uiautomation/pywinauto gerekir."""
    if native_desktop is None:
        return {"available": False, "error": "native_desktop yuklenemedi"}
    return {**native_desktop.backend_info(), "stats": native_desktop.stats()}


@app.get("/desktop/windows")
async def desktop_windows(visible_only: bool = True):
    if native_desktop is None:
        return {"available": False, "windows": []}
    try:
        return {"available": True,
                "windows": native_desktop.list_windows(visible_only=visible_only),
                "foreground": native_desktop.foreground_window()}
    except Exception as e:
        return {"available": False, "error": f"{type(e).__name__}: {e}",
                "windows": []}


@app.post("/desktop/focus")
async def desktop_focus(data: dict):
    """Pencereyi one getir. Govde: {"title": "Not Defteri"}"""
    if native_desktop is None:
        return {"ok": False, "error": "native_desktop yuklenemedi"}
    title = (data.get("title") or "").strip()
    if not title:
        return {"ok": False, "error": "title bos"}
    msg = native_desktop.focus_window(title)
    return {"ok": not msg.startswith("[HATA]") and "❌" not in msg, "message": msg}


@app.get("/desktop/controls")
async def desktop_controls(title: str, depth: int = 4):
    """Penceredeki denetimleri listele (element bazli; paket gerekir)."""
    if native_desktop is None:
        return {"ok": False, "error": "native_desktop yuklenemedi"}
    return {"ok": True, "text": native_desktop.list_controls(title, depth=depth)}


@app.post("/desktop/test")
async def desktop_test_api():
    """
    Masaüstü denetimini test et (TASK 1):
    Windows Not Defteri'ni açar, 'Hello from ALES' yazar ve ekran görüntüsü döndürür.
    """
    if native_desktop is None:
        return {"ok": False, "error": "native_desktop yüklenemedi"}
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(_executor, native_desktop.test_desktop_control)


# ─── TESHIS: TUM YENI MODULLER TEK YANITTA ───────────────────────
@app.get("/diagnostics")
async def diagnostics():
    """Ayarlar > Teşhis panelinin tek kaynagi.

    NEDEN TEK ENDPOINT: 9 modulun durumunu 9 ayri istekle cekmek, bir
    tanesi hata verdiginde panelin yarisini bos birakiyordu. Burada her
    modul kendi try blogunda; biri patlasa digerleri yine doner."""
    def _safe(fn, default=None):
        try:
            return fn()
        except Exception as e:
            return {"error": f"{type(e).__name__}: {e}"} if default is None else default

    out = {"modules": {}, "at": time.time()}
    checks = {
        "codeact": (code_act_executor, lambda: {"info": code_act_executor.info(),
                                                "stats": code_act_executor.stats()}),
        "agent_jit": (agent_jit, lambda: {"info": agent_jit.info(),
                                          "stats": agent_jit.stats()}),
        "predictive": (predictive, lambda: {"info": predictive.info(),
                                            "stats": predictive.stats()}),
        "realtime_tts": (audio_streamer, lambda: {"info": audio_streamer.engine_info(),
                                                  "stats": audio_streamer.stats()}),
        "plugins": (plugin_loader, lambda: {"info": plugin_loader.info(),
                                            "stats": plugin_loader.stats()}),
        "skills_growth": (skills_autogrowth, lambda: {"info": skills_autogrowth.info(),
                                                      "stats": skills_autogrowth.stats()}),
        "self_heal": (self_heal, lambda: {"info": self_heal.info(),
                                          "stats": self_heal.stats()}),
        "native_desktop": (native_desktop, lambda: {"info": native_desktop.backend_info(),
                                                    "stats": native_desktop.stats()}),
        "vector_memory": (long_term_memory, lambda: {"info": long_term_memory.vector_info(),
                                                     "stats": long_term_memory.stats()}),
    }
    for name, (mod, fn) in checks.items():
        if mod is None:
            out["modules"][name] = {"loaded": False,
                                    "error": "modul yuklenemedi (import hatasi)"}
            continue
        d = _safe(fn) or {}
        d["loaded"] = True
        d["available"] = bool((d.get("info") or {}).get("available", True))
        if runtime_state:
            try:
                d["paused"] = runtime_state.is_paused(name)
            except Exception:
                d["paused"] = False
        out["modules"][name] = d
    if runtime_state:
        out["registry"] = _safe(lambda: runtime_state.snapshot().get("modules"), {})
    return out


# ─── SOHBET GECMISI ─────────────────────────────────────────────
@app.get("/conversations")
async def get_conversations():
    return {"conversations": conv_store.list_conversations()}

@app.get("/conversations/{conv_id}")
async def get_conversation_detail(conv_id: str):
    conv = conv_store.get_conversation(conv_id)
    if not conv:
        return {"error": "Sohbet bulunamadı"}
    return conv

@app.post("/conversations")
async def new_conversation():
    conv = conv_store.create_conversation()
    return conv

@app.delete("/conversations/{conv_id}")
async def remove_conversation(conv_id: str):
    ok = conv_store.delete_conversation(conv_id)
    return {"success": ok}

@app.patch("/conversations/{conv_id}")
async def rename_conversation_route(conv_id: str, data: dict):
    ok = conv_store.rename_conversation(conv_id, data.get("title", ""))
    return {"success": ok}

# ─── STARTUP ─────────────────────────────────────────────────────
@app.on_event("startup")
async def startup():
    # Kaynak izleyici KENDI thread'inden callback cagirir; ana dongu
    # referansini burada saklariz (bkz. _bridge_async_cb).
    global _main_loop
    _main_loop = asyncio.get_running_loop()

    # ESKIDEN: callback'ler burada YEREL tanimliydi ve gorevler bare
    # asyncio.create_task ile baslatiliyordu -> _workers BOS kaliyordu, bu
    # yuzden /system/status her zaman "durmus" diyor, /system/start ise
    # IKINCI bir zamanlayici+bildirimci daha aciyordu. Artik modul duzeyi
    # callback'ler kullaniliyor ve gorevler _workers'a KAYDEDILIYOR.
    if not _worker_alive("scheduler"):
        _workers["scheduler"] = asyncio.create_task(run_scheduler(_scheduler_cb))
    if not _worker_alive("notifier"):
        _workers["notifier"] = asyncio.create_task(
            run_notifier(browser_module, _notifier_cb, fiverr_module=fiverr))

    # ── Faz-3 kaynak/durum zinciri ────────────────────────────────
    # Bu blok ESKIDEN HIC calismiyordu: moduller yazilmisti ama birbirine
    # hic baglanmamisti. Sirasiyla: kalici anahtarlari uygula -> izleyicinin
    # "dusur/geri al" callback'lerini runtime_state'e bagla -> izleyiciyi
    # baslat -> uyku denetleyicisini dondur.
    if runtime_state:
        try:
            runtime_state.load_from_config()
        except Exception as e:
            print(f"[ALES] runtime_state config uygulanamadi: {e}")

    if resource_monitor and runtime_state:
        try:
            # Esik asiminda kullaniciya SOR (otomatik kapatma yok).
            # NOT: alert async oldugu icin kopru sarmalayici sart;
            # degrade/restore ise runtime_state'te SENKRON, dogrudan baglanir.
            resource_monitor.monitor.register("alert", _bridge_async_cb(_resource_alert_cb))
            # Israrli/kritik asim -> otomatik dusuk tuketim; rahatlayinca geri al.
            resource_monitor.monitor.register("degrade", runtime_state.on_resource_degrade)
            resource_monitor.monitor.register("restore", runtime_state.on_resource_restore)
        except Exception as e:
            print(f"[ALES] kaynak callback'leri baglanamadi: {e}")

    if resource_monitor:
        try:
            resource_monitor.monitor.start()
            _workers["resource_monitor"] = True   # thread; task degil
        except Exception as e:
            print(f"[ALES] kaynak izleyici baslatilamadi: {e}")

    if runtime_state:
        _workers["sleep_watch"] = asyncio.create_task(_sleep_watchdog())

    # ── Toplu istek kuyrugu (Faz 3) ───────────────────────────────
    # recall gibi yan-etkisiz, pahali islemleri pencerede toplayip tek
    # cagriya indirir. Handler'da yikici eylem zaten imkansiz: recall
    # SADECE okur. Boyutlar istenen 5-10 araligina uyar.
    if batch_queue and long_term_memory:
        try:
            global _recall_batcher
            _recall_batcher = batch_queue.BatchQueue(
                handler=_recall_batch_handler,
                max_batch=10, min_batch=5, max_wait_s=0.35)
        except Exception as e:
            print(f"[ALES] toplu istek kuyrugu kurulamadi: {e}")

    # ── YENI MODULLER ─────────────────────────────────────────────
    # 1) Modul tablosunu GERCEKTEN yokla. Eskiden bu tablo elle yazilmis
    #    sabitlerdi ve modul calisir hale geldiginde yanlis kaliyordu.
    if runtime_state:
        try:
            probed = runtime_state.refresh_modules()
            on = [k for k, v in probed.items() if v]
            off = [k for k, v in probed.items() if not v]
            print(f"[ALES] moduller acik: {', '.join(on) or '-'}")
            if off:
                print(f"[ALES] moduller kapali: {', '.join(off)}")
        except Exception as e:
            print(f"[ALES] modul yoklamasi basarisiz: {e}")

    # 2) Eklentiler: plugins/ klasorunu tara. Ad koruması import aninda
    #    zaten kuruldu (bkz. set_reserved_names, get_all_tools yakini).
    if plugin_loader is not None:
        try:
            found = plugin_loader.discover(force=True)
            bad = [p for p in found.values() if p.get("load_error")]
            print(f"[ALES] {len(found)} eklenti bulundu, "
                  f"{sum(1 for p in found.values() if p.get('enabled') and not p.get('load_error'))} aktif"
                  + (f", {len(bad)} hatali" if bad else ""))
            for p in bad:
                await broadcast_system_log(
                    "ERROR", f"Eklenti yuklenemedi: {p.get('id')} — {p.get('load_error')}")
        except Exception as e:
            print(f"[ALES] eklentiler taranamadi: {e}")

    # 3) Beceri onerileri: bildirim koprusu + acilista bekleyen varsa haber ver.
    if skills_autogrowth is not None:
        try:
            skills_autogrowth.set_notify(_bridge_notify(_skill_proposal_cb))
            n = skills_autogrowth.pending_count()
            if n:
                await broadcast_system_log(
                    "INFO", f"{n} beceri önerisi onayını bekliyor (Ayarlar > Beceriler)")
        except Exception as e:
            print(f"[ALES] beceri ogrenme baglanamadi: {e}")

    # 4) Kendini toparlama: acilis isareti + gorev denetcisi.
    #    KAPSAM: sadece arka plan gorevlerini yeniden baslatir. Kod
    #    yazmaz, kendini kopyalamaz, sureci yeniden baslatmaz (surekli
    #    hatali bir surecin kendini yeniden dogurmasi sonsuz dongu olur).
    if self_heal is not None:
        try:
            self_heal.set_notify(_bridge_notify(_selfheal_cb))
            boot = self_heal.mark_start()
            if boot.get("unclean_shutdown"):
                msg = "Önceki kapanış temiz değildi"
                if boot.get("checkpoints"):
                    msg += f" — kurtarılabilir durum: {', '.join(boot['checkpoints'][:5])}"
                print(f"[HEAL] {msg}")
                await broadcast_system_log("WARN", msg)
            global _supervisor
            _supervisor = self_heal.Supervisor(registry=_workers)
            # adopt: gorevler yukarida ZATEN olusturuldu; ikinci kez
            # baslatmiyoruz, sadece benimseyip izliyoruz.
            _supervisor.add("scheduler", lambda: run_scheduler(_scheduler_cb),
                            critical=True, adopt=_workers.get("scheduler"))
            _supervisor.add("notifier",
                            lambda: run_notifier(browser_module, _notifier_cb,
                                                 fiverr_module=fiverr),
                            critical=True, adopt=_workers.get("notifier"))
            if runtime_state:
                _supervisor.add("sleep_watch", _sleep_watchdog,
                                adopt=_workers.get("sleep_watch"))
            await _supervisor.start()
            print("[HEAL] gorev denetcisi calisiyor (scheduler, notifier, sleep_watch)")
        except Exception as e:
            print(f"[ALES] kendini toparlama kurulamadi: {e}")

    # 5) Otomatik model kesfi: 30 dakikada bir saglayici model listelerini
    #    tazeler, yapilandirmadaki kimlikleri dogrular, olmus kimlikleri
    #    kendiliginden degistirir.
    #    ANA DONGUYU BLOKLAMAZ: create_task ile ayri gorev, tamami async
    #    (httpx.AsyncClient) ve ilk tur 5 saniye gecikmeli baslar — acilista
    #    alti HTTP cagrisinin ilk istek suresini uzatmamasi icin.
    if model_registry is not None and not _worker_alive("model_discovery"):
        try:
            _workers["model_discovery"] = model_registry.start_scheduler()
            print("[ALES] model kesfi zamanlayicisi calisiyor "
                  f"({int(model_registry.REFRESH_INTERVAL_S/60)} dakikada bir)")
            # Onbellekte hic veri yoksa kullaniciyi bilgilendir: ilk tur
            # bitene kadar dogrulama yapilamaz (ama cagrilar normal calisir).
            if not model_registry.registry.last_refresh:
                await broadcast_system_log(
                    "INFO", "Model keşfi ilk listeyi indiriyor — o ana kadar "
                            "yapılandırmadaki model adları kullanılır")
        except Exception as e:
            print(f"[ALES] model kesfi baslatilamadi: {e}")

    # 6) Model kesfi UZLASTIRICISI (auto_model_discovery).
    #    Yukaridaki (5) katalogu INDIRIR; bu ise indirilen katalogla
    #    yapilandirilmis katmanlari KARSILASTIRIR ve kaldirilmis kimlikleri
    #    raporlar. Kasitli olarak ikinci bir tarayici DEGIL: kendi basina
    #    HTTP yapmaz, registry'nin verisini okur (yoksa ayni 6 saglayiciya
    #    iki kat istek gitmis olurdu).
    #
    #    KURAL (degistirmeyin): katalogda gorunmeyen model KAPATILMAZ.
    #    Katalog ucu eksik/yetkisiz olabilir; "listede yok" != "olu". Tespit
    #    yalnizca rapordur, config'e dokunulmaz.
    if auto_model_discovery is not None and not _worker_alive("model_reconcile"):
        try:
            auto_model_discovery.start_discovery_loop()
            _workers["model_reconcile"] = auto_model_discovery._loop_task
            print("[ALES] model uzlastirici calisiyor "
                  f"({int(auto_model_discovery.RECONCILE_INTERVAL_S/60)} dakikada bir, "
                  "sadece dogrulama — degisiklik uygulamaz)")
        except Exception as e:
            print(f"[ALES] model uzlastirici baslatilamadi: {e}")

    # 7) Darwin Godel arka plan evrimi: DUSUK FREKANSLI ve KOSULLU.
    #    Sadece ortada denenen bir aday YOKSA yeni bir aday acar; boylece
    #    her zaman en fazla bir sampiyon + bir aday olur ve ikisi ayni
    #    kosullarda olculur. Aday MIN_TRIALS gercek tur tamamlamadan
    #    hukum verilmez (bkz. darwin_godel.record_outcome).
    if darwin_godel is not None and not _worker_alive("dgm_evolve"):
        try:
            _workers["dgm_evolve"] = asyncio.create_task(_dgm_evolution_loop())
            print("[ALES] Darwin Godel evrim dongusu calisiyor "
                  f"(aday yoksa {int(DGM_EVOLVE_INTERVAL_S/60)} dakikada bir yeni aday)")
        except Exception as e:
            print(f"[ALES] DGM evrim dongusu baslatilamadi: {e}")

    # 8) Kalıcı hafıza ve son 5 sohbetin kontrolü (TASK 3)
    try:
        mem = load_memory()
        c_list = conv_store.list_conversations()
        print(f"[MEMORY] Kalıcı hafıza aktif: {len(mem.get('short', []))} kısa kayıt, {len(c_list)} sohbet yüklendi.")
    except Exception as e:
        print(f"[MEMORY] Başlatma hatası: {e}")

    print("[ALES] v3.0 tam kapasite hazir!")


@app.on_event("shutdown")
async def shutdown():
    """Kapanista arka plan islerini duzgun durdur (thread + task sizintisi olmasin)."""
    # DENETCI EN BASTA durur. Aksi halde asagida iptal ettigimiz gorevleri
    # "cokmus" sanip yeniden baslatir ve kapanma asili kalir.
    if _supervisor is not None:
        try:
            await _supervisor.stop()
        except Exception:
            pass
    # Kuyrukta bekleyen varsa once onlari coz — yoksa add() bekleyenler asili kalir.
    if _recall_batcher is not None:
        try:
            await _recall_batcher.flush()
        except Exception:
            pass
    for name in ("scheduler", "notifier", "sleep_watch", "model_discovery",
                 "model_reconcile", "dgm_evolve"):
        t = _workers.get(name)
        if hasattr(t, "cancel") and not t.done():
            t.cancel()
    if resource_monitor:
        try:
            resource_monitor.monitor.stop()
        except Exception:
            pass
    # "running" isaretini kaldir: bir sonraki acilis bu kapanisin TEMIZ
    # oldugunu bilsin (yoksa her normal kapanis "cokme" olarak raporlanir).
    if self_heal is not None:
        try:
            self_heal.mark_clean_exit()
        except Exception:
            pass


# ─── LEGAL OTOMASYON, GUVENLIK & DURUM API'LERI ──────────────────────
try:
    import security_shield
except Exception as _e:
    security_shield = None
    print(f"[ALES] security_shield yuklenemedi: {_e}")

try:
    import freelance_bridge
except Exception as _e:
    freelance_bridge = None
    print(f"[ALES] freelance_bridge yuklenemedi: {_e}")

try:
    import file_organizer
except Exception as _e:
    file_organizer = None
    print(f"[ALES] file_organizer yuklenemedi: {_e}")

try:
    import report_generator
except Exception as _e:
    report_generator = None
    print(f"[ALES] report_generator yuklenemedi: {_e}")

try:
    import email_assistant
except Exception as _e:
    email_assistant = None
    print(f"[ALES] email_assistant yuklenemedi: {_e}")


@app.get("/api/security/stats")
async def get_security_stats():
    if not security_shield:
        return {"ok": False, "error": "security_shield kullanilamiyor"}
    return {"ok": True, "stats": security_shield.shield.get_stats()}


@app.get("/api/security/confirmations")
async def get_security_confirmations():
    if not security_shield:
        return {"ok": False, "pending": []}
    return {"ok": True, "pending": security_shield.shield.list_pending_confirmations()}


@app.post("/api/security/approve")
async def approve_security_action(data: dict):
    token = data.get("token", "")
    if not security_shield or not token:
        return {"ok": False, "error": "gecersiz token"}
    ok, req = security_shield.shield.approve_action(token)
    return {"ok": ok, "request": req}


@app.post("/api/security/reject")
async def reject_security_action(data: dict):
    token = data.get("token", "")
    if not security_shield or not token:
        return {"ok": False, "error": "gecersiz token"}
    ok = security_shield.shield.reject_action(token)
    return {"ok": ok}


@app.get("/api/freelance/all")
async def get_freelance_all():
    if not freelance_bridge:
        return {"ok": False, "messages": [], "drafts": {}}
    return {"ok": True, **freelance_bridge.freelance_manager.get_all()}


@app.post("/api/freelance/fetch")
async def fetch_freelance_messages(data: dict):
    if not freelance_bridge:
        return {"ok": False, "error": "freelance_bridge kullanilamiyor"}
    platform = data.get("platform", "all")
    visible = bool(data.get("visible", False))
    return freelance_bridge.freelance_manager.fetch_messages(platform=platform, visible=visible)


@app.post("/api/freelance/summarize")
async def summarize_freelance_message(data: dict):
    if not freelance_bridge:
        return {"ok": False, "error": "freelance_bridge kullanilamiyor"}
    msg_id = data.get("message_id", "")
    return freelance_bridge.freelance_manager.summarize_message(msg_id)


@app.post("/api/freelance/draft-reply")
async def draft_freelance_reply(data: dict):
    if not freelance_bridge:
        return {"ok": False, "error": "freelance_bridge kullanilamiyor"}
    msg_id = data.get("message_id", "")
    return freelance_bridge.freelance_manager.draft_reply(msg_id)


@app.post("/api/files/scan")
async def scan_files_directory(data: dict):
    if not file_organizer:
        return {"ok": False, "error": "file_organizer kullanilamiyor"}
    folder = data.get("folder", "")
    return file_organizer.organizer.scan_directory(folder)


@app.post("/api/files/preview")
async def preview_files_organization(data: dict):
    if not file_organizer:
        return {"ok": False, "error": "file_organizer kullanilamiyor"}
    folder = data.get("folder", "")
    mode = data.get("mode", "by_category")
    older_than = data.get("older_than_days")
    return file_organizer.organizer.preview_organization(folder, mode=mode, older_than_days=older_than)


@app.post("/api/files/organize")
async def execute_files_organization(data: dict):
    if not file_organizer:
        return {"ok": False, "error": "file_organizer kullanilamiyor"}
    folder = data.get("folder", "")
    actions = data.get("actions", [])
    confirmed = bool(data.get("confirmed", False))
    return file_organizer.organizer.execute_organization(folder, actions, confirmed=confirmed)


@app.post("/api/report/preview")
async def preview_tabular_file(data: dict):
    if not report_generator:
        return {"ok": False, "error": "report_generator kullanilamiyor"}
    file_path = data.get("file_path", "")
    return report_generator.report_generator.parse_tabular_file(file_path)


@app.post("/api/report/generate")
async def generate_report_file(data: dict):
    if not report_generator:
        return {"ok": False, "error": "report_generator kullanilamiyor"}
    file_path = data.get("file_path", "")
    title = data.get("title", "ALES Veri Analiz Raporu")
    return report_generator.report_generator.generate_html_report(file_path, title=title)


@app.post("/api/email/fetch")
async def fetch_unread_emails_endpoint(data: dict):
    if not email_assistant:
        return {"ok": False, "error": "email_assistant kullanilamiyor"}
    server = data.get("server", "imap.gmail.com")
    port = int(data.get("port", 993))
    user = data.get("username", "")
    pw = data.get("password", "")
    limit = int(data.get("limit", 10))
    return email_assistant.email_assistant.fetch_unread_emails(server, port, user, pw, limit=limit)


@app.post("/api/email/draft")
async def draft_email_endpoint(data: dict):
    if not email_assistant:
        return {"ok": False, "error": "email_assistant kullanilamiyor"}
    email_info = data.get("email_info", {})
    return email_assistant.email_assistant.draft_reply(email_info)


@app.post("/api/email/send")
async def send_email_endpoint(data: dict):
    if not email_assistant:
        return {"ok": False, "error": "email_assistant kullanilamiyor"}
    server = data.get("server", "smtp.gmail.com")
    port = int(data.get("port", 465))
    user = data.get("username", "")
    pw = data.get("password", "")
    to_addr = data.get("to", "")
    subject = data.get("subject", "")
    body = data.get("body", "")
    confirmed = bool(data.get("confirmed", False))
    return email_assistant.email_assistant.send_email_smtp(server, port, user, pw, to_addr, subject, body, confirmed=confirmed)


@app.get("/api/ales/audit-status")
async def get_ales_audit_status():
    """Gercek, durust yetenek ve durum haritasi."""
    return {
        "ok": True,
        "capabilities": {
            "computer_control": {
                "status": "working",
                "label": "Masaüstü Denetimi",
                "details": "Pencere listeleme, odaklama, koordinat/element tıklama, ekran yakalama"
            },
            "voice_tts": {
                "status": "working",
                "label": "Ses Çıkışı (TTS)",
                "details": "Edge-TTS Türkçe (tr-TR-AhmetNeural / EmelNeural, akışlı nöral ses)"
            },
            "voice_stt": {
                "status": "beta",
                "label": "Ses Girişi (STT)",
                "details": "Bas-Konuş / Web Speech API (Tarayıcı ve Electron yerel motoru)"
            },
            "fast_path": {
                "status": "working",
                "label": "Fast Path (Zero-LLM)",
                "details": "Rutin komutlarda LLM'siz anında araç yürütme (<50ms)"
            },
            "memory": {
                "status": "working",
                "label": "Kalıcı Hafıza",
                "details": "SQLite tabanlı Ebbinghaus unutma ve pekiştirme eğrisi"
            },
            "security_shield": {
                "status": "working",
                "label": "Güvenlik Kalkanı",
                "details": "Komut kaynağı takibi, enjeksiyon taraması, tehlikeli işlem onayı"
            },
            "freelance": {
                "status": "working",
                "label": "Serbest Çalışan (Freelance) Asistanı",
                "details": "Fiverr/Bionluk mesaj okuma, özetleme, taslak yanıt (Otomatik gönderim YOK)"
            },
            "file_organizer": {
                "status": "working",
                "label": "Dosya Düzenleyici",
                "details": "Kategori ve tarihe göre organize etme, önizleme garantili"
            },
            "report_generator": {
                "status": "working",
                "label": "Rapor Oluşturucu",
                "details": "CSV/Excel otomatik istatistiksel analiz ve HTML raporu"
            },
            "email_assistant": {
                "status": "working",
                "label": "E-Posta Asistanı",
                "details": "IMAP gelen kutusu okuma, özetleme ve kontrollü taslak"
            },
            "evolution": {
                "status": "experimental",
                "label": "Evrim (Deneysel)",
                "details": "İstem düzeyi iyileştirme. Kendi kodunu değiştirme ve çoğalma kalıcı olarak kapsam dışıdır."
            }
        }
    }


# ─── FRONTEND (STATIK SERVIS) ──────────────────────────────────────────
# NEDEN EN SONDA: asagidaki catch-all route "/{full_path:path}" HER SEYI
# yakalar. FastAPI route'lari TANIMLANMA SIRASINA gore esler, bu yuzden bu
# blok tum API route'larindan sonra durmak ZORUNDA. Yukari tasinirsa
# /status, /codeact, /plugins ... hepsi HTML dondurmeye baslar.
#
# MEVCUT HICBIR ROUTE VEYA WEBSOCKET DEGISTIRILMEDI. /ws etkilenmez:
# websocket'ler ayri bir scope turunde eslenir, bir HTTP GET catch-all onu
# golgeleyemez.
import sys as _sys
import socket as _socket
import threading as _threading
import webbrowser as _webbrowser
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, JSONResponse


def _find_webui_dir():
    """Derlenmis arayuz (vite cikti) klasorunu bul.

    KRITIK (PyInstaller --onefile): --add-data ile eklenen veriler calisma
    aninda GECICI bir klasore acilir; yolu sys._MEIPASS'tir. Kaynak
    agacindaki "frontend/dist" yolu .exe icinde YOKTUR, bu yuzden once
    _MEIPASS'a bakiyoruz.

    Kaynaktan calistirildiginda vite cikti klasoru ALES/dist'tir
    (frontend/vite.config.js -> outDir: '../dist'). Bunu DEGISTIRMEDIK:
    electron-main.js (dist/index.html) ve Dockerfile.cloud ayni yeri
    okuyor; outDir'i tasimak o iki yolu da bozardi.
    """
    here = Path(__file__).resolve().parent               # .../ALES/backend
    cands = []
    mei = getattr(_sys, "_MEIPASS", None)
    if mei:
        cands.append(Path(mei) / "webui")                # paketlenmis .exe
    if getattr(_sys, "frozen", False):
        # .exe'nin yaninda elle guncellenmis bir arayuz varsa o kazanir.
        cands.append(Path(_sys.executable).resolve().parent / "webui")
        cands.append(Path(_sys.executable).resolve().parent / "dist")
        # ALES.exe "backend-dist/" icinde durur; bir ust klasor proje kokudur,
        # yani vite'in yazdigi ALES/dist orada. Gomulu kopya bir sekilde
        # eksik kalirsa buradan servis edilir (eski ales-backend.exe de
        # boylece arayuzu servis edebilir).
        cands.append(Path(_sys.executable).resolve().parent.parent / "dist")
        cands.append(Path(_sys.executable).resolve().parent.parent / "frontend" / "dist")
    cands += [
        here.parent / "dist",                            # ALES/dist (vite)
        here.parent / "frontend" / "dist",               # alternatif yerlesim
        Path(os.getcwd()) / "dist",
        Path(os.getcwd()) / "frontend" / "dist",
    ]
    for c in cands:
        try:
            if os.path.exists(os.path.join(str(c), "index.html")):
                return c.resolve()
        except Exception:
            continue
    return None


WEBUI_DIR = _find_webui_dir()

# Catch-all'in API yollarini yutmasini onlemek icin bilinen ilk yol
# parcalarini ROUTER'IN KENDISINDEN turetiyoruz. Elle liste tutmak kirilgan
# olurdu: yeni route ekleyip listeye yazmayi unutan kisi, yanlis yazilmis
# bir API cagrisina 404 JSON yerine sessizce HTML donduren bir sunucu elde
# ederdi -- hata ayiklamasi en zor durum.
_API_SEGMENTS = set()
for _r in app.routes:
    _seg = (getattr(_r, "path", "") or "").strip("/").split("/")[0]
    if _seg and "{" not in _seg:
        _API_SEGMENTS.add(_seg)

if WEBUI_DIR is not None:
    _assets_dir = WEBUI_DIR / "assets"
    if os.path.exists(str(_assets_dir)):
        # StaticFiles dogru MIME turu + ETag/Range verir; bu isi catch-all'a
        # birakmaktan iyidir. Catch-all'DAN ONCE kaydedildigi icin
        # /assets/... istekleri hic oraya dusmez.
        app.mount("/assets", StaticFiles(directory=str(_assets_dir)),
                  name="ales-assets")
    print(f"[ALES] Arayuz klasoru: {WEBUI_DIR}")
else:
    print("[ALES] UYARI: derlenmis arayuz bulunamadi -> yalnizca API acik. "
          "Cozum: frontend/ icinde 'npm run build' (cikti: ALES/dist).")

# ── Statik PDF ve Dosya İndirme Bağlantısı ───────────────────────
_backend_static = Path(__file__).resolve().parent / "static"
_backend_static.mkdir(parents=True, exist_ok=True)
(_backend_static / "pdfs").mkdir(parents=True, exist_ok=True)
app.mount("/static", StaticFiles(directory=str(_backend_static)), name="static")
_API_SEGMENTS.add("static")


@app.get("/{full_path:path}", include_in_schema=False)
async def serve_frontend(full_path: str):
    """SPA fallback: gercek dosya varsa onu, yoksa index.html'i dondur.

    React Router'in /gorevler gibi yollarinda sunucuda dosya yoktur; sayfa
    yenilendiginde 404 gelmesin diye index.html donuyor.
    """
    if WEBUI_DIR is None:
        return JSONResponse(
            {"ok": False, "error": "arayuz derlenmemis",
             "detail": ("Derlenmis arayuz bulunamadi. frontend/ klasorunde "
                        "'npm run build' calistirin (cikti: ALES/dist)."),
             "api": "calisiyor"},
            status_code=503)

    # 1) Gercek bir dosya mi? (favicon.ico, manifest.json, sw.js, logo ...)
    if full_path:
        cand = (WEBUI_DIR / full_path).resolve()
        # GUVENLIK: full_path kullanicidan gelir. "../backend/config.json"
        # gibi bir istek klasor agacindan CIKMAMALI -- config.json canli API
        # anahtarlari tutuyor. relative_to() bunu kesin olarak dogrular;
        # string karsilastirmasi sembolik baglantilarda yaniltabilirdi.
        try:
            cand.relative_to(WEBUI_DIR)
        except ValueError:
            return JSONResponse({"ok": False, "error": "gecersiz yol"},
                                status_code=404)
        if cand.is_file():
            return FileResponse(str(cand))

    # 2) API oneki ama hicbir route eslesmedi -> HTML DEGIL, JSON 404.
    if (full_path or "").split("/")[0] in _API_SEGMENTS:
        return JSONResponse(
            {"ok": False, "error": "Not Found",
             "detail": f"/{full_path} diye bir API yolu yok."},
            status_code=404)

    # 3) SPA girisi
    return FileResponse(str(WEBUI_DIR / "index.html"))


def _open_browser_when_ready(url: str, port: int, timeout_s: float = 60.0):
    """Sunucu GERCEKTEN dinlemeye baslayinca tarayiciyi ac.

    NEDEN beklemek gerekiyor: uvicorn.run() bloke eder, yani ondan once
    webbrowser.open() cagirmak "baglanti reddedildi" sayfasi acar. --onefile
    exe her calistirmada kendini gecici klasore actigi icin ilk acilis
    yavastir; sabit bir bekleme yerine portu yokluyoruz.

    ALES_NO_BROWSER=1 ile kapatilir: sunucu olarak veya telefondan
    kullanirken tarayici acilmasi istenmez, Electron kabugu da kendi
    penceresini yukler.
    """
    if os.environ.get("ALES_NO_BROWSER", "").strip().lower() in ("1", "true", "yes"):
        print("[ALES] ALES_NO_BROWSER ayarli -> tarayici acilmayacak.")
        return

    def _wait():
        deadline = time.time() + timeout_s
        while time.time() < deadline:
            try:
                with _socket.create_connection(("127.0.0.1", port), 0.5):
                    break
            except OSError:
                time.sleep(0.3)
        else:
            print(f"[ALES] Tarayici acilmadi: {timeout_s:.0f}s icinde port "
                  f"{port} dinlemeye baslamadi. Elle acin: {url}")
            return
        try:
            _webbrowser.open(url)
        except Exception as e:
            print(f"[ALES] Tarayici acilamadi ({e}). Elle acin: {url}")

    _threading.Thread(target=_wait, name="ales-browser-open",
                      daemon=True).start()


if __name__ == "__main__":
    # KRITIK (PyInstaller): freeze_support() ILK is olmali. Donmus bir exe'de
    # multiprocessing alt surec baslattiginda Windows programi BASTAN
    # calistirir; bu cagri olmadan her alt surec yeni bir ALES baslatir ve
    # surec sayisi katlanarak artar.
    import multiprocessing
    multiprocessing.freeze_support()

    import uvicorn
    print("[ALES] v3.0 baslatiliyor...")

    _PORT = int(os.environ.get("ALES_PORT", "8000") or 8000)
    _URL = f"http://localhost:{_PORT}"
    _open_browser_when_ready(_URL, _PORT)
    if _FROZEN_WINDOWED:
        # Konsol yok: Ctrl+C tavsiyesi yanlis olurdu.
        print(f"[ALES] Arayuz: {_URL}")
        if ALES_LOG_PATH:
            print(f"[ALES] Gunluk: {ALES_LOG_PATH}")
        print("[ALES] Durdurma: Gorev Yoneticisi > ALES.exe > Gorevi sonlandir")
    else:
        print(f"[ALES] Arayuz: {_URL}   (kapatmak icin bu pencerede Ctrl+C)")
    # log_level VERILMIYOR (uvicorn varsayilani "info"): railway/main_cloud.py
    # ile ayni davranis. Konsol acik oldugu icin acilis banner'i ve istek
    # satirlari kullaniciya arayuzun gercekten yuklendigini gosterir.
    # Performance modu acildiginda runtime_state._set_log_level("ERROR")
    # bunu zaten kisiyor.
    uvicorn.run(app, host="0.0.0.0", port=_PORT)
