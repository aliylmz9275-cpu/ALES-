"""
native_desktop.py — Yerel Windows masaustu denetimi (uiautomation + pywinauto).

NEDEN: Bugun ALES masaustunu SADECE koordinatla suruyor (main.py click_at ->
pyautogui.click(x, y)). Koordinat kirilgan: pencere kayarsa, cozunurluk
degisirse veya DPI olceklemesi farkliysa tiklama yanlis yere gider ve bunu
anlamanin yolu yoktur. Buradaki yaklasim ELEMENT ADIYLA denetim: "Kaydet"
dugmesine, ekranda nerede olursa olsun, adiyla tiklanir.

ONEMLI TESPIT — kullanicinin istegindeki "desktopctl/nuphus importlarini
bunlarla degistir" maddesi icin: kod tabaninda desktopctl veya nuphus adinda
HICBIR import/dosya/referans YOK (grep ile dogrulandi). Yani degistirilecek
bir sey yoktu; bu modul mevcut pyautogui yolunu SILMEDEN yanina EKLENIYOR.
main.py'deki click_at/type_text/press_key oldugu gibi kaliyor (calisan
akislari bozmamak icin), yeni araclar bunlarin YANINDA sunuluyor.

MOTOR KATMANLARI (cagri aninda secilir, import aninda degil):
  1. uiautomation — pip install uiautomation   (KURULU DEGIL)
     Element agacinda gezinme, ada gore tiklama, metin okuma/yazma.
  2. pywinauto    — pip install pywinauto      (KURULU DEGIL)
     Aynı isi backend="uia" ile yapar; uiautomation yoksa yedek.
  3. ctypes/user32 — HER ZAMAN VAR, kurulum gerektirmez.
     Pencere listeleme / odaklama / buyutme / kapatma bununla calisir.
     Element seviyesinde is YAPAMAZ.

Yani iki paket kurulmasa bile pencere yonetimi calisir; element bazli
islemler "paket kurulu degil" der ve NASIL kurulacagini soyler — sessizce
basarisiz olmaz.

GUVENLIK / KAPSAM:
  - Bu modul kullanicinin KENDI makinesindeki pencereleri yonetir.
  - Otomasyonu bir uygulamadan GIZLEMEZ, tespit atlatma icermez.
  - close_window() WM_CLOSE gonderir (uygulama "kaydetmek ister misin?"
    diye sorabilir); process OLDURMEZ. TerminateProcess kaydedilmemis isi
    sessizce yok ederdi.
"""
import sys
import os
import ctypes
import threading
import time
from ctypes import wintypes

def _bundle_path(rel_path: str) -> str:
    """PyInstaller _MEIPASS veya normal dosya yolu çözücü."""
    base = getattr(sys, "_MEIPASS", os.path.dirname(os.path.abspath(__file__)))
    return os.path.join(base, rel_path)


# ─── OPSIYONEL BAGIMLILIKLAR ───────────────────────────────────────────
try:
    import uiautomation as _uia
except Exception:
    _uia = None

try:
    from pywinauto import Application as _PwaApp
    from pywinauto import Desktop as _PwaDesktop
except Exception:
    _PwaApp = None
    _PwaDesktop = None

try:
    import pythoncom as _pythoncom          # pywin32 ile gelir
except Exception:
    _pythoncom = None

try:
    import pygetwindow as _pgw              # pyautogui ile gelir
except Exception:
    _pgw = None

try:
    import pyautogui as _pag
    _pag.FAILSAFE = False
except Exception:
    _pag = None

# ─── SABITLER ──────────────────────────────────────────────────────────
MAX_WINDOWS = 60
MAX_CONTROLS = 200
DEFAULT_DEPTH = 3
WAIT_POLL_S = 0.25
WM_CLOSE = 0x0010
SW_RESTORE = 9
SW_MAXIMIZE = 3
SW_MINIMIZE = 6

_lock = threading.RLock()
_tls = threading.local()
_stats = {"calls": 0, "windows_listed": 0, "focus": 0, "clicks": 0,
          "text_set": 0, "text_read": 0, "failures": 0,
          "backend_used": None, "last_error": None}

# ─── DPI FARKINDALIĞI & KOORDİNAT ÖLÇEKLEME (TASK 1) ─────────────────
_dpi_scale = None

