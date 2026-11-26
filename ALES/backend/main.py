"""
main.py — ALES Claude Code Architecture (7 Pillars) + Extended Tools

Pillar 1: ReAct Agent Loop (max 15 turns, auto-correction)
Pillar 2: 13 Tools (6 core + search_web + memory + plans + vision/GUI + PDF)
Pillar 3: Permission System (destructive command gate)
Pillar 4: Auto-Compact (token management)
Pillar 5: Project Memory (ALES.md)
Pillar 6: WebSocket events for TUI
Pillar 7: Pure coding harness — no bloat
"""
import asyncio, json, os, re, subprocess, sys, time, traceback, glob as glob_mod
import base64, uuid
from datetime import datetime
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor

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
        try: fh = open(os.devnull, "w")
        except: return
    if sys.stdout is None: sys.stdout = fh
    if sys.stderr is None: sys.stderr = fh
    print(f"\n{'='*60}\n[ALES] PID {os.getpid()} · {time.strftime('%Y-%m-%d %H:%M:%S')}\n{'='*60}")

_boot_streams()

from fastapi import FastAPI, WebSocket, WebSocketDisconnect, Request
from fastapi.responses import FileResponse, JSONResponse
from fastapi.middleware.cors import CORSMiddleware

from config_manager import load_config, save_config, get_key
from filesystem import read_file, write_file, str_replace_editor
import voice
import browser as browser_module
import document_generator
import profile_manager

# ─── APP ───────────────────────────────────────────────────────────
app = FastAPI(title="ALES", version="5.0")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

# ─── CONSTANTS ─────────────────────────────────────────────────────
MAX_AGENT_TURNS = 15
EXECUTOR = ThreadPoolExecutor(max_workers=4)

# ─── DATA DIRS ─────────────────────────────────────────────────────
_APPDATA = Path(os.environ.get("APPDATA", Path.home())) / "ALES"
_APPDATA.mkdir(parents=True, exist_ok=True)
_PLANS_FILE = _APPDATA / "plans.json"
_MEMORY_DIR = _APPDATA / "memory"
_MEMORY_DIR.mkdir(parents=True, exist_ok=True)

# ─── PILLAR 5: PROJECT MEMORY (ALES.md) ───────────────────────────
def load_ales_md(cwd: str = None) -> str:
    search_dirs = [cwd] if cwd else []
    search_dirs.extend([os.getcwd(), str(Path.home())])
    for d in search_dirs:
        if not d: continue
        p = os.path.join(d, "ALES.md")
        if os.path.isfile(p):
            try:
                content = Path(p).read_text(encoding="utf-8", errors="replace")[:4000]
                return f"\n\n[ALES.md Project Memory]\n{content}\n"
            except: pass
    return ""

# ─── SYSTEM PROMPT ─────────────────────────────────────────────────
BASE_SYSTEM = """You are ALES, a senior AI coding agent. You are an exact replica of Claude Code.

RULES:
1. NEVER explain how to do something. ALWAYS use your tools to do it directly.
2. If a task requires a file operation, USE the tool. Do not print code for the user to run.
3. When a bash command fails, analyze the error and retry with a fix (up to 5 retries per command).
4. Use edit_file for precise changes — NEVER rewrite entire files.
5. Be concise. No yapping. Output only what matters.
6. Think step by step internally, then act.

TOOLS AVAILABLE:
- read_file(path): Read file contents
- write_file(path, content): Create/overwrite a file
- edit_file(path, old_string, new_string): Replace EXACT string in file (must appear exactly once)
- run_bash(command, cwd): Run a shell command. CWD persists.
- grep_search(query, include_pattern): Search for text in files
- glob_search(pattern): Find files matching a glob pattern
- generate_pdf(title, content): Generate a PDF document
- search_web(query): Search the web with DuckDuckGo
- remember_fact(text, category): Save important information to long-term memory
- recall_memory(query): Retrieve relevant memories
- create_plan(goal, steps): Create a task plan with steps
- take_screenshot(): Capture the current screen (returns base64 image)
- mouse_click(x, y): Click at screen coordinates
- keyboard_type(text): Type text via keyboard

You speak Turkish when the user speaks Turkish, English when they speak English."""

# ─── PILLAR 3: PERMISSION SYSTEM ──────────────────────────────────
_PERMISSIONS_FILE = Path(__file__).parent / "permissions.json"
_permissions_cache = None

def _load_permissions() -> dict:
    global _permissions_cache
    if _permissions_cache is not None:
        return _permissions_cache
    try:
        _permissions_cache = json.loads(_PERMISSIONS_FILE.read_text(encoding="utf-8"))
    except:
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

# ─── PILLAR 2: CORE TOOLS ────────────────────────────────────────
_SESSION_CWD = os.getcwd()

