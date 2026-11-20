import asyncio
import json
from datetime import datetime, time as dtime
from pathlib import Path
from typing import Callable, Dict, List

try:
    from config_manager import SCHEDULES_FILE as schedule_file
except Exception:
    schedule_file = Path("schedules.json")

def load_schedules() -> List[dict]:
    if schedule_file.exists():
        return json.loads(schedule_file.read_text(encoding="utf-8"))
    return []

def save_schedules(schedules: List[dict]):
    schedule_file.write_text(json.dumps(schedules, ensure_ascii=False, indent=2), encoding="utf-8")

def add_schedule(name: str, time_str: str, action: str, repeat: str = "daily") -> str:
    """
    Zamanlanmış görev ekle.
    time_str: "09:00" formatında
    repeat: daily / weekdays / once
    """
    schedules = load_schedules()
    schedule_id = int(datetime.now().timestamp())
    schedules.append({
        "id": schedule_id,
        "name": name,
        "time": time_str,
        "action": action,
        "repeat": repeat,
        "active": True,
        "created": datetime.now().isoformat(),
        "last_run": None
    })
    save_schedules(schedules)
    return f"✅ Zamanlama eklendi: '{name}' → Her gün {time_str}'de '{action}'"

def remove_schedule(schedule_id: int) -> str:
    schedules = load_schedules()
    schedules = [s for s in schedules if s["id"] != schedule_id]
    save_schedules(schedules)
    return f"✅ Zamanlama kaldırıldı: {schedule_id}"

def list_schedules() -> str:
    schedules = load_schedules()
    if not schedules:
        return "⏰ Zamanlanmış görev yok."
    lines = ["⏰ Zamanlanmış Görevler:"]
    for s in schedules:
        status = "✅" if s["active"] else "⏸️"
        lines.append(f"  {status} [{s['id']}] {s['name']} → {s['time']} ({s['repeat']}): {s['action']}")
    return "\n".join(lines)

async def run_scheduler(message_callback: Callable):
    """
    Arka planda calisan zamanlama motoru.
    Her dakika kontrol eder.
    """
    print("[SCHEDULER] Motoru basladi...")
    while True:
        try:
            now = datetime.now()
            current_time = now.strftime("%H:%M")
            schedules = load_schedules()

            for s in schedules:
                if not s.get("active"):
                    continue
                if s["time"] == current_time:
                    last_run = s.get("last_run")
                    today = now.strftime("%Y-%m-%d")
                    if last_run and last_run.startswith(today):
                        continue

                    # Gorevi calistir
                    print(f"[SCHEDULER] Zamanlama calisiyor: {s['name']}")
                    await message_callback(s["action"])

                    # Son çalışma zamanını güncelle
                    s["last_run"] = now.isoformat()
                    if s["repeat"] == "once":
                        s["active"] = False

            save_schedules(schedules)

        except Exception as e:
            print(f"[SCHEDULER] Hata: {e}")

        await asyncio.sleep(60)  # Her dakika kontrol et