def get_dpi_scale() -> float:
    """Windows DPI ölçekleme katsayısını döner (örn. %100 -> 1.0, %125 -> 1.25, %150 -> 1.5)."""
    global _dpi_scale
    if _dpi_scale is not None:
        return _dpi_scale
    try:
        try:
            ctypes.windll.shcore.SetProcessDpiAwareness(2) # Per-monitor aware
        except Exception:
            try:
                ctypes.windll.user32.SetProcessDPIAware()
            except Exception:
                pass
        hdc = ctypes.windll.user32.GetDC(0)
        LOGPIXELSX = 88
        dpi = ctypes.windll.gdi32.GetDeviceCaps(hdc, LOGPIXELSX)
        ctypes.windll.user32.ReleaseDC(0, hdc)
        scale = round(dpi / 96.0, 2)
        _dpi_scale = scale if scale > 0 else 1.0
        print(f"[NATIVE_DESKTOP] DPI algılandı: {dpi} DPI (Ölçek: %{int(_dpi_scale*100)})")
    except Exception as e:
        print(f"[NATIVE_DESKTOP] DPI algılama hatası: {e}")
        _dpi_scale = 1.0
    return _dpi_scale

def scale_coords(x: int, y: int) -> tuple:
    """Ekran DPI ölçeklemesini hesaba katarak fiziksel piksel koordinatlarına dönüştürür."""
    scale = get_dpi_scale()
    return int(round(x * scale)), int(round(y * scale))

def click_at_scaled(x: int, y: int) -> str:
    """DPI farkındalığıyla koordinata tıklar."""
    try:
        scale = get_dpi_scale()
        sx, sy = scale_coords(x, y)
        if _pag is not None:
            _pag.click(sx, sy)
            return f"✅ ({x}, {y}) tıklandı (DPI ölçek: %{int(scale*100)}, hedef: {sx}, {sy})"
        else:
            user32 = ctypes.windll.user32
            user32.SetCursorPos(sx, sy)
            MOUSEEVENTF_LEFTDOWN = 0x0002
            MOUSEEVENTF_LEFTUP = 0x0004
            user32.mouse_event(MOUSEEVENTF_LEFTDOWN, 0, 0, 0, 0)
            user32.mouse_event(MOUSEEVENTF_LEFTUP, 0, 0, 0, 0)
            return f"✅ ({x}, {y}) ctypes ile tıklandı (DPI ölçek: %{int(scale*100)})"
    except Exception as e:
        return f"❌ Tıklama hatası: {e}"


def _bump(key: str, n: int = 1):
    with _lock:
        _stats[key] = _stats.get(key, 0) + n
        _stats["calls"] += 1


def _fail(where: str, e: Exception) -> str:
    with _lock:
        _stats["failures"] += 1
        _stats["last_error"] = f"{where}: {type(e).__name__}: {e}"[:250]
    return f"[HATA] {where}: {type(e).__name__}: {e}"


# ─── COM: HER THREAD ICIN BIR KEZ ──────────────────────────────────────
def _com_init():
    """UI Automation COM tabanlidir ve COM her THREAD'de ayri baslatilmali.

    ONEMLI: main.py araclari ThreadPoolExecutor(max_workers=8) icinde
    calistirir; yani bu fonksiyonlar ANA THREAD'de DEGIL. CoInitialize
    cagirilmazsa uiautomation/pywinauto "CoInitialize has not been called"
    ile duser. Thread-local bayrakla thread basina bir kez cagiriyoruz.
    """
    if getattr(_tls, "com_ready", False):
        return
    if _pythoncom is not None:
        try:
            _pythoncom.CoInitialize()
        except Exception:
            pass
    else:
        try:
            ctypes.windll.ole32.CoInitialize(None)
        except Exception:
            pass
    _tls.com_ready = True


# ─── MOTOR SECIMI ──────────────────────────────────────────────────────
def _backends() -> list:
    return [
        {"name": "uiautomation", "installed": _uia is not None,
         "element_level": True,
         "reason": "" if _uia else "pip install uiautomation",
         "note": "Element agaci; ada gore tiklama/metin. Tercih edilen."},
        {"name": "pywinauto", "installed": _PwaApp is not None,
         "element_level": True,
         "reason": "" if _PwaApp else "pip install pywinauto",
         "note": "backend='uia'; uiautomation yoksa yedek."},
        {"name": "pyautogui", "installed": _pag is not None,
         "element_level": False,
         "reason": "" if _pag else "pip install pyautogui",
         "note": "Fare ve klavye otomasyonu, metin yazma ve ekran kontrolü."},
        {"name": "pygetwindow", "installed": _pgw is not None,
         "element_level": False,
         "reason": "" if _pgw else "pyautogui ile gelir",
         "note": "Pencere listeleme/tasima; element yok."},
        {"name": "ctypes", "installed": True, "element_level": False,
         "reason": "",
         "note": "user32 dogrudan; kurulum gerektirmez. Pencere seviyesi."},
    ]


