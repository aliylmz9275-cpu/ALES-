# -*- mode: python ; coding: utf-8 -*-
"""
ales-backend.spec — Electron kabugunun icinde calisan ARKA UC exe'si.

Bu spec, ALES.spec'in KARDESI ama ayni sey DEGIL:

  ales-backend.spec -> backend-dist\\ales-backend.exe
                       arayuzu YOK; Electron penceresi cizer.
                       package.json > extraResources bu adi bekliyor.
  ALES.spec         -> backend-dist\\ALES.exe
                       arayuz exe'nin ICINDE; tarayicida acilir.

── BU DOSYA NEDEN YENIDEN YAZILDI ──────────────────────────────────────
Eski surum hiddenimports listesini ELLE tutuyordu ve icinde yalnizca 9
arka uc modulu vardi (filesystem, tool_router, vision, tunnel,
config_manager, conversations, multi_agent, skills_engine, connectors).

Bu SESSIZ bir ariza uretiyordu: runtime_state.refresh_modules() ve
plugin_loader modulleri importlib.import_module(METIN) ile yukluyor.
Metinle yapilan import PyInstaller'in statik cozumlemesine GORUNMEZ.
Yani Faz 2-6'da yazilan 20 modulun (agent_jit, batch_inference,
token_optimizer, speculative_cache, mixture_of_agents, darwin_godel,
reflection_agent, self_evolution, adaptive_timeouts, versioned_config,
contextual_experience_replay, predictive, fast_path, native_desktop,
self_heal, code_act_executor, evo_cua_bridge, openclaw_bridge,
auto_model_discovery, model_registry) HICBIRI pakete girmiyordu.
Exe derleniyor, aciliyor, calisiyor gibi gorunuyor -- ama her yeni
yetenek "modul yuklenemedi" durumunda kaliyor ve bunu yalnizca
UI > Teshis panelinde kucuk bir yazi soyluyor.

Cozum ALES.spec ile ayni: klasoru TARA, elle liste TUTMA.

── IKINCI DUZELTME: collect_all('cerebras') ────────────────────────────
Eski surum kosulsuz collect_all('cerebras') cagiriyordu; cerebras bu
makinede KURULU DEGIL. collect_all kurulu olmayan bir paket icin hata
firlatir ve butun derleme durur. Artik once find_spec ile bakiliyor.

── UCUNCU DUZELTME: upx=True -> False ──────────────────────────────────
UPX sikistirma virus tarayicilarinda yanlis pozitifi artiriyor ve
electron-main.js'in en sik gorulen sikayeti tam olarak buydu (Defender
exe'yi karantinaya aliyor, uygulama "sessizce acilmiyor"). Kazanilan
disk alani bu riski hak etmiyor. ALES.spec'te de kapali.
"""
import os
import importlib.util

from PyInstaller.utils.hooks import collect_all

# SPECPATH: PyInstaller'in enjekte ettigi spec klasoru = backend/.
# os.getcwd() KULLANILMIYOR: pyinstaller baska bir klasorden cagrilirsa
# butun yollar sessizce yanlis olur ve exe eksik derlenir.
try:
    BACKEND = SPECPATH                                            # noqa: F821
except NameError:
    BACKEND = os.path.abspath(os.getcwd())
ROOT = os.path.dirname(BACKEND)

datas = []
binaries = []

# ═══════════════════════════════════════════════════════════════════════
# 1) UVICORN — metinle import edilen dongu/protokol modulleri
# ═══════════════════════════════════════════════════════════════════════
# uvicorn bunlari calisma aninda METIN olarak import eder
# ("uvicorn.protocols.http.auto"). Statik cozumleme goremez -> exe
# derlenir ama acilista ModuleNotFoundError verip aninda kapanir.
hiddenimports = [
    "uvicorn.logging",
    "uvicorn.loops", "uvicorn.loops.auto", "uvicorn.loops.asyncio",
    "uvicorn.protocols",
    "uvicorn.protocols.http", "uvicorn.protocols.http.auto",
    "uvicorn.protocols.http.h11_impl",
    "uvicorn.protocols.websockets", "uvicorn.protocols.websockets.auto",
    "uvicorn.protocols.websockets.websockets_impl",
    "uvicorn.lifespan", "uvicorn.lifespan.on", "uvicorn.lifespan.off",
    "routers", "routers.profiles", "routers.terminal", "routers.tools", "routers.chat",
    "chromadb",
]

# ═══════════════════════════════════════════════════════════════════════
# 2) BACKEND/*.py TAMAMI — elle liste TUTMUYORUZ
# ═══════════════════════════════════════════════════════════════════════
# Yukaridaki "BU DOSYA NEDEN YENIDEN YAZILDI" notunun uyguladigi yer.
# "yeni modul yazdim, exe'de calismiyor" hatasini kokunden siler.
_backend_mods = []
for _f in sorted(os.listdir(BACKEND)):
    if not _f.endswith(".py"):
        continue
    if _f == "main.py" or _f.startswith(("test_", "verify_", "diag_")):
        continue                # main giris noktasi; tani betikleri dagitilmaz
    _backend_mods.append(_f[:-3])
hiddenimports += _backend_mods