def run_bash(command: str, cwd: str = None, timeout: int = 60) -> dict:
    global _SESSION_CWD
    cd_match = re.match(r'^cd\s+(.+)$', command.strip())
    if cd_match:
        target = cd_match.group(1).strip().strip('"').strip("'")
        target = os.path.expandvars(os.path.expanduser(target))
        if not os.path.isabs(target):
            target = os.path.join(_SESSION_CWD, target)
        target = os.path.normpath(target)
        if os.path.isdir(target):
            _SESSION_CWD = target
            return {"exit_code": 0, "stdout": f"Changed directory to: {_SESSION_CWD}", "stderr": ""}
        else:
            return {"exit_code": 1, "stdout": "", "stderr": f"Directory not found: {target}"}
    work_dir = cwd or _SESSION_CWD
    try:
        result = subprocess.run(
            command, shell=True, capture_output=True, text=True,
            timeout=timeout, cwd=work_dir,
            creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0) if os.name == 'nt' else 0
        )
        return {
            "exit_code": result.returncode,
            "stdout": result.stdout[:8000] if result.stdout else "",
            "stderr": result.stderr[:4000] if result.stderr else ""
        }
    except subprocess.TimeoutExpired:
        return {"exit_code": -1, "stdout": "", "stderr": f"Command timed out after {timeout}s"}
    except Exception as e:
        return {"exit_code": -1, "stdout": "", "stderr": str(e)}

def grep_search(query: str, include_pattern: str = None, cwd: str = None) -> str:
    work_dir = cwd or _SESSION_CWD
    try:
        if os.name == 'nt':
            cmd = f'findstr /s /n /i /c:"{query}" '
            if include_pattern:
                cmd += include_pattern
            else:
                cmd += '*.py *.js *.jsx *.ts *.tsx *.json *.md *.txt *.html *.css *.yaml *.yml *.toml *.cfg *.ini'
        else:
            cmd = f'grep -rn --include="*.py" --include="*.js" --include="*.jsx" -i "{query}" .'
            if include_pattern:
                cmd = f'grep -rn --include="{include_pattern}" -i "{query}" .'
        result = subprocess.run(cmd, shell=True, capture_output=True, text=True,
                              timeout=15, cwd=work_dir,
                              creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0) if os.name == 'nt' else 0)
        output = result.stdout[:6000] if result.stdout else "No matches found."
        lines = output.strip().split('\n')
        if len(lines) > 50:
            output = '\n'.join(lines[:50]) + f'\n... ({len(lines) - 50} more matches)'
        return output
    except Exception as e:
        return f"Search error: {e}"

def glob_search(pattern: str, cwd: str = None) -> str:
    work_dir = cwd or _SESSION_CWD
    try:
        matches = glob_mod.glob(os.path.join(work_dir, pattern), recursive=True)
        if not matches:
            return f"No files matching '{pattern}'"
        results = []
        for m in sorted(matches)[:100]:
            try:
                rel = os.path.relpath(m, work_dir)
                size = os.path.getsize(m)
                size_str = f"{size}B" if size < 1024 else f"{size//1024}KB" if size < 1048576 else f"{size//1048576}MB"
                results.append(f"  {rel} ({size_str})")
            except:
                results.append(f"  {m}")
        header = f"Found {len(matches)} file(s) matching '{pattern}':"
        if len(matches) > 100:
            header += f" (showing first 100)"
        return header + "\n" + "\n".join(results)
    except Exception as e:
        return f"Glob error: {e}"

# ─── SEARCH WEB TOOL ──────────────────────────────────────────────
def search_web(query: str) -> str:
    """Web search using DuckDuckGo (no API key needed)."""
    return browser_module.google_search(query)

# ─── MEMORY/RAG TOOLS (ChromaDB) ─────────────────────────────────
_chroma_client = None
_chroma_collection = None

def _get_memory_collection():
    global _chroma_client, _chroma_collection
    if _chroma_collection is not None:
        return _chroma_collection
    try:
        import chromadb
        _chroma_client = chromadb.PersistentClient(path=str(_MEMORY_DIR))
        _chroma_collection = _chroma_client.get_or_create_collection(
            name="ales_memory",
            metadata={"hnsw:space": "cosine"}
        )
        return _chroma_collection
    except Exception as e:
        print(f"[MEMORY] ChromaDB init error: {e}")
        return None