def pick_backend(element_level: bool = False) -> str:
    """Kullanilacak motoru cagri aninda sec."""
    bs = {b["name"]: b for b in _backends()}
    order = (("uiautomation", "pywinauto") if element_level
             else ("uiautomation", "pywinauto", "pyautogui", "pygetwindow", "ctypes"))
    for name in order:
        if bs[name]["installed"]:
            return name
    return None


def backend_info() -> dict:
    el = pick_backend(True)
    win = pick_backend(False)
    with _lock:
        used = _stats["backend_used"]
    return {
        "element_backend": el,
        "window_backend": win,
        "element_control": el is not None,
        "window_control": win is not None,
        "available": win is not None,
        "backends": _backends(),
        "backend_used": used,
        "install_hint": ("pip install uiautomation pywinauto"
                         if el is None else ""),
        "note": ("Element bazli islemler icin uiautomation veya pywinauto "
                 "gerekir. Ikisi de yoksa pencere yonetimi (listele/odakla/"
                 "kapat) ctypes ile calismaya devam eder."),
        "mobile": "Mobil icin ADB yolu degismedi (adb_engine.py).",
    }


get_stats = backend_info


def available() -> bool:
    return pick_backend(False) is not None


def element_available() -> bool:
    return pick_backend(True) is not None


def _need_element() -> str:
    return ("[HATA] Element bazli denetim icin paket gerekli. Kur: "
            "pip install uiautomation   (yedek: pip install pywinauto). "
            "Pencere listeleme/odaklama bu paketler olmadan da calisir.")


# ─── CTYPES: PENCERE LISTESI ───────────────────────────────────────────
_user32 = ctypes.windll.user32
_EnumWindowsProc = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND,
                                      wintypes.LPARAM)


def _win_title(hwnd) -> str:
    try:
        n = _user32.GetWindowTextLengthW(hwnd)
        if n <= 0:
            return ""
        buf = ctypes.create_unicode_buffer(n + 1)
        _user32.GetWindowTextW(hwnd, buf, n + 1)
        return buf.value
    except Exception:
        return ""


def _win_class(hwnd) -> str:
    try:
        buf = ctypes.create_unicode_buffer(256)
        _user32.GetClassNameW(hwnd, buf, 256)
        return buf.value
    except Exception:
        return ""


def _win_rect(hwnd) -> dict:
    try:
        r = wintypes.RECT()
        _user32.GetWindowRect(hwnd, ctypes.byref(r))
        return {"x": r.left, "y": r.top,
                "w": r.right - r.left, "h": r.bottom - r.top}
    except Exception:
        return {}


def _win_pid(hwnd) -> int:
    try:
        pid = wintypes.DWORD()
        _user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        return int(pid.value)
    except Exception:
        return 0


def list_windows(visible_only: bool = True, titled_only: bool = True) -> list:
    """Acik ust duzey pencereleri dondur. Kurulum GEREKTIRMEZ."""
    out = []

    def _cb(hwnd, _lp):
        try:
            if visible_only and not _user32.IsWindowVisible(hwnd):
                return True
            t = _win_title(hwnd)
            if titled_only and not t.strip():
                return True
            out.append({
                "hwnd": int(hwnd),
                "title": t,
                "class": _win_class(hwnd),
                "pid": _win_pid(hwnd),
                "rect": _win_rect(hwnd),
                "minimized": bool(_user32.IsIconic(hwnd)),
                "foreground": int(hwnd) == int(_user32.GetForegroundWindow()),
            })
        except Exception:
            pass
        return len(out) < MAX_WINDOWS

    try:
        _user32.EnumWindows(_EnumWindowsProc(_cb), 0)
    except Exception as e:
        with _lock:
            _stats["failures"] += 1
            _stats["last_error"] = f"list_windows: {e}"

    # If 0 windows found (common in background/child processes on Windows),
    # explicitly attach to the interactive desktop station 'winsta0\\default'
    if not out:
        try:
            hwinsta = _user32.OpenWindowStationW("winsta0", False, 0x037F)
            if hwinsta:
                _user32.SetProcessWindowStation(hwinsta)
                hdesk = _user32.OpenDesktopW("default", 0, False, 0x01FF)
                if hdesk:
                    _user32.SetThreadDesktop(hdesk)
                    _user32.EnumDesktopWindows(hdesk, _EnumWindowsProc(_cb), 0)
        except Exception:
            pass

    _bump("windows_listed", 0)
    with _lock:
        _stats["windows_listed"] += len(out)
        _stats["backend_used"] = "ctypes"
    return out


