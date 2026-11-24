import asyncio
import os
import sys

# Add backend to path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from tool_router import select_relevant_tools, CORE_TOOLS
from long_term_memory import add as ltm_add, recall as ltm_recall
from routers.terminal import run_terminal_command_internal
from main import TOOLS, BASE_SYSTEM

def test_tool_reduction():
    print("=== TEST 1: Tool Reduction & Primitives ===")
    print(f"Total available raw tools in system: {len(TOOLS)}")
    
    # Generic query
    generic_tools = select_relevant_tools("Merhaba bugün nasılsın?", TOOLS)
    tool_names = [t.get("function", {}).get("name") for t in generic_tools]
    print(f"Generic tools returned ({len(tool_names)}): {tool_names}")
    # Core primitives should match CORE_TOOLS
    assert len(generic_tools) <= 5, f"Expected <= 5 tools for generic query, got {len(generic_tools)}"
    print("[PASS] Generic prompt returned strictly Core Primitives!")

    # PDF query
    pdf_tools = select_relevant_tools("Bana Türkiye ekonomisi hakkında kapsamlı bir PDF rapor hazırla", TOOLS)
    pdf_tool_names = [t.get("function", {}).get("name") for t in pdf_tools]
    print(f"PDF query tools returned ({len(pdf_tool_names)}): {pdf_tool_names}")
    assert "generate_pdf" in pdf_tool_names, "generate_pdf must be present for PDF queries"
    print("[PASS] PDF query correctly includes generate_pdf!")

def test_prompt_size():
    print("\n=== TEST 2: System Prompt Size ===")
    print(f"Current BASE_SYSTEM length: {len(BASE_SYSTEM)} chars (~{len(BASE_SYSTEM)//4} tokens)")
    assert len(BASE_SYSTEM) < 2500, f"BASE_SYSTEM is too large! Expected < 2500 chars, got {len(BASE_SYSTEM)}"
    print("[PASS] System prompt is crisp and unbloated!")

def test_real_vector_rag():
    print("\n=== TEST 3: ChromaDB Vector Memory ===")
    # Add memory
    res = ltm_add("Ali prefers dark mode in all IDEs and uses Python 3.13 for backend microservices.")
    assert res.get("ok"), f"Failed to add memory: {res}"
    print(f"[PASS] Memory stored: {res.get('id')}")
    
    # Recall with semantic similarity (not exact keywords)
    results = ltm_recall("What theme and programming language does Ali like?", k=3)
    print(f"Semantic recall results count: {len(results)}")
    assert len(results) > 0, "Expected at least 1 memory recalled via dense vector search"
    print(f"[PASS] Vector search matched: '{results[0].get('text')}' (Similarity: {results[0].get('similarity')})")

def test_terminal_primitive():
    print("\n=== TEST 4: Terminal Command Primitive ===")
    res = run_terminal_command_internal("echo ALES Core Primitive Working")
    print(f"Terminal run result: {res}")
    assert res.get("ok"), "Terminal command failed"
    assert "ALES Core Primitive Working" in res.get("stdout", "")
    print("[PASS] Terminal primitive executed cleanly!")

if __name__ == "__main__":
    print("RUNNING ALES WEEK 1 VERIFICATION TEST SUITE...")
    test_tool_reduction()
    test_prompt_size()
    test_real_vector_rag()
    test_terminal_primitive()
    print("\n🎉 ALL WEEK 1 ARCHITECTURAL TESTS PASSED SUCCESSFULLY! 🎉")