def remember_fact(text: str, category: str = "general") -> str:
    """Save a fact to long-term ChromaDB vector memory."""
    collection = _get_memory_collection()
    if collection is None:
        return "❌ Memory system unavailable (ChromaDB not initialized)."
    try:
        doc_id = f"mem_{uuid.uuid4().hex[:12]}"
        metadata = {
            "category": category,
            "timestamp": datetime.now().isoformat(),
        }
        collection.add(
            documents=[text],
            metadatas=[metadata],
            ids=[doc_id]
        )
        count = collection.count()
        return f"✅ Fact saved to memory (ID: {doc_id}). Total memories: {count}"
    except Exception as e:
        return f"❌ Memory save error: {e}"

def recall_memory(query: str, n_results: int = 5) -> str:
    """Query ChromaDB vector memory for relevant facts."""
    collection = _get_memory_collection()
    if collection is None:
        return "❌ Memory system unavailable."
    try:
        if collection.count() == 0:
            return "Memory is empty. No facts stored yet."
        results = collection.query(
            query_texts=[query],
            n_results=min(n_results, collection.count())
        )
        if not results["documents"] or not results["documents"][0]:
            return f"No relevant memories found for: '{query}'"
        lines = [f"Found {len(results['documents'][0])} relevant memories:"]
        for i, (doc, meta) in enumerate(zip(results["documents"][0], results["metadatas"][0])):
            cat = meta.get("category", "general")
            ts = meta.get("timestamp", "?")[:19]
            lines.append(f"  [{i+1}] [{cat}] ({ts}) {doc}")
        return "\n".join(lines)
    except Exception as e:
        return f"❌ Memory recall error: {e}"

# ─── PLANS TOOLS ──────────────────────────────────────────────────
def _load_plans() -> list:
    try:
        return json.loads(_PLANS_FILE.read_text(encoding="utf-8"))
    except:
        return []

def _save_plans(plans: list):
    _PLANS_FILE.write_text(json.dumps(plans, ensure_ascii=False, indent=2), encoding="utf-8")

def create_plan(goal: str, steps: list = None) -> str:
    """Create a task plan with goal and steps."""
    plans = _load_plans()
    plan_id = f"plan_{uuid.uuid4().hex[:8]}"
    if not steps:
        steps = [{"title": goal, "status": "pending"}]
    else:
        steps = [{"title": s if isinstance(s, str) else s.get("title", str(s)), "status": "pending"} for s in steps]
    plan = {
        "id": plan_id,
        "goal": goal,
        "steps": steps,
        "status": "pending",
        "created_at": datetime.now().isoformat(),
        "updated_at": datetime.now().isoformat(),
    }
    plans.append(plan)
    _save_plans(plans)
    step_list = "\n".join([f"  [{i+1}] {s['title']}" for i, s in enumerate(steps)])
    return f"✅ Plan created: {plan_id}\nGoal: {goal}\nSteps:\n{step_list}"

def update_plan_step(plan_id: str, step_index: int, status: str, note: str = "") -> str:
    """Update a plan step status (pending/running/done/failed)."""
    plans = _load_plans()
    for plan in plans:
        if plan["id"] == plan_id:
            if 0 <= step_index < len(plan["steps"]):
                plan["steps"][step_index]["status"] = status
                if note:
                    plan["steps"][step_index]["note"] = note
                plan["updated_at"] = datetime.now().isoformat()
                # Update overall plan status
                statuses = [s["status"] for s in plan["steps"]]
                if all(s == "done" for s in statuses):
                    plan["status"] = "done"
                elif any(s == "running" for s in statuses):
                    plan["status"] = "running"
                elif any(s == "failed" for s in statuses):
                    plan["status"] = "failed"
                _save_plans(plans)
                return f"✅ Plan {plan_id} step {step_index+1} → {status}"
            return f"❌ Invalid step index: {step_index}"
    return f"❌ Plan not found: {plan_id}"

# ─── VISION/GUI TOOLS ─────────────────────────────────────────────
def take_screenshot() -> str:
    """Capture screen and return base64 PNG."""
    try:
        import mss
        with mss.mss() as sct:
            monitor = sct.monitors[1]  # Primary monitor
            img = sct.grab(monitor)
            # Convert to PNG bytes
            from PIL import Image
            import io
            pil_img = Image.frombytes("RGB", img.size, img.bgra, "raw", "BGRX")
            # Resize to max 1280px wide to keep token usage low
            max_w = 1280
            if pil_img.width > max_w:
                ratio = max_w / pil_img.width
                pil_img = pil_img.resize((max_w, int(pil_img.height * ratio)), Image.LANCZOS)
            buf = io.BytesIO()
            pil_img.save(buf, format="PNG", optimize=True)
            b64 = base64.b64encode(buf.getvalue()).decode("utf-8")
            # Also save to static for the UI
            ss_dir = Path(__file__).parent / "static" / "screenshots"
            ss_dir.mkdir(parents=True, exist_ok=True)
            ss_path = ss_dir / f"screen_{int(time.time())}.png"
            pil_img.save(str(ss_path), format="PNG")
            return json.dumps({
                "success": True,
                "base64": b64[:100] + "...(truncated for LLM)",
                "file": str(ss_path),
                "url": f"/static/screenshots/{ss_path.name}",
                "resolution": f"{pil_img.width}x{pil_img.height}"
            })
    except Exception as e:
        return f"❌ Screenshot error: {e}"

