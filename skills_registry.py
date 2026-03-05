# -*- coding: utf-8 -*-
"""
TYXT Skills Registry v0.1

This module provides:
1) Local skill discovery and manifest validation
2) Persistent state management (enabled/disabled, safe status)
3) Static risk scanning, quarantine, and blacklist persistence
4) Unified skill execution entrypoint
"""

from __future__ import annotations

import datetime
import importlib.util
import json
import os
import re
import shutil
import threading
import traceback
import uuid
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Tuple


SKILL_ID_RE = re.compile(r"^[a-z0-9_]+$")
SEMVER_RE = re.compile(r"^\d+\.\d+\.\d+(?:[-+][0-9A-Za-z.\-]+)?$")

SAFE_STATUS_UNKNOWN = "unknown"
SAFE_STATUS_SAFE = "safe"
SAFE_STATUS_WARNING = "warning"
SAFE_STATUS_QUARANTINED = "quarantined"
SAFE_STATUS_BLACKLISTED = "blacklisted"

SKILL_STATUS_NORMAL = "normal"
SKILL_STATUS_QUARANTINED = "quarantined"
SKILL_STATUS_BLACKLISTED = "blacklisted"

DEFAULT_ENTRY_TYPE = "python"
DEFAULT_ENTRY_MODULE = "handler"
DEFAULT_ENTRY_FUNCTION = "run"
SKILL_TYPE_PYTHON = "python"
SKILL_TYPE_MCP = "mcp"

_SCRIPT_EXTS = {".py", ".sh", ".bat", ".cmd", ".ps1", ".psm1", ".psd1", ".js"}

# Warning-level patterns: potentially risky, require manual enable by admin.
_WARNING_PATTERNS: List[Tuple[str, re.Pattern]] = [
    ("uses os.system", re.compile(r"\bos\.system\s*\(", re.IGNORECASE)),
    ("uses subprocess.Popen", re.compile(r"\bsubprocess\.Popen\s*\(", re.IGNORECASE)),
    ("uses subprocess.run", re.compile(r"\bsubprocess\.run\s*\(", re.IGNORECASE)),
    ("uses subprocess.call", re.compile(r"\bsubprocess\.call\s*\(", re.IGNORECASE)),
    ("uses eval", re.compile(r"\beval\s*\(", re.IGNORECASE)),
    ("uses exec", re.compile(r"\bexec\s*\(", re.IGNORECASE)),
]

# High-risk patterns: auto quarantine + blacklist.
_HIGH_RISK_PATTERNS: List[Tuple[str, re.Pattern]] = [
    ("contains rm -rf /", re.compile(r"\brm\s+-rf\s+/\b", re.IGNORECASE)),
    ("contains Windows full-drive delete", re.compile(r"\bdel\s+/f\s+/s\s+/q\s+[A-Za-z]:\\", re.IGNORECASE)),
    ("contains Windows format command", re.compile(r"\bformat\s+[A-Za-z]:\b", re.IGNORECASE)),
    ("contains dangerous PowerShell remove-item", re.compile(r"Remove-Item\s+-Recurse\s+-Force\s+[A-Za-z]:\\", re.IGNORECASE)),
    ("contains shutil.rmtree('/')", re.compile(r"shutil\.rmtree\s*\(\s*[\"']/(?:[\"']|\s*\))", re.IGNORECASE)),
]


@dataclass
class SkillDescriptor:
    id: str
    name: str
    version: str
    author: str
    description: str
    tags: List[str] = field(default_factory=list)
    unsafe: bool = False
    permissions: Dict[str, bool] = field(default_factory=lambda: {"network": False, "filesystem": False, "llm": False})
    entry: Dict[str, str] = field(default_factory=dict)
    inputs: Dict[str, Any] = field(default_factory=dict)
    outputs: Dict[str, Any] = field(default_factory=dict)
    dir_path: str = ""
    source: str = "local"
    status: str = SKILL_STATUS_NORMAL
    safe_status: str = SAFE_STATUS_UNKNOWN
    enabled: bool = False
    scan_reasons: List[str] = field(default_factory=list)
    has_update: bool = False
    update_url: str = ""
    skill_type: str = SKILL_TYPE_PYTHON
    server_name: str = ""
    tool_name: str = ""

    def to_dict(self, admin_view: bool = True) -> Dict[str, Any]:
        base = {
            "id": self.id,
            "name": self.name,
            "description": self.description,
            "version": self.version,
            "enabled": bool(self.enabled),
            "tags": list(self.tags or []),
            "source": self.source,
            "status": self.status,
            "has_update": bool(self.has_update),
            "update_url": str(self.update_url or ""),
            "type": str(self.skill_type or SKILL_TYPE_PYTHON),
        }
        if self.server_name:
            base["server_name"] = str(self.server_name)
        if self.tool_name:
            base["tool_name"] = str(self.tool_name)
        if admin_view:
            base.update(
                {
                    "safe_status": self.safe_status,
                    "unsafe": bool(self.unsafe),
                    "permissions": dict(self.permissions or {}),
                    "author": self.author,
                    "scan_reasons": list(self.scan_reasons or []),
                }
            )
        return base


