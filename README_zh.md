# TYXT Local Agent v1.1.1

![Python](https://img.shields.io/badge/Python-3.10%2B-3776AB?logo=python&logoColor=white)
![Platform](https://img.shields.io/badge/Platform-Windows%2010%2F11-0078D6?logo=windows&logoColor=white)
![Backend](https://img.shields.io/badge/Backend-Flask-000000?logo=flask&logoColor=white)
![License](https://img.shields.io/badge/License-AGPL--3.0-8A2BE2)

TYXT 是一个本地优先的 AI 助手系统（聊天、记忆、工具、局域网多用户）。

English: [README.md](README.md)

## 先看这条（下载方式）

当前版本无论你使用哪种部署方式，都需要下载完整仓库代码：

- 非 Docker 运行：需要完整源码
- Docker 运行：当前是本地构建镜像，也需要完整源码作为 build context

下载方式：

1. GitHub 点 `Code -> Download ZIP`
2. 或 `git clone https://github.com/Momoko1556/tyxt-local-agent.git`

## 方式 A：Windows 直接运行（推荐新手）

环境要求：

- Windows 10/11
- Python 3.10+
- Ollama（本地模型时）

步骤：

1. 运行初始化：
```bat
setup_project.bat
```
2. 启动服务：
```bat
start_agent.bat
```
3. 打开：
- `http://127.0.0.1:5000/`
- `https://127.0.0.1:5000/`（有 LAN 证书时）

## 方式 B：Docker 运行

详细说明见：

- [DOCKER.md](DOCKER.md)

常用命令：

```bat
docker compose up -d --build --pull never
docker compose ps
```

## 基础配置

先复制：

- `.env.example` -> `.env`

常用项：

- `LLM_PROVIDER=ollama` 或 `newapi`
- `MODEL_NAME=deepseek-r1:8b`
- `OLLAMA_BASE_URL=http://127.0.0.1:11434/v1`
- `NEWAPI_BASE_URL=...`
- `NEWAPI_API_KEY=...`

## 目录说明

```text
frontend/TYXT_UI.html      前端页面
ollama_multi_agent.py      主后端入口
skills/                    本地技能与 MCP 技能
configs/                   配置文件目录
memory_db/                 运行时数据库目录
memory_warehouse/          运行时记忆仓目录
profiles/                  运行时用户画像目录
```

## 隐私与上传

仓库已按公开发布做了清理，但以下文件仍应保持本地私有，不要上传：

- `.env`
- `config.json`
- `tools/api_config.json`
- `configs/user_profiles.json`
- `configs/persona_config.json`
- `configs/mcp_servers.json`
- `memory_db/*`
- `memory_warehouse/*`
- `profiles/*`

## 常见问题

- UI 打不开：检查 `start_agent.bat` 日志与端口占用
- 模型找不到：执行 `ollama list`，没有就 `ollama pull <model>`
- Docker 拉镜像慢：参考 [DOCKER.md](DOCKER.md) 的国内镜像方案

## 许可证

本项目使用 **AGPL-3.0**，详见 [LICENSE](LICENSE)。

## Support

<img src="docs/donate-qrcode.png" alt="donate" width="320" />
