# TYXT Skills (v0.1)

This folder contains local TYXT skills.

A **skill** is a plugin folder with:

- `skill.json` (manifest)
- `handler.py` (runtime entry)

The backend discovers skills from this directory, applies safety checks, and exposes them through `/tools/skills/*` APIs.

## Folder Layout

```text
skills/
  README.md
  local/
    local_ocr/
      skill.json
      handler.py
    local_tts_sovits/
      skill.json
      handler.py
    your_local_skill_id/
      skill.json
      handler.py
  mcp/
    mcp_web_search/
      skill.json
      handler.py
    your_mcp_skill_id/
      skill.json
      handler.py
```

## Manifest Spec (`skill.json`)

Minimum structure:

```json
{
  "id": "your_skill_id",
  "name": "Your Skill Name",
  "version": "0.1.0",
  "author": "Your Name",
  "description": "What this skill does",
  "entry": {
    "type": "python",
    "module": "handler",
    "function": "run"
  },
  "inputs": {
    "type": "object",
    "required": [],
    "properties": {}
  },
  "outputs": {
    "type": "object",
    "properties": {}
  },
  "permissions": {
    "network": false,
    "filesystem": false,
    "llm": false
  },
  "tags": [],
  "unsafe": false
}
```

Validation rules in current implementation:

- `id` is required and must match: `[a-z0-9_]+`
- `version` must be semantic version format (for example `0.1.0`)
- `entry.type` must be `"python"`
- missing `permissions` fields default to `false`

## Handler Contract (`handler.py`)

Your skill entry function:

```python
def run(params: dict, context: dict) -> dict:
    ...
```

- `params`: validated by `inputs` schema (including defaults, required, basic types, min/max for numeric fields)
- `context`: runtime context from backend (for example user/channel info)

Expected return shape:

```json
{
  "ok": true,
  "data": {},
  "error": ""
}
```

If an exception is raised, backend catches it and returns:

```json
{
  "ok": false,
  "data": null,
  "error": "ExceptionType: message"
}
```

## Safety Model

Skills are scanned before loading.

- warning-level patterns: `os.system`, `subprocess.*`, `eval`, `exec`, etc.
- high-risk patterns: obvious destructive commands (`rm -rf /`, disk format/delete patterns, etc.)

Behavior:

- **safe**: load normally
- **warning**: load but default disabled (admin must enable)
- **high risk**: auto-move to quarantine + add to blacklist
- **blacklisted**: blocked from normal loading/execution

## Runtime State Files

Configured in backend (defaults shown):

- skills directory: `./skills`
- quarantine directory: `./skills_quarantine`
- blacklist file: `./skills_blacklist.json`
- state file: `./skills_state.json`

These can be overridden with environment variables:

- `TYXT_SKILLS_DIR`
- `TYXT_SKILLS_QUARANTINE_DIR`
- `TYXT_SKILLS_BLACKLIST_PATH`
- `TYXT_SKILLS_STATE_PATH`

Runtime capability gates:

- `TYXT_SKILLS_ALLOW_NETWORK` (default: `1`)
- `TYXT_SKILLS_ALLOW_FILESYSTEM` (default: `1`)
- `TYXT_SKILLS_ALLOW_LLM` (default: `0`)

If a skill requests a permission that is globally disabled, execution is rejected.

## MCP Bridge (Phase X PoC)

TYXT can map MCP tools as runtime skills (`type: "mcp"`), without writing them to disk.

Environment flags:

- `TYXT_MCP_ENABLED=1` to enable
- `TYXT_MCP_CONFIG_PATH=...` to point to config file (json/yaml)

Example config:

```json
{
  "servers": [
    {
      "name": "claude_desktop_bridge",
      "command": "python",
      "args": ["-m", "my_mcp_bridge"],
      "cwd": "E:/your/path",
      "env": {
        "SOME_ENV": "value"
      },
      "tools_whitelist": ["weather", "code_search"]
    }
  ]
}
```

Whitelist rule in current PoC:

- `tools_whitelist` missing or empty => expose all tools from that server
- if provided with items => expose only listed tools

MCP skills are generated at runtime with IDs like:

- `mcp::claude_desktop_bridge::weather`

Useful MCP admin APIs:

- `GET /tools/mcp/status`
- `POST /tools/mcp/reload`
- `GET /tools/mcp/tools?server_name=...`
- `POST /tools/mcp/call`

## How to Add a Skill

1. Create a new folder under `skills/local/` or `skills/mcp/`, for example `skills/local/my_tool/`.
2. Add `skill.json` and `handler.py`.
3. In TYXT UI, open **Tools Settings** and click **Rescan**.
4. Enable the skill (admin only).
5. Run via API:

```http
POST /tools/skills/run
Content-Type: application/json

{
  "skill_id": "my_tool",
  "params": {}
}
```

## Skills APIs

- `GET /tools/skills/list`
- `POST /tools/skills/toggle`
- `POST /tools/skills/uninstall`
- `POST /tools/skills/run`
- `POST /tools/skills/rescan`

Notes:

- admin can manage all skills and view full safety details
- non-admin users only see enabled normal skills

## Built-in Skills

This project currently includes:

- `local_ocr`: local image OCR
- `local_tts_sovits`: local TTS via GPT-SoVITS bridge

## Uninstall Behavior

Uninstall is non-destructive in UI semantics:

- skill folder is moved to quarantine
- skill is recorded in blacklist (`manual_uninstall`)
- skill is disabled in state file