_LOCK = threading.RLock()
_CACHE: Dict[str, SkillDescriptor] = {}
_RUNTIME_SKILLS: Dict[str, SkillDescriptor] = {}
_SKILL_RUNNERS: Dict[str, Callable[[SkillDescriptor, Dict[str, Any], Dict[str, Any]], Dict[str, Any]]] = {}
_SUMMARY: Dict[str, Any] = {
    "loaded": 0,
    "warnings": 0,
    "quarantined": 0,
    "blacklisted": 0,
    "invalid": 0,
    "skipped": 0,
    "errors": [],
}

_CONFIG: Dict[str, str] = {}


def _clone_descriptor(d: SkillDescriptor) -> SkillDescriptor:
    return SkillDescriptor(
        id=str(d.id or ""),
        name=str(d.name or ""),
        version=str(d.version or "0.1.0"),
        author=str(d.author or ""),
        description=str(d.description or ""),
        tags=list(d.tags or []),
        unsafe=_safe_bool(getattr(d, "unsafe", False), False),
        permissions=dict(d.permissions or {}),
        entry=dict(d.entry or {}),
        inputs=dict(d.inputs or {}),
        outputs=dict(d.outputs or {}),
        dir_path=str(d.dir_path or ""),
        source=str(d.source or "local"),
        status=str(d.status or SKILL_STATUS_NORMAL),
        safe_status=str(d.safe_status or SAFE_STATUS_UNKNOWN),
        enabled=_safe_bool(getattr(d, "enabled", False), False),
        scan_reasons=list(d.scan_reasons or []),
        has_update=_safe_bool(getattr(d, "has_update", False), False),
        update_url=str(getattr(d, "update_url", "") or ""),
        skill_type=str(getattr(d, "skill_type", SKILL_TYPE_PYTHON) or SKILL_TYPE_PYTHON).strip().lower() or SKILL_TYPE_PYTHON,
        server_name=str(getattr(d, "server_name", "") or "").strip(),
        tool_name=str(getattr(d, "tool_name", "") or "").strip(),
    )


def _coerce_runtime_descriptor(obj: Any) -> Optional[SkillDescriptor]:
    if isinstance(obj, SkillDescriptor):
        out = _clone_descriptor(obj)
        out.source = str(out.source or "runtime")
        return out if out.id else None
    if not isinstance(obj, dict):
        return None
    sid = str(obj.get("id") or "").strip()
    if not sid:
        return None
    out = SkillDescriptor(
        id=sid,
        name=str(obj.get("name") or sid).strip() or sid,
        version=str(obj.get("version") or "0.1.0").strip() or "0.1.0",
        author=str(obj.get("author") or "").strip(),
        description=str(obj.get("description") or "").strip(),
        tags=[str(x).strip() for x in list(obj.get("tags") or []) if str(x).strip()],
        unsafe=_safe_bool(obj.get("unsafe"), False),
        permissions=_normalize_permissions(obj.get("permissions")),
        entry=dict(obj.get("entry") or {"type": "python", "module": "handler", "function": "run"}),
        inputs=dict(obj.get("inputs") or {"type": "object"}),
        outputs=dict(obj.get("outputs") or {"type": "object"}),
        dir_path=str(obj.get("dir_path") or "").strip(),
        source=str(obj.get("source") or "runtime").strip() or "runtime",
        status=str(obj.get("status") or SKILL_STATUS_NORMAL).strip() or SKILL_STATUS_NORMAL,
        safe_status=str(obj.get("safe_status") or SAFE_STATUS_UNKNOWN).strip() or SAFE_STATUS_UNKNOWN,
        enabled=_safe_bool(obj.get("enabled"), False),
        scan_reasons=[str(x).strip() for x in list(obj.get("scan_reasons") or []) if str(x).strip()],
        has_update=_safe_bool(obj.get("has_update"), False),
        update_url=str(obj.get("update_url") or "").strip(),
        skill_type=str(obj.get("type") or obj.get("skill_type") or SKILL_TYPE_PYTHON).strip().lower() or SKILL_TYPE_PYTHON,
        server_name=str(obj.get("mcp_server") or obj.get("server_name") or "").strip(),
        tool_name=str(obj.get("mcp_tool") or obj.get("tool_name") or "").strip(),
    )
    return out


def register_skill_runner(
    skill_type: str,
    runner: Optional[Callable[[SkillDescriptor, Dict[str, Any], Dict[str, Any]], Dict[str, Any]]],
) -> None:
    """
    Register a non-python skill runner.

    runner signature:
      runner(skill_descriptor, clean_params, context) -> {"ok": bool, "data": any, "error": str}
    """
    st = str(skill_type or "").strip().lower()
    if not st:
        return
    with _LOCK:
        if runner is None:
            _SKILL_RUNNERS.pop(st, None)
        else:
            _SKILL_RUNNERS[st] = runner


def set_runtime_skills(skills: List[Any], replace: bool = True) -> Dict[str, SkillDescriptor]:
    """
    Set runtime-only skills (for example: MCP tools mapped as skills).
    Runtime skills are merged into the same skill cache and state lifecycle.
    """
    incoming: Dict[str, SkillDescriptor] = {}
    for item in list(skills or []):
        desc = _coerce_runtime_descriptor(item)
        if desc is None:
            continue
        incoming[desc.id] = desc
    with _LOCK:
        if replace:
            _RUNTIME_SKILLS.clear()
        _RUNTIME_SKILLS.update(incoming)
    return reload_skills()


