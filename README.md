A local-first, autonomous AI agent harness inspired by Claude Code.
ALES is not just a chatbot; it's a fully functional desktop AI engineer that can read files, write code, execute terminal commands, and even control your desktop GUI.

https://img.shields.io/badge/Status-Active-brightgreen
https://img.shields.io/badge/Version-3.0.0-blue
https://img.shields.io/badge/Platform-Windows%20%7C%20Web%20%7C%20Mobile-lightgrey
https://img.shields.io/badge/License-MIT-purple

🚀 Overview
ALES started as an ambitious "God AI" project but was ruthlessly refactored into a lean, highly stable Agentic Harness. Just like Claude Code, ALES operates using a strict ReAct (Reason + Act) loop.

When you give ALES a task—such as "Create a Python script that generates a video, and run it"—it doesn't just give you instructions. It will:

Think about the required steps.

Write the Python code to a file.

Run pip install moviepy via the terminal.

Execute the script.

Self-Correct if it encounters an error, and try again until it succeeds.

✨ Core Features (The Harness)
🔄 The ReAct Agent Loop: A strict 15-turn reasoning loop. The agent observes terminal outputs and auto-corrects its own code if an error occurs.

🛠️ 6 Core Primitives: We deleted 75+ useless tools to prevent "Attention Dilution". ALES only uses what matters:

read_file

write_file

edit_file
 (Search-and-replace, no full rewrites)

run_bash
 (Stateful terminal)

grep_search & glob_search

💻 Stateful Terminal: ALES remembers its current working directory (cwd). If it cds into a folder, the next command runs inside that folder.

👁️ Computer Use (Vision): ALES can take screenshots, analyze the UI using Vision models, and physically click or type to control your desktop.

🔐 Access Code Authentication: No more pasting API keys every time you refresh. Enter your Access Code once, and ALES securely pulls your API keys from a local SQLite database.

🧠 Real Vector Memory: Powered by ChromaDB, replacing fake hash-based memory with real semantic search.

🎨 Premium UI: A Vercel/Claude-inspired dark theme (Zinc 950), featuring a clean chat interface and a live terminal console.

🏗️ Architecture Stack
Frontend: React + Vite (Electron for Desktop, PWA for Mobile)

Backend: Python + FastAPI

AI Engine: Multi-provider routing (Groq, Gemini, OpenAI, OpenRouter) with automatic fallback and self-healing model discovery.

Memory: ChromaDB (Vector RAG) + SQLite (Profiles & Keys)

Desktop Control: PyAutoGUI + MSS

🚦 Quick Start (For Users)
Navigate to the Releases page and download the latest ALES.exe (Portable).

Run the .exe. No installation or dependencies required.

Enter your Access Code (e.g., ali123).

If it's your first time, go to Settings, enter your API keys (Groq / Gemini / OpenAI) once, and save them to your profile.

Start chatting or ask ALES to code something for you!

💻 Building from Source (For Developers)
Prerequisites
Python 3.11+

Node.js 18+

Setup Backend
bash
cd backend
pip install -r requirements.txt
python main.py
Setup Frontend
bash
cd frontend
npm install
npm run build
Package as EXE
bash
npx electron-builder --win portable
🗺️ Roadmap
☑ Week 1: The Great Purge (Tool reduction, Real RAG, Monolith refactor).
☑ Week 2: Stateful PTY Terminal & Claude Code ReAct Loop.
□ Week 3: AST-based code mapping (tree-sitter) for multi-file edits.
□ Week 4: Premium UI Overhaul & Commercial-grade stability.
⚠️ Philosophy: "No Fluff, Just Function"
ALES is built on the principle of Brutal Honesty. If a feature doesn't work, it's deleted. There are no fake mockups, no simulated "Darwinian evolutions," and no fake AI councils. It is a pure, terminal-first coding agent designed to get the job done.

Created by Ali Yılmaz | Inspired by Anthropic's Claude Code.