# ═══════════════════════════════════════════════════════════════════════
# 3) UCUNCU PARTI ZORUNLULAR
# ═══════════════════════════════════════════════════════════════════════
hiddenimports += [
    "concurrent.futures", "groq", "edge_tts", "pyautogui", "psutil",
    "httpx", "PIL", "selenium", "playwright", "pyperclip", "pytesseract",
    "mss", "websockets", "dotenv", "sqlite3", "encodings.idna",
    "pyscreeze", "pymsgbox", "pytweening", "comtypes", "uiautomation", "pywinauto",
    "reportlab", "markdown",
]

def _have(pkg: str) -> bool:
    try:
        return importlib.util.find_spec(pkg) is not None
    except Exception:
        return False


# ═══════════════════════════════════════════════════════════════════════
# 4) OPSIYONEL PAKETLER — kurulu olani ekle, olmayani ATLA
# ═══════════════════════════════════════════════════════════════════════
# Kurulu olmayan bir adi hiddenimports'a yazmak derlemeyi uyari yiginina
# cevirir; kullanici uyariyi hata sanar. Kurulu olmayanlarda ilgili modul
# kendi yedegine duser ve Teshis panelinde "yok" gorunur -- COKMEZ.
OPTIONAL = {
    "sqlite_vec":   "vektor hafiza -> yoksa Python kosinus taramasi",
    "keyring":      "kimlik saklama -> yoksa sifreli yerel dosya",
    "pynvml":       "GPU olcumu -> yoksa GPU alani bos gecer",
    "uiautomation": "masaustu denetim erisimi -> yoksa ctypes+user32",
    "pywinauto":    "masaustu denetim erisimi (alternatif)",
    "pyttsx3":      "cevrimdisi TTS -> yoksa edge-tts",
    "RealtimeTTS":  "akisli TTS -> yoksa edge-tts cumle akisi",
    "win32com":     "Office/COM otomasyonu -> yoksa atlanir",
    "cerebras":     "Cerebras saglayicisi -> yoksa diger saglayicilar",
    "comtypes":     "COM baglantilari -> uiautomation icin gerekli",
}
_missing = []
for _p in OPTIONAL:
    if _have(_p):
        hiddenimports.append(_p)
    else:
        _missing.append(_p)

# collect_all: yaninda veri dosyasi / DLL tasiyan paketler.
# KOSULLU: eskiden cerebras icin kosulsuz cagriliyordu ve kurulu
# olmadigi icin butun derlemeyi durduruyordu.
for _p in ("edge_tts", "groq", "google.genai", "google.generativeai", "cerebras", "keyring",
           "RealtimeTTS", "sqlite_vec", "pyautogui", "pyscreeze", "pymsgbox",
           "pytweening", "mss", "uiautomation", "comtypes", "pywinauto", "reportlab"):
    if not _have(_p.split(".")[0]):
        continue
    try:
        _d, _b, _h = collect_all(_p)
        datas += _d
        binaries += _b
        hiddenimports += _h
    except Exception as _e:
        print("[ales-backend.spec] collect_all(%s) atlandi: %s" % (_p, _e))

print("[ales-backend.spec] backend modulu : %d adet" % len(_backend_mods))
if _missing:
    print("[ales-backend.spec] opsiyonel, KURULU DEGIL (exe'ye girmez, "
          "ALES yedege duser):")
    for _p in _missing:
        print("            - %-13s %s" % (_p, OPTIONAL[_p]))

# ═══════════════════════════════════════════════════════════════════════
# 5) HARIC TUTULANLAR
# ═══════════════════════════════════════════════════════════════════════
# tkinter LISTEDE YOK (bilincli): pyautogui -> pymsgbox + mouseinfo
# zinciri modul seviyesinde tkinter import ediyor. Haric tutmak ~12 MB
# kazandirir ama exe acilista ImportError verip kapanabilir.
excludes = [
    "matplotlib", "scipy", "pandas", "notebook", "IPython",
    "pytest", "sphinx", "PyQt5", "PyQt6", "PySide2", "PySide6", "wx",
]

if os.path.exists(os.path.join(BACKEND, "skills.json")):
    datas.append((os.path.join(BACKEND, "skills.json"), "."))
if os.path.exists(os.path.join(BACKEND, "custom_skills")):
    datas.append((os.path.join(BACKEND, "custom_skills"), "custom_skills"))
if os.path.exists(os.path.join(BACKEND, "static")):
    datas.append((os.path.join(BACKEND, "static"), "static"))

a = Analysis(
    [os.path.join(BACKEND, "main.py")],
    pathex=[BACKEND, ROOT],        # kardes moduller (config_manager vb.)
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=excludes,
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name="ales-backend",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    # UPX KAPALI — yukaridaki "UCUNCU DUZELTME" notu.
    upx=False,
    upx_exclude=[],
    runtime_tmpdir=None,
    # console=False: Electron zaten pencereyi ciziyor, siyah konsol
    # penceresi GORUNMEMELI. main.py._boot_streams() stdout/stderr'i
    # exe'nin yanindaki gunluk dosyasina baglar, yoksa konsolsuz
    # derlemede sys.stdout None olur ve tum tani bilgisi kaybolur.
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=os.path.join(ROOT, "assets", "icon.ico")
         if os.path.exists(os.path.join(ROOT, "assets", "icon.ico")) else None,
)
