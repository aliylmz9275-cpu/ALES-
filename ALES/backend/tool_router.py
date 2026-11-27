"""
tool_router.py — ALES: 8-Primitive Claude Code Engine

Exactly 8 tools:
1.  bash(command)              — Stateful terminal, persistent CWD
2.  read_file(path)            — Read file contents
3.  write_file(path, content)  — Create or overwrite file
4.  edit_file(path, old, new)  — Exact-once search-and-replace (raises if not unique)
5.  grep_search(query)         — Search text in project files
6.  glob_search(pattern)       — Find files by glob pattern
7.  task(description, prompt)  — Spawn isolated sub-agent, returns summary only
8.  todo_write(items)          — Update the UI task/todo list
"""

import glob as glob_mod
import json
import os
import re
import subprocess
import traceback
from pathlib import Path
from typing import Optional

from filesystem import read_file as _fs_read_file, write_file as _fs_write_file

# ─── STATEFUL WORKING DIRECTORY ───────────────────────────────────
_SESSION_CWD: str = os.getcwd()

# ─── TODO STATE (shared with WebSocket handler) ────────────────────
_current_todos: list = []


def get_cwd() -> str:
    return _SESSION_CWD


def set_cwd(path: str) -> str:
    global _SESSION_CWD
    _SESSION_CWD = path
    return _SESSION_CWD


def get_todos() -> list:
    return _current_todos


def _resolve_path(file_path: str) -> Path:
    p = Path(os.path.expandvars(os.path.expanduser(file_path)))
    if not p.is_absolute():
        p = Path(_SESSION_CWD) / p
    return p.resolve()


# ─── TOOL 1: bash ─────────────────────────────────────────────────
def bash(command: str, timeout: int = 60) -> str:
    """Run a shell command. Working directory persists across calls. Returns stdout + stderr."""
    global _SESSION_CWD

    # Handle cd natively to persist state
    cd_match = re.match(r'^cd\s+(.+)$', command.strip())
    if cd_match:
        target = cd_match.group(1).strip().strip('"').strip("'")
        target = os.path.expandvars(os.path.expanduser(target))
        if not os.path.isabs(target):
            target = os.path.join(_SESSION_CWD, target)
        target = os.path.normpath(target)
        if os.path.isdir(target):
            _SESSION_CWD = target
            return f"[EXIT CODE: 0]\n[STDOUT]\nChanged directory to: {_SESSION_CWD}"
        return f"[EXIT CODE: 1]\n[STDERR]\nDirectory not found: {target}"

    try:
        result = subprocess.run(
            command,
            shell=True,
            capture_output=True,
            text=True,
            timeout=timeout,
            cwd=_SESSION_CWD,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0) if os.name == "nt" else 0,
        )
        # Update CWD if the command changed it (via shell builtins on Unix)
        # On Windows/shell=True, we can't detect this — user must use explicit cd commands
        parts = [f"[EXIT CODE: {result.returncode}]"]
        if result.stdout:
            parts.append(f"[STDOUT]\n{result.stdout[:8000]}")
        if result.stderr:
            parts.append(f"[STDERR]\n{result.stderr[:4000]}")
        if not result.stdout and not result.stderr:
            parts.append("[STDOUT]\n(no output)")
        return "\n".join(parts)
    except subprocess.TimeoutExpired:
        return f"[EXIT CODE: -1]\n[STDERR]\nCommand timed out after {timeout}s"
    except Exception as e:
        return f"[EXIT CODE: -1]\n[STDERR]\n{e}"


# ─── TOOL 2: read_file ────────────────────────────────────────────
def read_file(path: str) -> str:
    """Read the contents of a file."""
    p = _resolve_path(path)
    return _fs_read_file(str(p))


# ─── TOOL 3: write_file ───────────────────────────────────────────
def write_file(path: str, content: str) -> str:
    """Create or overwrite a file with content."""
    p = _resolve_path(path)
    return _fs_write_file(str(p), content, overwrite=True)


# ─── TOOL 4: edit_file ────────────────────────────────────────────
def edit_file(path: str, old_string: str, new_string: str) -> str:
    """
    Replace an exact string in a file.
    CRITICAL: Raises ValueError if old_string is not found exactly once.
    Uses .replace(old, new, 1) — no full file rewrites.
    """
    p = _resolve_path(path)
    if not p.exists():
        raise FileNotFoundError(f"File not found: {p}")
    content = p.read_text(encoding="utf-8", errors="replace")
    count = content.count(old_string)
    if count == 0:
        raise ValueError(
            f"ERROR: old_string not found in {p.name}.\n"
            f"Read the file first and copy the EXACT text including whitespace and indentation."
        )
    if count > 1:
        raise ValueError(
            f"ERROR: old_string appears {count} times in {p.name}. "
            f"It must appear EXACTLY ONCE. Include more surrounding context lines to make it unique."
        )
    new_content = content.replace(old_string, new_string, 1)
    p.write_text(new_content, encoding="utf-8")
    return f"OK: Replaced 1 occurrence in {p.name}"


