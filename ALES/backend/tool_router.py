"""
tool_router.py — Strict 6-Tool Claude Code Primitives

Exactly 6 tools:
1. read_file(file_path)
2. write_file(file_path, content)
3. edit_file(file_path, old_string, new_string) -> errors if old_string not found exactly once
4. run_bash(command, cwd) -> stateful CWD, returns stdout and stderr
5. grep_search(query, include_pattern)
6. glob_search(pattern)
"""
import glob as glob_mod
import os
import re
import subprocess
import traceback
from pathlib import Path

from filesystem import read_file as _fs_read_file, write_file as _fs_write_file

# Stateful working directory across run_bash calls
_SESSION_CWD = os.getcwd()


def get_cwd() -> str:
    return _SESSION_CWD


def set_cwd(path: str) -> str:
    global _SESSION_CWD
    _SESSION_CWD = path
    return _SESSION_CWD


def _resolve_path(file_path: str) -> Path:
    p = Path(os.path.expandvars(os.path.expanduser(file_path)))
    if not p.is_absolute():
        p = Path(_SESSION_CWD) / p
    return p.resolve()


def read_file(file_path: str) -> str:
    """Read the contents of a file at file_path."""
    p = _resolve_path(file_path)
    return _fs_read_file(str(p))


def write_file(file_path: str, content: str) -> str:
    """Create or overwrite a file at file_path with content."""
    p = _resolve_path(file_path)
    return _fs_write_file(str(p), content, overwrite=True)


def edit_file(file_path: str, old_string: str, new_string: str) -> str:
    """Replace an exact string in a file. Raises ValueError if old_string is not found exactly once."""
    p = _resolve_path(file_path)
    if not p.exists():
        raise FileNotFoundError(f"File not found: {p}")
    content = p.read_text(encoding="utf-8", errors="replace")
    count = content.count(old_string)
    if count == 0:
        raise ValueError(
            f"old_string not found in {p}. Read the file first and match exact whitespace/indentation."
        )
    if count > 1:
        raise ValueError(
            f"old_string appears {count} times in {p}. It must appear EXACTLY ONCE. Include more surrounding lines."
        )
    new_content = content.replace(old_string, new_string, 1)
    p.write_text(new_content, encoding="utf-8")
    return f"OK: Edited {p} (1 replacement)"


def run_bash(command: str, cwd: str = None, timeout: int = 60) -> str:
    """Run a shell command with persistent working directory. Returns stdout and stderr."""
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
            return f"[EXIT CODE: 0]\n[STDOUT]\nChanged directory to: {_SESSION_CWD}"
        return f"[EXIT CODE: 1]\n[STDERR]\nDirectory not found: {target}"

    work_dir = cwd or _SESSION_CWD
    if cwd and os.path.isdir(cwd):
        _SESSION_CWD = os.path.abspath(cwd)
        work_dir = _SESSION_CWD

    try:
        result = subprocess.run(
            command,
            shell=True,
            capture_output=True,
            text=True,
            timeout=timeout,
            cwd=work_dir,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0) if os.name == "nt" else 0,
        )
        parts = [f"[EXIT CODE: {result.returncode}]"]
        if result.stdout:
            parts.append(f"[STDOUT]\n{result.stdout[:8000]}")
        if result.stderr:
            parts.append(f"[STDERR]\n{result.stderr[:4000]}")
        if not result.stdout and not result.stderr:
            parts.append("(no output)")
        return "\n".join(parts)
    except subprocess.TimeoutExpired:
        return f"[EXIT CODE: -1]\n[STDERR]\nCommand timed out after {timeout}s"
    except Exception as e:
        return f"[EXIT CODE: -1]\n[STDERR]\n{e}"


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
                cmd = f'grep -rn --include="*.py" --include="*.js" --include="*.jsx" -i "{query}" .'
        result = subprocess.run(
            cmd,
            shell=True,
            capture_output=True,
            text=True,
            timeout=15,
            cwd=work_dir,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0) if os.name == "nt" else 0,
        )
        output = result.stdout[:6000] if result.stdout else "No matches found."
        lines = output.strip().split("\n")
        if len(lines) > 50:
            output = "\n".join(lines[:50]) + f"\n... ({len(lines) - 50} more matches)"
        return output
    except Exception as e:
        return f"Search error: {e}"


def glob_search(pattern: str) -> str:
    """Find files matching a glob pattern."""
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


# ─── STRICT 6-TOOL SCHEMAS ────────────────────────────────────────
TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "read_file",
            "description": "Read the contents of a file at file_path.",
            "parameters": {
                "type": "object",
                "properties": {
                    "file_path": {"type": "string", "description": "Path to the file to read"}
                },
                "required": ["file_path"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "write_file",
            "description": "Create or overwrite a file with the given content.",
            "parameters": {
                "type": "object",
                "properties": {
                    "file_path": {"type": "string", "description": "Path to the file to write"},
                    "content": {"type": "string", "description": "Full content to write to the file"},
                },
                "required": ["file_path", "content"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "edit_file",
            "description": "Replace an exact string in a file. Raises an error if old_string does not appear exactly once.",
            "parameters": {
                "type": "object",
                "properties": {
                    "file_path": {"type": "string", "description": "Path to the file to edit"},
                    "old_string": {"type": "string", "description": "Exact string to replace (must appear exactly once)"},
                    "new_string": {"type": "string", "description": "Replacement string"},
                },
                "required": ["file_path", "old_string", "new_string"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "run_bash",
            "description": "Execute a shell/terminal command. Working directory persists across calls. Returns stdout and stderr.",
            "parameters": {
                "type": "object",
                "properties": {
                    "command": {"type": "string", "description": "Shell command to execute"},
                    "cwd": {"type": "string", "description": "Optional working directory"},
                },
                "required": ["command"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "grep_search",
            "description": "Search for text in project files.",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "Text to search for"},
                    "include_pattern": {"type": "string", "description": "Optional file filter, e.g. *.py"},
                },
                "required": ["query"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "glob_search",
            "description": "Find files matching a glob pattern (e.g. **/*.py).",
            "parameters": {
                "type": "object",
                "properties": {
                    "pattern": {"type": "string", "description": "Glob pattern"},
                },
                "required": ["pattern"],
            },
        },
    },
]


def execute_tool(name: str, args: dict) -> str:
    """Execute one of the 6 core tools and return its output/error string."""
    try:
        if name == "read_file":
            return read_file(args.get("file_path") or args.get("path", ""))
        if name == "write_file":
            return write_file(args.get("file_path") or args.get("path", ""), args.get("content", ""))
        if name == "edit_file":
            return edit_file(
                args.get("file_path") or args.get("path", ""),
                args.get("old_string", ""),
                args.get("new_string", ""),
            )
        if name == "run_bash":
            return run_bash(args.get("command", ""), args.get("cwd"))
        if name == "grep_search":
            return grep_search(args.get("query", ""), args.get("include_pattern"))
        if name == "glob_search":
            return glob_search(args.get("pattern", ""))
        return f"[ERROR] Unknown tool: {name}"
    except Exception as e:
        return f"[ERROR] ({name}): {e}"
