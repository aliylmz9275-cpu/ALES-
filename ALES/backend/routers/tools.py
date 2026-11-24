"""
routers/tools.py — ALES Araç, Doküman ve PDF Yürütme Router'ı.
"""

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse
from typing import Dict, Any
from pathlib import Path
import json

try:
    import document_generator
except Exception:
    document_generator = None

router = APIRouter(prefix="/api", tags=["Tools"])


@router.get("/download/pdf/{filename}")
async def download_pdf_endpoint(filename: str):
    """Oluşturulan PDF belgesini indirir."""
    if document_generator is None:
        raise HTTPException(status_code=500, detail="Belge üretim modülü aktif değil")
    p = document_generator.get_pdf_path(filename)
    if not p or not p.exists():
        raise HTTPException(status_code=404, detail="Dosya bulunamadı")
    return FileResponse(
        path=str(p),
        media_type="application/pdf",
        filename=p.name
    )


@router.post("/document/generate")
async def generate_document_endpoint(data: Dict[str, Any]):
    """Doğrudan PDF/doküman üretim API'si."""
    if document_generator is None:
        return {"ok": False, "error": "document_generator modülü yüklü değil"}
    title = data.get("title", "Belge")
    content = data.get("content", "")
    res = document_generator.generate_pdf(title, content)
    return res