# ─── TOOL 5: grep_search ──────────────────────────────────────────
def grep_search(query: str, include_pattern: str = None) -> str:
    """Search for text in files within the current working directory."""
    work_dir = _SESSION_CWD
    try:
        if os.name == "nt":
            pat = include_pattern or "*.py *.js *.jsx *.ts *.tsx *.json *.md *.txt *.html *.css"
            cmd = f'findstr /s /n /i /c:"{query}" {pat}'
        else:
            if include_pattern:
                cmd = f'grep -rn --include="{include_pattern}" -i "{query}" .'
            else:
                cmd = f'grep -rn --include="*.py" --include="*.js" --include="*.jsx" --include="*.ts" --include="*.md" -i "{query}" .'
        result = subprocess.run(
            cmd, shell=True, capture_output=True, text=True, timeout=20, cwd=work_dir,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0) if os.name == "nt" else 0,
        )
        output = result.stdout[:6000] if result.stdout else "No matches found."
        lines = output.strip().split("\n")
        if len(lines) > 60:
            output = "\n".join(lines[:60]) + f"\n... ({len(lines) - 60} more matches)"
        return output or "No matches found."
    except Exception as e:
        return f"Search error: {e}"


# ─── TOOL 6: glob_search ──────────────────────────────────────────
def glob_search(pattern: str) -> str:
    """Find files matching a glob pattern (e.g. **/*.py)."""
    work_dir = _SESSION_CWD
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
            except Exception:
                results.append(f"  {m}")
        header = f"Found {len(matches)} file(s) matching '{pattern}':"
        if len(matches) > 100:
            header += " (showing first 100)"
        return header + "\n" + "\n".join(results)
    except Exception as e:
        return f"Glob error: {e}"


# ─── TOOL 7: task (Sub-Agent) ────────────────────────────────────
def task(description: str, prompt: str) -> str:
    """
    Spawn an isolated sub-agent with a FRESH context window.
    The sub-agent uses the same LLM + 6 file tools but NO conversation history.
    Returns only a compact summary — context is NOT leaked to the main agent.
    """
    try:
        from openai import OpenAI
        import os as _os
        # Try available keys in priority order
        providers = []
        if k := _os.environ.get("GROQ_API_KEY"):
            providers.append(("groq", OpenAI(api_key=k, base_url="https://api.groq.com/openai/v1"), "moonshotai/kimi-k2-instruct"))
        if k := _os.environ.get("GEMINI_API_KEY"):
            providers.append(("gemini", OpenAI(api_key=k, base_url="https://generativelanguage.googleapis.com/v1beta/openai/"), "gemini-2.0-flash"))

        if not providers:
            return "[TASK ERROR] No API key available for sub-agent."

        _, client, model = providers[0]

        # Sub-agent has only file + search tools, no task/todo
        sub_tools = [t for t in TOOLS if t["function"]["name"] not in ("task", "todo_write")]

        sub_messages = [
            {
                "role": "system",
                "content": (
                    "You are a focused sub-agent. Your job: complete the given task using the tools provided. "
                    "Return a concise summary of ONLY your findings/results. No explanations. Be dense and factual."
                )
            },
            {"role": "user", "content": f"Task: {description}\n\nInstructions: {prompt}"}
        ]

        for _ in range(8):  # sub-agent max 8 turns
            resp = client.chat.completions.create(
                model=model, messages=sub_messages,
                tools=sub_tools, tool_choice="auto", max_tokens=2048, temperature=0.1
            )
            msg = resp.choices[0].message
            if not msg.tool_calls:
                return f"[SUBTASK RESULT: {description}]\n{msg.content or '(no result)'}"

            sub_messages.append({
                "role": "assistant",
                "content": msg.content or "",
                "tool_calls": [
                    {"id": tc.id, "type": "function",
                     "function": {"name": tc.function.name, "arguments": tc.function.arguments}}
                    for tc in msg.tool_calls
                ]
            })
            for tc in msg.tool_calls:
                fn_name = tc.function.name
                try:
                    fn_args = json.loads(tc.function.arguments)
                except Exception:
                    fn_args = {}
                result = execute_tool(fn_name, fn_args)
                sub_messages.append({"role": "tool", "tool_call_id": tc.id, "content": result[:3000]})

        return f"[SUBTASK RESULT: {description}]\n(Sub-agent hit max turns. Last context captured.)"
    except Exception as e:
        return f"[TASK ERROR] {e}\n{traceback.format_exc()[:500]}"