def _take_screenshot_raw_b64() -> str:
    """Return full base64 for internal use (vision API)."""
    try:
        import mss
        from PIL import Image
        import io
        with mss.mss() as sct:
            monitor = sct.monitors[1]
            img = sct.grab(monitor)
            pil_img = Image.frombytes("RGB", img.size, img.bgra, "raw", "BGRX")
            max_w = 1280
            if pil_img.width > max_w:
                ratio = max_w / pil_img.width
                pil_img = pil_img.resize((max_w, int(pil_img.height * ratio)), Image.LANCZOS)
            buf = io.BytesIO()
            pil_img.save(buf, format="PNG", optimize=True)
            return base64.b64encode(buf.getvalue()).decode("utf-8")
    except:
        return ""

def mouse_click(x: int, y: int) -> str:
    """Click at screen coordinates."""
    try:
        import pyautogui
        pyautogui.FAILSAFE = False
        pyautogui.click(x, y)
        return f"✅ Clicked at ({x}, {y})"
    except Exception as e:
        return f"❌ Click error: {e}"

def keyboard_type(text: str) -> str:
    """Type text via keyboard (uses clipboard for Unicode support)."""
    try:
        import pyautogui
        pyautogui.FAILSAFE = False
        # Use clipboard method for Turkish chars
        import subprocess as sp
        sp.run(['clip.exe'], input=text.encode('utf-16-le'), check=True,
               creationflags=getattr(sp, 'CREATE_NO_WINDOW', 0))
        pyautogui.hotkey('ctrl', 'v')
        time.sleep(0.1)
        return f"✅ Typed: {text[:50]}{'...' if len(text)>50 else ''}"
    except Exception as e:
        # Fallback to direct typing
        try:
            import pyautogui
            pyautogui.typewrite(text, interval=0.02)
            return f"✅ Typed (fallback): {text[:50]}"
        except Exception as e2:
            return f"❌ Type error: {e2}"

