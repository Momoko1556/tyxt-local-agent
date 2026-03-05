#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
TYXT MCP manager.

This module handles:
- loading/saving MCP config JSON
- validating `mcpServers` config blocks
- converting config into MCP bridge server map
"""

from __future__ import annotations

import json
import os
from typing import Any, Dict, List, Optional

import mcp_bridge


def _default_config() -> Dict[str, Any]:
    return {"mcpServers": {}}


def _log(logger: Any, level: str, msg: str, *args: Any) -> None:
    try:
        if logger is None:
            return
        fn = getattr(logger, str(level or "info").lower(), None)
        if callable(fn):
            fn("[MCP] " + str(msg), *args)
    except Exception:
        pass


def ensure_mcp_config_file(config_path: str, logger: Any = None) -> str:
    path = os.path.abspath(str(config_path or "").strip())
    if not path:
        raise ValueError("config_path is empty")
    parent = os.path.dirname(path)
    if parent:
        os.makedirs(parent, exist_ok=True)
    if not os.path.exists(path):
        with open(path, "w", encoding="utf-8") as f:
            json.dump(_default_config(), f, ensure_ascii=False, indent=2)
            f.write("\n")
        _log(logger, "info", "created default config file: %s", path)
    return path


def _normalize_env_dict(raw: Any) -> Dict[str, str]:
    out: Dict[str, str] = {}
    if not isinstance(raw, dict):
        return out
    for k, v in raw.items():
        kk = str(k or "").strip()
        if not kk:
            continue
        out[kk] = str(v if v is not None else "")
    return out


def _normalize_whitelist(raw: Any) -> Optional[List[str]]:
    if raw is None:
        return None
    if isinstance(raw, list):
        out = [str(x).strip() for x in raw if str(x).strip()]
        return out
    s = str(raw).strip()
    if not s:
        return []
    return [s]


def _normalize_one_server(name: str, row: Any) -> Dict[str, Any]:
    srv_name = str(name or "").strip()
    if not srv_name:
        raise ValueError("server name is empty")
    if not isinstance(row, dict):
        raise ValueError(f"server '{srv_name}' must be an object")

    command = str(row.get("command") or "").strip()
    if not command:
        raise ValueError(f"server '{srv_name}' missing command")

    raw_args = row.get("args")
    if raw_args is None:
        args: List[str] = []
    elif isinstance(raw_args, list):
        args = [str(x) for x in raw_args]
    else:
        raise ValueError(f"server '{srv_name}' args must be an array of strings")

    cwd = row.get("cwd")
    cwd_s = str(cwd).strip() if cwd is not None else ""
    env = _normalize_env_dict(row.get("env"))
    whitelist = _normalize_whitelist(row.get("tools_whitelist", row.get("toolsWhitelist")))

    out: Dict[str, Any] = {
        "command": command,
        "args": args,
    }
    if cwd_s:
        out["cwd"] = cwd_s
    if env:
        out["env"] = env
    if whitelist is not None:
        out["tools_whitelist"] = whitelist
    return out


def normalize_mcp_config_obj(raw_obj: Any) -> Dict[str, Any]:
    """
    Normalize supported MCP config shapes into:
    { "mcpServers": { "<name>": {command,args,cwd?,env?,tools_whitelist?}, ... } }
    """
    rows_by_name: Dict[str, Dict[str, Any]] = {}

    if isinstance(raw_obj, dict) and isinstance(raw_obj.get("mcpServers"), dict):
        m = raw_obj.get("mcpServers") or {}
        for name, row in m.items():
            norm = _normalize_one_server(str(name), row)
            rows_by_name[str(name).strip()] = norm
    elif isinstance(raw_obj, dict) and isinstance(raw_obj.get("servers"), list):
        for idx, row in enumerate(raw_obj.get("servers") or []):
            if not isinstance(row, dict):
                raise ValueError(f"servers[{idx}] must be an object")
            name = str(row.get("name") or "").strip()
            if not name:
                raise ValueError(f"servers[{idx}] missing name")
            norm = _normalize_one_server(name, row)
            rows_by_name[name] = norm
    elif isinstance(raw_obj, dict) and isinstance(raw_obj.get("mcp_servers"), list):
        for idx, row in enumerate(raw_obj.get("mcp_servers") or []):
            if not isinstance(row, dict):
                raise ValueError(f"mcp_servers[{idx}] must be an object")
            name = str(row.get("name") or "").strip()
            if not name:
                raise ValueError(f"mcp_servers[{idx}] missing name")
            norm = _normalize_one_server(name, row)
            rows_by_name[name] = norm
    elif isinstance(raw_obj, list):
        for idx, row in enumerate(raw_obj):
            if not isinstance(row, dict):
                raise ValueError(f"servers[{idx}] must be an object")
            name = str(row.get("name") or "").strip()
            if not name:
                raise ValueError(f"servers[{idx}] missing name")
            norm = _normalize_one_server(name, row)
            rows_by_name[name] = norm
    else:
        raise ValueError("top-level JSON must contain 'mcpServers' object")

    return {"mcpServers": rows_by_name}


def dump_mcp_config_text(cfg: Dict[str, Any]) -> str:
    return json.dumps(cfg or _default_config(), ensure_ascii=False, indent=2) + "\n"


def load_mcp_config(config_path: str, create_if_missing: bool = True, logger: Any = None) -> Dict[str, Any]:
    path = os.path.abspath(str(config_path or "").strip())
    if not path:
        raise ValueError("config_path is empty")
    if create_if_missing:
        ensure_mcp_config_file(path, logger=logger)
    if not os.path.exists(path):
        return _default_config()
    with open(path, "r", encoding="utf-8") as f:
        text = f.read().strip()
    if not text:
        cfg = _default_config()
    else:
        raw = json.loads(text)
        cfg = normalize_mcp_config_obj(raw)
    return cfg


def save_mcp_config(raw_text: str, config_path: str, logger: Any = None) -> Dict[str, Any]:
    path = ensure_mcp_config_file(config_path, logger=logger)
    text = str(raw_text or "").strip()
    if not text:
        raise ValueError("config_text is empty")
    raw = json.loads(text)
    cfg = normalize_mcp_config_obj(raw)
    with open(path, "w", encoding="utf-8") as f:
        f.write(dump_mcp_config_text(cfg))
    _log(logger, "info", "saved mcp config: %s servers=%s", path, len(cfg.get("mcpServers") or {}))
    return cfg


def build_bridge_config_map(cfg: Dict[str, Any]) -> Dict[str, mcp_bridge.MCPServerConfig]:
    m = cfg.get("mcpServers") if isinstance(cfg, dict) else {}
    if not isinstance(m, dict):
        return {}
    out: Dict[str, mcp_bridge.MCPServerConfig] = {}
    for name, row in m.items():
        srv_name = str(name or "").strip()
        if not srv_name or not isinstance(row, dict):
            continue
        command = str(row.get("command") or "").strip()
        if not command:
            continue
        args = [str(x) for x in list(row.get("args") or [])]
        cwd = str(row.get("cwd") or "").strip() or None
        env = _normalize_env_dict(row.get("env"))
        whitelist = _normalize_whitelist(row.get("tools_whitelist", row.get("toolsWhitelist")))
        out[srv_name] = mcp_bridge.MCPServerConfig(
            name=srv_name,
            command=command,
            args=args,
            cwd=os.path.abspath(cwd) if cwd else None,
            env=env,
            tools_whitelist=whitelist,
        )
    return out