def list_windows_text(visible_only: bool = True) -> str:
    """Modelin okuyacagi metin hali (araclar string dondurur)."""
    wins = list_windows(visible_only=visible_only)
    if not wins:
        return "Acik pencere bulunamadi."
    lines = []
    for w in wins:
        r = w.get("rect") or {}
        mark = "*" if w.get("foreground") else ("_" if w.get("minimized") else " ")
        lines.append(f"{mark} [{w['hwnd']}] {w['title'][:70]}  "
                     f"({w.get('class','')[:24]}, pid={w.get('pid')}, "
                     f"{r.get('w','?')}x{r.get('h','?')})")
    return (f"Acik pencereler ({len(wins)}; * = on planda, _ = simge durumunda):\n"
            + "\n".join(lines))


def _find_hwnd(title: str):
    """Baslikla pencere bul. TAM eslesme once, sonra parca eslesme.

    Parca eslesmede tek bir aday varsa onu kullaniyoruz; birden fazla varsa
    en on plandakini/ilkini aliyoruz ama kac aday oldugunu cagirana
    bildiriyoruz — yanlis pencereye yazmak veri kaybettirir.
    """
    t = (title or "").strip().casefold()
    if not t:
        return None, []
    wins = list_windows()
    exact = [w for w in wins if w["title"].casefold() == t]
    if exact:
        return exact[0], exact
    part = [w for w in wins if t in w["title"].casefold()]
    if part:
        part.sort(key=lambda w: (not w.get("foreground"), w.get("minimized")))
        return part[0], part
    return None, []


# ─── PENCERE ISLEMLERI ─────────────────────────────────────────────────
def focus_window(title: str) -> str:
    """Pencereyi on plana al (simge durumundaysa geri yukle)."""
    w, cands = _find_hwnd(title)
    if not w:
        return f"[HATA] '{title}' basligiyla pencere bulunamadi. " \
               f"Acik pencereleri gormek icin list_windows kullan."
    hwnd = w["hwnd"]
    try:
        if _user32.IsIconic(hwnd):
            _user32.ShowWindow(hwnd, SW_RESTORE)
        # SetForegroundWindow bazen sessizce basarisiz olur (Windows odak
        # hirsizligi korumasi). Once pencereyi one getirip sonra deniyoruz.
        _user32.BringWindowToTop(hwnd)
        ok = bool(_user32.SetForegroundWindow(hwnd))
        _bump("focus")
        extra = f" ({len(cands)} aday vardi, ilki secildi)" if len(cands) > 1 else ""
        if not ok:
            time.sleep(0.15)
            ok = int(_user32.GetForegroundWindow()) == hwnd
        return (f"[OK] '{w['title'][:60]}' odaklandi{extra}" if ok else
                f"[UYARI] '{w['title'][:60]}' one getirildi ama Windows odagi "
                f"vermedi (odak hirsizligi korumasi). Pencere goruniyor olabilir.")
    except Exception as e:
        return _fail("focus_window", e)


def window_state(title: str, state: str = "restore") -> str:
    """Pencereyi buyut / kucult / geri yukle. state: maximize|minimize|restore"""
    w, _ = _find_hwnd(title)
    if not w:
        return f"[HATA] '{title}' bulunamadi."
    flag = {"maximize": SW_MAXIMIZE, "minimize": SW_MINIMIZE,
            "restore": SW_RESTORE}.get((state or "restore").lower())
    if flag is None:
        return "[HATA] state: maximize | minimize | restore olmali."
    try:
        _user32.ShowWindow(w["hwnd"], flag)
        _bump("calls", 0)
        return f"[OK] '{w['title'][:60]}' -> {state}"
    except Exception as e:
        return _fail("window_state", e)


def close_window(title: str) -> str:
    """Pencereye WM_CLOSE gonder.

    GUVENLIK: process OLDURULMEZ. WM_CLOSE uygulamanin normal kapanma
    yoludur; kaydedilmemis is varsa uygulama kullaniciya sorar. Zorla
    oldurmek (TerminateProcess) o isi sessizce yok ederdi.
    """
    w, cands = _find_hwnd(title)
    if not w:
        return f"[HATA] '{title}' bulunamadi."
    if len(cands) > 1:
        titles = ", ".join(c["title"][:40] for c in cands[:5])
        return (f"[HATA] '{title}' {len(cands)} pencereye uyuyor ({titles}). "
                "Yanlis pencereyi kapatmamak icin daha belirgin bir baslik ver.")
    try:
        _user32.PostMessageW(w["hwnd"], WM_CLOSE, 0, 0)
        _bump("calls", 0)
        return (f"[OK] '{w['title'][:60]}' kapatma istegi gonderildi. "
                "Uygulama kaydetme onayi sorabilir.")
    except Exception as e:
        return _fail("close_window", e)


