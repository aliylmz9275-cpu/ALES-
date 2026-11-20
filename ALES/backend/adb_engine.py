"""
adb_engine.py — ALES icin ultra-hizli, NON-BLOCKING (asenkron) ADB katmani.

Tum adb cagrilari asyncio.create_subprocess_exec ile yapilir - hicbir
cagri event loop'unu bloklamaz, yuzlerce gorev pes pese akabilir.

Cekirdek yetenekler:
  - Deep-linking: hedefi native uygulamada aninda ac (VIEW intent).
  - UI Polling Engine: statik sleep yerine 100ms'lik dongude uiautomator
    dump alir (dump sonrasi 0.3s XML tampon beklemesi), hedef element/metin
    gorunur gorunmez donguyu kirar.
  - Ratio tap: element bounds yerine ekran oranina (X%, Y%) gore dokunma -
    ogrenilen sablonlar (templates.json) bu oranlari saklar.
  - Adaptive Latency Sync: her adb cagrisinin gecikmesi olculur; ag
    titremesi (jitter) tespit edilirse poll araligi lineer buyutulur.
"""
import asyncio
import re
import time
import xml.etree.ElementTree as ET
from pathlib import Path

from phone_speed_control import load_settings, get_active_profile

# uiautomator dump cihazda buraya yazar; sonra cekip okuruz.
_REMOTE_XML = "/sdcard/window_dump.xml"
_REMOTE_PNG = "/sdcard/ales_screen.png"

# ─── ADAPTIF GECIKME TAKIBI ──────────────────────────────────────
# Son N adb cagrisinin sure ortalamasi; jitter yuksekse poll araligi
# lineer olarak buyutulur (agir/uzak cihazlarda bosuna CPU yakmasin).
_latency_samples = []
_LAT_WINDOW = 12


def _record_latency(dt: float):
    _latency_samples.append(dt)
    if len(_latency_samples) > _LAT_WINDOW:
        _latency_samples.pop(0)


def _latency_stats():
    if not _latency_samples:
        return 0.0, 0.0
    avg = sum(_latency_samples) / len(_latency_samples)
    var = sum((x - avg) ** 2 for x in _latency_samples) / len(_latency_samples)
    return avg, var ** 0.5  # (ortalama, std sapma=jitter)


def adaptive_poll_interval(base_ms: int) -> float:
    """Temel poll araligini (ms) ag jitter'ina gore lineer olceklendirir.
    Jitter dusukse temel deger; yuksekse ~2x'e kadar buyur. saniye doner."""
    s = load_settings()
    if not s.get("adaptive_latency", True):
        return base_ms / 1000.0
    avg, jitter = _latency_stats()
    # jitter, ortalamanin bir orani olarak: 0 -> 1x, >=1.0 -> 2x (clamp)
    factor = 1.0
    if avg > 0:
        factor = 1.0 + min(1.0, jitter / avg)
    return (base_ms * factor) / 1000.0


# ─── DUSUK SEVIYE ADB CAGRISI ────────────────────────────────────
def _adb_base() -> list:
    s = load_settings()
    base = [s.get("adb_path", "adb")]
    serial = (s.get("adb_serial") or "").strip()
    if serial:
        base += ["-s", serial]
    return base


async def adb(*args, timeout: float = 15.0, binary: bool = False):
    """
    Tek bir adb komutunu asenkron calistirir. (returncode, stdout, stderr)
    doner. stdout binary=True ise ham bytes, degilse utf-8 str.
    Gecikme adaptif poll icin kaydedilir.
    """
    cmd = _adb_base() + list(args)
    t0 = time.monotonic()
    try:
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        try:
            out, err = await asyncio.wait_for(proc.communicate(), timeout=timeout)
        except asyncio.TimeoutError:
            try: proc.kill()
            except Exception: pass
            return 124, (b"" if binary else ""), "timeout"
    except FileNotFoundError:
        return 127, (b"" if binary else ""), "adb bulunamadi (PATH veya adb_path ayarini kontrol et)"
    except Exception as e:
        return 1, (b"" if binary else ""), str(e)
    finally:
        _record_latency(time.monotonic() - t0)

    stdout = out if binary else out.decode("utf-8", "replace")
    return proc.returncode, stdout, err.decode("utf-8", "replace")


