"""
routers/terminal.py — ALES Terminal ve Kodlama Ajanı Komut Yürütücü Router'ı.
"""

from fastapi import APIRouter
from pathlib import Path
from typing import Dict, Any
import subprocess
import os

router = APIRouter(prefix="/api/terminal", tags=["Terminal"])


def run_terminal_command_internal(cmd: str, timeout: int = 45, cwd: str = None) -> Dict[str, Any]:
    """Komut satırında komut çalıştırır ve yapılandırılmış çıktı döner."""
    if not cmd or not str(cmd).strip():
        return {"ok": False, "error": "Komut boş olamaz"}

    cmd_str = str(cmd).strip()
    root_dir = Path(__file__).resolve().parent.parent.parent
    exec_cwd = str(root_dir)
    if cwd and os.path.isdir(cwd):
        exec_cwd = cwd

    try:
        res = subprocess.run(
            cmd_str,
            shell=True,
            capture_output=True,
            text=True,
            timeout=timeout,
            cwd=exec_cwd
        )
        return {
            "ok": True,
            "command": cmd_str,
            "exit_code": res.returncode,
            "stdout": res.stdout or "",
            "stderr": res.stderr or "",
            "cwd": exec_cwd
        }
    except subprocess.TimeoutExpired:
        return {
            "ok": False,
            "command": cmd_str,
            "exit_code": -1,
            "stdout": "",
            "stderr": f"⏱️ Komut zaman aşımına uğradı ({timeout}s).",
            "cwd": exec_cwd,
            "error": "Timeout"
        }
    except Exception as e:
        return {
            "ok": False,
            "command": cmd_str,
            "exit_code": 1,
            "stdout": "",
            "stderr": str(e),
            "cwd": exec_cwd,
            "error": str(e)
        }


@router.post("/run")
async def terminal_run_endpoint(data: Dict[str, Any]):
    """Terminalde komut çalıştırır."""
    cmd = (data.get("command") or data.get("cmd") or "").strip()
    timeout = int(data.get("timeout") or 45)
    cwd = data.get("cwd")
    res = run_terminal_command_internal(cmd, timeout=timeout, cwd=cwd)
    return res
