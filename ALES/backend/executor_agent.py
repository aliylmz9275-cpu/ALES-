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
        # Eğer dışarıdan tool_executor_fn verildiyse onu kullan
        if tool_executor_fn is not None:
            if asyncio.iscoroutinefunction(tool_executor_fn):
                res = await tool_executor_fn(tool, params)
            else:
                res = await asyncio.to_thread(tool_executor_fn, tool, params)
            result_text = str(res)
            success = not ("❌" in result_text or "HATA" in result_text.upper() or "ERROR" in result_text.upper())
        else:
            # Fallback doğrudan araç çağırma (native_desktop veya komut)
            result_text = await _fallback_tool_exec(tool, params)
            success = not ("❌" in result_text or "HATA" in result_text.upper() or "ERROR" in result_text.upper())

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
        # Hata öğrenme mekanizmasını tetikle
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
    if t in ("open_app", "launch_app"):
        import subprocess
        app = params.get("app_name") or params.get("name") or "notepad"
        subprocess.Popen(app, shell=True)
        return f"✅ '{app}' başlatıldı."
    elif t in ("type_text", "write_text"):
        import pyautogui
        text = params.get("text", "")
        pyautogui.write(text, interval=0.05)
        return f"✅ Metin yazıldı: {text}"
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
    else:
        return f"ℹ️ Araç '{tool}' yerel olarak çalıştırılamadı, parametreler: {params}"
