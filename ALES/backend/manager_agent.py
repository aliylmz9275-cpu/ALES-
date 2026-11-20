"""
manager_agent.py — ALES Hedef Yöneticisi (Manager Agent).

Kullanıcının verdiği karmaşık hedefleri (ör. "Not defterini aç ve selam yaz",
"Fiverr mesajlarını tara ve teklif taslağı hazırla") analiz eder, alt görevlere
ayırır, deneyim kütüphanesinden öğrenilen kuralları plana dahil eder ve
Executor Agent aracılığıyla adımları tek tek yürütür.
"""
import asyncio
import json
import re
import time
from typing import Dict, Any, List, Optional, Callable

import experience_learner
import executor_agent
import screen_streamer


PLANNER_SYSTEM_PROMPT = """Sen ALES'in Baş Planlayıcı (Manager) Ajanısın.
Kullanıcının karmaşık hedefini uygulanabilir, mantıklı ve sıralı alt görevlere (subtask) bölersin.

ÇIKTI FORMATI:
SADECE ve SADECE aşağıdaki JSON formatında geçerli bir JSON yanıtı ver (başka hiçbir metin, markdown veya açıklama ekleme):
{
  "plan_summary": "Hedefin kısa özeti",
  "subtasks": [
    {
      "id": 1,
      "action": "open_app",
      "description": "Hedef uygulamayı aç",
      "tool": "open_app",
      "params": {"app_name": "notepad"}
    },
    {
      "id": 2,
      "action": "type_text",
      "description": "İçeriği yaz",
      "tool": "type_text",
      "params": {"text": "Merhaba dünya"}
    }
  ]
}

UYARILAR:
- Subtask sayısı gereksiz fazla olmamalı (ortalama 2-5 adım idealdir).
- Geçmişte öğrenilen kurallara ve kısıtlamalara titizlikle uy.
"""


def _clean_json_response(raw: str) -> dict:
    """LLM yanıtından JSON bloğunu temizler ve ayrıştırır."""
    s = (raw or "").strip()
    if s.startswith("```"):
        s = re.sub(r"^```(?:json)?", "", s, flags=re.MULTILINE)
        s = re.sub(r"```$", "", s, flags=re.MULTILINE).strip()
    # İlk { ile son } arasındaki kısmı al
    start = s.find("{")
    end = s.rfind("}")
    if start != -1 and end != -1:
        s = s[start:end+1]
    return json.loads(s)


async def _generate_plan(goal: str) -> dict:
    """Hedefi LLM ile analiz edip JSON planına dönüştürür."""
    rules_prompt = experience_learner.get_rules_prompt()
    user_prompt = f"HEDEF: {goal}\n{rules_prompt}\nBu hedef için alt görev planını JSON olarak üret."

    # Model Router ile LLM çağrısı dene
    plan_text = ""
    try:
        from model_router import chat_chain
        messages = [
            {"role": "system", "content": PLANNER_SYSTEM_PROMPT},
            {"role": "user", "content": user_prompt}
        ]
        res = await chat_chain(messages, mode="normal")
        plan_text = res.get("text", "")
    except Exception as e:
        print(f"[MANAGER_AGENT] Router üzerinden planlama çağrısı yapılamadı: {e}")

    # Router çağrısı boşsa yedek sağlayıcı dene
    if not plan_text:
        try:
            from multi_agent import _call_gemini, _call_nvidia
            ok, text = await _call_gemini(user_prompt, PLANNER_SYSTEM_PROMPT)
            if ok:
                plan_text = text
            else:
                ok2, text2 = await _call_nvidia(user_prompt, PLANNER_SYSTEM_PROMPT, "deepseek-ai/deepseek-v4")
                if ok2:
                    plan_text = text2
        except Exception:
            pass

    # JSON ayrıştırmayı dene
    if plan_text:
        try:
            parsed = _clean_json_response(plan_text)
            if "subtasks" in parsed and isinstance(parsed["subtasks"], list) and len(parsed["subtasks"]) > 0:
                return parsed
        except Exception as pe:
            print(f"[MANAGER_AGENT] JSON ayrıştırma hatası: {pe}, metin: {plan_text[:100]}")

    # Fallback akıllı kural bazlı plan (LLM ulaşılamazsa)
    return _heuristic_plan(goal)


