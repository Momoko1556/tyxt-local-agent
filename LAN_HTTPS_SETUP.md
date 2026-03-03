# TYXT LAN HTTPS (One-Click Version)

## Goal

Make LAN UI access trusted (`https://...`) with minimum manual steps.

## Server side (double-click)

Use:

```bat
start_lan_https_easy.bat
```

What it does automatically:

1. Detects server LAN IPv4 and default gateway.
2. Tries to install `mkcert` automatically (winget/choco) if missing.
3. Generates LAN certs under `certs/lan/`:
   - `server.pem`
   - `server-key.pem`
   - `rootCA.cer`
   - `rootCA.pem`
   - `lan_bootstrap.json`
4. Adds a custom local domain on server hosts (best effort): `tyxt-<hostname>.local`
5. Starts backend with HTTPS enabled (via `start_agent.bat`).

## Client side (double-click)

Use:

```bat
client_join_lan_ui.bat
```

Optional:

```bat
client_join_lan_ui.bat 192.168.1.23
```

What it does automatically:

1. Reads local `certs/lan/lan_bootstrap.json` if available.
2. If needed, downloads root CA from server endpoint:
   - `https://<server-ip>:5000/tools/lan/rootca`
3. Imports root CA into trusted root store (`CurrentUser\Root`).
4. Tries to add hosts mapping for custom domain (admin required).
5. Opens browser to UI automatically.

## Backend bootstrap endpoints

- `GET /tools/lan/rootca`  
  Returns `certs/lan/rootCA.cer`
- `GET /tools/lan/bootstrap`  
  Returns `certs/lan/lan_bootstrap.json`

## Important

- First trust setup is still required once per client machine (browser security model).
- Do not commit private key:
  - `certs/lan/server-key.pem`