# ─── TOOL SCHEMAS ─────────────────────────────────────────────────
TOOLS = [
    # 6 Core Claude Code tools
    {"type":"function","function":{"name":"read_file","description":"Read the contents of a file at the given path.","parameters":{"type":"object","properties":{"path":{"type":"string","description":"File path to read"}},"required":["path"]}}},
    {"type":"function","function":{"name":"write_file","description":"Create or overwrite a file with the given content.","parameters":{"type":"object","properties":{"path":{"type":"string","description":"File path to write"},"content":{"type":"string","description":"Full file content to write"}},"required":["path","content"]}}},
    {"type":"function","function":{"name":"edit_file","description":"Replace an EXACT string in a file. The old_string MUST appear exactly once. Use for precise edits without rewriting the whole file.","parameters":{"type":"object","properties":{"path":{"type":"string","description":"File path to edit"},"old_string":{"type":"string","description":"Exact text to find (must appear exactly once)"},"new_string":{"type":"string","description":"Replacement text"}},"required":["path","old_string","new_string"]}}},
    {"type":"function","function":{"name":"run_bash","description":"Run a shell/terminal command. Working directory persists across calls. Use for: git, npm, pip, python, build, test, etc.","parameters":{"type":"object","properties":{"command":{"type":"string","description":"Shell command to execute"},"timeout":{"type":"integer","description":"Timeout in seconds (default 60)"}},"required":["command"]}}},
    {"type":"function","function":{"name":"grep_search","description":"Search for text across files in the project (like grep/ripgrep).","parameters":{"type":"object","properties":{"query":{"type":"string","description":"Text to search for"},"include_pattern":{"type":"string","description":"File pattern filter, e.g. *.py or *.js"}},"required":["query"]}}},
    {"type":"function","function":{"name":"glob_search","description":"Find files matching a glob pattern (e.g. **/*.py, src/**/*.jsx).","parameters":{"type":"object","properties":{"pattern":{"type":"string","description":"Glob pattern, e.g. **/*.py"}},"required":["pattern"]}}},
    # Extended tools
    {"type":"function","function":{"name":"generate_pdf","description":"Generate a beautifully formatted PDF. Write content as clean Markdown. Turkish chars supported.","parameters":{"type":"object","properties":{"title":{"type":"string","description":"Document title"},"content":{"type":"string","description":"Markdown content for the PDF body"}},"required":["title","content"]}}},
    {"type":"function","function":{"name":"search_web","description":"Search the web for information. Returns DuckDuckGo results.","parameters":{"type":"object","properties":{"query":{"type":"string","description":"Search query"}},"required":["query"]}}},
    {"type":"function","function":{"name":"remember_fact","description":"Save important information to long-term vector memory (ChromaDB). Use to store user preferences, project facts, decisions, etc.","parameters":{"type":"object","properties":{"text":{"type":"string","description":"The fact or information to remember"},"category":{"type":"string","description":"Category: general, user, project, decision, code"}},"required":["text"]}}},
    {"type":"function","function":{"name":"recall_memory","description":"Retrieve relevant facts from long-term memory. Semantic search.","parameters":{"type":"object","properties":{"query":{"type":"string","description":"What to search for in memory"}},"required":["query"]}}},
    {"type":"function","function":{"name":"create_plan","description":"Create a task plan with a goal and ordered steps. Each step will be tracked (pending/running/done/failed).","parameters":{"type":"object","properties":{"goal":{"type":"string","description":"The overall goal of the plan"},"steps":{"type":"array","items":{"type":"string"},"description":"List of step descriptions in order"}},"required":["goal","steps"]}}},
    {"type":"function","function":{"name":"update_plan_step","description":"Update a plan step's status. Use after completing or failing a step.","parameters":{"type":"object","properties":{"plan_id":{"type":"string","description":"Plan ID (e.g. plan_abc12345)"},"step_index":{"type":"integer","description":"Step index (0-based)"},"status":{"type":"string","enum":["pending","running","done","failed"],"description":"New status"}},"required":["plan_id","step_index","status"]}}},
    {"type":"function","function":{"name":"take_screenshot","description":"Capture the current screen. Returns screenshot file path and base64 image data.","parameters":{"type":"object","properties":{}}}},
    {"type":"function","function":{"name":"mouse_click","description":"Click at specific screen coordinates.","parameters":{"type":"object","properties":{"x":{"type":"integer","description":"X coordinate"},"y":{"type":"integer","description":"Y coordinate"}},"required":["x","y"]}}},
    {"type":"function","function":{"name":"keyboard_type","description":"Type text via keyboard. Supports Turkish characters.","parameters":{"type":"object","properties":{"text":{"type":"string","description":"Text to type"}},"required":["text"]}}},
]

# ─── TOOL EXECUTOR ─────────────────────────────────────────────────
def execute_tool(name: str, args: dict) -> str:
    try:
        if name == "read_file":
            return read_file(args.get("path", ""))
        elif name == "write_file":
            return write_file(args.get("path", ""), args.get("content", ""), overwrite=True)
        elif name == "edit_file":
            return str_replace_editor(
                args.get("path", ""),
                args.get("old_string", ""),
                args.get("new_string", "")
            )
        elif name == "run_bash":
            result = run_bash(
                args.get("command", ""),
                args.get("cwd"),
                int(args.get("timeout", 60))
            )
            parts = []
            if result["exit_code"] != 0:
                parts.append(f"[EXIT CODE: {result['exit_code']}]")
            if result["stdout"]:
                parts.append(result["stdout"])
            if result["stderr"]:
                parts.append(f"[STDERR]\n{result['stderr']}")
            if not parts:
                parts.append("(no output)")
            return "\n".join(parts)
        elif name == "grep_search":
            return grep_search(args.get("query", ""), args.get("include_pattern"))
        elif name == "glob_search":
            return glob_search(args.get("pattern", ""))
        elif name == "generate_pdf":
            result = document_generator.generate_pdf(
                args.get("title", "Document"),
                args.get("content", "")
            )
            return json.dumps(result, ensure_ascii=False)
        elif name == "search_web":
            return search_web(args.get("query", ""))
        elif name == "remember_fact":
            return remember_fact(args.get("text", ""), args.get("category", "general"))
        elif name == "recall_memory":
            return recall_memory(args.get("query", ""))
        elif name == "create_plan":
            return create_plan(args.get("goal", ""), args.get("steps", []))
        elif name == "update_plan_step":
            return update_plan_step(
                args.get("plan_id", ""),
                int(args.get("step_index", 0)),
                args.get("status", "done")
            )
        elif name == "take_screenshot":
            return take_screenshot()
        elif name == "mouse_click":
            return mouse_click(int(args.get("x", 0)), int(args.get("y", 0)))
        elif name == "keyboard_type":
            return keyboard_type(args.get("text", ""))
        else:
            return f"Unknown tool: {name}"
    except Exception as e:
        return f"Tool error ({name}): {traceback.format_exc()}"