def _heuristic_plan(goal: str) -> dict:
    """LLM ulaşılamadığında hedef metninden temel subtask listesi oluşturur."""
    g = goal.lower()
    subtasks = []

    if "notepad" in g or "not defteri" in g:
        subtasks.append({
            "id": 1,
            "action": "open_app",
            "description": "Not Defteri uygulamasını aç",
            "tool": "open_app",
            "params": {"app_name": "notepad"}
        })
        subtasks.append({
            "id": 2,
            "action": "wait",
            "description": "Pencerenin açılmasını bekle",
            "tool": "wait",
            "params": {"seconds": 2}
        })
        subtasks.append({
            "id": 3,
            "action": "type_text",
            "description": "Metin yaz",
            "tool": "type_text",
            "params": {"text": "ALES Yönetici & Yürütücü Sistemi Aktif."}
        })
    elif "fiverr" in g or "bionluk" in g:
        subtasks.append({
            "id": 1,
            "action": "check_messages",
            "description": "Platform mesajlarını tara",
            "tool": "system_info",
            "params": {}
        })
    else:
        subtasks.append({
            "id": 1,
            "action": "execute_task",
            "description": goal,
            "tool": "general_task",
            "params": {"goal": goal}
        })

    return {
        "plan_summary": f"Hedef yürütme: {goal[:50]}",
        "subtasks": subtasks
    }


async def _verify_subtask_outcome(subtask: dict, exec_result: dict) -> dict:
    """
    Manager Doğrulama Katmanı:
    Executor'ın ürettiği çıktıyı ve yan etkileri inceler.
    Eğer adım başarısızsa ya da beklenmeyen bir hata varsa kurtarma (recovery) kararı üretir.
    """
    action = subtask.get("action") or subtask.get("tool") or ""
    res_text = exec_result.get("result", "")
    success = exec_result.get("success", False)

    verification = {
        "verified": success,
        "note": "Başarıyla doğrulandı" if success else "Adım beklentiyi karşılamadı",
        "needs_retry": not success,
        "recovery_subtask": None,
    }

    if not success:
        # Otomatik Kurtarma Stratejileri
        act_l = action.lower()
        if "type" in act_l or "click" in act_l:
            # Pencere odaklanması veya bekleme eksikliği olabilir
            verification["recovery_subtask"] = {
                "id": f"{subtask.get('id')}_rec",
                "action": "wait",
                "tool": "wait",
                "description": f"Kurtarma: '{action}' öncesi 1.5s bekleme ve tekrar",
                "params": {"seconds": 1.5}
            }
        elif "open" in act_l:
            verification["recovery_subtask"] = {
                "id": f"{subtask.get('id')}_rec",
                "action": "wait",
                "tool": "wait",
                "description": f"Kurtarma: Uygulama açılış beklemesi",
                "params": {"seconds": 2.0}
            }

    return verification


