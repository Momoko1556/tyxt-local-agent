# Repository Safety Audit (2026-03-28)

## Scope
- Checked tracked files for absolute local paths.
- Checked tracked files for personal/runtime data risk.
- Checked untracked runtime directories that could be accidentally committed.
- Updated ignore rules for Git and Docker build context.

## Findings

### 1) Tracked data status
- No runtime chat logs or ChromaDB runtime databases are tracked in Git.
- Runtime directories in Git are placeholder-only (`.gitkeep`) for:
  - `memory_db/`
  - `profiles/`
  - `memory_warehouse/`
  - `Ollama_agent_shared/`
  - `group_memory/`
  - `state/`
  - `agents/`

### 2) Untracked sensitive/local runtime data found
- `configs/theater/` (local theater configuration and cards)
- `memory_db_theater/` (theater ChromaDB files, sqlite/bin indexes)

These were not tracked yet, but needed explicit ignore protection.

### 3) Absolute path check
- Found one absolute path example in docs:
  - `docs/group_chat_v1_examples.md`
- Action: replaced with a relative path (`group_memory/1024001`).

## Remediation Applied
1. `.gitignore` updates:
   - Added ignore rules for:
     - `memory_db_theater/*`
     - `configs/theater/*`
     - `__*.log`
   - Kept optional placeholders:
     - `!memory_db_theater/.gitkeep`
     - `!configs/theater/.gitkeep`
2. `.dockerignore` updates:
   - Added runtime/privacy exclusions consistent with Git ignore, including:
     - `memory_db_theater/*`
     - `configs/theater/*`
     - `group_memory/*`
     - `state/*`
     - `agents/*`
     - `__*.log`
3. Documentation cleanup:
   - Removed absolute local path example from `docs/group_chat_v1_examples.md`.

## Recommended Pre-Push Checklist
Run before each public push:

```bat
git status --short
git ls-files | rg "memory_db|memory_db_theater|runtime_logs|user_profiles|group_chats\\.json|config\\.json|\\.env"
git grep -nE "([A-Za-z]:\\\\|/Users/|/home/)"
```