# ─── PILLAR 4: AUTO-COMPACT ──────────────────────────────────────
def estimate_tokens(text: str) -> int:
    return len(text) // 3

def should_compact(messages: list, max_context: int = 8192) -> bool:
    total = sum(estimate_tokens(json.dumps(m)) for m in messages)
    return total > int(max_context * 0.7)

async def auto_compact(messages: list, client_info: tuple) -> list:
    provider, client = client_info
    if len(messages) < 4:
        return messages
    system_msg = messages[0] if messages[0].get("role") == "system" else None
    conversation = messages[1:] if system_msg else messages
    summary_prompt = [{
        "role": "system",
        "content": "Summarize the following conversation. Keep: 1) Files created/modified and their paths, 2) Current goal/task, 3) Any errors encountered. Be very concise."
    }, {
        "role": "user",
        "content": json.dumps(conversation[-20:], ensure_ascii=False)[:6000]
    }]
    try:
        cfg = load_config()
        model = _default_model_for(provider, cfg)
        resp = client.chat.completions.create(model=model, messages=summary_prompt, max_tokens=1024)
        summary = resp.choices[0].message.content
    except:
        summary = None
    result = []
    if system_msg:
        result.append(system_msg)
    if summary:
        result.append({"role": "assistant", "content": f"[AUTO-COMPACT SUMMARY]\n{summary}"})
    result.extend(conversation[-4:])
    return result

# ─── LLM CLIENT ───────────────────────────────────────────────────
def get_clients() -> list:
    from openai import OpenAI
    clients = []
    if k := get_key("groq_key"):
        clients.append(("groq", OpenAI(api_key=k, base_url="https://api.groq.com/openai/v1"), "openai/gpt-oss-120b"))
    if k := get_key("gemini_key"):
        clients.append(("gemini", OpenAI(api_key=k, base_url="https://generativelanguage.googleapis.com/v1beta/openai/"), "gemini-3.8-flash"))
    if k := get_key("openrouter_key"):
        clients.append(("openrouter", OpenAI(api_key=k, base_url="https://openrouter.ai/api/v1"), "qwen/qwen3.8-27b"))
    if k := get_key("nvidia_key"):
        clients.append(("nvidia", OpenAI(api_key=k, base_url="https://integrate.api.nvidia.com/v1"), "deepseek-ai/deepseek-v4-pro"))
    return clients

def get_client():
    clients = get_clients()
    if clients:
        return clients[0][0], clients[0][1]
    return None, None

def _default_model_for(provider: str, cfg: dict) -> str:
    if cfg.get("model"):
        return cfg["model"]
    for p, _, m in get_clients():
        if p == provider:
            return m
    return "llama-3.3-70b-versatile"

# ─── PILLAR 1: THE REACT AGENT LOOP ──────────────────────────────
# Active WebSocket connections for broadcasting plan updates
_active_ws: list = []

