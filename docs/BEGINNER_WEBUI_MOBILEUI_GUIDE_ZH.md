# TYXT 新手教程：局域网与跨网启动（WebUI + 手机UI）

这份教程给第一次接触 TYXT 的用户，按步骤操作即可。

## 0. 先理解 3 件事

1. `http://你的IP:5000/` 打开的是 **WebUI**（后端自带页面）。
2. **手机UI** 是独立前端，不在 `5000/` 根路由里。
3. 手机UI登录时，账号密码校验来自你的后端（不是 `tyxt.site` 统一账号）。

---

## 1. 一次性准备（只做一次）

1. 下载项目源码（ZIP 或 `git clone`）。
2. 运行：
```bat
setup_start_cn.bat
```
3. 等待安装完成后，确认有 `.venv` 目录。

---

## 2. 局域网内使用（电脑和手机在同一 Wi-Fi）

## 2.1 启动后端

在项目根目录双击：

```bat
start_local.bat
```

启动成功后，后端地址通常是：

- `http://127.0.0.1:5000/`
- 局域网：`http://你的局域网IP:5000/`

例如你的 IP 是 `192.168.0.103`，则后端是 `http://192.168.0.103:5000/`。

## 2.2 打开 WebUI（电脑）

电脑浏览器打开：

```text
http://127.0.0.1:5000/
```

或：

```text
http://192.168.0.103:5000/
```

## 2.3 打开手机UI（手机）

在电脑开一个终端（CMD 或 PowerShell）：

```bat
cd /d "e:\Ollama memory_project\third_party\tyxt_mobile_frontend"
npm install
npm run dev -- --host 0.0.0.0 --port 5173
```

然后手机浏览器打开：

```text
http://192.168.0.103:5173
```

登录页填写：

- 服务器地址：`http://192.168.0.103:5000/v1`
- 服务器 Key：如果你在 WebUI 配置了“手机关联密码/入站 API Key”，这里要填同一个值
- 账号密码：你后端里的账号密码

## 2.4 局域网模式常见报错

1. `npm ERR! enoent ... C:\Users\xxx\package.json`  
原因：你没进入 `tyxt_mobile_frontend` 目录。  
修复：用 `cd /d "e:\Ollama memory_project\third_party\tyxt_mobile_frontend"`。

2. 手机打不开 `:5173`  
原因：防火墙拦截 Node。  
修复：允许 Node 在“专用网络”通信。

---

## 3. 手机与服务器跨网/跨域登录（手机 5G、异地访问）

适用于手机不在同一局域网（比如手机开 5G）。

## 3.1 启动后端 + 公网隧道（推荐）

在项目根目录双击：

```bat
start_remote_easy.bat
```

脚本会：

1. 启动后端（5000）
2. 自动创建公网临时地址（`https://xxxx.trycloudflare.com`）

记录脚本窗口里输出的公网地址，记作 `PUBLIC_URL`。

## 3.2 打开 WebUI（电脑）

电脑本机仍然用：

```text
http://127.0.0.1:5000/
```

## 3.3 打开手机UI（手机）

手机浏览器打开：

```text
https://tyxt.site
```

登录页填写：

- 服务器地址：`PUBLIC_URL/v1`
- 服务器 Key：如果你启用了入站 API Key，这里填同一个值
- 账号密码：后端账号

## 3.4 Cloudflare 不稳定时（备用 ngrok）

运行：

```bat
start_remote_ngrok.bat
```

如果提示 token，先执行：

```bat
ngrok config add-authtoken <你的token>
```

然后用脚本输出的 `https://xxxx.ngrok-free.app`（或 `dev`）地址，手机端填：

```text
https://xxxx.ngrok-xxx.xxx/v1
```

## 3.5 跨网模式常见报错

1. 登录成功但后续请求异常  
检查手机“调试日志”里聊天 URL 是否是你的后端：
`https://你的公网地址/v1/chat/completions`。
如果不是，说明配置走偏了。

2. `Unauthorized: missing or invalid API key`  
说明后端开了入站 API Key，但手机没填或填错服务器 Key。

3. 隧道一断手机就连不上  
这是正常现象。`start_remote_easy.bat` / `start_remote_ngrok.bat` 窗口必须保持运行。

---

## 4. 一键停止

在项目根目录双击：

```bat
stop_all.bat
```

---

## 5. 最简单记忆版

1. 同 Wi-Fi：`start_local.bat` + 手机开 `http://你的IP:5173`。  
2. 外网 5G：`start_remote_easy.bat` + 手机开 `https://tyxt.site`，服务器地址填 `PUBLIC_URL/v1`。  
3. 账号永远是你后端里的账号，不是 `tyxt.site` 平台账号。  
