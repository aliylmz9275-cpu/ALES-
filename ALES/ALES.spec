# -*- mode: python ; coding: utf-8 -*-
"""
ALES.spec — TEK DOSYA .exe (arayuz gomulu, Electron'a gerek yok)

Kullanim (proje kokunden):
    build_exe.bat
veya elle:
    npm run build:frontend
    pyinstaller ALES.spec --noconfirm --distpath backend-dist --workpath backend/build

CIKTI: backend-dist\\ALES.exe

── MEVCUT DERLEME ZINCIRINE DOKUNULMADI ────────────────────────────────
backend/ales-backend.spec + build.bat + electron-builder zinciri AYNEN
kaliyor; "release\\ALES Setup 3.0.0.exe" hala uretilebilir. Bu spec onun
YERINE degil, YANINA calisir:

  ales-backend.exe -> arayuzu Electron penceresi cizer   (iki parca)
  ALES.exe         -> arayuzu KENDI servis eder, tarayicida acilir (tek parca)

package.json > build.files icinde "!backend-dist/**" var ve extraResources
yalnizca "ales-backend.exe" adini veriyor; dolayisiyla bu yeni exe electron
kurulum dosyasina SIZMAZ (kurulum boyutu artmaz).
"""
import os
import importlib.util

from PyInstaller.utils.hooks import collect_all

# SPECPATH: PyInstaller'in spec dosyasina enjekte ettigi klasor yolu.
# NEDEN os.getcwd() DEGIL: pyinstaller baska bir klasorden cagrilirsa
# butun yollar sessizce yanlis olur ve exe eksik derlenir.
try:
    ROOT = SPECPATH                                              # noqa: F821
except NameError:
    ROOT = os.path.abspath(os.getcwd())
BACKEND = os.path.join(ROOT, "backend")

# ─── KONSOL PENCERESI ───────────────────────────────────────────────────
# False = sessiz arka plan uygulamasi (--noconsole): cift tiklayinca siyah
#         pencere ACILMAZ, yalnizca tarayici acilir. Istenen davranis bu.
# True  = siyah pencere acik kalir; acilis gunlugu canli akar ve sunucuyu
#         Ctrl+C ile durdurabilirsin. Bir sorunu teshis ederken bunu True
#         yapip yeniden derlemek en hizli yoldur.
#
# False'un iki bedeli var, ikisi de karsilandi:
#   1) Acilis gunlugu gorunmez  -> main.py._boot_streams() stdout/stderr'i
#      exe'nin yanindaki ALES_log.txt'ye baglar (konsolsuz derlemede
#      sys.stdout None'dir; print() sessizce yutulur ve tum tani bilgisi
#      kaybolurdu).
#   2) Ctrl+C ile durdurulamaz   -> Gorev Yoneticisi > ALES.exe > Gorevi
#      sonlandir. PID her oturumda gunluge yazilir.
CONSOLE = False

# ═══════════════════════════════════════════════════════════════════════
# 1) ARAYUZ VERISI
# ═══════════════════════════════════════════════════════════════════════
# vite ALES/dist'e yazar (frontend/vite.config.js -> outDir '../dist'),
# frontend/dist'e DEGIL. Pakete "webui" adiyla giriyor; calisma aninda
# main.py._find_webui_dir() once sys._MEIPASS/webui'ye bakar.
#
# NEDEN "dist" adiyla degil: PyInstaller da varsayilan olarak dist/'e yazar,
# yani ayni ad iki ayri anlama gelirdi. Dahasi vite.config.js'de
# emptyOutDir=true -- bir sonraki "npm run build" dist/ ICINI SILER.
# ALES.exe oraya konsaydi ilk frontend yeniden derlemesinde YOK OLURDU.
# Bu yuzden exe cikti klasoru backend-dist/ (build.bat ile ayni gelenek).
WEBUI_SRC = os.path.join(ROOT, "dist")
if not os.path.exists(os.path.join(WEBUI_SRC, "index.html")):
    raise SystemExit(
        "\n[ALES.spec] HATA: derlenmis arayuz yok.\n"
        "  Aranan : %s\n"
        "  Cozum  : cd frontend && npm run build\n"
        "           (kokten 'npm run build:frontend' bu makinede CALISMAZ:\n"
        "            node_modules\\.bin icinde vite.cmd yok, yalnizca\n"
        "            uzantisiz POSIX shim var -> cmd.exe onu goremez.)\n"
        % os.path.join(WEBUI_SRC, "index.html"))

datas = [(WEBUI_SRC, "webui")]
if os.path.exists(os.path.join(BACKEND, "static")):
    datas.append((os.path.join(BACKEND, "static"), "static"))
binaries = []
hiddenimports = []

# GUVENLIK: backend/config.json BILINCLI OLARAK pakete alinmiyor -- icinde
# canli API anahtarlari var, exe'yi baskasina verirsen anahtarlar da gider.
# Uygulama anahtarlari %APPDATA%\ALES\config.json'dan okur (config_manager).
#
# skills/ ve plugins/ de pakete alinmiyor: --onefile verisi her acilista
# GECICI bir klasore acilir ve kapanista silinir; bu iki klasor ise
# YAZILABILIR + KALICI olmali (ogrenilen beceriler, kullanici eklentileri).
# build_exe.bat onlari exe'nin YANINA kopyalar; skills_engine._skills_dir()
# ve plugin_loader._plugins_dir() zaten exe'nin yanindaki klasore bakiyor.