async def run_agent(user_message: str, ws: WebSocket = None, conversation_history: list = None):
    clients = get_clients()
    if not clients:
        yield {"type": "error", "content": "❌ API anahtarı yapılandırılmamış. Ayarlar'dan bir API anahtarı girin."}
        return

    client_idx = 0
    provider, client, default_model = clients[client_idx]
    cfg = load_config()
    model = cfg.get("model") or default_model

    system_prompt = BASE_SYSTEM + load_ales_md(_SESSION_CWD)
    system_prompt += f"\n\nCurrent working directory: {_SESSION_CWD}"

    if conversation_history is None:
        conversation_history = []

    messages = [{"role": "system", "content": system_prompt}]
    messages.extend(conversation_history)
    messages.append({"role": "user", "content": user_message})

    if should_compact(messages):
        yield {"type": "status", "content": "🗜️ Auto-compacting context..."}
        messages = await auto_compact(messages, (provider, client))

    turn = 0
    bash_retries = {}

    while turn < MAX_AGENT_TURNS:
        turn += 1
        yield {"type": "thinking", "content": f"🧠 Thinking... (turn {turn}/{MAX_AGENT_TURNS})"}

        try:
            response = client.chat.completions.create(
                model=model,
                messages=messages,
                tools=TOOLS,
                tool_choice="auto",
                max_tokens=4096,
                temperature=0.1
            )

            choice = response.choices[0]
            msg = choice.message

            if not msg.tool_calls:
                content = msg.content or ""
                yield {"type": "response", "content": content}
                return

            messages.append({
                "role": "assistant",
                "content": msg.content or "",
                "tool_calls": [
                    {"id": tc.id, "type": "function",
                     "function": {"name": tc.function.name, "arguments": tc.function.arguments}}
                    for tc in msg.tool_calls
                ]
            })

            for tool_call in msg.tool_calls:
                fn_name = tool_call.function.name
                try:
                    fn_args = json.loads(tool_call.function.arguments)
                except:
                    fn_args = {}

                # Permission check for run_bash
                if fn_name == "run_bash" and is_destructive(fn_args.get("command", "")):
                    cmd = fn_args.get("command", "")
                    yield {"type": "permission_request", "command": cmd, "tool_call_id": tool_call.id}

                    req_id = tool_call.id
                    _permission_requests[req_id] = asyncio.Event()
                    _permission_results[req_id] = None

                    try:
                        await asyncio.wait_for(_permission_requests[req_id].wait(), timeout=120)
                    except asyncio.TimeoutError:
                        _permission_results[req_id] = False

                    allowed = _permission_results.get(req_id, False)
                    del _permission_requests[req_id]
                    del _permission_results[req_id]

                    if not allowed:
                        tool_result = "⚠️ User denied this command. Try a different approach."
                        yield {"type": "tool_denied", "tool": fn_name, "command": cmd}
                    else:
                        yield {"type": "tool_call", "tool": fn_name, "args": fn_args}
                        tool_result = await asyncio.get_event_loop().run_in_executor(
                            EXECUTOR, execute_tool, fn_name, fn_args
                        )
                        yield {"type": "tool_result", "tool": fn_name, "result": tool_result[:2000]}
                else:
                    yield {"type": "tool_call", "tool": fn_name, "args": fn_args}
                    tool_result = await asyncio.get_event_loop().run_in_executor(
                        EXECUTOR, execute_tool, fn_name, fn_args
                    )
                    yield {"type": "tool_result", "tool": fn_name, "result": tool_result[:2000]}

                    # Broadcast plan updates to frontend
                    if fn_name in ("create_plan", "update_plan_step"):
                        plans = _load_plans()
                        for active_ws in _active_ws:
                            try:
                                await active_ws.send_json({"type": "plan_update", "plans": plans})
                            except:
                                pass

                messages.append({
                    "role": "tool",
                    "tool_call_id": tool_call.id,
                    "content": tool_result[:4000]
                })

                # Auto-correction for bash failures
                if fn_name == "run_bash" and "[EXIT CODE:" in tool_result and "[EXIT CODE: 0]" not in tool_result:
                    cmd_key = fn_args.get("command", "")[:100]
                    retries = bash_retries.get(cmd_key, 0)
                    if retries < 5:
                        bash_retries[cmd_key] = retries + 1
                        yield {"type": "status", "content": f"⚠️ Command failed. Auto-retry {retries+1}/5..."}

        except Exception as e:
            if client_idx + 1 < len(clients):
                client_idx += 1
                provider, client, default_model = clients[client_idx]
                model = cfg.get("model") or default_model
                yield {"type": "status", "content": f"⚠️ {clients[client_idx-1][0]} failed ({str(e)[:80]}), switching to {provider}..."}
                turn -= 1
                continue
            error_msg = f"LLM Error: {e}"
            yield {"type": "error", "content": error_msg}
            return

    yield {"type": "response", "content": "⚠️ Maximum agent turns (15) reached. Task may be incomplete."}

# ─── WEBSOCKET ENDPOINT ──────────────────────────────────────────
_conversations: dict = {}

@app.websocket("/ws")
async def websocket_endpoint(ws: WebSocket):
    await ws.accept()
    conn_id = id(ws)
    _conversations[conn_id] = []
    _active_ws.append(ws)

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
                        _conversations[conn_id].append({
                            "role": "assistant",
                            "content": event["content"]
                        })
                        if len(_conversations[conn_id]) > 40:
                            _conversations[conn_id] = _conversations[conn_id][-30:]

            elif msg_type == "permission_response":
                req_id = data.get("tool_call_id")
                allowed = data.get("allowed", False)
                if req_id in _permission_requests:
                    _permission_results[req_id] = allowed
                    _permission_requests[req_id].set()

            elif msg_type == "clear":
                _conversations[conn_id] = []
                await ws.send_json({"type": "status", "content": "Conversation cleared."})

    except WebSocketDisconnect:
        _conversations.pop(conn_id, None)
        if ws in _active_ws:
            _active_ws.remove(ws)
    except Exception as e:
        print(f"[WS ERROR] {e}")
        _conversations.pop(conn_id, None)
        if ws in _active_ws:
            _active_ws.remove(ws)

# ─── REST ENDPOINTS ──────────────────────────────────────────────
@app.get("/status")
def status():
    provider, client = get_client()
    return {
        "status": "running",
        "version": "5.0",
        "provider": provider,
        "has_key": client is not None,
        "cwd": _SESSION_CWD,
        "tools": len(TOOLS),
        "architecture": "Claude Code (7 Pillars) + Extended"
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
            status_code=401
        )
    _load_keys_into_session(res.get("keys", {}))
    # Security: never return API keys to frontend
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

