"""
executor_agent.py — ALES Alt Görev Yürütücüsü (Executor Agent).

Manager Agent tarafından belirlenen her bir alt görevi (subtask) sırayla
ve bağımsız olarak yürütür.

Özellikler:
  - Her alt görev öncesinde ve sonrasında screen_streamer'a görev durumu bildirir.
  - Araç çağrısını güvenli bir şekilde yürütür.
  - Hata oluşursa experience_learner'a başarısızlığı kaydeder; 2+ tekrarda kural çıkarır.
  - Alt görev sonucunu (başarı/başarısızlık + çıktı) Manager'a geri raporlar.
"""
import asyncio
import json
import time
from typing import Dict, Any, Optional

import experience_learner
import screen_streamer


async def execute_subtask(subtask: Dict[str, Any], tool_executor_fn=None) -> Dict[str, Any]:
    """
    Tek bir alt görevi yürütür.
    subtask örneği:
      {
        "id": 1,
        "action": "open_app",
        "description": "Not defterini aç",
        "tool": "open_app",
        "params": {"app_name": "notepad"}
      }
    """
    sub_id = subtask.get("id", 1)
    action = subtask.get("action") or subtask.get("tool") or "islem"
    desc = subtask.get("description", f"Alt görev #{sub_id}")
    tool = subtask.get("tool") or action
    params = subtask.get("params") or {}

    task_tag = f"Subtask #{sub_id}: {desc}"
    screen_streamer.start_task(task_tag)
    screen_streamer.log_activity(f"[{task_tag}] Yürütülüyor... Araç: {tool}", level="INFO", tool=tool)

    start_t = time.time()
    success = False
    result_text = ""
    error_text = None
    rule_learned = None

    try:
        executed = False
        # 1. Öncelik: Çağıran tarafından iletilen özel araç işleyicisi
        if tool_executor_fn is not None:
            try:
                if asyncio.iscoroutinefunction(tool_executor_fn):
                    res = await tool_executor_fn(tool, params)
                else:
                    res = await asyncio.to_thread(tool_executor_fn, tool, params)
                result_text = str(res)
                executed = True
            except Exception as e_fn:
                print(f"[EXECUTOR] tool_executor_fn hatası: {e_fn}")

        # 2. Öncelik: ALES ana araç merkezi (main.execute_tool)
        if not executed:
            try:
                import main
                if hasattr(main, "execute_tool"):
                    res = await asyncio.to_thread(main.execute_tool, tool, params)
                    result_text = str(res)
                    executed = True
            except Exception as e_main:
                pass

        # 3. Fallback: Yerel araç motoru
        if not executed:
            result_text = await _fallback_tool_exec(tool, params)

        # Başarı değerlendirmesi
        upper_res = result_text.upper()
        has_error_mark = "❌" in result_text or "HATA:" in upper_res or "ERROR:" in upper_res or "YÜRÜTÜLEMEDİ" in upper_res
        success = not has_error_mark

    except Exception as e:
        error_text = str(e)
        result_text = f"❌ Yürütme hatası: {error_text}"
        success = False

    elapsed = round(time.time() - start_t, 2)

    if success:
        screen_streamer.log_activity(f"[{task_tag}] Başarılı ({elapsed}s)", level="SUCCESS", tool=tool)
    else:
        err_msg = error_text or result_text
        screen_streamer.log_activity(f"[{task_tag}] Başarısız ({elapsed}s): {err_msg[:100]}", level="ERROR", tool=tool)
        # Hata öğrenme mekanizmasını tetikle: 2+ tekrarda kural çıkarır ve learned_rules.json'a yazar
        rule_learned = experience_learner.record_failure(action, err_msg, desc)
        if rule_learned:
            screen_streamer.log_activity(f"💡 Yeni kural öğrenildi: {rule_learned}", level="WARN", tool=tool)

    screen_streamer.finish_task(task_tag)

    return {
        "id": sub_id,
        "action": action,
        "description": desc,
        "tool": tool,
        "success": success,
        "result": result_text,
        "error": error_text,
        "rule_learned": rule_learned,
        "elapsed_s": elapsed,
    }


async def _fallback_tool_exec(tool: str, params: dict) -> str:
    """Doğrudan temel araçları çağırabilen yerel icra motoru."""
    t = tool.lower()
    try:
        if t in ("open_app", "launch_app"):
            import subprocess
            app = params.get("app_name") or params.get("name") or "notepad"
            subprocess.Popen(app, shell=True)
            return f"✅ '{app}' başlatıldı."

        elif t in ("type_text", "write_text"):
            text = params.get("text", "")
            try:
                import pyautogui
                pyautogui.write(text, interval=0.03)
                return f"✅ Metin yazıldı: {text}"
            except Exception:
                import native_desktop
                w, _ = native_desktop._find_hwnd("Notepad") or native_desktop._find_hwnd("Not Defteri")
                if w:
                    native_desktop.focus_window(w["title"])
                import ctypes
                user32 = ctypes.windll.user32
                for ch in text:
                    vk = user32.VkKeyScanW(ord(ch))
                    user32.keybd_event(vk & 0xFF, 0, 0, 0)
                    user32.keybd_event(vk & 0xFF, 0, 2, 0)
                return f"✅ Metin ctypes ile yazıldı: {text}"

        elif t in ("wait", "sleep"):
            sec = float(params.get("seconds", 2.0))
            await asyncio.sleep(sec)
            return f"✅ {sec} saniye beklendi."

        elif t in ("click", "click_at"):
            import pyautogui
            x = int(params.get("x", 100))
            y = int(params.get("y", 100))
            pyautogui.click(x, y)
            return f"✅ ({x}, {y}) noktasına tıklandı."

        elif t in ("take_screenshot", "screenshot"):
            import screen_streamer
            shot = await asyncio.to_thread(screen_streamer._capture_screen_jpeg_base64)
            return f"✅ Ekran görüntüsü alındı ({len(shot or '')} bayt)."

        elif t in ("focus_window", "list_windows", "close_window"):
            import native_desktop
            fn = getattr(native_desktop, t, None)
            if fn:
                res = fn(**params)
                return str(res)
            return f"❌ native_desktop üzerinde '{t}' bulunamadı."

        elif t in ("read_file", "write_file"):
            p = params.get("path", "")
            if t == "read_file":
                with open(p, "r", encoding="utf-8") as f:
                    return f.read()[:2000]
            else:
                with open(p, "w", encoding="utf-8") as f:
                    f.write(params.get("content", ""))
                return f"✅ Dosya yazıldı: {p}"

        else:
            return f"ℹ️ Araç '{tool}' yerel olarak çalıştırılamadı, parametreler: {params}"
    except Exception as ex:
        return f"❌ Fallback araç hatası ({tool}): {ex}"
