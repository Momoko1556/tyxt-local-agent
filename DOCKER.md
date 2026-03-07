# TYXT Docker Guide

This project provides a publish-ready Docker packaging setup:

- `Dockerfile`
- `docker-compose.yml`
- `.dockerignore`

## 1. Prerequisites

- Docker Desktop / Docker Engine
- Ollama running on host machine (default: `http://127.0.0.1:11434`)

## 2. Configure Env

Copy `.env.example` to `.env` and adjust values as needed.

Important for Docker:

- `OLLAMA_BASE_URL=http://host.docker.internal:11434/v1`

## 3. Build and Run

```bash
docker compose up -d --build --pull never
```

This Docker setup defaults to China mirrors for build speed:

- APT mirror: `mirrors.tuna.tsinghua.edu.cn`
- pip mirror: `https://pypi.tuna.tsinghua.edu.cn/simple`

You can override via environment variables before build:

```bash
set APT_MIRROR=mirrors.aliyun.com
set PIP_INDEX_URL=https://mirrors.aliyun.com/pypi/simple
set PIP_TRUSTED_HOST=mirrors.aliyun.com
docker compose up -d --build --pull never
```

Open:

- `http://127.0.0.1:5000/`

## 3.1 If build still tries docker.io (China network timeout)

If you see errors like `auth.docker.io` / `registry-1.docker.io` timeout, force a China base image explicitly:

```bat
cd /d "E:\Ollama memory_project"
set BASE_IMAGE=swr.cn-north-4.myhuaweicloud.com/ddn-k8s/docker.io/library/python:3.10-slim-bookworm
set APT_MIRROR=mirrors.tuna.tsinghua.edu.cn
set PIP_INDEX_URL=https://pypi.tuna.tsinghua.edu.cn/simple
set PIP_TRUSTED_HOST=pypi.tuna.tsinghua.edu.cn
"%ProgramFiles%\Docker\Docker\resources\bin\docker.exe" compose build --no-cache
"%ProgramFiles%\Docker\Docker\resources\bin\docker.exe" compose up -d --pull never
"%ProgramFiles%\Docker\Docker\resources\bin\docker.exe" compose ps
```

If `--progress=plain` is needed, use:

```bat
"%ProgramFiles%\Docker\Docker\resources\bin\docker.exe" compose --progress plain build --no-cache
```

If this mirror is slow/unavailable, try:

```bat
set BASE_IMAGE=docker.m.daocloud.io/library/python:3.10-slim-bookworm
```

Quick connectivity test before build:

```bat
"%ProgramFiles%\Docker\Docker\resources\bin\docker.exe" pull %BASE_IMAGE%
```

## 4. Stop

```bash
docker compose down
```

## 5. Privacy / Publish Safety

Sensitive/local runtime files are excluded from build context by `.dockerignore`, including:

- `.env`
- `config.json`
- `tools/api_config.json`
- `configs/user_profiles.json`
- `configs/persona_config.json`
- `configs/mcp_servers.json`
- `memory_db/*`
- `memory_warehouse/*`
- `profiles/*`
- `Ollama_agent_shared/*`

This means personal data and local secrets are not baked into the image during build.
