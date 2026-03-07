# TYXT Local Agent v1.1.0（桃源星庭本地智能体系统）

![Python](https://img.shields.io/badge/Python-3.10%2B-3776AB?logo=python&logoColor=white)
![平台](https://img.shields.io/badge/平台-Windows%2010%2F11-0078D6?logo=windows&logoColor=white)
![后端](https://img.shields.io/badge/后端-Flask-000000?logo=flask&logoColor=white)
![记忆引擎](https://img.shields.io/badge/记忆引擎-ChromaDB-5A45FF)
![安装方式](https://img.shields.io/badge/安装方式-一键BAT-2EA44F)
![许可](https://img.shields.io/badge/许可-AGPL--3.0-8A2BE2)

TYXT 是一个本地优先的 AI 助手系统，支持聊天、记忆、工具扩展和局域网多用户访问。
默认场景是 Windows 本机部署，也可以按需接入云 API、QQ 桥接和 MCP 工具。

English: [README.md](README.md)

## 功能概览

- 本地优先架构（Flask 后端 + 浏览器 UI）
- 多用户登录与权限区分（管理员 / 普通用户）
- 持久记忆系统（ChromaDB + 用户画像 + 记忆条）
- 工具系统（本地 Skills + MCP Skills）
- 可选 OCR / TTS 能力
- 可选 NapCat QQ 桥接
- 面向新手的一键初始化与启动脚本

## 环境要求

- Windows 10/11（推荐）
- Python 3.10+
- Ollama（如果你使用本地模型推理）
- 可选：Tesseract OCR（图片文字识别）

## 快速开始（推荐）

1. 一键初始化环境：

```bat
setup_project.bat
```

2. 启动后端与 UI：

```bat
start_agent.bat
```

3. 浏览器打开：

- `http://127.0.0.1:5000/`
- `https://127.0.0.1:5000/`（存在局域网证书时）

## 局域网 HTTPS（可选）

服务端首次配置：

```bat
start_lan_https_easy.bat
```

客户端首次信任证书：

```bat
client_join_lan_ui_zero_input.bat
```

首次信任后，客户端通常可直接使用收藏的 HTTPS 地址访问。

## 环境变量配置

主配置文件：

- `.env`（由 `.env.example` 复制）

常用配置项：

- `LLM_PROVIDER=ollama` 或 `newapi`
- `MODEL_NAME=deepseek-r1:8b`
- `OLLAMA_BASE_URL=http://127.0.0.1:11434/v1`
- `NEWAPI_BASE_URL=...`
- `NEWAPI_API_KEY=...`

MCP 桥接配置：

- `TYXT_MCP_ENABLED=0` 或 `1`
- `TYXT_MCP_CONFIG_PATH=./configs/mcp_servers.json`

联网搜索说明：

- `web_search_provider` / `web_search_api_key` 通过 UI 设置管理
- 如果你使用 Tavily，请先在 `https://app.tavily.com/home` 注册并获取 API Key

## 项目结构

```text
.
├─ ollama_multi_agent.py          # 主后端
├─ frontend/TYXT_UI.html          # 前端 UI
├─ memory_store.py                # 记忆写入/元数据
├─ memory_retriever_v2.py         # 检索逻辑
├─ skills_registry.py             # Skill 加载与运行
├─ mcp_bridge.py                  # MCP Bridge 核心
├─ mcp_manager.py                 # MCP 配置管理
├─ skills/                        # local + mcp 技能
├─ tools/                         # 辅助脚本
├─ memory_db/                     # 运行时数据库（仓库内默认空）
├─ memory_warehouse/              # 运行时仓库（仓库内默认空）
├─ profiles/                      # 运行时画像（仓库内默认空）
└─ Ollama_agent_shared/           # 共享运行目录（仓库内默认空）
```

## 发布前数据清理策略

本仓库按可发布状态处理：

- 数据库文件清空
- 临时文件和缓存清空
- 用户画像和人格文件重置
- 本地敏感配置重置/忽略提交

请不要提交以下本地私密文件：

- `.env`
- `config.json`
- `tools/api_config.json`
- `configs/user_profiles.json`
- `configs/persona_config.json`
- `configs/mcp_servers.json`

## 常见问题

- UI 打不开：先看 `start_agent.bat` 控制台报错，再检查端口和防火墙。
- 模型找不到：执行 `ollama list`，没有就 `ollama pull <模型名>`。
- OCR 不可用：安装 Tesseract，然后检查 `GET /tools/ocr_status`。
- MCP 工具不可用：检查 MCP JSON 配置和相关 API Key。

## 许可证

本项目采用 **GNU Affero General Public License v3.0（AGPL-3.0）**。
详见 [LICENSE](LICENSE)。
