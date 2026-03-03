# TYXT Local Agent (Taoyuan Xingting Local Agent System)

![Python](https://img.shields.io/badge/Python-3.10%2B-3776AB?logo=python&logoColor=white)
![Platform](https://img.shields.io/badge/Platform-Windows%2010%2F11-0078D6?logo=windows&logoColor=white)
![Backend](https://img.shields.io/badge/Backend-Flask-000000?logo=flask&logoColor=white)
![Memory](https://img.shields.io/badge/Memory-ChromaDB-5A45FF)
![Setup](https://img.shields.io/badge/Setup-One--Click%20BAT-2EA44F)
![License](https://img.shields.io/badge/License-AGPL--3.0-8A2BE2)

> TYXT is part of Peach's private project ecosystem.  
> `Ollama memory_project` is the local deployment of that Agent system.  
> Its goal is to provide a private AI assistant on your own machine or LAN for chat, memory, and daily support tasks.

中文说明: [README_zh.md](README_zh.md)

## 1. What This Project Is

TYXT includes the following core capabilities:

- Local-first architecture: core logic runs locally, with optional cloud model APIs
- Multi-user support: LAN login with role separation (admin / normal user)
- Persistent memory: ChromaDB + long-term memory + memory strips + user profiles + visual memory management
- Web UI: browser-based interface with chat, parameter settings, and interface settings
- Historical data import: import previous chats and knowledge files into the memory system
- Optional QQ bridge: connect QQ private/group chats through `napcat_bridge.py`
- Optional TTS: model-side text-to-speech through `GPT-SoVITS`

## 2. Difficulty (Beginner Friendly)

- Difficulty: easy (if you can extract files and double-click `.bat` files)
- Not required: Docker, Linux, advanced CLI experience
- Recommended OS: Windows 10/11

## 3. Entry Points

- Backend: `ollama_multi_agent.py` (Flask)
- Frontend: `frontend/TYXT_UI.html` (served by backend route `/`)
- Optional QQ bridge: `napcat_bridge.py`

## 4. Requirements

- Python 3.10+
- Windows 10/11 (recommended)
- Ollama (if you plan to use local models)
- OCR (optional):
  - Install Tesseract to enable image text OCR
  - Without Tesseract, chat still works; only OCR-related features are unavailable

## 5. One-Click Initialization (Recommended)

Run once:

```bat
setup_project.bat
```

This script will automatically:

1. Create a `.venv` virtual environment
2. Install dependencies from `requirements.txt`
3. Copy `.env.example` to `.env` if `.env` does not exist
4. Initialize an empty ChromaDB in `memory_db/`
5. Try to auto-install Ollama (best effort)
6. Try to pull the model from `MODEL_NAME` in `.env` (default: `deepseek-r1:8b`)

Note:
- The first run may take a few minutes depending on network speed and model download size.

## 6. Start Backend + UI

```bat
start_agent.bat
```

Open:

- HTTP: `http://127.0.0.1:5000/`
- HTTPS: `https://127.0.0.1:5000/` (when certs exist in `certs/lan/`)

Additional note:
- `start_agent.bat` automatically prefers `.venv\Scripts\python.exe`.

## 7. Optional: Multi-User LAN HTTPS

Server side (first-time setup):

```bat
start_lan_https_easy.bat
```

Client side (first-time certificate trust):

```bat
client_join_lan_ui_zero_input.bat
```

After first-time trust setup, clients can usually open the saved HTTPS URL directly in a browser.

## 8. Environment Configuration (`.env`)

1. Copy `.env.example` to `.env` (if not already done by setup)
2. Update model/API/path values as needed
3. Restart backend to apply changes

Common keys (examples):

- `LLM_PROVIDER=ollama` or `newapi`
- `MODEL_NAME=deepseek-r1:8b`
- `NEWAPI_BASE_URL=...`
- `NEWAPI_API_KEY=...`

OCR notes:

- `TESSERACT_PATH` may be left empty
- If empty, the backend auto-detects Tesseract from system `PATH`
- Health check endpoint: `GET /tools/ocr_status`

## 9. Memory System (Brief)

- `memory_store.py`: memory writes, metadata schema, and multi-tenant collection management
- `memory_retriever_v2.py`: retrieval logic and trigger strategy
- `profiles/`: user profiles and memory strips (JSON)
- `memory_warehouse/`: warehouse for imported history/knowledge files
- `memory_db/`: Chroma persistence directory

Manual Chroma initialization (if needed):

```bat
.venv\Scripts\python tools\init_chromadb.py
```

## 10. Project Layout (Core)

```text
.
├─ ollama_multi_agent.py
├─ napcat_bridge.py
├─ memory_store.py
├─ memory_retriever_v2.py
├─ profiles_store.py
├─ multimodal_tools.py
├─ frontend/
│  └─ TYXT_UI.html
├─ tools/
│  └─ init_chromadb.py
├─ memory_db/              # ChromaDB persistence
├─ profiles/               # user profile and memory strip data
├─ memory_warehouse/       # memory import warehouse
└─ Ollama_agent_shared/    # shared runtime directory (uploads/exports/logs, etc.)
```

## 11. FAQ

### Q1: `setup_project.bat` failed. What should I do?
- Confirm Python 3.10+ is installed and `Add to PATH` was enabled during installation.
- If Ollama auto-install fails, install Ollama manually and run setup again.

### Q2: `http://127.0.0.1:5000/` cannot be opened
- Check the `start_agent.bat` console for errors.
- Check for port conflicts and firewall blocking.

### Q3: Model not found
- Run `ollama list` first.
- If missing, run `ollama pull deepseek-r1:8b` (or your target model).

### Q4: OCR is not working
- Install Tesseract and restart the backend.
- Or check `GET /tools/ocr_status`.

## 12. License

This project is licensed under **GNU Affero General Public License v3.0 (AGPL-3.0)**.  
See [LICENSE](LICENSE) for details.

## 13. Support Taoyuan Xingting 🌱

The long-term goal of the Taoyuan Xingting project is to explore a living model where humans, AI, and nature can thrive in harmony.  
This local deployment system is only the first step.

If this project has helped you, and you would like to support this dream,  
you are welcome to support it via the QR code below.  
You are also welcome to contact me via Xiaohongshu (RED) or email.

WeChat / Alipay donation QR code:

![donate](docs/donate-qrcode.png)

---

If you only want the fastest path:

1. Double-click `setup_project.bat`
2. Double-click `start_agent.bat`