def wait_for_window(title: str, timeout_s: float = 10.0) -> str:
    """Pencere acilana kadar bekle (acilis yavas uygulamalar icin)."""
    t0 = time.time()
    timeout_s = max(0.5, min(60.0, float(timeout_s or 10.0)))
    while time.time() - t0 < timeout_s:
        w, _ = _find_hwnd(title)
        if w:
            return f"[OK] '{w['title'][:60]}' {round(time.time()-t0,2)}s icinde bulundu."
        time.sleep(WAIT_POLL_S)
    return f"[HATA] '{title}' {timeout_s}s icinde acilmadi."


def foreground_window() -> dict:
    """Su anda on planda olan pencere — predictive/vision icin faydali."""
    try:
        hwnd = _user32.GetForegroundWindow()
        if not hwnd:
            return {}
        return {"hwnd": int(hwnd), "title": _win_title(hwnd),
                "class": _win_class(hwnd), "pid": _win_pid(hwnd),
                "rect": _win_rect(hwnd)}
    except Exception:
        return {}


# ─── ELEMENT SEVIYESI: uiautomation ────────────────────────────────────
def _uia_window(title: str, timeout_s: float = 3.0):
    """uiautomation ile pencere kontrolu bul. Once tam ad, sonra parca."""
    _com_init()
    ctrl = _uia.WindowControl(searchDepth=1, Name=title)
    if ctrl.Exists(maxSearchSeconds=timeout_s):
        return ctrl
    t = (title or "").casefold()
    for w in _uia.GetRootControl().GetChildren():
        try:
            if t in (w.Name or "").casefold():
                return w
        except Exception:
            continue
    return None


def _uia_walk(node, depth: int, out: list, level: int = 0):
    if depth < 0 or len(out) >= MAX_CONTROLS:
        return
    try:
        children = node.GetChildren()
    except Exception:
        return
    for ch in children:
        if len(out) >= MAX_CONTROLS:
            return
        try:
            name = (ch.Name or "").strip()
            ctype = ch.ControlTypeName
            auto_id = getattr(ch, "AutomationId", "") or ""
            enabled = True
            try:
                enabled = bool(ch.IsEnabled)
            except Exception:
                pass
            out.append({"level": level, "name": name[:80], "type": ctype,
                        "automation_id": str(auto_id)[:40], "enabled": enabled})
            _uia_walk(ch, depth - 1, out, level + 1)
        except Exception:
            continue


def list_controls(title: str, depth: int = DEFAULT_DEPTH) -> str:
    """Pencere icindeki elementleri agac olarak listele.

    Modelin "hangi dugmeye tiklayabilirim" sorusuna cevabi bu. Element
    paketi yoksa NASIL kurulacagini soyler.
    """
    el = pick_backend(True)
    if el is None:
        return _need_element()
    depth = max(0, min(6, int(depth or DEFAULT_DEPTH)))
    out = []
    try:
        with _lock:
            _stats["backend_used"] = el
        if el == "uiautomation":
            w = _uia_window(title)
            if w is None:
                return f"[HATA] '{title}' penceresi bulunamadi."
            _uia_walk(w, depth, out)
        else:
            _com_init()
            win = _PwaDesktop(backend="uia").window(title_re=f".*{title}.*")
            for c in win.descendants()[:MAX_CONTROLS]:
                try:
                    out.append({"level": 0,
                                "name": (c.window_text() or "")[:80],
                                "type": type(c).__name__,
                                "automation_id": "", "enabled": True})
                except Exception:
                    continue
    except Exception as e:
        return _fail("list_controls", e)
    _bump("calls", 0)
    if not out:
        return f"'{title}' icinde element bulunamadi (derinlik {depth})."
    lines = [("  " * min(c["level"], 5)) +
             f"[{c['type']}] {c['name'] or '(adsiz)'}"
             + ("" if c["enabled"] else "  (devre disi)")
             + (f"  id={c['automation_id']}" if c["automation_id"] else "")
             for c in out]
    more = "\n... (kirpildi)" if len(out) >= MAX_CONTROLS else ""
    return f"'{title}' elementleri ({len(out)}):\n" + "\n".join(lines) + more


def _uia_find(win, name: str, control_type: str = None):
    """Pencere altinda ada gore element bul. Tam ad > parca ad."""
    target = (name or "").casefold()
    found_partial = None
    stack = [(win, 0)]
    seen = 0
    while stack and seen < MAX_CONTROLS * 3:
        node, lvl = stack.pop()
        if lvl > 6:
            continue
        try:
            children = node.GetChildren()
        except Exception:
            continue
        for ch in children:
            seen += 1
            try:
                nm = (ch.Name or "").strip()
                if control_type and control_type.lower() not in \
                        (ch.ControlTypeName or "").lower():
                    stack.append((ch, lvl + 1))
                    continue
                if nm.casefold() == target:
                    return ch
                if found_partial is None and target and target in nm.casefold():
                    found_partial = ch
                stack.append((ch, lvl + 1))
            except Exception:
                continue
    return found_partial


