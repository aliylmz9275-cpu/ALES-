"""
routers/profiles.py — ALES Profil ve API Anahtarı Yönetimi Router'ı.
"""

from fastapi import APIRouter, HTTPException, Request
from typing import Dict, Any
import profile_manager

router = APIRouter(prefix="/api", tags=["Profiles"])


@router.post("/profile/save")
async def save_profile_endpoint(data: Dict[str, Any]):
    """Kullanıcı profilini ve API anahtarlarını SQLite'a kaydeder."""
    code = (data.get("access_code") or data.get("code") or "").strip()
    name = (data.get("name") or "").strip()
    if not code:
        return {"ok": False, "error": "access_code boş olamaz"}
    res = profile_manager.save_profile(code, name, data)
    return res


@router.post("/profile/load")
async def load_profile_endpoint(data: Dict[str, Any]):
    """Erişim koduna göre profili ve API anahtarlarını yükler."""
    code = (data.get("access_code") or data.get("code") or "").strip()
    if not code:
        return {"ok": False, "error": "access_code boş olamaz"}
    res = profile_manager.load_profile(code)
    return res


@router.get("/profiles")
async def list_profiles_endpoint():
    """Kayıtlı profilleri maskeli anahtarlarla listeler."""
    return {"ok": True, "profiles": profile_manager.list_profiles()}


@router.delete("/profile/{access_code}")
async def delete_profile_endpoint(access_code: str):
    """Profili siler."""
    ok = profile_manager.delete_profile(access_code)
    return {"ok": ok}