async def adb_shell(*args, timeout: float = 15.0, binary: bool = False):
    return await adb("shell", *args, timeout=timeout, binary=binary)


# ─── CIHAZ / EKRAN ───────────────────────────────────────────────
async def list_devices() -> list:
    rc, out, _ = await adb("devices")
    if rc != 0:
        return []
    devices = []
    for line in out.splitlines()[1:]:
        line = line.strip()
        if line and "\tdevice" in line:
            devices.append(line.split("\t")[0])
    return devices


async def is_device_ready() -> bool:
    return len(await list_devices()) > 0


_screen_size_cache = None


async def get_screen_size() -> tuple:
    """(width, height). 'wm size' ciktisini parse eder, sonucu cache'ler."""
    global _screen_size_cache
    if _screen_size_cache:
        return _screen_size_cache
    rc, out, _ = await adb_shell("wm", "size")
    m = re.search(r"(\d+)x(\d+)", out or "")
    if m:
        _screen_size_cache = (int(m.group(1)), int(m.group(2)))
    else:
        _screen_size_cache = (1080, 2400)  # makul varsayilan
    return _screen_size_cache


# ─── DEEP LINKING ────────────────────────────────────────────────
async def open_deep_link(url: str, package: str = None) -> bool:
    """
    Hedefi native uygulamada aninda acar (VIEW intent). Ornek:
      adb shell am start -a android.intent.action.VIEW -d <url>
    package verilirse intent o uygulamaya kilitlenir (disambiguation
    ekranini atlar).
    """
    args = ["am", "start", "-a", "android.intent.action.VIEW", "-d", url]
    if package:
        args += ["-p", package]
    rc, out, err = await adb_shell(*args, timeout=12.0)
    return rc == 0 and "Error" not in (out or "") and "Error" not in (err or "")


# Instagram/Twitter icin kullanisli deep-link kuruculari
def instagram_profile_link(username: str) -> str:
    return f"https://instagram.com/_u/{username.lstrip('@')}"


def twitter_profile_link(username: str) -> str:
    return f"https://twitter.com/{username.lstrip('@')}"


# ─── UIAUTOMATOR DUMP + POLLING ENGINE ───────────────────────────
async def _dump_ui_xml(profile: dict) -> str:
    """uiautomator dump alir, 0.3s (profil) XML tampon bekler, XML'i ceker.
    Bos/gecersiz olursa '' doner."""
    rc, out, err = await adb_shell("uiautomator", "dump", _REMOTE_XML, timeout=10.0)
    # dump bazen "UI hierchary dumped to: ..." yazar ama dosya biraz gec
    # tam yazilir - bu yuzden kisa bir XML tampon beklemesi sart.
    await asyncio.sleep(profile.get("xml_buffer_s", 0.3))
    rc2, xml, err2 = await adb_shell("cat", _REMOTE_XML, timeout=10.0)
    if rc2 != 0 or not xml or "<hierarchy" not in xml:
        return ""
    return xml


def _parse_nodes(xml: str) -> list:
    """XML'i parse edip her node icin {text, desc, resource_id, bounds}
    listesi doner. bounds = (l, t, r, b)."""
    nodes = []
    try:
        root = ET.fromstring(xml)
    except Exception:
        return nodes
    for node in root.iter("node"):
        b = node.get("bounds", "")
        m = re.match(r"\[(\d+),(\d+)\]\[(\d+),(\d+)\]", b)
        bounds = (int(m.group(1)), int(m.group(2)), int(m.group(3)), int(m.group(4))) if m else None
        nodes.append({
            "text": node.get("text", "") or "",
            "desc": node.get("content-desc", "") or "",
            "resource_id": node.get("resource-id", "") or "",
            "clickable": node.get("clickable", "") == "true",
            "bounds": bounds,
        })
    return nodes


