"""
main.py — ALES: 1:1 Claude Code Engine v7.0

Architecture:
- Strict ReAct loop (max 15 turns): Think → Tool Call → Observation → Repeat
- 8 Core Primitives: bash, read_file, write_file, edit_file, grep_search, glob_search, task, todo_write
- Deny-first Permission System with WebSocket gate
- Auto-Compact at 70% context window
- Project Memory (ALES.md injection)
- Sub-Agent isolation via task() tool
- Access Code SQLite auth (profile_manager.py)
"""
import asyncio
import json
import os
import re
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

# ─── FROZEN EXE BOOT ───────────────────────────────────────────────
ALES_LOG_PATH = None
_FROZEN = False


def _boot_streams():
    global ALES_LOG_PATH, _FROZEN
    if sys.stdout is not None and sys.stderr is not None:
        return
    if not getattr(sys, "frozen", False):
        return
    _FROZEN = True
    try:
        d = os.path.dirname(os.path.abspath(sys.executable))
        p = os.path.join(d, "ALES_log.txt")
        big = os.path.exists(p) and os.path.getsize(p) > 2_000_000
        fh = open(p, "w" if big else "a", encoding="utf-8", errors="replace", buffering=1)
        ALES_LOG_PATH = p
    except Exception:
        try:
            fh = open(os.devnull, "w")
        except Exception:
            return
    if sys.stdout is None:
        sys.stdout = fh
    if sys.stderr is None:
        sys.stderr = fh
    print(f"\n{'='*60}\n[ALES] PID {os.getpid()} · {time.strftime('%Y-%m-%d %H:%M:%S')}\n{'='*60}")


_boot_streams()

from fastapi import FastAPI, WebSocket, WebSocketDisconnect, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from config_manager import BASE_SYSTEM, load_config, save_config, get_key
import profile_manager
from tool_router import TOOLS, execute_tool, get_cwd, get_todos
import voice

# ─── APP ───────────────────────────────────────────────────────────
app = FastAPI(title="ALES", version="7.0")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

MAX_AGENT_TURNS = 15
EXECUTOR = ThreadPoolExecutor(max_workers=4)

# ─── PROJECT MEMORY (ALES.md) ──────────────────────────────────────
def load_ales_md(cwd: str = None) -> str:
    search_dirs = [cwd] if cwd else []
    search_dirs.extend([os.getcwd(), str(Path.home())])
    for d in search_dirs:
        if not d:
            continue
        p = os.path.join(d, "ALES.md")
        if os.path.isfile(p):
            try:
                content = Path(p).read_text(encoding="utf-8", errors="replace")[:4000]
                return f"\n\n[ALES.md Project Memory]\n{content}\n"
            except Exception:
                pass
    return ""


# ─── PERMISSION SYSTEM (Deny-First) ───────────────────────────────
_PERMISSIONS_FILE = Path(__file__).parent / "permissions.json"
_permissions_cache = None


def _load_permissions() -> dict:
    global _permissions_cache
    if _permissions_cache is not None:
        return _permissions_cache
    try:
        _permissions_cache = json.loads(_PERMISSIONS_FILE.read_text(encoding="utf-8"))
    except Exception:
        _permissions_cache = {"destructive_patterns": [], "always_allow": []}
    return _permissions_cache


def is_destructive(command: str) -> bool:
    perms = _load_permissions()
    cmd_lower = command.lower().strip()
    for safe in perms.get("always_allow", []):
        if cmd_lower.startswith(safe.lower()):
            return False
    for pattern in perms.get("destructive_patterns", []):
        if pattern.lower() in cmd_lower:
            return True
    return False


_permission_requests: dict = {}
_permission_results: dict = {}