# ═══════════════════════════════════════════════════════════════════════
# 2) GIZLI IMPORTLAR
# ═══════════════════════════════════════════════════════════════════════
# uvicorn dongu/protokol modullerini calisma aninda METIN olarak import eder
# ("uvicorn.protocols.http.auto"). PyInstaller'in statik analizi bu cagriyi
# GOREMEZ -> exe sorunsuz derlenir ama acilista ModuleNotFoundError verip
# aninda kapanir. Bu liste o yuzden var.
hiddenimports += [
    "uvicorn.logging",
    "uvicorn.loops", "uvicorn.loops.auto", "uvicorn.loops.asyncio",
    "uvicorn.protocols",
    "uvicorn.protocols.http", "uvicorn.protocols.http.auto",
    "uvicorn.protocols.http.h11_impl",
    "uvicorn.protocols.websockets", "uvicorn.protocols.websockets.auto",
    "uvicorn.protocols.websockets.websockets_impl",
    "uvicorn.lifespan", "uvicorn.lifespan.on", "uvicorn.lifespan.off",
]

# backend/*.py TAMAMI -- elle liste TUTMUYORUZ.
# NEDEN: runtime_state.refresh_modules() modulleri
# importlib.import_module(ISIM) ile yukluyor (_PROBES tablosu), plugin_loader
# da benzerini yapiyor. Metin tabanli import PyInstaller'a gorunmez.
# Klasoru tarayarak listelemek "yeni modul yazdim, exe'de calismiyor"
# hatasini kokunden siler.
_backend_mods = []
for _f in sorted(os.listdir(BACKEND)):
    if not _f.endswith(".py"):
        continue
    if _f == "main.py" or _f.startswith(("test_", "verify_")):
        continue                    # main giris noktasi; test_*/verify_* dagitilmaz
    _backend_mods.append(_f[:-3])
hiddenimports += _backend_mods

# Ucuncu parti zorunlular (eskiden build.bat icinde elle sayiliyordu).
hiddenimports += [
    "concurrent.futures", "groq", "edge_tts", "pyautogui", "psutil",
    "httpx", "PIL", "selenium", "playwright", "pyperclip", "pytesseract",
    "mss", "websockets", "dotenv", "sqlite3", "encodings.idna",
    "pyscreeze", "pymsgbox", "pytweening", "comtypes", "uiautomation", "pywinauto",
    "reportlab", "markdown",
]

# ═══════════════════════════════════════════════════════════════════════
# 3) OPSIYONEL PAKETLER
# ═══════════════════════════════════════════════════════════════════════
# KURULU olani pakete ekle, kurulu OLMAYANI atla. Kurulu olmayan bir adi
# hiddenimports'a yazmak derlemeyi uyari yiginina cevirir ve kullanici
# uyariyi hata sanir. Kurulu olmayanlarda ilgili modul kendi yedegine duser
# ve UI > Teshis panelinde "yok" gorunur -- uygulama COKMEZ.


def _have(pkg: str) -> bool:
    try:
        return importlib.util.find_spec(pkg) is not None
    except Exception:
        return False


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
}
_missing = []
for _p in OPTIONAL:
    if _have(_p):
        hiddenimports.append(_p)
    else:
        _missing.append(_p)

# collect_all: yaninda veri dosyasi / DLL tasiyan paketler.
# Yalnizca KURULU olanlar icin cagriliyor.
for _p in ("edge_tts", "groq", "google.generativeai", "cerebras", "keyring",
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
        print("[ALES.spec] collect_all(%s) atlandi: %s" % (_p, _e))

print("[ALES.spec] arayuz          : %s" % WEBUI_SRC)
print("[ALES.spec] backend modulu  : %d adet" % len(_backend_mods))
if _missing:
    print("[ALES.spec] opsiyonel, KURULU DEGIL (exe'ye girmez, ALES yedege "
          "duser):")
    for _p in _missing:
        print("            - %-13s %s" % (_p, OPTIONAL[_p]))

# ═══════════════════════════════════════════════════════════════════════
# 4) HARIC TUTULANLAR (boyut kucultme)
# ═══════════════════════════════════════════════════════════════════════
# Hicbiri ALES tarafindan kullanilmiyor; PyInstaller bunlari baska paketlerin
# opsiyonel dallarindan "belki gerekir" diye toplayabiliyor.
#
# tkinter LISTEDE YOK (bilincli): main.py ucunda "import pyautogui" var,
# pyautogui ise pymsgbox + mouseinfo cekiyor ve ikisi de modul seviyesinde
# tkinter import ediyor. Haric tutmak ~12 MB kazandirir ama exe acilista
# ImportError verip aninda kapanabilir. Bu takas kotu bir takas.
excludes = [
    "matplotlib", "scipy", "pandas", "notebook", "IPython",
    "pytest", "sphinx", "PyQt5", "PyQt6", "PySide2", "PySide6", "wx",
]

_icon = os.path.join(ROOT, "assets", "icon.ico")
if not os.path.exists(_icon):
    _icon = None

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
    a.binaries,          # a.binaries + a.datas EXE'ye verilince --onefile
    a.datas,             # olur (COLLECT yok -> tek dosya).
    [],
    name="ALES",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    # UPX KAPALI (ales-backend.spec'te acikti, bilincli olarak degistirildi):
    # sikistirma hem virus tarayicilarinda yanlis pozitifi artirir hem de
    # exe her acilista once kendini acmak zorunda kaldigi icin baslangici
    # yavaslatir. Kazanilan disk alani bunu hak etmiyor.
    upx=False,
    upx_exclude=[],
    runtime_tmpdir=None,
    # Konsol penceresi: dosyanin BASINDAKI "CONSOLE" anahtari belirler.
    # Su an False -> sessiz arka plan uygulamasi; acilis gunlugu exe'nin
    # yanindaki ALES_log.txt'ye yazilir (main.py._boot_streams).
    console=CONSOLE,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=_icon,
)