def _match_node(nodes: list, targets: list) -> dict:
    """targets = aranan metin/desc/resource-id parcalari (kucuk harf,
    substring eslesme). Ilk eslesen node'u doner, yoksa None."""
    tl = [t.lower() for t in targets if t]
    for n in nodes:
        hay = f"{n['text']} {n['desc']} {n['resource_id']}".lower()
        if any(t in hay for t in tl):
            return n
    return None


async def poll_for_element(targets: list, profile: dict = None) -> dict:
    """
    HIZ CEKIRDEGI: statik sleep yerine ~100ms'lik dongude uiautomator dump
    alir, hedef metin/element gorunur gorunmez donguyu KIRAR ve node'u
    doner. Bulamazsa max_poll_loops sonunda None doner.

    Poll araligi adaptif: ag jitter'i yuksekse aralik lineer buyur.
    """
    profile = profile or get_active_profile()
    base_ms = profile.get("poll_interval_ms", 100)
    max_loops = profile.get("max_poll_loops", 40)

    for _ in range(max_loops):
        xml = await _dump_ui_xml(profile)
        if xml:
            node = _match_node(_parse_nodes(xml), targets)
            if node:
                return node
        await asyncio.sleep(adaptive_poll_interval(base_ms))
    return None


async def wait_ui_settle(profile: dict = None):
    """Sadece bir XML dump + tampon bekler - 'ekran oturdu mu' icin hafif
    bir senkron nokta (sabit sleep yerine)."""
    profile = profile or get_active_profile()
    await _dump_ui_xml(profile)


# ─── DOKUNMA / GIRIS ─────────────────────────────────────────────
async def tap(x: int, y: int, profile: dict = None) -> bool:
    profile = profile or get_active_profile()
    rc, _, _ = await adb_shell("input", "tap", str(int(x)), str(int(y)), timeout=8.0)
    await asyncio.sleep(profile.get("action_gap_s", 0.05))
    return rc == 0


async def tap_ratio(rx: float, ry: float, profile: dict = None) -> bool:
    """Ekran oranina (0..1) gore dokun - ogrenilen sablonlar bu oranlari
    saklar, boylece cozunurluk degisse bile dogru noktaya basar."""
    w, h = await get_screen_size()
    return await tap(int(w * rx), int(h * ry), profile=profile)


async def tap_node(node: dict, profile: dict = None) -> bool:
    """Bir uiautomator node'unun merkezine dokun."""
    b = node.get("bounds")
    if not b:
        return False
    cx = (b[0] + b[2]) // 2
    cy = (b[1] + b[3]) // 2
    return await tap(cx, cy, profile=profile)


def node_center_ratio(node: dict, screen: tuple) -> tuple:
    """Node merkezini ekran oranina cevirir (sablon ogrenmek icin)."""
    b = node.get("bounds")
    if not b or not screen or screen[0] == 0 or screen[1] == 0:
        return None
    cx = (b[0] + b[2]) / 2
    cy = (b[1] + b[3]) / 2
    return (round(cx / screen[0], 4), round(cy / screen[1], 4))


async def input_text(text: str, profile: dict = None) -> bool:
    profile = profile or get_active_profile()
    safe = text.replace(" ", "%s").replace("'", "")
    rc, _, _ = await adb_shell("input", "text", safe, timeout=8.0)
    await asyncio.sleep(profile.get("action_gap_s", 0.05))
    return rc == 0


async def press_back():
    await adb_shell("input", "keyevent", "4", timeout=6.0)


# ─── EKRAN GORUNTUSU (gorsel fallback icin) ──────────────────────
async def screenshot_png() -> bytes:
    """Cihaz ekran goruntusunu PNG bytes olarak doner (exec-out ile,
    diske yazmadan). Basarisizsa b'' doner."""
    rc, out, _ = await adb("exec-out", "screencap", "-p", timeout=12.0, binary=True)
    if rc == 0 and out:
        return out
    # Fallback: dosyaya cek + pull
    await adb_shell("screencap", "-p", _REMOTE_PNG, timeout=12.0)
    rc2, out2, _ = await adb("exec-out", "cat", _REMOTE_PNG, timeout=12.0, binary=True)
    return out2 if rc2 == 0 else b""