def click_control(title: str, name: str, control_type: str = None,
                  double: bool = False) -> str:
    """Pencere icindeki elemente ADIYLA tikla (koordinat yok).

    Koordinatli tiklamanin aksine pencere kaysa/olceklense de dogru yere
    gider; element bulunamazsa TIKLAMAZ ve bunu soyler (pyautogui ise
    bos bir yere tiklardi ve "basarili" derdi).
    """
    el = pick_backend(True)
    if el is None:
        return _need_element()
    try:
        with _lock:
            _stats["backend_used"] = el
        if el == "uiautomation":
            w = _uia_window(title)
            if w is None:
                return f"[HATA] '{title}' penceresi bulunamadi."
            try:
                w.SetActive()
            except Exception:
                pass
            ctrl = _uia_find(w, name, control_type)
            if ctrl is None:
                err_msg = f"[HATA] uiautomation: '{title}' içinde '{name}' elementi bulunamadı. list_controls ile mevcut elementleri kontrol edin."
                print(f"[NATIVE_DESKTOP] {err_msg}")
                return err_msg
            try:
                if not ctrl.IsEnabled:
                    err_msg = f"[HATA] uiautomation: '{name}' elementi devre dışı (disabled); tıklanamaz."
                    print(f"[NATIVE_DESKTOP] {err_msg}")
                    return err_msg
            except Exception:
                pass
            ctrl.DoubleClick() if double else ctrl.Click()
        else:
            _com_init()
            win = _PwaDesktop(backend="uia").window(title_re=f".*{title}.*")
            c = win.child_window(title_re=f".*{name}.*")
            c.double_click_input() if double else c.click_input()
        _bump("clicks")
        return f"[OK] '{name}' {'cift ' if double else ''}tiklandi ({title})."
    except Exception as e:
        print(f"[NATIVE_DESKTOP] click_control istisnası ({title} / {name}): {e}")
        return _fail("click_control", e)


def set_control_text(title: str, name: str, text: str) -> str:
    """Bir metin alanina yaz (Turkce karakterler dahil).

    pyautogui.typewrite ASCII disini yazamadigi icin main.py clipboard
    hilesine basvuruyor; UI Automation ise degeri DOGRUDAN set eder,
    clipboard'a hic dokunmaz (kullanicinin kopyaladigi sey bozulmaz).
    """
    el = pick_backend(True)
    if el is None:
        return _need_element()
    try:
        with _lock:
            _stats["backend_used"] = el
        if el == "uiautomation":
            w = _uia_window(title)
            if w is None:
                return f"[HATA] '{title}' penceresi bulunamadi."
            ctrl = _uia_find(w, name, "Edit") or _uia_find(w, name)
            if ctrl is None:
                return f"[HATA] '{title}' icinde '{name}' alani yok."
            try:
                ctrl.GetValuePattern().SetValue(str(text))
            except Exception:
                ctrl.Click()
                ctrl.SendKeys("{Ctrl}a", waitTime=0.05)
                ctrl.SendKeys(str(text).replace("{", "{{").replace("}", "}}"))
        else:
            _com_init()
            win = _PwaDesktop(backend="uia").window(title_re=f".*{title}.*")
            win.child_window(title_re=f".*{name}.*").set_edit_text(str(text))
        _bump("text_set")
        return f"[OK] '{name}' alanina yazildi ({len(str(text))} karakter)."
    except Exception as e:
        return _fail("set_control_text", e)


def get_control_text(title: str, name: str) -> str:
    """Bir elementin metnini OKU — ekran goruntusu + OCR'a gerek yok.

    OCR yolu vision-LLM token'i harciyor ve yanlis okuyabiliyor; UI
    Automation gercek degeri verir.
    """
    el = pick_backend(True)
    if el is None:
        return _need_element()
    try:
        with _lock:
            _stats["backend_used"] = el
        if el == "uiautomation":
            w = _uia_window(title)
            if w is None:
                return f"[HATA] '{title}' penceresi bulunamadi."
            ctrl = _uia_find(w, name)
            if ctrl is None:
                return f"[HATA] '{title}' icinde '{name}' yok."
            val = ""
            try:
                val = ctrl.GetValuePattern().Value or ""
            except Exception:
                pass
            if not val:
                try:
                    val = ctrl.GetTextPattern().DocumentRange.GetText(4000)
                except Exception:
                    val = ctrl.Name or ""
        else:
            _com_init()
            win = _PwaDesktop(backend="uia").window(title_re=f".*{title}.*")
            val = win.child_window(title_re=f".*{name}.*").window_text() or ""
        _bump("text_read")
        val = str(val)
        return val[:4000] if val.strip() else f"'{name}' bos."
    except Exception as e:
        return _fail("get_control_text", e)


