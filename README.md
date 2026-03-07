# TYXT Local Agent v1.1.1

![Python](https://img.shields.io/badge/Python-3.10%2B-3776AB?logo=python&logoColor=white)
![Platform](https://img.shields.io/badge/Platform-Windows%2010%2F11-0078D6?logo=windows&logoColor=white)
![Backend](https://img.shields.io/badge/Backend-Flask-000000?logo=flask&logoColor=white)
![License](https://img.shields.io/badge/License-AGPL--3.0-8A2BE2)

TYXT is a local-first AI assistant system for chat, memory, tools, and LAN multi-user access.

中文文档: [README_zh.md](README_zh.md)

## Read This First (How to Download)

In the current release, both deployment methods require the full repository:

- Non-Docker mode: requires full source code
- Docker mode: image is built locally, so full repo is needed as build context

Download options:

1. GitHub `Code -> Download ZIP`
2. Or `git clone https://github.com/Momoko1556/tyxt-local-agent.git`

## Option A: Run on Windows (Recommended)

Requirements:

- Windows 10/11
- Python 3.10+
- Ollama (for local model inference)

Steps:

1. Initialize:
```bat
setup_project.bat
```
2. Start:
```bat
start_agent.bat
```
3. Open:
- `http://127.0.0.1:5000/`
- `https://127.0.0.1:5000/` (when LAN certs exist)

## Option B: Run with Docker

See full guide:

- [DOCKER.md](DOCKER.md)

Common commands:

```bat
docker compose up -d --build --pull never
docker compose ps
```

## Basic Configuration

Copy:

- `.env.example` -> `.env`

Common keys:

- `LLM_PROVIDER=ollama` or `newapi`
- `MODEL_NAME=deepseek-r1:8b`
- `OLLAMA_BASE_URL=http://127.0.0.1:11434/v1`
- `NEWAPI_BASE_URL=...`
- `NEWAPI_API_KEY=...`

## Project Layout

```text
frontend/TYXT_UI.html      Frontend page
ollama_multi_agent.py      Main backend entry
skills/                    Local + MCP skills
configs/                   Config directory
memory_db/                 Runtime DB directory
memory_warehouse/          Runtime memory warehouse
profiles/                  Runtime user profiles
```

## Privacy and GitHub Upload

This repo is prepared for public release, but keep these local/private files out of Git:

- `.env`
- `config.json`
- `tools/api_config.json`
- `configs/user_profiles.json`
- `configs/persona_config.json`
- `configs/mcp_servers.json`
- `memory_db/*`
- `memory_warehouse/*`
- `profiles/*`

## Troubleshooting

- UI not opening: check `start_agent.bat` logs and port conflicts
- Model missing: run `ollama list`, then `ollama pull <model>`
- Slow Docker pull: use the China mirror instructions in [DOCKER.md](DOCKER.md)

## License

Licensed under **AGPL-3.0**. See [LICENSE](LICENSE).

## Support

<img src="docs/donate-qrcode.png" alt="donate" width="320" />