# ─── TOOL 8: todo_write ───────────────────────────────────────────
def todo_write(items: list) -> str:
    """
    Update the agent's todo list. Each item: {"id": str, "text": str, "status": "pending"|"in_progress"|"done"}.
    The UI sidebar reflects this in real-time.
    """
    global _current_todos
    if not isinstance(items, list):
        return "[ERROR] todo_write: items must be a list"
    _current_todos = items
    return f"OK: Todo list updated ({len(items)} items)"


# ─── 8-TOOL SCHEMAS (OpenAI Function Calling Format) ──────────────
TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "bash",
            "description": (
                "Execute a shell/terminal command. The working directory persists across calls. "
                "Returns [EXIT CODE], [STDOUT], and [STDERR]. If the command fails, read the error "
                "and fix your approach — do not give up."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "command": {"type": "string", "description": "Shell command to execute"},
                },
                "required": ["command"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "read_file",
            "description": "Read the full contents of a file at the given path.",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "Absolute or relative path to the file"},
                },
                "required": ["path"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "write_file",
            "description": "Create or completely overwrite a file with the given content.",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "Path to the file to write"},
                    "content": {"type": "string", "description": "Full content to write"},
                },
                "required": ["path", "content"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "edit_file",
            "description": (
                "Replace an EXACT substring in a file with new text. "
                "CRITICAL RULE: old_string MUST appear EXACTLY ONCE in the file. "
                "If it appears 0 or 2+ times, this tool will FAIL. "
                "Always read_file first to verify the exact text before editing."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "Path to the file to edit"},
                    "old_string": {
                        "type": "string",
                        "description": "Exact string to replace (must appear exactly once, with exact whitespace)"
                    },
                    "new_string": {
                        "type": "string",
                        "description": "Replacement string"
                    },
                },
                "required": ["path", "old_string", "new_string"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "grep_search",
            "description": "Search for text patterns in source files within the current working directory.",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "Text or pattern to search for"},
                    "include_pattern": {
                        "type": "string",
                        "description": "Optional file filter, e.g. '*.py' or '*.js'"
                    },
                },
                "required": ["query"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "glob_search",
            "description": "Find files matching a glob pattern, e.g. '**/*.py' or 'src/**/*.jsx'.",
            "parameters": {
                "type": "object",
                "properties": {
                    "pattern": {"type": "string", "description": "Glob pattern to match files"},
                },
                "required": ["pattern"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "task",
            "description": (
                "Spawn an isolated sub-agent with a fresh context window to handle a focused subtask. "
                "The sub-agent does the work and returns ONLY a summary. "
                "Use for heavy research tasks: 'find all usages of X across the repo', 'scan for bugs in module Y'. "
                "Do NOT use for simple file reads or edits."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "description": {
                        "type": "string",
                        "description": "Short label for the subtask (shown in UI)"
                    },
                    "prompt": {
                        "type": "string",
                        "description": "Detailed instructions for the sub-agent"
                    },
                },
                "required": ["description", "prompt"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "todo_write",
            "description": (
                "Update the agent's live todo list visible in the UI sidebar. "
                "Call this when you have a multi-step plan to show progress. "
                "Status must be 'pending', 'in_progress', or 'done'."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "items": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "id":     {"type": "string"},
                                "text":   {"type": "string"},
                                "status": {"type": "string", "enum": ["pending", "in_progress", "done"]},
                            },
                            "required": ["id", "text", "status"],
                        },
                        "description": "List of todo items with their current status"
                    }
                },
                "required": ["items"],
            },
        },
    },
]


# ─── DISPATCHER ───────────────────────────────────────────────────
def execute_tool(name: str, args: dict) -> str:
    """Execute one of the 8 primitives and return its output string."""
    try:
        if name == "bash":
            return bash(args.get("command", ""))
        # Legacy alias: run_bash → bash
        if name == "run_bash":
            return bash(args.get("command", ""), )
        if name == "read_file":
            return read_file(args.get("path") or args.get("file_path", ""))
        if name == "write_file":
            return write_file(args.get("path") or args.get("file_path", ""), args.get("content", ""))
        if name == "edit_file":
            return edit_file(
                args.get("path") or args.get("file_path", ""),
                args.get("old_string", ""),
                args.get("new_string", ""),
            )
        if name == "grep_search":
            return grep_search(args.get("query", ""), args.get("include_pattern"))
        if name == "glob_search":
            return glob_search(args.get("pattern", ""))
        if name == "task":
            return task(args.get("description", "subtask"), args.get("prompt", ""))
        if name == "todo_write":
            return todo_write(args.get("items", []))
        return f"[ERROR] Unknown tool: {name}"
    except Exception as e:
        return f"[ERROR] ({name}): {e}"
