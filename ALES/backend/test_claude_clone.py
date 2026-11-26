import os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from main import TOOLS, execute_tool, run_terminal_command, BASE_SYSTEM
from filesystem import str_replace_editor
from tool_router import select_relevant_tools, CORE_TOOLS

print("=== TEST 1: TOOLS & str_replace_editor ===")
test_file = os.path.join(os.path.dirname(__file__), "scratch_test.txt")
with open(test_file, "w", encoding="utf-8") as f:
    f.write("Line 1: Hello World\nLine 2: Target text to replace\nLine 3: Goodbye\n")

res = execute_tool("str_replace_editor", {
    "file_path": test_file,
    "old_string": "Line 2: Target text to replace",
    "new_string": "Line 2: Replaced by Claude Code Clone!"
})
print(f"str_replace_editor result: {res}")
with open(test_file, "r", encoding="utf-8") as f:
    content = f.read()
assert "Replaced by Claude Code Clone!" in content, "Replacement failed!"
if os.path.exists(test_file): os.remove(test_file)
print("[PASS] str_replace_editor verified successfully!")

print("\n=== TEST 2: Persistent Terminal CWD ===")
cwd_before = run_terminal_command("cd backend")
print(f"cd backend result: {cwd_before}")
out_dir = run_terminal_command("dir")
print(f"dir output contains files: {'main.py' in out_dir or 'filesystem.py' in out_dir}")
assert "main.py" in out_dir or "filesystem.py" in out_dir, "cwd did not persist!"
print("[PASS] Persistent terminal cwd verified successfully!")

print("\n=== TEST 3: Computer Use GUI Tools ===")
gui_tools = ["take_screenshot", "mouse_click", "keyboard_type", "keyboard_press"]
for gt in gui_tools:
    assert any(t.get("function", {}).get("name") == gt for t in TOOLS), f"{gt} missing from TOOLS!"
print(f"[PASS] All Computer Use tools ({gui_tools}) present in TOOLS!")

print("\n=== TEST 4: Tool Router Core Tools ===")
assert "str_replace_editor" in CORE_TOOLS, "str_replace_editor missing from CORE_TOOLS"
assert "mouse_click" in CORE_TOOLS, "mouse_click missing from CORE_TOOLS"
print(f"[PASS] Core tools include Claude Code & GUI primitives: {len(CORE_TOOLS)} tools")

print("\n=== TEST 5: System Prompt Brevity ===")
assert "You are ALES, a Claude Code clone" in BASE_SYSTEM, "Prompt identity missing"
assert "BE EXTREMELY BRIEF" in BASE_SYSTEM, "Brevity rule missing"
print(f"[PASS] Crisp Claude Code clone prompt verified! (~{len(BASE_SYSTEM)} chars)")

print("\n🎉 ALL CLAUDE CODE & COMPUTER USE TESTS PASSED! 🎉")
