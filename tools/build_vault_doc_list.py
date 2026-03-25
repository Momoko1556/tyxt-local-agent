import argparse
import json
import os
import time
from typing import Dict, List


PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
VAULT_ROOT = os.path.join(PROJECT_ROOT, "Ollama_agent_shared", "vault_docs")


def _normalize_agent_id(value: str) -> str:
    text = str(value or "").strip()
    return text or "moyuan"


def _normalize_user_id(value: str) -> str:
    text = str(value or "").strip()
    if not text:
        return "anonymous"
    low = text.lower()
    if low.startswith("qq_"):
        text = text[3:]
    elif low.startswith("qq:"):
        text = text.split(":", 1)[1]
    return text or "anonymous"


def _legacy_user_id_alias(user_id: str) -> str:
    uid = _normalize_user_id(user_id)
    low = uid.lower()
    if (not uid) or uid == "anonymous" or low.startswith("group_") or low.startswith("qq_"):
        return ""
    return f"qq_{uid}"


def _summary_from_markdown(content: str, max_len: int = 220) -> str:
    lines = [str(line or "").strip() for line in str(content or "").splitlines()]
    body = [line for line in lines if line and (not line.startswith("#"))]
    summary = " ".join(body[:4]).strip()
    if len(summary) > max_len:
        summary = summary[:max_len].rstrip() + "..."
    return summary


def _collect_doc_entries(agent_id: str, user_id: str) -> List[Dict[str, object]]:
    user_dir = os.path.join(VAULT_ROOT, agent_id, user_id)
    legacy_user_id = _legacy_user_id_alias(user_id)
    legacy_dir = os.path.join(VAULT_ROOT, agent_id, legacy_user_id) if legacy_user_id else ""
    if legacy_dir and os.path.isdir(legacy_dir) and not os.path.exists(user_dir):
        try:
            os.replace(legacy_dir, user_dir)
        except Exception:
            user_dir = legacy_dir
    os.makedirs(user_dir, exist_ok=True)
    entries: List[Dict[str, object]] = []
    for name in sorted(os.listdir(user_dir)):
        if name.lower() == "list.json" or (not name.lower().endswith(".md")):
            continue
        path = os.path.join(user_dir, name)
        if not os.path.isfile(path):
            continue
        try:
            with open(path, "r", encoding="utf-8", errors="ignore") as f:
                content = str(f.read() or "")
        except Exception:
            content = ""
        title = ""
        for line in content.splitlines():
            stripped = str(line or "").strip()
            if stripped.startswith("#"):
                title = stripped.lstrip("#").strip()
                break
        if not title:
            title = os.path.splitext(name)[0]
        try:
            stat = os.stat(path)
            mtime = int(stat.st_mtime)
            size = int(stat.st_size)
        except Exception:
            mtime = 0
            size = 0
        entries.append(
            {
                "agent_id": agent_id,
                "user_id": user_id,
                "file_name": name,
                "title": title,
                "summary": _summary_from_markdown(content),
                "path": os.path.abspath(path).replace("\\", "/"),
                "rel_path": os.path.relpath(path, PROJECT_ROOT).replace("\\", "/"),
                "mtime": mtime,
                "size": size,
            }
        )
    entries.sort(key=lambda row: (-int(row.get("mtime") or 0), str(row.get("file_name") or "")))
    return entries


def _write_list(agent_id: str, user_id: str) -> Dict[str, object]:
    entries = _collect_doc_entries(agent_id, user_id)
    payload: Dict[str, object] = {
        "agent_id": agent_id,
        "user_id": user_id,
        "updated_at": int(time.time()),
        "count": len(entries),
        "items": entries,
    }
    list_path = os.path.join(VAULT_ROOT, agent_id, user_id, "list.json")
    with open(list_path, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)
    return {"agent_id": agent_id, "user_id": user_id, "count": len(entries), "list_path": list_path.replace("\\", "/")}


def _iter_targets(agent_id: str, user_id: str) -> List[Dict[str, str]]:
    if agent_id and user_id:
        return [{"agent_id": _normalize_agent_id(agent_id), "user_id": _normalize_user_id(user_id)}]
    targets: List[Dict[str, str]] = []
    if not os.path.isdir(VAULT_ROOT):
        return targets
    for agent_name in sorted(os.listdir(VAULT_ROOT)):
        agent_dir = os.path.join(VAULT_ROOT, agent_name)
        if not os.path.isdir(agent_dir):
            continue
        if agent_id and agent_name != _normalize_agent_id(agent_id):
            continue
        for user_name in sorted(os.listdir(agent_dir)):
            user_dir = os.path.join(agent_dir, user_name)
            if not os.path.isdir(user_dir):
                continue
            if user_id and user_name != _normalize_user_id(user_id):
                continue
            targets.append({"agent_id": agent_name, "user_id": user_name})
    return targets


def main() -> int:
    parser = argparse.ArgumentParser(description="Build list.json for vault_docs markdown files")
    parser.add_argument("--agent-id", default="", help="Target agent id")
    parser.add_argument("--user-id", default="", help="Target user id")
    args = parser.parse_args()

    os.makedirs(VAULT_ROOT, exist_ok=True)
    results: List[Dict[str, object]] = []
    for item in _iter_targets(args.agent_id, args.user_id):
        results.append(_write_list(item["agent_id"], item["user_id"]))
    print(json.dumps({"ok": True, "results": results}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