# ─── ISTATISTIK ────────────────────────────────────────────────────────
def stats() -> dict:
    with _lock:
        s = dict(_stats)
    s["element_backend"] = pick_backend(True)
    s["window_backend"] = pick_backend(False)
    return s


def reset_stats() -> dict:
    with _lock:
        _stats.update({"calls": 0, "windows_listed": 0, "focus": 0,
                       "clicks": 0, "text_set": 0, "text_read": 0,
                       "failures": 0, "backend_used": None,
                       "last_error": None})
    return stats()


def info() -> dict:
    return backend_info()


def test_desktop_control() -> dict:
    """
    Masaüstü denetimini test et:
    1. Windows Not Defteri'ni aç (notepad.exe).
    2. Pencerenin açılmasını bekle ve odakla.
    3. 'Hello from ALES' yaz.
    4. Ekran görüntüsü al ve base64 olarak UI'ya döndür.
    """
    import subprocess
    import io
    import base64
    from PIL import Image

    proc = None
    try:
        # 1. Not Defteri'ni baslat
        proc = subprocess.Popen(["notepad.exe"])
        time.sleep(1.2)

        # 2. Odakla
        w, _ = _find_hwnd("Notepad")
        if not w:
            w, _ = _find_hwnd("Not Defteri")
        if w:
            focus_window(w["title"])
            time.sleep(0.3)

        # 3. Metin yaz
        typed = False
        if _pag is not None:
            try:
                _pag.write("Hello from ALES", interval=0.03)
                typed = True
            except Exception:
                pass

        if not typed and _uia is not None:
            try:
                np_ctrl = _uia_window("Notepad", timeout_s=1.0) or _uia_window("Not Defteri", timeout_s=1.0)
                if np_ctrl:
                    np_ctrl.SendKeys("Hello from ALES", waitTime=0.02)
                    typed = True
            except Exception:
                pass

        if not typed:
            # Clipboard / ctypes fallback
            try:
                import ctypes
                user32 = ctypes.windll.user32
                for ch in "Hello from ALES":
                    vk = user32.VkKeyScanW(ord(ch))
                    user32.keybd_event(vk & 0xFF, 0, 0, 0)
                    user32.keybd_event(vk & 0xFF, 0, 2, 0)
                typed = True
            except Exception:
                pass

        time.sleep(0.5)

        # 4. Ekran goruntusu al
        img = None
        try:
            import mss
            with mss.mss() as sct:
                mon = sct.monitors[1] if len(sct.monitors) > 1 else sct.monitors[0]
                shot = sct.grab(mon)
                img = Image.frombytes("RGB", shot.size, shot.bgra, "raw", "BGRX")
        except Exception:
            try:
                from PIL import ImageGrab
                img = ImageGrab.grab()
            except Exception as ge:
                return {"ok": False, "error": f"Ekran görüntüsü alınamadı: {ge}"}

        if img is None:
            return {"ok": False, "error": "Ekran görüntüsü oluşturulamadı."}

        # Görüntüyü makul bir boyuta ölçekle ve PNG base64 yap
        img.thumbnail((1280, 720))
        buf = io.BytesIO()
        img.save(buf, format="PNG")
        b64 = base64.b64encode(buf.getvalue()).decode("ascii")

        return {
            "ok": True,
            "message": "Windows Not Defteri açıldı, 'Hello from ALES' yazıldı ve ekran görüntüsü alındı.",
            "screenshot": b64,
            "typed": typed
        }
    except Exception as e:
        return {"ok": False, "error": f"Test başarısız: {type(e).__name__}: {e}"}


# ═══════════════════════════════════════════════════════════════════════
# CLAUDE CODE STATEFUL TERMINAL & COMPUTER USE GUI AGENT PRIMITIVES
# ═══════════════════════════════════════════════════════════════════════
import subprocess
import re
import base64
from pathlib import Path

# Oturum boyunca çalışma dizinini saklayan state
_SESSION_CWD: str = str(Path(__file__).resolve().parent.parent)

def get_terminal_cwd() -> str:
    """Mevcut çalışma dizinini döner."""
    global _SESSION_CWD
    if not os.path.exists(_SESSION_CWD):
        _SESSION_CWD = str(Path(__file__).resolve().parent.parent)
    return _SESSION_CWD

def set_terminal_cwd(new_dir: str) -> bool:
    """Çalışma dizinini günceller."""
    global _SESSION_CWD
    try:
        p = Path(new_dir) if os.path.isabs(new_dir) else (Path(_SESSION_CWD) / new_dir)
        res = p.resolve()
        if res.exists() and res.is_dir():
            _SESSION_CWD = str(res)
            return True
    except Exception:
        pass
    return False

