# TYXT Local Agent v1.2.0

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
or:
```bat
start_local.bat
```
3. Open:
- `http://127.0.0.1:5000/`
- `https://127.0.0.1:5000/` (when LAN certs exist)

Recommended for China mainland networks (beginner two-step flow):

1. Step 1: Install Python dependencies first (without model pull)
Run `setup_start_cn.bat`. It uses CN pip mirrors by default.
When you see `[OK] Setup completed.`, step 1 is done.
2. Step 2: Install/start Ollama, pull model, then start TYXT
Install and start Ollama first. If `ollama` is not recognized, install Ollama before continuing:
- Official Windows download: https://ollama.com/download/windows
- Fallback install command (PowerShell): `winget install -e --id Ollama.Ollama`

After install, reopen terminal and verify:
```bat
ollama --version
```

Then run:
```bat
ollama pull deepseek-r1:8b
```
Then run:
```bat
start_agent.bat
```
Finally open `http://127.0.0.1:5000/`.

## Option B: Run with Docker

See full guide:

- [DOCKER.md](DOCKER.md)

Common commands:

```bat
docker compose up -d --build --pull never
docker compose ps
```

## Option C: Remote Access Without Domain (Self-Hosted Friendly)

Use this if users deploy by themselves and want phone access over 5G/public networks without domain setup.

Steps:

1. First-time local setup:
```bat
setup_start_cn.bat
```
2. Start remote entry (Cloudflare quick tunnel):
```bat
start_remote_easy.bat
```
If Cloudflare is unstable on your network, use the ngrok fallback:
```bat
start_remote_ngrok.bat
```
3. The script prints a public URL like `https://xxxx.trycloudflare.com`. Share this URL to phone users.
4. To stop tunnel and backend quickly:
```bat
stop_all.bat
```

Notes:

- This URL is temporary and changes after restart.
- Keep the `start_remote_easy.bat` window open during use.
- If `cloudflared` is missing, the script tries to install it automatically.

## Mobile Frontend (Phone)

The mobile client source is located in:

- `third_party/tyxt_mobile_frontend`

Real-device validation checklist:

- [docs/MOBILE_FRONTEND_QA.md](docs/MOBILE_FRONTEND_QA.md)

## When to Use Each BAT Script

- `setup_start_cn.bat`
CN-friendly setup/start entry. Uses China pip mirrors and follows a two-step default flow (dependencies first, Ollama/model handled separately).
- `setup_project.bat`
Use this for first-time setup. It creates `.venv`, installs dependencies, initializes ChromaDB, and tries to prepare Ollama/model.
- `start_agent.bat`
Use this for normal daily startup. It runs the backend with local env and opens the local UI URL.
- `start_local.bat`
Simplified local start shortcut. It warns if `.venv` is missing, then calls `start_agent.bat`.
- `start_remote_easy.bat`
No-domain remote access entry. It starts local backend in HTTP mode and creates a temporary public tunnel URL.
- `start_remote_ngrok.bat`
Fallback remote access entry using ngrok, useful when Cloudflare tunnel is unstable in your network.
- `stop_all.bat`
One-click stop for cloudflared/ngrok tunnels and backend processes on port 5000.
- `start_lan_https_easy.bat`
Use this on the server machine when you want LAN clients to access via HTTPS. It prepares certs and then starts the backend.
- `client_join_lan_ui.bat`
Use this on a LAN client machine for first-time client onboarding. It auto-discovers server and installs trust cert.
- `client_join_lan_ui_zero_input.bat`
Use this zero-input client script when server IP/domain is pre-filled, for non-technical users to connect with one double-click.

## Basic Configuration

Copy:

- `.env.example` -> `.env`

Common keys:

- `LLM_PROVIDER=ollama` or `newapi`
- `MODEL_NAME=deepseek-r1:8b`
- `OLLAMA_BASE_URL=http://127.0.0.1:11434/v1`
- `NEWAPI_BASE_URL=...`
- `NEWAPI_API_KEY=...`
- `TYXT_INBOUND_API_KEY=...` (optional but recommended when backend is exposed publicly)

Inbound API key enforcement:

- If `TYXT_INBOUND_API_KEY` is set, backend requires `Authorization: Bearer <key>` (or `X-API-Key`) for non-whitelisted routes.
- Default exempt paths include `/` and `/health` to avoid locking out basic checks.
- Mobile frontend can use this by filling `API Key` in API settings.

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

