"""
screen_streamer.py — ALES Canlı Ekran Yayını & Aktivite Akışı (Faz 5).

WebSocket (/ws/stream) üzerinden istemcilere:
  1) Aktif görev yürütülürken canlı ekran karelerini (JPEG base64, 800px, 2 FPS) iletir.
  2) ALES'in yaptığı tüm araç ve sistem eylemlerini anlık aktivite günlüğü olarak yayınlar.

KAYNAK DİSİPLİNİ:
  - Ekran yakalama döngüsü YALNIZCA aktif bir görev varken ve bağlı istemci varken çalışır!
  - Boşta kalındığında döngü durur, CPU ve GPU tüketimi 0'a iner.
"""
import asyncio
import base64
import io
import time
from collections import deque
from datetime import datetime
from typing import Set, Optional
from fastapi import WebSocket, WebSocketDisconnect

_active_tasks: Set[str] = set()
_clients: Set[WebSocket] = set()
_activity_feed = deque(maxlen=100)
_capture_task: Optional[asyncio.Task] = None
_lock = asyncio.Lock()


def log_activity(message: str, level: str = "INFO", tool: Optional[str] = None):
    """Aktivite günlüğüne olay ekler ve bağlı istemcilere yayınlar."""
    entry = {
        "type": "activity",
        "time": datetime.now().strftime("%H:%M:%S"),
        "level": level,
        "tool": tool,
        "message": message,
    }
    _activity_feed.append(entry)

    # İstemcilere async yayın (arkaplanda)
    if _clients:
        asyncio.create_task(_broadcast(entry))


async def _broadcast(msg: dict):
    """Tüm bağlı istemcilere JSON paketi gönderir."""
    if not _clients:
        return
    dead = set()
    for ws in list(_clients):
        try:
            await ws.send_json(msg)
        except Exception:
            dead.add(ws)
    for ws in dead:
        _clients.discard(ws)


def _capture_screen_jpeg_base64() -> Optional[str]:
    """Ekranı yakalar, 800px genişliğe ölçekler ve JPEG base64 dizesi döner."""
    try:
        from PIL import Image
        img = None

        # 1. Önce mss dene (hızlı ve hafif)
        try:
            import mss
            with mss.mss() as sct:
                # Birincil monitörü al
                mon = sct.monitors[1] if len(sct.monitors) > 1 else sct.monitors[0]
                raw = sct.grab(mon)
                img = Image.frombytes("RGB", raw.size, raw.bgra, "raw", "BGRX")
        except Exception:
            pass

        # 2. MSS başarısız olursa ImageGrab dene
        if img is None:
            try:
                from PIL import ImageGrab
                img = ImageGrab.grab()
            except Exception:
                pass

        if img is None:
            return None

        # 800px genişliğe oranını koruyarak küçült
        w, h = img.size
        max_w = 800
        if w > max_w:
            new_h = int(h * (max_w / w))
            img = img.resize((max_w, new_h), Image.Resampling.BILINEAR)

        buf = io.BytesIO()
        img.save(buf, format="JPEG", quality=65, optimize=True)
        b64 = base64.b64encode(buf.getvalue()).decode("ascii")
        return f"data:image/jpeg;base64,{b64}"
    except Exception as e:
        print(f"[SCREEN_STREAMER] Ekran yakalama hatası: {e}")
        return None


async def _screen_capture_loop():
    """Bağlı istemci varken ekranı yakalayıp yayınlayan döngü (aktifken 2 FPS, boştayken 1 FPS)."""
    print("[SCREEN_STREAMER] Ekran yayını BAŞLATILDI.")
    try:
        while len(_clients) > 0:
            frame_b64 = await asyncio.to_thread(_capture_screen_jpeg_base64)
            is_active = len(_active_tasks) > 0
            if frame_b64:
                msg = {
                    "type": "frame",
                    "status": "active" if is_active else "idle",
                    "image": frame_b64,
                    "active_tasks": list(_active_tasks),
                    "time": datetime.now().strftime("%H:%M:%S"),
                }
                await _broadcast(msg)
            # Aktif görev varken 2 FPS (500ms), boştayken 1 FPS (1000ms)
            interval = 0.5 if is_active else 1.0
            await asyncio.sleep(interval)
    except asyncio.CancelledError:
        pass
    except Exception as e:
        print(f"[SCREEN_STREAMER] Yakalama döngüsü istisnası: {e}")
    finally:
        print("[SCREEN_STREAMER] Ekran yayını DURDURULDU (İstemci yok).")


async def _check_capture_state():
    """Bağlı istemci durumuna göre döngüyü açar veya kapatır."""
    global _capture_task
    async with _lock:
        should_run = len(_clients) > 0
        if should_run:
            if _capture_task is None or _capture_task.done():
                _capture_task = asyncio.create_task(_screen_capture_loop())
        else:
            if _capture_task is not None and not _capture_task.done():
                _capture_task.cancel()
                _capture_task = None


def start_task(name: str):
    """Yeni bir aktif görev başlatıldığında çağrılır."""
    _active_tasks.add(name)
    log_activity(f"Görev başladı: {name}", level="INFO")
    try:
        loop = asyncio.get_running_loop()
        loop.create_task(_check_capture_state())
    except RuntimeError:
        pass


def finish_task(name: str):
    """Görev tamamlandığında veya bittiğinde çağrılır."""
    _active_tasks.discard(name)
    log_activity(f"Görev tamamlandı: {name}", level="SUCCESS")
    try:
        loop = asyncio.get_running_loop()
        loop.create_task(_check_capture_state())
    except RuntimeError:
        pass


async def handle_stream_websocket(websocket: WebSocket):
    """FastAPI WebSocket /ws/stream uç noktası işleyicisi."""
    await websocket.accept()
    _clients.add(websocket)
    try:
        # İstemciye başlangıç durumunu ve geçmiş aktivite günlüğünü ilet
        init_payload = {
            "type": "init",
            "status": "active" if _active_tasks else "idle",
            "active_tasks": list(_active_tasks),
            "activities": list(_activity_feed),
        }
        await websocket.send_json(init_payload)

        # Duruma göre yakalama döngüsünü tetikle
        await _check_capture_state()

        # İstemciden gelebilecek ping/pong veya komutları dinle
        while True:
            data = await websocket.receive_text()
            if data == "ping":
                await websocket.send_text("pong")
    except WebSocketDisconnect:
        pass
    except Exception as e:
        print(f"[SCREEN_STREAMER] WebSocket hatası: {e}")
    finally:
        _clients.discard(websocket)
        await _check_capture_state()