@app.post("/test-key")
async def test_key(request: Request):
    data = await request.json()
    provider = data.get("provider", "groq")
    key = data.get("key", "")
    try:
        if provider == "groq":
            from openai import OpenAI
            c = OpenAI(api_key=key, base_url="https://api.groq.com/openai/v1")
            c.chat.completions.create(model="openai/gpt-oss-120b", messages=[{"role":"user","content":"hi"}], max_tokens=5)
            return {"ok": True, "model": "openai/gpt-oss-120b"}
        elif provider == "gemini":
            from openai import OpenAI
            c = OpenAI(api_key=key, base_url="https://generativelanguage.googleapis.com/v1beta/openai/")
            c.chat.completions.create(model="gemini-3.8-flash", messages=[{"role":"user","content":"hi"}], max_tokens=5)
            return {"ok": True, "model": "gemini-3.8-flash"}
        return {"ok": False, "error": f"Unknown provider: {provider}"}
    except Exception as e:
        return {"ok": False, "error": str(e)}

# ─── PLANS API ───────────────────────────────────────────────────
@app.get("/api/plans")
def api_plans_list():
    return _load_plans()

@app.get("/api/plans/{plan_id}")
def api_plan_get(plan_id: str):
    for plan in _load_plans():
        if plan["id"] == plan_id:
            return plan
    return JSONResponse({"error": "Not found"}, status_code=404)

# ─── MEMORY API ──────────────────────────────────────────────────
@app.get("/api/memory")
def api_memory_list():
    collection = _get_memory_collection()
    if collection is None or collection.count() == 0:
        return {"count": 0, "items": []}
    try:
        all_data = collection.get(limit=100, include=["documents", "metadatas"])
        items = []
        for doc, meta, doc_id in zip(all_data["documents"], all_data["metadatas"], all_data["ids"]):
            items.append({"id": doc_id, "text": doc, "category": meta.get("category", "general"), "timestamp": meta.get("timestamp", "")})
        return {"count": collection.count(), "items": items}
    except Exception as e:
        return {"count": 0, "items": [], "error": str(e)}

@app.get("/api/memory/search")
def api_memory_search(q: str = ""):
    if not q:
        return {"results": []}
    result = recall_memory(q)
    return {"query": q, "result": result}

@app.delete("/api/memory/{mem_id}")
def api_memory_delete(mem_id: str):
    collection = _get_memory_collection()
    if collection is None:
        return {"ok": False, "error": "Memory unavailable"}
    try:
        collection.delete(ids=[mem_id])
        return {"ok": True}
    except Exception as e:
        return {"ok": False, "error": str(e)}

# ─── SCREENSHOT API ──────────────────────────────────────────────
@app.get("/api/screenshot")
def api_screenshot():
    result = take_screenshot()
    try:
        return json.loads(result)
    except:
        return {"error": result}

@app.get("/static/screenshots/{filename}")
async def serve_screenshot(filename: str):
    ss_dir = Path(__file__).parent / "static" / "screenshots"
    file_path = ss_dir / filename
    if file_path.exists():
        return FileResponse(str(file_path), media_type="image/png")
    return JSONResponse({"error": "Not found"}, status_code=404)

# ─── SPEAK ENDPOINT ──────────────────────────────────────────────
@app.post("/speak")
async def speak(request: Request):
    data = await request.json()
    text = data.get("text", "")
    voice_id = data.get("voice", "nova")
    if not text:
        return {"ok": False, "error": "No text"}
    try:
        result = await voice.synthesize(text, voice_id=voice_id)
        return result
    except Exception as e:
        return {"ok": False, "error": str(e)}

# ─── PDF DOWNLOAD ────────────────────────────────────────────────
@app.get("/static/pdfs/{filename}")
async def serve_pdf(filename: str):
    pdf_dir = Path(__file__).parent / "static" / "pdfs"
    file_path = pdf_dir / filename
    if file_path.exists():
        return FileResponse(str(file_path), media_type="application/pdf", filename=filename)
    return JSONResponse({"error": "Not found"}, status_code=404)

# ─── STARTUP ─────────────────────────────────────────────────────
if __name__ == "__main__":
    import uvicorn
    print(f"[ALES] Claude Code Architecture — 7 Pillars + Extended Tools")
    print(f"[ALES] Tools: {len(TOOLS)} total")
    print(f"[ALES] CWD: {_SESSION_CWD}")
    print(f"[ALES] Starting on http://0.0.0.0:8000")
    uvicorn.run(app, host="0.0.0.0", port=8000, log_level="warning")
