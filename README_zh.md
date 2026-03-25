# TYXT Local Agent v1.2.0

![Python](https://img.shields.io/badge/Python-3.10%2B-3776AB?logo=python&logoColor=white)
![Platform](https://img.shields.io/badge/Platform-Windows%2010%2F11-0078D6?logo=windows&logoColor=white)
![Backend](https://img.shields.io/badge/Backend-Flask-000000?logo=flask&logoColor=white)
![License](https://img.shields.io/badge/License-AGPL--3.0-8A2BE2)

TYXT 是一个本地优先的 AI 助手系统（聊天、记忆、工具、局域网多用户）。

English: [README.md](README.md)

## 新增功能

- **群聊**
  - 支持群会话、群基础信息、群成员管理与群级记忆。
- **多 Agent 协作**
  - 采用 Router + Worker 的群聊/接力回复链路，支持多 Agent 联动回复。
- **Agent 权限**
  - 按场景（chat/work）配置权限矩阵，可控文档、画像、关系、运行日志等资源访问。
- **待机作业**
  - 支持反刍层、深度思考层后台作业，会话可开始/暂停/继续/结束并追踪进度。
- **手机端接入**
  - 支持手机端账号登录 + API Key 鉴权；后端可直接提供 `/mobile/` 入口。

## 新手教程（WebUI + 手机UI）

如果你想按步骤完成“局域网使用”或“手机 5G 跨网登录”，看这份详细教程：

- [docs/BEGINNER_WEBUI_MOBILEUI_GUIDE_ZH.md](docs/BEGINNER_WEBUI_MOBILEUI_GUIDE_ZH.md)

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
或使用：
```bat
start_local.bat
```
3. 打开：
- `http://127.0.0.1:5000/`
- `https://127.0.0.1:5000/`（有 LAN 证书时）

中国用户安装（小白两步走）：

1. 第一步：先装 Python 依赖（不拉模型）
运行 `setup_start_cn.bat`，脚本会自动使用国内 pip 镜像安装依赖。  
看到 `[OK] Setup completed.` 就表示第一步完成。
2. 第二步：单独安装 Ollama 并拉模型，再启动项目
先安装并启动 Ollama（如果提示 `ollama 不是内部或外部命令`，说明 Ollama 还没安装好）：
- 官方下载（Windows）：https://ollama.com/download/windows
- 备用安装命令（PowerShell）：`winget install -e --id Ollama.Ollama`

安装完成后，重新打开命令行，先验证：
```bat
ollama --version
```

然后执行：
```bat
ollama pull deepseek-r1:8b
```
拉完模型后，回到项目目录运行：
```bat
start_agent.bat
```
最后打开 `http://127.0.0.1:5000/`。

## 方式 B：Docker 运行

详细说明见：

- [DOCKER.md](DOCKER.md)

常用命令：

```bat
docker compose up -d --build --pull never
docker compose ps
```

## 方式 C：自部署跨网访问（无需域名）

适合“用户自己部署 + 手机 5G/外网访问”，不想折腾域名备案。

步骤：

1. 先本地初始化一次（首次）：
```bat
setup_start_cn.bat
```
2. 启动跨网入口（自动使用 Cloudflare Quick Tunnel）：
```bat
start_remote_easy.bat
```
若 Cloudflare 网络不稳定，可改用 ngrok 备用入口：
```bat
start_remote_ngrok.bat
```
3. 脚本会输出一个 `https://xxxx.trycloudflare.com` 地址，发给手机端即可。
   - Web 端地址：`https://xxxx.trycloudflare.com/`
   - 手机 UI 地址：`https://xxxx.trycloudflare.com/mobile/`
   - 手机 API 地址：`https://xxxx.trycloudflare.com/v1`
4. 停止服务时运行：
```bat
stop_all.bat
```

注意：

- 该地址是临时地址，重启隧道后会变化。
- 运行 `start_remote_easy.bat` 的窗口必须保持打开。
- 如果本机未安装 `cloudflared`，脚本会尝试自动安装；失败时会提示手动安装命令。

## BAT 脚本什么时候用

- `setup_start_cn.bat`
面向中国网络环境的一键安装+启动入口。优先用国内 pip 镜像，并按“两步走”默认策略先装依赖、再单独处理 Ollama/模型。
- `setup_project.bat`
首次初始化环境时使用。会创建 `.venv`、安装依赖、初始化 ChromaDB，并尝试安装/拉取 Ollama 模型。
- `start_agent.bat`
日常启动后端和网页时使用。默认优先用 `.venv`，自动打开本机 UI 地址。
- `start_local.bat`
本地启动快捷入口（等价于调用 `start_agent.bat`），给小白用户减少选择困难。
- `start_mobile_ui.bat`
手机 UI 启动快捷入口。自动切到 `third_party\tyxt_mobile_frontend`，首次会自动 `npm install`，并以局域网可访问方式启动 `5173` 端口。
- `start_remote_easy.bat`
跨网免域名入口。自动拉起本地后端并创建临时公网地址（`trycloudflare.com`），适合手机外网访问测试。
- `start_remote_ngrok.bat`
跨网备用入口（ngrok）。当 Cloudflare 隧道在本机网络下不稳定时可切换使用。
- `stop_all.bat`
一键停止 `cloudflared` / `ngrok` 隧道和 5000 端口后端进程。
- `start_lan_https_easy.bat`
当你要给局域网其他设备通过 HTTPS 访问时使用（服务端机器执行）。会准备证书并调用 `start_agent.bat` 启动。
- `client_join_lan_ui.bat`
给局域网客户端首次接入时使用（客户端机器执行）。会自动发现服务端并安装信任证书。
- `client_join_lan_ui_zero_input.bat`
零输入客户端脚本（固定了服务端 IP/域名），适合发给不懂配置的客户端用户直接双击接入。

## 手机端启动与登录（推荐）

1. 启动后端 + 公网隧道：
```bat
start_remote_easy.bat
```
2. 手机浏览器打开：
   - `https://<隧道域名>/mobile/`
3. 登录弹窗中填写：
   - 服务器 API 地址：`https://<隧道域名>/v1`
   - 服务器 API Key：与 `mobile_link_api_key` / `TYXT_INBOUND_API_KEY` 相同
   - 账号和密码：TYXT 账号密码
4. 隧道重启后域名会变化，需要同步更新手机端页面地址和 API 地址。

## 基础配置

先复制：

- `.env.example` -> `.env`

常用项：

- `LLM_PROVIDER=ollama` 或 `newapi`
- `MODEL_NAME=deepseek-r1:8b`
- `OLLAMA_BASE_URL=http://127.0.0.1:11434/v1`
- `NEWAPI_BASE_URL=...`
- `NEWAPI_API_KEY=...`
- `TYXT_INBOUND_API_KEY=...`（可选；公网暴露时强烈建议设置）

入站 API Key 强制校验说明：

- 设置 `TYXT_INBOUND_API_KEY` 后，后端会对非白名单路由强制校验：
  `Authorization: Bearer <key>`（或 `X-API-Key`）。
- 默认白名单包含 `/`、`/health`，避免把基础探活和首页锁死。
- 手机端可在 API 配置里的 `API Key` 填同一密钥接入。

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

