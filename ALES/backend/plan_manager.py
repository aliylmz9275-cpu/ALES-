"""
plan_manager.py — ALES Görev ve Eylem Planlama Modülü (Task Planning).

Kullanıcının hedeflerini adım adım planlara (JSON tabanlı) böler,
araçları (tool) plan adımlarıyla eşleştirir, adım adım yürütür
ve her adımın durumunu (bekliyor, yürütülüyor, tamamlandı, hata) kaydeder.
"""

import json
import re
import uuid
from datetime import datetime
from pathlib import Path
from typing import Dict, Any, List, Optional

try:
    from config_manager import get_appdata_dir
    PLANS_DIR = get_appdata_dir()
except Exception:
    PLANS_DIR = Path(__file__).resolve().parent

PLANS_FILE = PLANS_DIR / "ales_plans.json"


def _load_all_plans() -> Dict[str, Any]:
    """Tüm planları dosyadan okur."""
    if not PLANS_FILE.exists():
        return {}
    try:
        with open(PLANS_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        print(f"[PLAN] Plan okuma hatası: {e}")
        return {}


def _save_all_plans(plans: Dict[str, Any]):
    """Tüm planları dosyaya kaydeder."""
    PLANS_DIR.mkdir(parents=True, exist_ok=True)
    try:
        with open(PLANS_FILE, "w", encoding="utf-8") as f:
            json.dump(plans, f, ensure_ascii=False, indent=2)
    except Exception as e:
        print(f"[PLAN] Plan kaydetme hatası: {e}")


def create_plan(goal: str, title: str = "", steps: List[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Yeni bir görev planı oluşturur."""
    goal_str = (goal or "").strip()
    plan_id = f"plan_{uuid.uuid4().hex[:8]}"
    now = datetime.now().isoformat()
    plan_title = (title or goal_str[:50] or "Yeni Görev Planı").strip()

    formatted_steps = []
    raw_steps = steps or [
        {"title": "Gereksinimleri ve Dosyaları İncele", "description": f"'{goal_str}' için ortam ve girdi analizi", "tool": "read_file", "args": {}},
        {"title": "İşlemleri ve Kodu Yürüt", "description": "Gerekli komut ve düzenlemeleri uygula", "tool": "run_terminal_command", "args": {}},
        {"title": "Sonuçları Doğrula", "description": "İşlem çıktısını ve başarıyı test et", "tool": "run_terminal_command", "args": {}},
    ]

    for idx, s in enumerate(raw_steps, 1):
        formatted_steps.append({
            "id": s.get("id") or idx,
            "title": s.get("title") or f"Adım {idx}",
            "description": s.get("description") or "",
            "tool": s.get("tool") or "think",
            "args": s.get("args") or {},
            "status": s.get("status") or "pending",  # pending | running | completed | failed
            "result": s.get("result") or None,
            "updated_at": now
        })

    plan = {
        "id": plan_id,
        "title": plan_title,
        "goal": goal_str,
        "status": "pending",  # pending | running | completed | failed
        "created_at": now,
        "updated_at": now,
        "steps": formatted_steps
    }

    plans = _load_all_plans()
    plans[plan_id] = plan
    _save_all_plans(plans)
    return plan


def get_plan(plan_id: str) -> Optional[Dict[str, Any]]:
    """Tek bir planı döner."""
    plans = _load_all_plans()
    return plans.get(plan_id)


def list_plans() -> List[Dict[str, Any]]:
    """Tüm planları oluşturulma tarihine göre döner."""
    plans = _load_all_plans()
    plan_list = list(plans.values())
    plan_list.sort(key=lambda x: x.get("created_at", ""), reverse=True)
    return plan_list


def delete_plan(plan_id: str) -> bool:
    """Planı siler."""
    plans = _load_all_plans()
    if plan_id in plans:
        del plans[plan_id]
        _save_all_plans(plans)
        return True
    return False


def update_plan_step(plan_id: str, step_id: int, status: str, result: str = None) -> Optional[Dict[str, Any]]:
    """Belirli bir adımın durumunu günceller."""
    plans = _load_all_plans()
    plan = plans.get(plan_id)
    if not plan:
        return None

    now = datetime.now().isoformat()
    step_found = False
    for step in plan.get("steps", []):
        if step.get("id") == step_id:
            step["status"] = status
            if result is not None:
                step["result"] = str(result)
            step["updated_at"] = now
            step_found = True
            break

    if step_found:
        # Tüm adımların durumunu kontrol et
        all_completed = all(s.get("status") == "completed" for s in plan.get("steps", []))
        any_failed = any(s.get("status") == "failed" for s in plan.get("steps", []))
        any_running = any(s.get("status") == "running" for s in plan.get("steps", []))

        if any_failed:
            plan["status"] = "failed"
        elif all_completed:
            plan["status"] = "completed"
        elif any_running:
            plan["status"] = "running"
        else:
            plan["status"] = "pending"

        plan["updated_at"] = now
        plans[plan_id] = plan
        _save_all_plans(plans)

    return plan


async def generate_plan_with_llm(goal: str, caller_fn = None) -> Dict[str, Any]:
    """
    LLM'den hedef için yapılandırılmış (structured) JSON plan üretmesini ister.
    caller_fn: async (prompt, system_prompt) -> (ok, text)
    """
    system_prompt = """Sen Claude Code ve ALES seviyesinde uzman bir Görev ve Planlama Motorusun (Task Planner).
Kullanıcının verdiği hedefe göre mantıksal, sıralı ve uygulanabilir 3 ila 6 adımlı bir plan üretmelisin.
Her adım gerçek bir araçla (tool) ilişkilendirilmelidir.

Kullanılabilir Araçlar:
- run_terminal_command: Komut satırında test, build, pip, npm veya sistem komutu çalıştırma (args: {"cmd": "..."})
- read_file: Dosya içeriği okuma (args: {"path": "..."})
- write_file: Dosya içeriği yazma/oluşturma (args: {"path": "...", "content": "..."})
- edit_file: Dosyadaki metni değiştirme (args: {"path": "...", "old_text": "...", "new_text": "..."})
- generate_pdf: Rapor/belge üretme (args: {"title": "...", "content": "..."})
- web_search_deep: İnternette derin arama (args: {"query": "..."})
- think: Genel mantıksal analiz veya sentez adımı (args: {})

SADECE geçerli bir JSON objesi döndür. Markdown işareti (```json) kullanma veya içine sadece saf JSON koy.
Şema:
{
  "title": "Kısa Plan Başlığı",
  "steps": [
    {
      "title": "Adım Başlığı",
      "description": "Adımın ayrıntılı açıklaması",
      "tool": "run_terminal_command veya read_file veya write_file...",
      "args": { ... }
    }
  ]
}"""

    prompt = f"Hedef: {goal}\nLütfen yukarıdaki şemaya göre JSON formatında adım adım plan üret."

    steps_data = None
    if caller_fn:
        try:
            ok, text = await caller_fn(prompt, system_prompt)
            if ok and text:
                clean_text = text.strip()
                if "```json" in clean_text:
                    clean_text = clean_text.split("```json", 1)[1].split("```", 1)[0].strip()
                elif "```" in clean_text:
                    clean_text = clean_text.split("```", 1)[1].split("```", 1)[0].strip()

                parsed = json.loads(clean_text)
                if isinstance(parsed, dict) and "steps" in parsed:
                    return create_plan(goal, parsed.get("title", ""), parsed["steps"])
        except Exception as e:
            print(f"[PLAN] LLM plan üretim hatası: {e}")

    # Fallback plan
    fallback_steps = [
        {"title": "Gereksinimleri İncele", "description": f"'{goal}' hedefinin analiz edilmesi ve dosya yapısının taranması", "tool": "read_file", "args": {"path": "."}},
        {"title": "Geliştirme ve Kodlama", "description": "Gerekli dosyaların düzenlenmesi ve kod değişikliklerinin yazılması", "tool": "write_file", "args": {}},
        {"title": "Test ve Doğrulama", "description": "Yapılan değişikliklerin terminalde test edilmesi ve doğrulanması", "tool": "run_terminal_command", "args": {"cmd": "git status"}},
        {"title": "Sonuç Raporlama", "description": "Çalışmanın tamamlanarak kullanıcıya bildirilmesi", "tool": "think", "args": {}},
    ]
    return create_plan(goal, f"Plan: {goal[:40]}", fallback_steps)


async def execute_plan(plan_id: str, executor_fn = None) -> Dict[str, Any]:
    """
    Plan adımlarını sırayla yürütür, her adımın sonucunu kaydeder ve planı günceller.
    executor_fn: async (tool_name, args) -> str
    """
    plan = get_plan(plan_id)
    if not plan:
        return {"ok": False, "error": "Plan bulunamadı"}

    plan["status"] = "running"
    _save_all_plans({**_load_all_plans(), plan_id: plan})

    for step in plan.get("steps", []):
        step_id = step["id"]
        tool = step.get("tool") or "think"
        args = step.get("args") or {}

        update_plan_step(plan_id, step_id, "running")

        result = ""
        status = "completed"
        try:
            if executor_fn and tool != "think":
                res = await executor_fn(tool, args)
                result = str(res)
            else:
                result = f"✅ Adım başarıyla değerlendirildi: {step.get('title')}"
        except Exception as e:
            status = "failed"
            result = f"❌ Hata: {str(e)}"

        update_plan_step(plan_id, step_id, status, result)
        if status == "failed":
            break

    return get_plan(plan_id) or plan
