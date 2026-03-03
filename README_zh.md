# TYXT Local Agent（桃源星庭本地智能体系统）

![Python](https://img.shields.io/badge/Python-3.10%2B-3776AB?logo=python&logoColor=white)
![平台](https://img.shields.io/badge/平台-Windows%2010%2F11-0078D6?logo=windows&logoColor=white)
![后端](https://img.shields.io/badge/后端-Flask-000000?logo=flask&logoColor=white)
![记忆引擎](https://img.shields.io/badge/记忆引擎-ChromaDB-5A45FF)
![安装方式](https://img.shields.io/badge/安装方式-一键BAT-2EA44F)
![许可](https://img.shields.io/badge/许可-AGPL--3.0-8A2BE2)

> 【桃源星庭本】是作者桃子的一个私人项目。Ollama memory_project是桃子为桃源星庭项目开发的一个本地部署 Agent 智能体系统。  
> 目标是让用户在本机或局域网里，拥有一个私人智能体，可以像AI管家一样聊天、记忆、辅助用户管理事务。

English README: [README.md](README.md)

## 1. 这是一个什么项目

TYXT 提供以下核心能力：

- 本地优先：核心逻辑本地运行，可选接入云模型 API
- 多用户：支持局域网内登录与权限区分（管理员 / 普通用户）
- 永久记忆：ChromaDB + 长期记忆 + 记忆条+用户画像 +可视化记忆管理
- Web UI：浏览器可用，支持聊天、参数设置、界面设置等
- 历史数据导入：支持导入历史对话/知识文件到记忆体系
- QQ 桥接（可选）：通过 `napcat_bridge.py` 接入 QQ 私聊/群聊
- TTS语音（可选）：通过 `GPT-SoVITS` 实现模型端文字转语音


## 2. 难度说明（给新手）

- 难度：简单（会解压文件、会双击 bat 即可）
- 不要求：Docker、Linux、复杂命令行操作
- 推荐系统：Windows 10/11

## 3. 项目入口

- 后端：`ollama_multi_agent.py`（Flask）
- 前端：`frontend/TYXT_UI.html`（由后端 `/` 路由返回）
- QQ 桥接（可选）：`napcat_bridge.py`

## 4. 环境要求

- Python 3.10+
- Windows 10/11（推荐）
- 若使用本地模型：安装 Ollama
- OCR（可选）：
  - 安装 Tesseract 可启用图片文字识别
  - 不装也能正常聊天，只是 OCR 功能不可用

## 5. 一键初始化（推荐）

首次运行一次：

```bat
setup_project.bat
```

脚本会自动做这些事：

1. 创建 `.venv` 虚拟环境
2. 安装 `requirements.txt` 依赖
3. 若不存在 `.env`，自动从 `.env.example` 复制
4. 初始化空 ChromaDB（`memory_db/`）
5. 尝试自动安装 Ollama（best-effort）
6. 尝试自动拉取 `.env` 中 `MODEL_NAME` 对应模型（默认 `deepseek-r1:8b`）

说明：
- 第一次可能需要几分钟（取决于网络和模型下载速度）

## 6. 启动后端 + UI

```bat
start_agent.bat
```

打开地址：

- HTTP：`http://127.0.0.1:5000/`
- HTTPS：`https://127.0.0.1:5000/`（当 `certs/lan/` 证书存在时）

补充：
- `start_agent.bat` 会优先使用 `.venv\Scripts\python.exe`

## 7. 如果需要多用户在局域网 HTTPS内使用（可选）

服务端（首次配置）：

```bat
start_lan_https_easy.bat
```

客户端（首次信任证书）：

```bat
client_join_lan_ui_zero_input.bat
```

通常首次完成后，客户端可直接通过浏览器收藏网址访问。

## 8. 环境变量配置（.env）

1. 复制 `.env.example` 为 `.env`（若脚本未自动完成）
2. 按需修改模型/API/路径
3. 重启后端生效

常用项（示例）：

- `LLM_PROVIDER=ollama` 或 `newapi`
- `MODEL_NAME=deepseek-r1:8b`
- `NEWAPI_BASE_URL=...`
- `NEWAPI_API_KEY=...`

OCR 说明：

- `TESSERACT_PATH` 可留空
- 留空时后端会尝试从系统 `PATH` 自动发现
- 检查接口：`GET /tools/ocr_status`

## 9. 记忆系统说明（简版）

- `memory_store.py`：记忆写入、元数据规范、多租户集合管理
- `memory_retriever_v2.py`：记忆检索与触发策略
- `profiles/`：用户画像与记忆条（JSON）
- `memory_warehouse/`：导入仓（历史对话/知识资料）
- `memory_db/`：Chroma 持久化目录

手动初始化 Chroma（必要时）：

```bat
.venv\Scripts\python tools\init_chromadb.py
```

## 10. 项目结构（核心）

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
├─ memory_db/              # ChromaDB 持久化
├─ profiles/               # 用户画像与记忆条数据
├─ memory_warehouse/       # 记忆导入仓
└─ Ollama_agent_shared/    # 共享运行目录（上传/导出/日志等）
```

## 11. 常见问题（FAQ）

### Q1：`setup_project.bat` 失败怎么办？
- 先确认已安装 Python 3.10+，并勾选 `Add to PATH`
- 若 Ollama 自动安装失败，请手动安装 Ollama 后再执行一次脚本

### Q2：`http://127.0.0.1:5000/` 打不开
- 检查 `start_agent.bat` 窗口是否报错
- 检查端口占用/防火墙拦截

### Q3：模型不存在
- 先执行：`ollama list` 查看模型
- 不存在则执行：`ollama pull deepseek-r1:8b`（或你的模型名）

### Q4：图片 OCR 不工作
- 安装 Tesseract 后重启后端
- 或检查 `GET /tools/ocr_status`

## 12. 许可证

本项目采用 **GNU Affero General Public License v3.0（AGPL-3.0）**。  
详见 [LICENSE](LICENSE)。

## 13. 支持桃源星庭 🌱

桃源星庭项目的长期目标，是探索人与 AI、与自然和谐共生的示范区。  
这个本地部署系统，是这条路上的第一步。

如果它对你有帮助，如果你也愿意支持这个梦想，  
欢迎通过下方二维码为项目添一块砖。  
也欢迎通过小红书或邮箱与我联系。

微信 / 支付宝赞赏码：

![donate](docs/donate-qrcode.png)

---

如果你只想“快速跑起来”，按这个顺序：

1. 双击 `setup_project.bat`
2. 双击 `start_agent.bat`
