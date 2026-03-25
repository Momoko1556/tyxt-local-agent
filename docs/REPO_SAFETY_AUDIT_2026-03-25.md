# Repository Safety Audit (2026-03-25)

## Scope
- Checked absolute paths in source files.
- Checked potential personal information / chat database files that could be uploaded by mistake.
- Verified current git tracking and ignore rules.

## Findings

### 1) Absolute paths
- Found hard-coded local Windows paths in `frontend/TYXT_UI.html` shared-folder labels.
- Action: replaced with relative paths (`Ollama_agent_shared/...`).

### 2) Personal/runtime data risk
Runtime files containing IDs / chat metadata / vector DB were present locally, including:
- `agents/*` (agent state, relationship params)
- `group_memory/*` (group vector DB, sqlite, index files)
- `state/*` (idle session state)
- `configs/group_chats.json` (real group/member IDs and runtime path)
- `configs/agent_permissions.json` (runtime permission matrix)

### 3) Git safety status
- Sensitive runtime files above were **not guaranteed** to be ignored before this audit.
- Action: updated `.gitignore` to ignore these runtime/sensitive files.

## Remediation Applied
1. `.gitignore` updated:
   - `group_memory/*` (keep `.gitkeep`)
   - `state/*` (keep `.gitkeep`)
   - `agents/*` (keep `.gitkeep`)
   - `configs/group_chats.json`
   - `configs/agent_permissions.json`
   - `tools/cloudflared.exe`
2. Added placeholders to keep empty dirs:
   - `agents/.gitkeep`
   - `group_memory/.gitkeep`
   - `state/.gitkeep`
3. Added sanitized examples:
   - `configs/group_chats.example.json`
   - `configs/agent_permissions.example.json`
4. Removed hard-coded absolute path display values in:
   - `frontend/TYXT_UI.html`

## Recommended Ongoing Rules
- Keep real runtime data local only; commit only `*.example.json` templates.
- Before each push, run:
  - `git status --short`
  - `git ls-files`
  - `git check-ignore -v <path>` for any suspicious runtime file.
- Never commit `.env`, API keys, user profiles, or memory DB files.