def clear_runtime_skills(source: Optional[str] = None) -> Dict[str, SkillDescriptor]:
    src = str(source or "").strip().lower()
    with _LOCK:
        if not src:
            _RUNTIME_SKILLS.clear()
        else:
            for sid in list(_RUNTIME_SKILLS.keys()):
                d = _RUNTIME_SKILLS.get(sid)
                if not isinstance(d, SkillDescriptor):
                    _RUNTIME_SKILLS.pop(sid, None)
                    continue
                if str(d.source or "").strip().lower() == src:
                    _RUNTIME_SKILLS.pop(sid, None)
    return reload_skills()


def _now_iso() -> str:
    return datetime.datetime.now(datetime.timezone.utc).replace(microsecond=0).isoformat()


def _project_root_default() -> str:
    return os.path.dirname(os.path.abspath(__file__))


def configure(
    skills_dir: Optional[str] = None,
    quarantine_dir: Optional[str] = None,
    blacklist_path: Optional[str] = None,
    state_path: Optional[str] = None,
) -> Dict[str, str]:
    root = _project_root_default()
    cfg = {
        "skills_dir": os.path.abspath(str(skills_dir or os.path.join(root, "skills"))),
        "quarantine_dir": os.path.abspath(str(quarantine_dir or os.path.join(root, "skills_quarantine"))),
        "blacklist_path": os.path.abspath(str(blacklist_path or os.path.join(root, "skills_blacklist.json"))),
        "state_path": os.path.abspath(str(state_path or os.path.join(root, "skills_state.json"))),
    }
    with _LOCK:
        _CONFIG.update(cfg)
    _ensure_dirs()
    return dict(cfg)


def get_config() -> Dict[str, str]:
    with _LOCK:
        if not _CONFIG:
            configure()
        return dict(_CONFIG)


def _ensure_dirs() -> None:
    cfg = get_config()
    os.makedirs(cfg["skills_dir"], exist_ok=True)
    os.makedirs(cfg["quarantine_dir"], exist_ok=True)
    for file_path in (cfg["blacklist_path"], cfg["state_path"]):
        parent = os.path.dirname(file_path)
        if parent:
            os.makedirs(parent, exist_ok=True)


def _read_json(path: str, default_value: Any) -> Any:
    try:
        if not os.path.exists(path):
            return default_value
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return default_value


