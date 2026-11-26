# 🧠 ALES - Advanced Logic Execution System

> **A local-first, autonomous AI agent harness inspired by Claude Code.** 
> ALES is not just a chatbot; it's a fully functional desktop AI engineer that reads files, writes code, executes terminal commands, and self-corrects errors in real-time.

![Status](https://img.shields.io/badge/Status-Active-brightgreen)
![Version](https://img.shields.io/badge/Version-3.0.0-blue)
![Platform](https://img.shields.io/badge/Platform-Windows%20%7C%20Web%20%7C%20Mobile-lightgrey)
![License](https://img.shields.io/badge/License-MIT-purple)

---

## 🚀 Overview

ALES was built to solve a major problem in the AI ecosystem: **bloated, simulated AI agents.** After rigorous architectural audits, we stripped away 75+ useless tools and fake memories to build a lean, highly stable **Agentic Harness**. 

Inspired by Claude Code, ALES operates using a strict **ReAct (Reason + Act)** loop. When you give ALES a task—such as *"Create a Python script that generates a video, and run it"*—it doesn't give you instructions. It:
1. **Thinks** about the required steps.
2. **Writes** the Python code to a file (`write_file`).
3. **Installs** dependencies (`run_bash: pip install moviepy`).
4. **Executes** the script.
5. **Self-Corrects** if it encounters an error, reading terminal logs to fix the code and retry until success.

---

## ✨ Core Features

*   **🔄 Strict ReAct Agent Loop:** A 15-turn reasoning loop that prioritizes action over explanation. 
*   **🛠️ 6 Core Primitives (No Bloat):** We deleted 75+ tools to prevent "Attention Dilution." ALES only uses:
    *   `read_file`
    *   `write_file`
    *   `edit_file` (Exact search-and-replace, no full rewrites)
    *   `run_bash` (Stateful terminal that remembers `cwd`)
    *   `grep_search` & `glob_search`
*   **🔐 Access Code Authentication:** Securely store API keys in a local SQLite DB. Enter your Access Code once, and ALES remembers you.
*   **🧠 Real Vector Memory:** Powered by **ChromaDB**, replacing fake hash-based memory with real semantic search.
*   **🎨 Premium UI:** A Vercel/Claude-inspired dark theme featuring a live terminal console so you can watch the AI think, code, and execute in real-time.
*   **👁️ Computer Use (Vision):** ALES can take screenshots, analyze UIs using Vision models, and physically click/type to control your desktop.

---

## 🏗️ Architecture Stack

*   **Frontend:** React + Vite (Electron for Desktop, PWA for Mobile)
*   **Backend:** Python + FastAPI
*   **AI Engine:** Multi-provider routing (Groq, Gemini, OpenAI, OpenRouter, Anthropic).
*   **Memory:** ChromaDB (Vector RAG) + SQLite (Profiles & Keys)
*   **Desktop Control:** PyAutoGUI + MSS

---

## 🚦 Quick Start (For Users)

1. Navigate to the **Releases** page and download the latest **`ALES.exe`** (Portable).
2. Run the `.exe`. No installation required.
3. Enter your **Access Code** (e.g., `my_secret_code`). 
4. If it's your first time, go to **Settings**, enter your API keys (Groq / Gemini / Anthropic) once, and save them to your profile.
5. Start chatting, or ask ALES to code something for you!

---

## 💻 Building from Source (For Developers)

### Prerequisites
*   Python 3.11+
*   Node.js 18+

### Setup Backend
```bash
cd backend
pip install -r requirements.txt
python main.py
```
```bash
Setup Frontend
bash
cd frontend
npm install
npm run build
```
Package as EXE
```bash
npx electron-builder --win portable
