"""
_ales_e2e_test.py — Tests the 8-primitive engine directly (no server needed).
"""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "backend"))

from tool_router import bash, write_file, read_file, edit_file, todo_write, get_todos, execute_tool, TOOLS

print(f"\n{'='*60}")
print("ALES v7 E2E TEST — 8 Primitive Engine")
print(f"{'='*60}")

# TEST 1: tool count
assert len(TOOLS) == 8, f"Expected 8 tools, got {len(TOOLS)}"
tool_names = [t["function"]["name"] for t in TOOLS]
expected = {"bash", "read_file", "write_file", "edit_file", "grep_search", "glob_search", "task", "todo_write"}
assert set(tool_names) == expected, f"Wrong tools: {set(tool_names)}"
print(f"✅ TOOLS: {tool_names}")

# TEST 2: write_file
r = write_file("_e2e_test.py", 'print("Hello")\n')
assert "OK" in r or "Written" in r or "reated" in r, f"write_file failed: {r}"
print(f"✅ write_file: {r}")

# TEST 3: read_file
content = read_file("_e2e_test.py")
assert 'print("Hello")' in content, f"read_file content wrong: {content}"
print(f"✅ read_file: got {len(content)} chars")

# TEST 4: bash — run script
out = bash("python _e2e_test.py")
assert "Hello" in out, f"bash output wrong: {out}"
print(f"✅ bash run: {out.strip()[:80]}")

# TEST 5: edit_file — exact once replacement
r = edit_file("_e2e_test.py", 'print("Hello")', 'print("Hi")')
assert "OK" in r, f"edit_file failed: {r}"
content2 = read_file("_e2e_test.py")
assert 'print("Hi")' in content2, f"edit_file did not replace: {content2}"
print(f"✅ edit_file: replaced Hello -> Hi")

# TEST 6: bash — verify edit
out2 = bash("python _e2e_test.py")
assert "Hi" in out2, f"after edit bash output wrong: {out2}"
print(f"✅ bash after edit: {out2.strip()[:80]}")

# TEST 7: edit_file error on 0 occurrences
try:
    edit_file("_e2e_test.py", 'print("DOES_NOT_EXIST")', 'x')
    assert False, "Should have raised ValueError"
except ValueError as e:
    print(f"✅ edit_file ValueError (0 occurrences): {str(e)[:60]}")

# TEST 8: todo_write
r = todo_write([
    {"id":"1","text":"Write script","status":"done"},
    {"id":"2","text":"Run script","status":"in_progress"},
    {"id":"3","text":"Edit script","status":"pending"},
])
assert "OK" in r, f"todo_write failed: {r}"
todos = get_todos()
assert len(todos) == 3, f"Expected 3 todos, got {len(todos)}"
print(f"✅ todo_write: {r}")

# TEST 9: execute_tool dispatcher for bash alias
r9 = execute_tool("bash", {"command": "echo DISPATCHER_OK"})
assert "DISPATCHER_OK" in r9, f"dispatcher bash failed: {r9}"
print(f"✅ execute_tool(bash): {r9.strip()[:60]}")

# Cleanup
bash("del _e2e_test.py" if os.name == "nt" else "rm -f _e2e_test.py")

print(f"\n{'='*60}")
print("✅ ALL E2E TESTS PASSED — ALES v7 Engine Verified")
print(f"{'='*60}\n")