def _write_json(path: str, data: Any) -> None:
    parent = os.path.dirname(path)
    if parent:
        os.makedirs(parent, exist_ok=True)
    tmp_path = f"{path}.tmp.{uuid.uuid4().hex}"
    with open(tmp_path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    os.replace(tmp_path, path)


def _load_blacklist_raw() -> Dict[str, Any]:
    cfg = get_config()
    raw = _read_json(cfg["blacklist_path"], {"skills": []})
    if not isinstance(raw, dict):
        return {"skills": []}
    skills = raw.get("skills")
    if not isinstance(skills, list):
        raw["skills"] = []
    return raw


def _save_blacklist_raw(raw: Dict[str, Any]) -> None:
    cfg = get_config()
    if not isinstance(raw, dict):
        raw = {"skills": []}
    if not isinstance(raw.get("skills"), list):
        raw["skills"] = []
    _write_json(cfg["blacklist_path"], raw)


def _blacklist_map() -> Dict[str, Dict[str, Any]]:
    raw = _load_blacklist_raw()
    out: Dict[str, Dict[str, Any]] = {}
    for item in list(raw.get("skills") or []):
        if not isinstance(item, dict):
            continue
        sid = str(item.get("id") or "").strip()
        if not sid:
            continue
        out[sid] = item
    return out


def _append_blacklist(
    skill_id: str,
    reason: str,
    quarantined_path: str = "",
    status: str = SKILL_STATUS_BLACKLISTED,
    details: Optional[List[str]] = None,
) -> None:
    sid = str(skill_id or "").strip()
    if not sid:
        return
    raw = _load_blacklist_raw()
    items = [x for x in list(raw.get("skills") or []) if isinstance(x, dict)]
    next_items: List[Dict[str, Any]] = []
    for item in items:
        if str(item.get("id") or "").strip() != sid:
            next_items.append(item)
    next_items.append(
        {
            "id": sid,
            "reason": str(reason or "blacklisted"),
            "detected_at": _now_iso(),
            "quarantined_path": str(quarantined_path or ""),
            "status": str(status or SKILL_STATUS_BLACKLISTED),
            "details": list(details or []),
        }
    )
    raw["skills"] = next_items
    _save_blacklist_raw(raw)


def _load_state_raw() -> Dict[str, Any]:
    cfg = get_config()
    raw = _read_json(cfg["state_path"], {})
    if not isinstance(raw, dict):
        return {}
    return raw


def _save_state_raw(raw: Dict[str, Any]) -> None:
    cfg = get_config()
    if not isinstance(raw, dict):
        raw = {}
    _write_json(cfg["state_path"], raw)


def _safe_bool(v: Any, default: bool = False) -> bool:
    if isinstance(v, bool):
        return v
    if v is None:
        return bool(default)
    s = str(v).strip().lower()
    if s in {"1", "true", "yes", "y", "on"}:
        return True
    if s in {"0", "false", "no", "n", "off"}:
        return False
    return bool(default)


def _normalize_permissions(v: Any) -> Dict[str, bool]:
    src = v if isinstance(v, dict) else {}
    return {
        "network": _safe_bool(src.get("network"), False),
        "filesystem": _safe_bool(src.get("filesystem"), False),
        "llm": _safe_bool(src.get("llm"), False),
    }


def _validate_manifest(raw: Any) -> Tuple[bool, Optional[Dict[str, Any]], str]:
    if not isinstance(raw, dict):
        return False, None, "manifest is not a JSON object"

    sid = str(raw.get("id") or "").strip()
    if not sid:
        return False, None, "id is required"
    if not SKILL_ID_RE.match(sid):
        return False, None, "id must match [a-z0-9_]+"

    name = str(raw.get("name") or sid).strip() or sid
    version = str(raw.get("version") or "0.1.0").strip() or "0.1.0"
    if not SEMVER_RE.match(version):
        return False, None, "version must be semantic (e.g. 0.1.0)"

    entry_raw = raw.get("entry") if isinstance(raw.get("entry"), dict) else {}
    skill_type = str(raw.get("type") or raw.get("skill_type") or entry_raw.get("type") or SKILL_TYPE_PYTHON).strip().lower()
    if skill_type not in {SKILL_TYPE_PYTHON, SKILL_TYPE_MCP}:
        return False, None, "unsupported skill type (allowed: python/mcp)"

    if skill_type == SKILL_TYPE_MCP:
        # MCP skill: config-driven. Keep invocation target in manifest.
        mcp_server = str(raw.get("mcp_server") or raw.get("server_name") or "").strip()
        mcp_tool = str(raw.get("mcp_tool") or raw.get("tool_name") or "").strip()
        if (not mcp_server) or (not mcp_tool):
            # Compatibility fallback for runtime-like ids: mcp::<server>::<tool>
            sid_server = ""
            sid_tool = ""
            if sid.startswith("mcp::"):
                parts = sid.split("::", 2)
                if len(parts) == 3:
                    sid_server = str(parts[1] or "").strip()
                    sid_tool = str(parts[2] or "").strip()
            mcp_server = mcp_server or sid_server
            mcp_tool = mcp_tool or sid_tool
        if not mcp_server:
            return False, None, "mcp_server is required for mcp skill"
        if not mcp_tool:
            return False, None, "mcp_tool is required for mcp skill"

        input_schema = raw.get("input_schema") if isinstance(raw.get("input_schema"), dict) else None
        if not isinstance(input_schema, dict):
            input_schema = raw.get("inputs") if isinstance(raw.get("inputs"), dict) else {"type": "object"}

        out = {
            "id": sid,
            "name": name,
            "version": version,
            "author": str(raw.get("author") or "").strip(),
            "description": str(raw.get("description") or "").strip(),
            "type": SKILL_TYPE_MCP,
            "skill_type": SKILL_TYPE_MCP,
            "entry": {"type": SKILL_TYPE_MCP, "module": "", "function": "run"},
            "inputs": input_schema,
            "input_schema": input_schema,
            "outputs": raw.get("outputs") if isinstance(raw.get("outputs"), dict) else {"type": "object"},
            "permissions": _normalize_permissions(raw.get("permissions")),
            "tags": [str(x).strip() for x in list(raw.get("tags") or []) if str(x).strip()],
            "unsafe": _safe_bool(raw.get("unsafe"), False),
            "mcp_server": mcp_server,
            "mcp_tool": mcp_tool,
            "server_name": mcp_server,
            "tool_name": mcp_tool,
        }
        return True, out, ""

    entry_type = str(entry_raw.get("type") or DEFAULT_ENTRY_TYPE).strip().lower()
    entry_module = str(entry_raw.get("module") or DEFAULT_ENTRY_MODULE).strip() or DEFAULT_ENTRY_MODULE
    entry_func = str(entry_raw.get("function") or DEFAULT_ENTRY_FUNCTION).strip() or DEFAULT_ENTRY_FUNCTION
    if entry_type != "python":
        return False, None, "unsupported entry.type (only python is supported for local skills)"

    out = {
        "id": sid,
        "name": name,
        "version": version,
        "author": str(raw.get("author") or "").strip(),
        "description": str(raw.get("description") or "").strip(),
        "type": SKILL_TYPE_PYTHON,
        "skill_type": SKILL_TYPE_PYTHON,
        "entry": {
            "type": entry_type,
            "module": entry_module,
            "function": entry_func,
        },
        "inputs": raw.get("inputs") if isinstance(raw.get("inputs"), dict) else {"type": "object"},
        "outputs": raw.get("outputs") if isinstance(raw.get("outputs"), dict) else {"type": "object"},
        "permissions": _normalize_permissions(raw.get("permissions")),
        "tags": [str(x).strip() for x in list(raw.get("tags") or []) if str(x).strip()],
        "unsafe": _safe_bool(raw.get("unsafe"), False),
        "mcp_server": "",
        "mcp_tool": "",
        "server_name": "",
        "tool_name": "",
    }
    return True, out, ""


def _read_file_text(path: str, max_bytes: int = 512 * 1024) -> str:
    try:
        with open(path, "rb") as f:
            raw = f.read(max_bytes)
        return raw.decode("utf-8", errors="ignore")
    except Exception:
        return ""


def _scan_skill_dir(skill_dir: str) -> Tuple[str, List[str]]:
    reasons: List[str] = []
    warning_reasons: List[str] = []
    high_reasons: List[str] = []
    for base, _dirs, files in os.walk(skill_dir):
        for fn in files:
            ext = os.path.splitext(fn)[1].lower()
            if ext not in _SCRIPT_EXTS:
                continue
            path = os.path.join(base, fn)
            text = _read_file_text(path)
            if not text:
                continue
            for name, pat in _HIGH_RISK_PATTERNS:
                if pat.search(text):
                    high_reasons.append(f"{name} ({fn})")
            for name, pat in _WARNING_PATTERNS:
                if pat.search(text):
                    warning_reasons.append(f"{name} ({fn})")
    if high_reasons:
        reasons.extend(sorted(set(high_reasons)))
        return "high_risk", reasons
    if warning_reasons:
        reasons.extend(sorted(set(warning_reasons)))
        return SAFE_STATUS_WARNING, reasons
    return SAFE_STATUS_SAFE, []


def _move_to_quarantine(skill_dir: str, skill_id: str) -> str:
    cfg = get_config()
    quarantine_root = cfg["quarantine_dir"]
    os.makedirs(quarantine_root, exist_ok=True)
    base_name = str(skill_id or "unknown_skill").strip() or "unknown_skill"
    target = os.path.join(quarantine_root, base_name)
    if os.path.exists(target):
        target = os.path.join(quarantine_root, f"{base_name}_{datetime.datetime.now().strftime('%Y%m%d_%H%M%S')}")
    shutil.move(skill_dir, target)
    return os.path.abspath(target)


def _manifest_path(skill_dir: str) -> str:
    return os.path.join(skill_dir, "skill.json")


def _load_manifest(skill_dir: str) -> Tuple[bool, Optional[Dict[str, Any]], str]:
    mp = _manifest_path(skill_dir)
    if not os.path.exists(mp):
        return False, None, "missing skill.json"
    raw = _read_json(mp, None)
    ok, normalized, err = _validate_manifest(raw)
    return ok, normalized, err


def _touch_state_record(state: Dict[str, Any], skill_id: str, safe_status: str, enabled_default: bool = False) -> Dict[str, Any]:
    now = _now_iso()
    row = state.get(skill_id)
    if not isinstance(row, dict):
        row = {
            "enabled": bool(enabled_default),
            "installed_at": now,
            "last_checked_at": now,
            "safe_status": safe_status,
        }
    else:
        row["enabled"] = _safe_bool(row.get("enabled"), enabled_default)
        row["installed_at"] = str(row.get("installed_at") or now)
        row["last_checked_at"] = now
        row["safe_status"] = safe_status
    state[skill_id] = row
    return row


def _discover_skill_dirs(skills_root: str) -> Tuple[List[Tuple[str, str]], List[str]]:
    """
    Discover skill directories under `skills_root`.

    Supported layouts:
    1) skills/<skill_id>/skill.json
    2) skills/<category>/<skill_id>/skill.json  (for example: local/ or mcp/)
    """
    rows: List[Tuple[str, str]] = []
    errors: List[str] = []
    try:
        entries = sorted(os.listdir(skills_root))
    except Exception as e:
        return [], [f"cannot list skills dir: {e}"]

    for name in entries:
        path = os.path.join(skills_root, name)
        if not os.path.isdir(path):
            continue

        # Direct skill folder.
        if os.path.isfile(_manifest_path(path)):
            rows.append((str(name), path))
            continue

        # Category folder: one more level deep.
        try:
            children = sorted(os.listdir(path))
        except Exception as e:
            errors.append(f"cannot list category dir {name}: {e}")
            continue
        for child in children:
            cpath = os.path.join(path, child)
            if not os.path.isdir(cpath):
                continue
            if os.path.isfile(_manifest_path(cpath)):
                rows.append((f"{name}/{child}", cpath))
    return rows, errors


def reload_skills() -> Dict[str, SkillDescriptor]:
    _ensure_dirs()
    cfg = get_config()
    skills_dir = cfg["skills_dir"]
    blacklist = _blacklist_map()
    state = _load_state_raw()
    descriptors: Dict[str, SkillDescriptor] = {}

    summary = {
        "loaded": 0,
        "runtime_loaded": 0,
        "warnings": 0,
        "quarantined": 0,
        "blacklisted": 0,
        "invalid": 0,
        "skipped": 0,
        "errors": [],
    }

    skill_dirs, discovery_errors = _discover_skill_dirs(skills_dir)
    if discovery_errors:
        summary["errors"].extend(discovery_errors)

    for name, path in skill_dirs:
        ok, manifest, err = _load_manifest(path)
        if not ok or not manifest:
            summary["invalid"] += 1
            summary["errors"].append(f"{name}: {err}")
            continue

        skill_id = str(manifest.get("id") or "").strip()
        if not skill_id:
            summary["invalid"] += 1
            summary["errors"].append(f"{name}: empty skill id")
            continue

        # Already blacklisted: quarantine immediately if it still appears in skills dir.
        if skill_id in blacklist:
            try:
                qpath = _move_to_quarantine(path, skill_id)
                old = blacklist.get(skill_id) or {}
                _append_blacklist(
                    skill_id=skill_id,
                    reason=str(old.get("reason") or "blacklisted"),
                    quarantined_path=qpath,
                    status=str(old.get("status") or SKILL_STATUS_BLACKLISTED),
                    details=list(old.get("details") or []),
                )
            except Exception as e:
                summary["errors"].append(f"{skill_id}: failed to move blacklisted skill to quarantine: {e}")
            summary["blacklisted"] += 1
            _touch_state_record(state, skill_id, SAFE_STATUS_BLACKLISTED, enabled_default=False)["enabled"] = False
            continue

        scan_level, reasons = _scan_skill_dir(path)
        if scan_level == "high_risk":
            qpath = ""
            try:
                qpath = _move_to_quarantine(path, skill_id)
            except Exception as e:
                summary["errors"].append(f"{skill_id}: quarantine failed: {e}")
            _append_blacklist(
                skill_id=skill_id,
                reason="high_risk static scan",
                quarantined_path=qpath,
                status=SKILL_STATUS_QUARANTINED,
                details=reasons,
            )
            row = _touch_state_record(state, skill_id, SAFE_STATUS_QUARANTINED, enabled_default=False)
            row["enabled"] = False
            summary["quarantined"] += 1
            continue

        safe_status = SAFE_STATUS_WARNING if scan_level == SAFE_STATUS_WARNING else SAFE_STATUS_SAFE
        row = _touch_state_record(state, skill_id, safe_status, enabled_default=False)
        enabled = bool(row.get("enabled", False))

        if safe_status == SAFE_STATUS_WARNING:
            summary["warnings"] += 1
            # New warning skills stay disabled by default.
            if "enabled" not in row:
                enabled = False

        desc = SkillDescriptor(
            id=skill_id,
            name=str(manifest.get("name") or skill_id),
            version=str(manifest.get("version") or "0.1.0"),
            author=str(manifest.get("author") or ""),
            description=str(manifest.get("description") or ""),
            tags=list(manifest.get("tags") or []),
            unsafe=_safe_bool(manifest.get("unsafe"), False),
            permissions=_normalize_permissions(manifest.get("permissions")),
            entry=dict(manifest.get("entry") or {}),
            inputs=dict(manifest.get("inputs") or {"type": "object"}),
            outputs=dict(manifest.get("outputs") or {"type": "object"}),
            dir_path=path,
            status=SKILL_STATUS_NORMAL,
            safe_status=safe_status,
            enabled=enabled,
            scan_reasons=list(reasons or []),
            source="local",
            skill_type=str(manifest.get("type") or manifest.get("skill_type") or SKILL_TYPE_PYTHON).strip().lower() or SKILL_TYPE_PYTHON,
            server_name=str(manifest.get("mcp_server") or manifest.get("server_name") or "").strip(),
            tool_name=str(manifest.get("mcp_tool") or manifest.get("tool_name") or "").strip(),
        )
        descriptors[skill_id] = desc
        summary["loaded"] += 1

    # Merge runtime skills (for example MCP tools bridged as skills).
    with _LOCK:
        runtime_skills = {sid: _clone_descriptor(d) for sid, d in _RUNTIME_SKILLS.items() if isinstance(d, SkillDescriptor)}

    for sid in sorted(runtime_skills.keys()):
        rd = runtime_skills[sid]
        if sid in blacklist:
            item = blacklist.get(sid) or {}
            status = str(item.get("status") or SKILL_STATUS_BLACKLISTED).strip() or SKILL_STATUS_BLACKLISTED
            rd.status = status
            rd.safe_status = SAFE_STATUS_QUARANTINED if status == SKILL_STATUS_QUARANTINED else SAFE_STATUS_BLACKLISTED
            rd.enabled = False
            rd.unsafe = True
            rd.scan_reasons = list(item.get("details") or [])
            descriptors[sid] = rd
            if status == SKILL_STATUS_QUARANTINED:
                summary["quarantined"] += 1
            else:
                summary["blacklisted"] += 1
            continue

        row = _touch_state_record(state, sid, rd.safe_status or SAFE_STATUS_UNKNOWN, enabled_default=False)
        rd.enabled = bool(row.get("enabled", False))
        rd.status = str(rd.status or SKILL_STATUS_NORMAL).strip() or SKILL_STATUS_NORMAL
        rd.safe_status = str(rd.safe_status or SAFE_STATUS_UNKNOWN).strip() or SAFE_STATUS_UNKNOWN
        descriptors[sid] = rd
        summary["runtime_loaded"] += 1

    # Build stubs from blacklist so admin can still see blocked skills.
    latest_blacklist = _blacklist_map()
    for sid, item in latest_blacklist.items():
        if sid in descriptors:
            continue
        status = str(item.get("status") or SKILL_STATUS_BLACKLISTED).strip() or SKILL_STATUS_BLACKLISTED
        safe_status = SAFE_STATUS_QUARANTINED if status == SKILL_STATUS_QUARANTINED else SAFE_STATUS_BLACKLISTED
        desc = SkillDescriptor(
            id=sid,
            name=sid,
            version="0.0.0",
            author="",
            description=str(item.get("reason") or "blacklisted"),
            tags=[],
            unsafe=True,
            permissions={"network": False, "filesystem": False, "llm": False},
            entry={"type": "python", "module": "handler", "function": "run"},
            inputs={"type": "object"},
            outputs={"type": "object"},
            dir_path="",
            status=status,
            safe_status=safe_status,
            enabled=False,
            scan_reasons=list(item.get("details") or []),
            source="local",
        )
        descriptors[sid] = desc
        if status == SKILL_STATUS_QUARANTINED:
            summary["quarantined"] += 1
        else:
            summary["blacklisted"] += 1

    _save_state_raw(state)
    with _LOCK:
        _CACHE.clear()
        _CACHE.update(descriptors)
        _SUMMARY.clear()
        _SUMMARY.update(summary)
    return dict(descriptors)


def load_all_skills(force: bool = False) -> Dict[str, SkillDescriptor]:
    with _LOCK:
        need_reload = force or not bool(_CACHE)
    if need_reload:
        return reload_skills()
    with _LOCK:
        return dict(_CACHE)


def get_scan_summary() -> Dict[str, Any]:
    load_all_skills(force=False)
    with _LOCK:
        return dict(_SUMMARY)


def list_skills(admin_view: bool = True) -> List[Dict[str, Any]]:
    skills = load_all_skills(force=False)
    rows: List[Dict[str, Any]] = []
    for sid in sorted(skills.keys()):
        d = skills[sid]
        if not admin_view:
            if not d.enabled or d.status != SKILL_STATUS_NORMAL:
                continue
        rows.append(d.to_dict(admin_view=admin_view))
    return rows


def get_skill_state(skill_id: str) -> Dict[str, Any]:
    sid = str(skill_id or "").strip()
    state = _load_state_raw()
    row = state.get(sid)
    if not isinstance(row, dict):
        return {}
    return dict(row)


def set_skill_enabled(skill_id: str, enabled: bool) -> Tuple[bool, str, Optional[Dict[str, Any]]]:
    sid = str(skill_id or "").strip()
    if not sid:
        return False, "missing skill_id", None
    skills = load_all_skills(force=False)
    d = skills.get(sid)
    if d is None:
        return False, "skill_not_found", None
    if d.status != SKILL_STATUS_NORMAL:
        return False, f"skill_status_{d.status}", d.to_dict(admin_view=True)

    state = _load_state_raw()
    row = _touch_state_record(state, sid, d.safe_status, enabled_default=False)
    row["enabled"] = bool(enabled)
    _save_state_raw(state)

    # Update cache
    with _LOCK:
        if sid in _CACHE:
            _CACHE[sid].enabled = bool(enabled)
    return True, "", load_all_skills(force=False).get(sid).to_dict(admin_view=True) if sid in load_all_skills(force=False) else None


def update_skill_safe_status(skill_id: str, safe_status: str) -> None:
    sid = str(skill_id or "").strip()
    if not sid:
        return
    next_safe = str(safe_status or SAFE_STATUS_UNKNOWN).strip() or SAFE_STATUS_UNKNOWN
    state = _load_state_raw()
    row = _touch_state_record(state, sid, next_safe, enabled_default=False)
    row["safe_status"] = next_safe
    _save_state_raw(state)
    with _LOCK:
        if sid in _CACHE:
            _CACHE[sid].safe_status = next_safe


def uninstall_skill(skill_id: str) -> Tuple[bool, str]:
    sid = str(skill_id or "").strip()
    if not sid:
        return False, "missing_skill_id"
    skills = load_all_skills(force=False)
    d = skills.get(sid)
    if d is None:
        return False, "skill_not_found"
    if d.status != SKILL_STATUS_NORMAL:
        return False, f"skill_status_{d.status}"
    is_runtime_only = (str(d.skill_type or SKILL_TYPE_PYTHON) != SKILL_TYPE_PYTHON) or (not d.dir_path)

    try:
        qpath = ""
        if not is_runtime_only:
            if not os.path.isdir(d.dir_path):
                return False, "skill_dir_not_found"
            qpath = _move_to_quarantine(d.dir_path, sid)
        _append_blacklist(
            skill_id=sid,
            reason="manual_uninstall",
            quarantined_path=qpath,
            status=SKILL_STATUS_BLACKLISTED,
            details=[],
        )
        st = _load_state_raw()
        row = _touch_state_record(st, sid, SAFE_STATUS_BLACKLISTED, enabled_default=False)
        row["enabled"] = False
        _save_state_raw(st)
        reload_skills()
        return True, ""
    except Exception as e:
        return False, f"uninstall_failed: {e}"


def _validate_input_type(value: Any, expected_type: str) -> bool:
    t = str(expected_type or "").strip().lower()
    if t == "string":
        return isinstance(value, str)
    if t == "integer":
        return isinstance(value, int) and not isinstance(value, bool)
    if t == "number":
        return isinstance(value, (int, float)) and not isinstance(value, bool)
    if t == "boolean":
        return isinstance(value, bool)
    if t == "object":
        return isinstance(value, dict)
    if t == "array":
        return isinstance(value, list)
    return True


def _validate_inputs(schema: Dict[str, Any], params: Dict[str, Any]) -> Tuple[bool, Dict[str, Any], str]:
    if not isinstance(schema, dict):
        return True, dict(params or {}), ""
    if str(schema.get("type") or "object") != "object":
        return True, dict(params or {}), ""

    payload = dict(params or {}) if isinstance(params, dict) else {}
    required = list(schema.get("required") or [])
    props = schema.get("properties") if isinstance(schema.get("properties"), dict) else {}

    # Defaults
    for k, spec in props.items():
        if k not in payload and isinstance(spec, dict) and "default" in spec:
            payload[k] = spec.get("default")

    for key in required:
        if key not in payload:
            return False, {}, f"missing required param: {key}"

    for k, spec in props.items():
        if k not in payload:
            continue
        if not isinstance(spec, dict):
            continue
        expected = str(spec.get("type") or "").strip().lower()
        if expected and not _validate_input_type(payload.get(k), expected):
            return False, {}, f"invalid type for {k}: expected {expected}"
        if expected in {"integer", "number"}:
            v = payload.get(k)
            if "minimum" in spec:
                try:
                    if float(v) < float(spec.get("minimum")):
                        return False, {}, f"{k} is below minimum"
                except Exception:
                    return False, {}, f"invalid numeric value for {k}"
            if "maximum" in spec:
                try:
                    if float(v) > float(spec.get("maximum")):
                        return False, {}, f"{k} is above maximum"
                except Exception:
                    return False, {}, f"invalid numeric value for {k}"
    return True, payload, ""


def _build_context_for_skill(context: Dict[str, Any], permissions: Dict[str, bool]) -> Dict[str, Any]:
    src = context if isinstance(context, dict) else {}
    out = {
        "user_id": str(src.get("user_id") or "").strip(),
        "channel_type": str(src.get("channel_type") or src.get("scene") or "").strip(),
        "owner_id": str(src.get("owner_id") or "").strip(),
        "role": str(src.get("role") or "").strip(),
        "meta": dict(src.get("meta") or {}) if isinstance(src.get("meta"), dict) else {},
        "time_iso": _now_iso(),
    }
    # Only expose shared paths when filesystem permission is granted.
    if _safe_bool(permissions.get("filesystem"), False):
        out["shared_root"] = str(src.get("shared_root") or "")
        out["import_dir"] = str(src.get("import_dir") or "")
    return out


def run_skill(skill_id: str, params: Dict[str, Any], context: Dict[str, Any]) -> Dict[str, Any]:
    sid = str(skill_id or "").strip()
    if not sid:
        return {"ok": False, "data": None, "error": "missing_skill_id"}

    skills = load_all_skills(force=False)
    d = skills.get(sid)
    if d is None:
        return {"ok": False, "data": None, "error": "skill_not_found"}
    if d.status != SKILL_STATUS_NORMAL:
        return {"ok": False, "data": None, "error": f"skill_status_{d.status}"}
    if not d.enabled:
        return {"ok": False, "data": None, "error": "skill_disabled"}

    # Permission gates against runtime capability flags.
    caps = {}
    if isinstance(context, dict) and isinstance(context.get("__caps"), dict):
        caps = dict(context.get("__caps") or {})
    allow_network = _safe_bool(caps.get("network"), True)
    allow_filesystem = _safe_bool(caps.get("filesystem"), False)
    allow_llm = _safe_bool(caps.get("llm"), False)

    perms = _normalize_permissions(d.permissions)
    if perms.get("network") and not allow_network:
        return {"ok": False, "data": None, "error": "network_permission_denied"}
    if perms.get("filesystem") and not allow_filesystem:
        return {"ok": False, "data": None, "error": "filesystem_permission_denied"}
    if perms.get("llm") and not allow_llm:
        return {"ok": False, "data": None, "error": "llm_permission_denied"}

    ok, clean_params, err = _validate_inputs(d.inputs, params if isinstance(params, dict) else {})
    if not ok:
        return {"ok": False, "data": None, "error": err or "invalid_params"}

    skill_context = _build_context_for_skill(context if isinstance(context, dict) else {}, perms)
    skill_type = str(d.skill_type or SKILL_TYPE_PYTHON).strip().lower() or SKILL_TYPE_PYTHON
    if skill_type != SKILL_TYPE_PYTHON:
        runner = None
        with _LOCK:
            runner = _SKILL_RUNNERS.get(skill_type)
        if not callable(runner):
            return {"ok": False, "data": None, "error": f"unsupported_skill_type: {skill_type}"}
        try:
            result = runner(d, clean_params, skill_context)
            if not isinstance(result, dict):
                return {"ok": True, "data": {"result": result}, "error": ""}
            return {
                "ok": _safe_bool(result.get("ok"), False if result.get("error") else True),
                "data": result.get("data"),
                "error": str(result.get("error") or ""),
            }
        except Exception as e:
            traceback.print_exc()
            return {"ok": False, "data": None, "error": f"{type(e).__name__}: {e}"}

    entry = d.entry or {}
    module_name = str(entry.get("module") or DEFAULT_ENTRY_MODULE).strip() or DEFAULT_ENTRY_MODULE
    func_name = str(entry.get("function") or DEFAULT_ENTRY_FUNCTION).strip() or DEFAULT_ENTRY_FUNCTION
    module_rel = module_name.replace(".", os.sep) + ".py"
    module_path = os.path.join(d.dir_path, module_rel)
    if not os.path.isfile(module_path):
        return {"ok": False, "data": None, "error": f"entry_module_not_found: {module_rel}"}

    try:
        unique_name = f"tyxt_skill_{sid}_{uuid.uuid4().hex}"
        spec = importlib.util.spec_from_file_location(unique_name, module_path)
        if spec is None or spec.loader is None:
            return {"ok": False, "data": None, "error": "import_spec_failed"}
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)  # type: ignore[attr-defined]
        fn = getattr(mod, func_name, None)
        if not callable(fn):
            return {"ok": False, "data": None, "error": f"entry_function_not_callable: {func_name}"}
        result = fn(clean_params, skill_context)
        if not isinstance(result, dict):
            return {"ok": True, "data": {"result": result}, "error": ""}
        return {
            "ok": _safe_bool(result.get("ok"), False if result.get("error") else True),
            "data": result.get("data"),
            "error": str(result.get("error") or ""),
        }
    except Exception as e:
        traceback.print_exc()
        return {"ok": False, "data": None, "error": f"{type(e).__name__}: {e}"}


# Initialize default config on module import.
configure()
