# TYXT Local Agent v1.1.1

![Python](https://img.shields.io/badge/Python-3.10%2B-3776AB?logo=python&logoColor=white)
![Platform](https://img.shields.io/badge/Platform-Windows%2010%2F11-0078D6?logo=windows&logoColor=white)
![Backend](https://img.shields.io/badge/Backend-Flask-000000?logo=flask&logoColor=white)
![Memory](https://img.shields.io/badge/Memory-ChromaDB-5A45FF)
![Setup](https://img.shields.io/badge/Setup-One--Click%20BAT-2EA44F)
![License](https://img.shields.io/badge/License-AGPL--3.0-8A2BE2)

TYXT is a local-first AI assistant system for chat, memory, tools, and LAN multi-user access.
It is designed to run on your own Windows machine first, with optional cloud API and optional QQ bridge.

中文文档: [README_zh.md](README_zh.md)

## Features

- Local-first architecture (Flask backend + browser UI)
- Multi-user login and role separation (admin / user)
- Persistent memory system (ChromaDB + profiles + memory strips)
- Tool system (local skills + MCP skills)
- Optional OCR / TTS support
- Optional NapCat QQ bridge
- One-click setup and startup scripts for beginners

## Requirements

- Windows 10/11 (recommended)
- Python 3.10+
- Ollama (if you want local model inference)
- Optional: Tesseract OCR (for image text recognition)

## Quick Start (Recommended)

1. Initialize environment:

```bat
setup_project.bat
```

2. Start backend + web UI:

```bat
start_agent.bat
```

3. Open UI in browser:

- `http://127.0.0.1:5000/`
- `https://127.0.0.1:5000/` (when LAN certs exist)

## Docker Deployment

Use the publish-ready Docker packaging:

- [DOCKER.md](DOCKER.md)

## LAN HTTPS (Optional)

Server first-time setup:

```bat
start_lan_https_easy.bat
```

Client first-time trust:

```bat
client_join_lan_ui_zero_input.bat
```

After trust is installed, clients can open the saved HTTPS URL directly.

## Environment Config

Main config file:

- `.env` (copy from `.env.example`)

Common keys:

- `LLM_PROVIDER=ollama` or `newapi`
- `MODEL_NAME=deepseek-r1:8b`
- `OLLAMA_BASE_URL=http://127.0.0.1:11434/v1`
- `NEWAPI_BASE_URL=...`
- `NEWAPI_API_KEY=...`

MCP bridge keys:

- `TYXT_MCP_ENABLED=0` or `1`
- `TYXT_MCP_CONFIG_PATH=./configs/mcp_servers.json`

Web search keys:

- `web_search_provider` / `web_search_api_key` are managed in UI settings
- If using Tavily, register at `https://app.tavily.com/home` to get an API key

## Project Layout

```text
.
├─ ollama_multi_agent.py          # main backend
├─ frontend/TYXT_UI.html          # web UI
├─ memory_store.py                # memory write / metadata
├─ memory_retriever_v2.py         # retrieval logic
├─ skills_registry.py             # skill loader/runtime
├─ mcp_bridge.py                  # MCP bridge core
├─ mcp_manager.py                 # MCP config manager
├─ skills/                        # local + mcp skills
├─ tools/                         # helper scripts
├─ memory_db/                     # runtime DB (kept empty in repo)
├─ memory_warehouse/              # runtime warehouse (kept empty in repo)
├─ profiles/                      # runtime profiles (kept empty in repo)
└─ Ollama_agent_shared/           # shared runtime files (kept empty in repo)
```

## Runtime Data Policy

This repository is prepared for publishing:

- Runtime DB files are cleared
- Temporary/cache files are cleared
- User profiles and persona data are reset
- Local secret configs are reset/ignored

Do **not** commit private files such as:

- `.env`
- `config.json`
- `tools/api_config.json`
- `configs/user_profiles.json`
- `configs/persona_config.json`
- `configs/mcp_servers.json`

## Troubleshooting

- UI cannot open: check `start_agent.bat` console output and firewall/port usage.
- Model not found: run `ollama list`, then `ollama pull <model>`.
- OCR unavailable: install Tesseract and check `GET /tools/ocr_status`.
- MCP tool not working: verify MCP JSON config and related API keys.

## License

Licensed under **GNU Affero General Public License v3.0 (AGPL-3.0)**.
See [LICENSE](LICENSE).

## Support Taoyuan Xingting 🌱

If this project helps you and you want to support future development:

<img src="docs/donate-qrcode.png" alt="donate" width="320" />