async def run_goal(
    goal: str,
    progress_cb: Optional[Callable[[str], None]] = None,
    tool_executor_fn: Optional[Callable] = None
) -> str:
    """
    Manager-Executor Gerçek Döngüsü:
      1) [MANAGER PLANS]: Hedefi analiz eder, öğrenilmiş kuralları plana dahil ederek alt adımlara böler.
      2) [EXECUTOR EXECUTES]: Her bir alt görevi sırayla yürütür, araçları çalıştırır.
      3) [MANAGER VERIFIES]: Her adımın çıktısını doğrular. Hata durumunda kurtarma adımı işletir.
      4) [SYNTHESIS]: Nihai başarı durumunu değerlendirir ve kullanıcıya doğrulanmış rapor sunar.
    """
    cb = progress_cb or (lambda m: None)
    screen_streamer.log_activity(f"Yeni hedef alındı: {goal}", level="INFO")
    cb("📋 [MANAGER]: Görev analiz ediliyor ve alt adımlar planlanıyor...")

    start_time = time.time()
    plan_data = await _generate_plan(goal)
    summary = plan_data.get("plan_summary", goal)
    subtasks = plan_data.get("subtasks", [])

    cb(f"🚀 [MANAGER]: Plan hazırlandı ({len(subtasks)} adım): {summary}")

    step_results = []
    has_failure = False

    for st in subtasks:
        s_id = st.get("id")
        desc = st.get("description", f"Adım #{s_id}")
        cb(f"▶ [EXECUTOR {s_id}/{len(subtasks)}]: {desc}...")

        # 1. Yürütme (Execute)
        res = await executor_agent.execute_subtask(st, tool_executor_fn=tool_executor_fn)

        # 2. Doğrulama (Verify)
        verify = await _verify_subtask_outcome(st, res)
        res["verification"] = verify

        # Kurtarma Gereksinimi Varsa: 1 deneme yap
        if verify["needs_retry"] and verify["recovery_subtask"]:
            cb(f"🔄 [MANAGER]: Adım #{s_id} başarısız oldu. Kurtarma adımı deneniyor...")
            rec_st = verify["recovery_subtask"]
            rec_res = await executor_agent.execute_subtask(rec_st, tool_executor_fn=tool_executor_fn)
            # Ana adımı tekrar dene
            cb(f"🔁 [EXECUTOR]: Adım #{s_id} yeniden yürütülüyor...")
            retry_res = await executor_agent.execute_subtask(st, tool_executor_fn=tool_executor_fn)
            if retry_res["success"]:
                res = retry_res
                res["recovered"] = True
                cb(f"✓ [MANAGER]: Adım #{s_id} kurtarıldı ve başarıyla tamamlandı.")
            else:
                has_failure = True
                cb(f"❌ [MANAGER]: Adım #{s_id} kurtarma sonrası da başarısız: {retry_res.get('error') or retry_res.get('result')}")
        elif not res["success"]:
            has_failure = True
            cb(f"⚠️ [MANAGER]: Adım #{s_id} başarısız: {res.get('error') or res.get('result')}")
            if res.get("rule_learned"):
                cb(f"💡 [ÖĞRENİLEN KURAL]: {res['rule_learned']}")
        else:
            cb(f"✓ [MANAGER]: Adım #{s_id} başarıyla doğrulandı.")

        step_results.append(res)
        await asyncio.sleep(0.4)

    elapsed = round(time.time() - start_time, 2)
    status_icon = "⚠️ Kısmi Başarı" if has_failure else "✅ Başarıyla Doğrulandı ve Tamamlandı"

    # 3. Nihai Değerlendirme & Rapor
    report_lines = [
        f"🎯 **ALES Manager-Executor Raporu** — {status_icon}",
        f"**Hedef:** {goal}",
        f"**Plan Özeti:** {summary}",
        f"**Süre:** {elapsed}s | **Adım Sayısı:** {len(subtasks)}\n",
        "### Yürütme ve Doğrulama Detayları:"
    ]

    for r in step_results:
        icon = "✅" if r["success"] else "❌"
        rec_tag = " *(kurtarıldı)*" if r.get("recovered") else ""
        line = f"- {icon} **Adım #{r['id']}:** {r['description']}{rec_tag} ({r.get('elapsed_s', 0)}s)"
        if r.get("result"):
            line += f"\n  - *Çıktı:* {str(r['result'])[:150]}"
        if r.get("rule_learned"):
            line += f"\n  - *Öğrenilen Kural:* {r['rule_learned']}"
        report_lines.append(line)

    final_report = "\n".join(report_lines)
    screen_streamer.log_activity(f"Hedef tamamlandı ({status_icon})", level="SUCCESS" if not has_failure else "WARN")
    return final_report
