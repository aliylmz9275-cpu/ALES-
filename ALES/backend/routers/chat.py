"""
routers/chat.py — ALES Görev Planlayıcı ve Sohbet Destek Router'ı.
"""

from fastapi import APIRouter, HTTPException
from typing import Dict, Any
import plan_manager

router = APIRouter(prefix="/api", tags=["Chat & Plans"])


@router.post("/plan/create")
async def plan_create_endpoint(data: Dict[str, Any]):
    """Hedefe göre adım adım plan oluşturur."""
    goal = (data.get("goal") or "").strip()
    detail_level = data.get("detail_level", "medium")
    if not goal:
        return {"ok": False, "error": "Hedef belirtilmedi"}
    res = await plan_manager.generate_plan_with_llm(goal, detail_level)
    return res


@router.post("/plan/execute")
async def plan_execute_endpoint(data: Dict[str, Any]):
    """Planı sırayla yürütür."""
    plan_id = (data.get("plan_id") or "").strip()
    if not plan_id:
        return {"ok": False, "error": "plan_id belirtilmedi"}

    try:
        from main import execute_tool
        async def _exec_tool(tool_name, args):
            return execute_tool(tool_name, args)

        res = await plan_manager.execute_plan(plan_id, _exec_tool)
        return {"ok": True, "plan": res}
    except Exception as e:
        return {"ok": False, "error": str(e)}


@router.get("/plans")
async def list_plans_endpoint():
    """Tüm planları listeler."""
    return {"ok": True, "plans": plan_manager.list_plans()}


@router.get("/plan/{plan_id}")
async def get_plan_endpoint(plan_id: str):
    """Belirli bir planı döner."""
    p = plan_manager.get_plan(plan_id)
    if not p:
        raise HTTPException(status_code=404, detail="Plan bulunamadı")
    return {"ok": True, "plan": p}


@router.delete("/plan/{plan_id}")
async def delete_plan_endpoint(plan_id: str):
    """Planı siler."""
    ok = plan_manager.delete_plan(plan_id)
    return {"ok": ok}


@router.post("/models/refresh")
async def refresh_models_endpoint():
    """Canlı model listesini ve model registry'yi yeniler."""
    try:
        import model_registry
        res = await model_registry.refresh_all_models()
        return {"ok": True, "result": res}
    except Exception as e:
        return {"ok": False, "error": str(e)}