# ─── AUTO-COMPACT ──────────────────────────────────────────────────
def estimate_tokens(text: str) -> int:
    return max(1, len(text) // 3)


def should_compact(messages: list, max_context: int = 8192) -> bool:
    total = sum(estimate_tokens(json.dumps(m)) for m in messages)
    return total > int(max_context * 0.70)


async def auto_compact(messages: list, client_info: tuple) -> list:
    provider, client, model = client_info
    if len(messages) < 4:
        return messages
    system_msg = messages[0] if messages[0].get("role") == "system" else None
    conversation = messages[1:] if system_msg else messages
    summary_prompt = [
        {
            "role": "system",
            "content": (
                "Summarize this conversation in a dense paragraph. "
                "Keep: 1) Files created/modified with their paths, "
                "2) The current goal, 3) Errors encountered and fixes applied. "
                "Be concise and factual. Output only the summary."
            ),
        },
        {"role": "user", "content": json.dumps(conversation[-20:], ensure_ascii=False)[:6000]},
    ]
    try:
        resp = client.chat.completions.create(model=model, messages=summary_prompt, max_tokens=1024)
        summary = resp.choices[0].message.content
    except Exception:
        summary = None
    result = []
    if system_msg:
        result.append(system_msg)
    if summary:
        result.append({"role": "assistant", "content": f"[AUTO-COMPACT SUMMARY]\n{summary}"})
    result.extend(conversation[-4:])
    return result


# ─── LLM CLIENT CHAIN ──────────────────────────────────────────────
def get_clients() -> list:
    """Return ordered list of (provider, client, model) tuples for fallback."""
    from openai import OpenAI

    clients = []
    if k := get_key("groq_key"):
        groq_client = OpenAI(api_key=k, base_url="https://api.groq.com/openai/v1")
        clients.append(("groq", groq_client, "moonshotai/kimi-k2-instruct"))
        clients.append(("groq", groq_client, "openai/gpt-oss-120b"))
    if k := get_key("gemini_key"):
        clients.append((
            "gemini",
            OpenAI(api_key=k, base_url="https://generativelanguage.googleapis.com/v1beta/openai/"),
            "gemini-2.0-flash",
        ))
    if k := get_key("openrouter_key"):
        clients.append((
            "openrouter",
            OpenAI(api_key=k, base_url="https://openrouter.ai/api/v1"),
            "qwen/qwen3-72b",
        ))
    if k := get_key("nvidia_key"):
        clients.append((
            "nvidia",
            OpenAI(api_key=k, base_url="https://integrate.api.nvidia.com/v1"),
            "nvidia/llama-3.1-nemotron-70b-instruct",
        ))
    return clients


def get_client():
    clients = get_clients()
    if clients:
        return clients[0][0], clients[0][1]
    return None, None


# ─── THOUGHT PARSER ────────────────────────────────────────────────
_THOUGHT_RE = re.compile(r"<thought>(.*?)</thought>", re.DOTALL | re.IGNORECASE)


def _extract_thoughts(text: str) -> tuple:
    if not text:
        return [], ""
    thoughts = [t.strip() for t in _THOUGHT_RE.findall(text) if t.strip()]
    cleaned = _THOUGHT_RE.sub("", text).strip()
    return thoughts, cleaned


# ─── THE REACT LOOP (STRICT CLAUDE CODE ENGINE) ────────────────────
async def run_agent(user_message: str, ws: WebSocket = None, conversation_history: list = None):
    """
    Strict 15-iteration ReAct loop.

    Flow each turn:
      1. LLM receives messages + 8-tool schemas
      2. If <thought> tags present → stream to UI as 🧠
      3. If tool_calls present → execute tool → append Observation → loop
      4. If no tool_calls → final answer, return
      5. On bash failure (stderr / exit!=0) → feed error back, LLM self-corrects
      6. On LLM error → try next provider in fallback chain
    """
    clients = get_clients()
    if not clients:
        yield {"type": "error", "content": "❌ API anahtarı yapılandırılmamış. Ayarlar'dan bir API anahtarı girin."}
        return

    client_idx = 0
    provider, client, default_model = clients[client_idx]
    cfg = load_config()
    model = cfg.get("model") or default_model

    cwd = get_cwd()
    system_prompt = (
        BASE_SYSTEM
        + load_ales_md(cwd)
        + f"\n\nCurrent working directory: {cwd}"
        + f"\nDate/time: {time.strftime('%Y-%m-%d %H:%M:%S')}"
    )

    if conversation_history is None:
        conversation_history = []

    messages = [{"role": "system", "content": system_prompt}]
    messages.extend(conversation_history)
    messages.append({"role": "user", "content": user_message})

    # Auto-compact check
    if should_compact(messages):
        yield {"type": "status", "content": "🗜️ Bağlam çok büyük, otomatik sıkıştırma yapılıyor..."}
        messages = await auto_compact(messages, (provider, client, model))
        yield {"type": "status", "content": "✅ Auto-compact tamamlandı."}

    turn = 0
    used_tools = False

    while turn < MAX_AGENT_TURNS:
        turn += 1
        yield {"type": "thinking", "content": f"Turn {turn}/{MAX_AGENT_TURNS} · {provider}:{model}"}

        try:
            response = client.chat.completions.create(
                model=model,
                messages=messages,
                tools=TOOLS,
                tool_choice="auto",
                max_tokens=4096,
                temperature=0.1,
            )
            msg = response.choices[0].message

            # Stream <thought> tags
            thoughts, clean_text = _extract_thoughts(msg.content or "")
            for th in thoughts:
                yield {"type": "thought", "content": th}

            # No tool calls → final answer
            if not msg.tool_calls:
                if used_tools:
                    yield {"type": "status", "content": "✅ Görev tamamlandı."}
                yield {"type": "response", "content": clean_text or "(Tamamlandı)"}
                return

            # Append assistant message with tool calls
            used_tools = True
            messages.append({
                "role": "assistant",
                "content": msg.content or "",
                "tool_calls": [
                    {
                        "id": tc.id,
                        "type": "function",
                        "function": {"name": tc.function.name, "arguments": tc.function.arguments},
                    }
                    for tc in msg.tool_calls
                ],
            })

            # Execute each tool call
            for tool_call in msg.tool_calls:
                fn_name = tool_call.function.name
                try:
                    fn_args = json.loads(tool_call.function.arguments)
                except Exception:
                    fn_args = {}

                # ── PERMISSION GATE (bash only, deny-first) ──────────
                if fn_name in ("bash", "run_bash") and is_destructive(fn_args.get("command", "")):
                    cmd = fn_args.get("command", "")
                    yield {"type": "permission_request", "command": cmd, "tool_call_id": tool_call.id}
                    req_id = tool_call.id
                    _permission_requests[req_id] = asyncio.Event()
                    _permission_results[req_id] = None
                    try:
                        await asyncio.wait_for(_permission_requests[req_id].wait(), timeout=120)
                    except asyncio.TimeoutError:
                        _permission_results[req_id] = False
                    allowed = _permission_results.pop(req_id, False)
                    _permission_requests.pop(req_id, None)

                    if not allowed:
                        observation = "Observation: Kullanıcı bu komutu reddetti. Farklı bir yaklaşım dene."
                        yield {"type": "tool_denied", "tool": fn_name, "command": cmd}
                    else:
                        yield {"type": "tool_call", "tool": fn_name, "args": fn_args}
                        raw_out = await asyncio.get_event_loop().run_in_executor(
                            EXECUTOR, execute_tool, fn_name, fn_args
                        )
                        observation = f"Observation:\n{raw_out}"
                        yield {"type": "tool_result", "tool": fn_name, "result": raw_out[:3000]}

                # ── TODO_WRITE: also broadcast todos to UI ────────────
                elif fn_name == "todo_write":
                    yield {"type": "tool_call", "tool": fn_name, "args": fn_args}
                    raw_out = await asyncio.get_event_loop().run_in_executor(
                        EXECUTOR, execute_tool, fn_name, fn_args
                    )
                    observation = f"Observation:\n{raw_out}"
                    yield {"type": "tool_result", "tool": fn_name, "result": raw_out}
                    # Broadcast updated todos to frontend
                    yield {"type": "todos", "items": get_todos()}

                # ── ALL OTHER TOOLS ───────────────────────────────────
                else:
                    yield {"type": "tool_call", "tool": fn_name, "args": fn_args}
                    raw_out = await asyncio.get_event_loop().run_in_executor(
                        EXECUTOR, execute_tool, fn_name, fn_args
                    )
                    observation = f"Observation:\n{raw_out}"
                    yield {"type": "tool_result", "tool": fn_name, "result": raw_out[:3000]}

                # Append tool result as observation
                messages.append({
                    "role": "tool",
                    "tool_call_id": tool_call.id,
                    "content": observation[:5000],
                })

        except Exception as e:
            # Try next provider in fallback chain
            if client_idx + 1 < len(clients):
                prev_label = f"{provider}:{model}"
                client_idx += 1
                provider, client, default_model = clients[client_idx]
                model = cfg.get("model") or default_model
                yield {
                    "type": "status",
                    "content": f"⚠️ {prev_label} hata verdi ({str(e)[:80]}), {provider}:{model} deneniyor...",
                }
                turn -= 1
                continue
            yield {"type": "error", "content": f"LLM Hatası: {e}"}
            return

    yield {"type": "response", "content": "⚠️ Maksimum tur sayısına (15) ulaşıldı. Görev tamamlanmamış olabilir."}


# ─── WEBSOCKET ENDPOINT ──────────────────────────────────────────
_conversations: dict = {}


@app.websocket("/ws")
async def websocket_endpoint(ws: WebSocket):
    await ws.accept()
    conn_id = id(ws)
    _conversations[conn_id] = []

    try:
        while True:
            data = await ws.receive_json()
            msg_type = data.get("type", "chat")

            if msg_type == "chat":
                user_msg = data.get("message", "")
                if not user_msg.strip():
                    continue
                _conversations[conn_id].append({"role": "user", "content": user_msg})

                async for event in run_agent(user_msg, ws, _conversations[conn_id]):
                    await ws.send_json(event)
                    if event["type"] == "response":
                        _conversations[conn_id].append({"role": "assistant", "content": event["content"]})
                        # Trim history to avoid unbounded growth (keep last 30 exchanges)
                        if len(_conversations[conn_id]) > 60:
                            _conversations[conn_id] = _conversations[conn_id][-40:]

            elif msg_type == "permission_response":
                req_id = data.get("tool_call_id")
                allowed = data.get("allowed", False)
                if req_id in _permission_requests:
                    _permission_results[req_id] = allowed
                    _permission_requests[req_id].set()

            elif msg_type == "clear":
                _conversations[conn_id] = []
                await ws.send_json({"type": "status", "content": "Konuşma temizlendi."})
                await ws.send_json({"type": "todos", "items": []})

    except WebSocketDisconnect:
        _conversations.pop(conn_id, None)
    except Exception as e:
        print(f"[WS ERROR] {e}")
        _conversations.pop(conn_id, None)


# ─── REST ENDPOINTS ──────────────────────────────────────────────
@app.get("/status")
def status():
    provider, client = get_client()
    return {
        "status": "running",
        "version": "7.0",
        "provider": provider,
        "has_key": client is not None,
        "cwd": get_cwd(),
        "tools": len(TOOLS),
        "architecture": "Claude Code 1:1 (8 Primitives: bash, read_file, write_file, edit_file, grep_search, glob_search, task, todo_write)",
    }


@app.get("/config")
def get_config():
    cfg = load_config()
    masked = {}
    for k, v in cfg.items():
        if k.endswith("_key") and v:
            masked[k] = v[:8] + "..." if len(v) > 8 else "***"
        else:
            masked[k] = v
    return masked


@app.post("/config")
async def set_config(request: Request):
    data = await request.json()
    cfg = load_config()
    cfg.update(data)
    save_config(cfg)
    return {"ok": True}


# ─── ACCESS CODE PROFILE AUTH (SQLite) ───────────────────────────
_ENV_KEY_MAP = {
    "groq_key": "GROQ_API_KEY",
    "gemini_key": "GEMINI_API_KEY",
    "openrouter_key": "OPENROUTER_API_KEY",
    "nvidia_key": "NVIDIA_API_KEY",
    "openai_key": "OPENAI_API_KEY",
    "elevenlabs_key": "ELEVENLABS_API_KEY",
    "cerebras_key": "CEREBRAS_API_KEY",
    "sambanova_key": "SAMBANOVA_API_KEY",
}


def _load_keys_into_session(keys: dict):
    cfg = load_config()
    for k, val in (keys or {}).items():
        if val and str(val).strip():
            clean_val = str(val).strip()
            cfg[k] = clean_val
            if k in _ENV_KEY_MAP:
                os.environ[_ENV_KEY_MAP[k]] = clean_val
    save_config(cfg)


@app.post("/api/profile/save")
async def api_profile_save(request: Request):
    data = await request.json()
    code = (data.get("access_code") or "").strip()
    name = (data.get("name") or "").strip()
    keys = data.get("keys") or data
    res = profile_manager.save_profile(code, name, keys)
    if res.get("ok"):
        _load_keys_into_session(keys)
    return res


@app.post("/api/profile/load")
@app.get("/api/profile/load")
async def api_profile_load(request: Request):
    if request.method == "POST":
        body = await request.json()
        code = (body.get("access_code") or "").strip()
    else:
        code = (request.query_params.get("access_code") or "").strip()

    res = profile_manager.load_profile(code)
    if not res.get("ok"):
        return JSONResponse(
            {"success": False, "ok": False, "error": res.get("error", "Geçersiz erişim kodu")},
            status_code=401,
        )
    _load_keys_into_session(res.get("keys", {}))
    return {
        "success": True,
        "ok": True,
        "message": "Giriş başarılı",
        "name": res.get("name", ""),
        "access_code": res.get("access_code", code),
    }


@app.get("/api/profiles")
def api_profiles_list():
    return {"ok": True, "profiles": profile_manager.list_profiles()}


@app.post("/speak")
async def speak(request: Request):
    data = await request.json()
    text = data.get("text", "")
    voice_id = data.get("voice", "nova")
    if not text:
        return {"ok": False, "error": "No text"}
    try:
        return await voice.synthesize(text, voice_id=voice_id)
    except Exception as e:
        return {"ok": False, "error": str(e)}


# ─── STATIC FRONTEND (Cloud / Web UI) ───────────────────────────
_DIST_CANDIDATES = [
    Path(__file__).resolve().parent.parent / "dist",
    Path("/app/dist"),
    Path("dist"),
]
_DIST_DIR = next((d for d in _DIST_CANDIDATES if d.exists() and (d / "index.html").exists()), None)

if _DIST_DIR is not None:
    _assets_dir = _DIST_DIR / "assets"
    if _assets_dir.exists():
        app.mount("/assets", StaticFiles(directory=str(_assets_dir)), name="assets")

    @app.get("/")
    async def serve_spa_root():
        return FileResponse(str(_DIST_DIR / "index.html"))


# ─── STARTUP ─────────────────────────────────────────────────────
if __name__ == "__main__":
    import uvicorn

    _port = int(os.environ.get("PORT", 8000))
    print("[ALES] 1:1 Claude Code Engine v7.0")
    print(f"[ALES] Tools: {len(TOOLS)} (bash, read_file, write_file, edit_file, grep_search, glob_search, task, todo_write)")
    print(f"[ALES] CWD: {get_cwd()}")
    print(f"[ALES] Starting on http://0.0.0.0:{_port}")
    uvicorn.run(app, host="0.0.0.0", port=_port, log_level="warning")
