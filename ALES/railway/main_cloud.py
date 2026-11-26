"""
ALES Cloud Entrypoint (Render / Railway)

Uses the unified FastAPI app from backend/main.py (Claude Code 7-pillar loop,
Access Code SQLite auth, ChromaDB memory, Plans, WebSocket /ws, and static dist/).
"""
import os
import sys
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
BACKEND_DIR = BASE_DIR / "backend"
if not BACKEND_DIR.exists():
    for _b in [Path("/app/backend"), Path("backend"), Path("ALES/backend")]:
        if _b.exists():
            BACKEND_DIR = _b
            break

sys.path.insert(0, str(BACKEND_DIR))

from main import app  # noqa: E402, F401

if __name__ == "__main__":
    import uvicorn
    port = int(os.environ.get("PORT", 10000))
    print(f"[ALES CLOUD] Starting on http://0.0.0.0:{port}")
    uvicorn.run(app, host="0.0.0.0", port=port, log_level="info")