def run_terminal_command(cmd: str, timeout: int = 60) -> str:
    """Stateful Terminal Runner:
    - 'cd' komutlarını algılayıp _SESSION_CWD durumunu kalıcı olarak değiştirir.
    - pip install veya npm install gibi paket yönetim komutlarını o dizinde çalıştırır.
    - [Exit Code: X], [CWD: Y], STDOUT ve STDERR döner.
    """
    global _SESSION_CWD
    if not cmd or not str(cmd).strip():
        return "❌ Komut boş olamaz."
    cmd_str = str(cmd).strip()

    # cd tespiti
    cd_match = re.match(r"^cd\s+(.+)$", cmd_str, re.IGNORECASE)
    if cd_match:
        target = cd_match.group(1).strip().strip('"').strip("'")
        if set_terminal_cwd(target):
            return f"✅ Çalışma dizini değiştirildi: {_SESSION_CWD}\n[Exit Code: 0]\n[CWD: {_SESSION_CWD}]"
        else:
            return f"❌ Dizin bulunamadı: {target}\n[Exit Code: 1]\n[CWD: {_SESSION_CWD}]"

    curr_cwd = get_terminal_cwd()
    try:
        res = subprocess.run(
            cmd_str,
            shell=True,
            capture_output=True,
            text=True,
            timeout=timeout,
            cwd=curr_cwd
        )
        out = (res.stdout or "").strip()
        err = (res.stderr or "").strip()
        lines = [f"[Exit Code: {res.returncode}]", f"[CWD: {curr_cwd}]"]
        if out:
            lines.append(f"STDOUT:\n{out}")
        if err:
            lines.append(f"STDERR:\n{err}")
        if not out and not err:
            lines.append("(Komut çıktı vermeden başarıyla tamamlandı)")
        return "\n\n".join(lines)
    except subprocess.TimeoutExpired:
        return f"⏱️ Komut zaman aşımına uğradı ({timeout}s).\n[Exit Code: 124]\n[CWD: {curr_cwd}]"
    except Exception as e:
        return f"❌ Terminal hatası: {e}\n[Exit Code: 1]\n[CWD: {curr_cwd}]"


# ── Computer Use (GUI Agent: MSS + PyAutoGUI) ───────────────────────────
def take_screenshot_gui(region: str = "auto") -> dict:
    """Ekran görüntüsü alır (MSS ile ultra hızlı), base64 JPEG ve dosya yolunu döner."""
    try:
        import mss
        import tempfile
        import io
        from PIL import Image

        path = os.path.join(tempfile.gettempdir(), "ales_screen.jpg")
        with mss.mss() as sct:
            mon = sct.monitors[1] if len(sct.monitors) > 1 else sct.monitors[0]
            shot = sct.grab(mon)
            img = Image.frombytes("RGB", shot.size, shot.bgra, "raw", "BGRX")

        # Görseli JPEG olarak optimize kaydet
        img.save(path, format="JPEG", quality=80)

        # Gemini 3.8 Vision için base64 üret
        buf = io.BytesIO()
        img.save(buf, format="JPEG", quality=75)
        b64 = base64.b64encode(buf.getvalue()).decode("ascii")

        return {
            "ok": True,
            "path": path,
            "width": img.width,
            "height": img.height,
            "base64": b64,
            "message": f"Ekran görüntüsü alındı ({img.width}x{img.height}): {path}"
        }
    except Exception as e:
        return {"ok": False, "error": f"Ekran görüntüsü hatası: {e}"}

def mouse_click_gui(x: int, y: int) -> str:
    """Ekranda (x, y) koordinatına fare ile tıklar."""
    try:
        import pyautogui
        pyautogui.FAILSAFE = False
        pyautogui.click(int(x), int(y))
        return f"✅ Fare tıklandı: ({x}, {y})"
    except Exception as e:
        return f"❌ Fare tıklama hatası ({x}, {y}): {e}"

def keyboard_type_gui(text: str) -> str:
    """Klavyeden metin yazar."""
    try:
        import pyautogui
        pyautogui.write(str(text), interval=0.01)
        return f"✅ Metin yazıldı ({len(text)} karakter)"
    except Exception as e:
        return f"❌ Klavye yazma hatası: {e}"

def keyboard_press_gui(key: str) -> str:
    """Klavyeden tuşa basar."""
    try:
        import pyautogui
        k = str(key).strip().lower()
        if "+" in k:
            parts = [p.strip() for p in k.split("+")]
            pyautogui.hotkey(*parts)
            return f"✅ Kısayol tuşlandı: {k}"
        else:
            pyautogui.press(k)
            return f"✅ Tuşa basıldı: {k}"
    except Exception as e:
        return f"❌ Tuş basma hatası ({key}): {e}"

