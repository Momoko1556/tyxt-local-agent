# -*- coding: utf-8 -*-
"""
TYXT MCP Bridge (Phase X PoC)

This module provides a small, safety-first MCP bridge:
- load MCP server configs
- list tools from a server
- call a tool on a server

Current implementation is intentionally simple:
- one subprocess per request (sync)
- no long-lived process pool
- robust timeout and exception handling
"""

from __future__ import annotations

import json
import os
import subprocess
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple


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


def _now_ts() -> float:
    try:
        return time.time()
    except Exception:
        return 0.0


@dataclass
class MCPServerConfig:
    name: str
    command: str
    args: List[str] = field(default_factory=list)
    cwd: Optional[str] = None
    env: Dict[str, str] = field(default_factory=dict)
    tools_whitelist: Optional[List[str]] = None


@dataclass
class MCPToolDescriptor:
    server_name: str
    tool_name: str
    title: str
    description: str
    schema: Dict[str, Any] = field(default_factory=dict)


def _normalize_server_row(row: Any) -> Optional[MCPServerConfig]:
    if not isinstance(row, dict):
        return None
    name = str(row.get("name") or "").strip()
    command = str(row.get("command") or "").strip()
    if not name or not command:
        return None

    args: List[str] = []
    raw_args = row.get("args")
    if isinstance(raw_args, list):
        args = [str(x) for x in raw_args]

    cwd = row.get("cwd")
    cwd_s = str(cwd).strip() if cwd is not None else None
    if cwd_s == "":
        cwd_s = None

    env_raw = row.get("env")
    env: Dict[str, str] = {}
    if isinstance(env_raw, dict):
        for k, v in env_raw.items():
            kk = str(k).strip()
            if not kk:
                continue
            env[kk] = str(v)

    whitelist: Optional[List[str]] = None
    raw_whitelist = row.get("tools_whitelist")
    if isinstance(raw_whitelist, list):
        cleaned = [str(x).strip() for x in raw_whitelist if str(x).strip()]
        whitelist = cleaned if cleaned else []
    elif raw_whitelist is not None:
        s = str(raw_whitelist).strip()
        whitelist = [s] if s else []

    return MCPServerConfig(
        name=name,
        command=command,
        args=args,
        cwd=os.path.abspath(cwd_s) if cwd_s else None,
        env=env,
        tools_whitelist=whitelist,
    )


def load_mcp_server_configs(config_path: str, logger: Any = None) -> Dict[str, MCPServerConfig]:
    """
    Load MCP server configs from json/yaml file.
    Returns a map: {server_name: MCPServerConfig}
    """
    path = os.path.abspath(str(config_path or "").strip()) if config_path else ""
    if not path:
        return {}
    if not os.path.exists(path):
        if logger:
            logger.warning("[MCP] config file not found: %s", path)
        return {}

    raw: Any = None
    try:
        with open(path, "r", encoding="utf-8") as f:
            text = f.read()
        ext = os.path.splitext(path)[1].lower()
        if ext in {".yaml", ".yml"}:
            try:
                import yaml  # type: ignore
            except Exception:
                if logger:
                    logger.error("[MCP] yaml config is not supported because PyYAML is missing: %s", path)
                return {}
            raw = yaml.safe_load(text)
        else:
            raw = json.loads(text)
    except Exception as e:
        if logger:
            logger.error("[MCP] failed to load config %s: %s", path, e)
        return {}

    rows: List[Any] = []
    if isinstance(raw, dict):
        if isinstance(raw.get("servers"), list):
            rows = list(raw.get("servers") or [])
        elif isinstance(raw.get("mcp_servers"), list):
            rows = list(raw.get("mcp_servers") or [])
    elif isinstance(raw, list):
        rows = list(raw)

    out: Dict[str, MCPServerConfig] = {}
    for i, row in enumerate(rows):
        cfg = _normalize_server_row(row)
        if cfg is None:
            if logger:
                logger.warning("[MCP] invalid server row skipped: idx=%s", i)
            continue
        if cfg.name in out and logger:
            logger.warning("[MCP] duplicate server name '%s' in config. last one wins.", cfg.name)
        out[cfg.name] = cfg
    if logger:
        logger.info("[MCP] loaded %s server config(s) from %s", len(out), path)
    return out


class MCPBridge:
    """
    Simple MCP bridge: one subprocess per request.
    """

    def __init__(self, config_map: Dict[str, MCPServerConfig], logger: Any = None):
        self._config_map: Dict[str, MCPServerConfig] = dict(config_map or {})
        self._logger = logger

    def _log_info(self, msg: str, *args: Any) -> None:
        if self._logger:
            self._logger.info("[MCP] " + msg, *args)
        else:
            print("[MCP] " + (msg % args if args else msg))

    def _log_warn(self, msg: str, *args: Any) -> None:
        if self._logger:
            self._logger.warning("[MCP] " + msg, *args)
        else:
            print("[MCP][WARN] " + (msg % args if args else msg))

    def _log_error(self, msg: str, *args: Any) -> None:
        if self._logger:
            self._logger.error("[MCP] " + msg, *args)
        else:
            print("[MCP][ERROR] " + (msg % args if args else msg))

    def set_config_map(self, config_map: Dict[str, MCPServerConfig]) -> None:
        self._config_map = dict(config_map or {})

    def list_servers(self) -> List[str]:
        return sorted(self._config_map.keys())

    def _get_server(self, server_name: str) -> Optional[MCPServerConfig]:
        name = str(server_name or "").strip()
        if not name:
            return None
        return self._config_map.get(name)

    def _spawn(self, cfg: MCPServerConfig) -> subprocess.Popen:
        cmd = [str(cfg.command)] + [str(x) for x in list(cfg.args or [])]
        env = os.environ.copy()
        for k, v in dict(cfg.env or {}).items():
            kk = str(k).strip()
            if not kk:
                continue
            env[kk] = str(v)
        cwd = cfg.cwd if cfg.cwd else None
        return subprocess.Popen(
            cmd,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            cwd=cwd,
            env=env,
        )

    @staticmethod
    def _rpc_request(method: str, params: Dict[str, Any]) -> Dict[str, Any]:
        return {
            "jsonrpc": "2.0",
            "id": str(uuid.uuid4().hex),
            "method": str(method or "").strip(),
            "params": params if isinstance(params, dict) else {},
        }

    @staticmethod
    def _encode_rpc_message(req: Dict[str, Any], framed: bool = True) -> bytes:
        payload = json.dumps(req, ensure_ascii=False).encode("utf-8")
        if framed:
            header = f"Content-Length: {len(payload)}\r\n\r\n".encode("utf-8")
            return header + payload
        return payload + b"\n"

    @staticmethod
    def _try_json_load(s: bytes) -> Optional[Any]:
        try:
            return json.loads(s.decode("utf-8", errors="ignore"))
        except Exception:
            return None

    @classmethod
    def _decode_rpc_messages(cls, raw: bytes) -> List[Dict[str, Any]]:
        msgs: List[Dict[str, Any]] = []
        data = raw or b""
        n = len(data)
        i = 0

        # Parse MCP/LSP framed messages (Content-Length).
        while i < n:
            while i < n and data[i] in b" \t\r\n":
                i += 1
            if i >= n:
                break

            header_end = data.find(b"\r\n\r\n", i)
            delim = 4
            if header_end < 0:
                header_end = data.find(b"\n\n", i)
                delim = 2
            if header_end < 0:
                break

            header_blob = data[i:header_end].decode("utf-8", errors="ignore")
            if "content-length" not in header_blob.lower():
                break

            content_len = -1
            for ln in header_blob.splitlines():
                if ":" not in ln:
                    continue
                k, v = ln.split(":", 1)
                if str(k).strip().lower() == "content-length":
                    try:
                        content_len = int(str(v).strip())
                    except Exception:
                        content_len = -1
                    break
            if content_len < 0:
                break

            body_start = header_end + delim
            body_end = body_start + content_len
            if body_end > n:
                break
            body = data[body_start:body_end]
            j = cls._try_json_load(body)
            if isinstance(j, dict):
                msgs.append(j)
            i = body_end

        if msgs:
            return msgs

        # Fallback: one-json-per-line
        try:
            text = data.decode("utf-8", errors="ignore")
        except Exception:
            text = ""
        for ln in text.splitlines():
            s = ln.strip()
            if not s:
                continue
            j = cls._try_json_load(s.encode("utf-8"))
            if isinstance(j, dict):
                msgs.append(j)
        if msgs:
            return msgs

        # Fallback: whole stdout as one JSON object
        j = cls._try_json_load(data)
        if isinstance(j, dict):
            return [j]
        return []

    def _run_rpc_once(
        self,
        cfg: MCPServerConfig,
        method: str,
        params: Dict[str, Any],
        timeout: float,
        framed: bool,
    ) -> Tuple[bool, Any, str]:
        req = self._rpc_request(method, params)
        payload = self._encode_rpc_message(req, framed=framed)
        proc: Optional[subprocess.Popen] = None
        try:
            proc = self._spawn(cfg)
            out, err = proc.communicate(input=payload, timeout=max(float(timeout or 30.0), 0.1))
        except subprocess.TimeoutExpired:
            if proc is not None:
                try:
                    proc.kill()
                except Exception:
                    pass
                try:
                    proc.communicate(timeout=1)
                except Exception:
                    pass
            return False, None, f"timeout after {timeout}s"
        except Exception as e:
            return False, None, f"process_error: {e}"

        messages = self._decode_rpc_messages(out or b"")
        if not messages:
            stderr_txt = (err or b"").decode("utf-8", errors="ignore").strip()
            if stderr_txt:
                return False, None, f"empty_response: {stderr_txt[:240]}"
            return False, None, "empty_response"

        req_id = str(req.get("id") or "")
        resp = None
        for msg in messages:
            if str(msg.get("id") or "") == req_id:
                resp = msg
                break
        if resp is None:
            resp = messages[-1]

        if "error" in resp:
            e = resp.get("error")
            if isinstance(e, dict):
                msg = str(e.get("message") or e.get("code") or "rpc_error")
            else:
                msg = str(e or "rpc_error")
            return False, None, msg
        if "result" not in resp:
            return False, None, "response_missing_result"
        return True, resp.get("result"), ""

    def _run_rpc(
        self,
        cfg: MCPServerConfig,
        method: str,
        params: Dict[str, Any],
        timeout: float,
    ) -> Tuple[bool, Any, str]:
        # Try framed MCP first; fallback to line-based JSON for simple servers.
        ok, result, err = self._run_rpc_once(cfg, method, params, timeout, framed=True)
        if ok:
            return True, result, ""
        ok2, result2, err2 = self._run_rpc_once(cfg, method, params, timeout, framed=False)
        if ok2:
            return True, result2, ""
        return False, None, f"{err}; fallback_error={err2}"

    @staticmethod
    def _extract_tools_list(result: Any) -> List[Dict[str, Any]]:
        if isinstance(result, list):
            return [x for x in result if isinstance(x, dict)]
        if not isinstance(result, dict):
            return []
        raw = result.get("tools")
        if isinstance(raw, list):
            return [x for x in raw if isinstance(x, dict)]
        if isinstance(result.get("result"), dict):
            inner = result.get("result").get("tools")
            if isinstance(inner, list):
                return [x for x in inner if isinstance(x, dict)]
        return []

    def list_tools(self, server_name: str) -> List[MCPToolDescriptor]:
        cfg = self._get_server(server_name)
        if cfg is None:
            self._log_warn("list_tools skipped: server not found: %s", server_name)
            raise ValueError(f"server_not_found: {server_name}")
        start = _now_ts()
        self._log_info("list_tools server=%s", cfg.name)
        ok, result, err = self._run_rpc(cfg, "tools/list", {}, timeout=20.0)
        if not ok:
            ok2, result2, err2 = self._run_rpc(cfg, "list_tools", {}, timeout=20.0)
            if not ok2:
                msg = f"list_tools failed server={cfg.name} err={err} / {err2}"
                self._log_error("%s", msg)
                raise RuntimeError(msg)
            result = result2

        rows = self._extract_tools_list(result)
        # Whitelist behavior in Phase X PoC:
        # - tools_whitelist is None or [] => allow all tools.
        wl = cfg.tools_whitelist if isinstance(cfg.tools_whitelist, list) else None
        wl_set = {str(x).strip() for x in list(wl or []) if str(x).strip()}
        out: List[MCPToolDescriptor] = []
        for row in rows:
            tool_name = str(row.get("name") or row.get("tool_name") or "").strip()
            if not tool_name:
                continue
            if wl is not None and wl_set and tool_name not in wl_set:
                continue
            title = str(row.get("title") or tool_name).strip() or tool_name
            desc = str(row.get("description") or "").strip()
            schema = row.get("inputSchema")
            if not isinstance(schema, dict):
                schema = row.get("schema")
            if not isinstance(schema, dict):
                schema = row.get("parameters")
            if not isinstance(schema, dict):
                schema = {"type": "object"}
            out.append(
                MCPToolDescriptor(
                    server_name=cfg.name,
                    tool_name=tool_name,
                    title=title,
                    description=desc,
                    schema=dict(schema or {"type": "object"}),
                )
            )
        self._log_info("list_tools ok server=%s count=%s cost=%.2fs", cfg.name, len(out), max(0.0, _now_ts() - start))
        return out

    def call_tool(
        self,
        server_name: str,
        tool_name: str,
        args: Dict[str, Any],
        timeout: float = 30.0,
    ) -> Dict[str, Any]:
        cfg = self._get_server(server_name)
        if cfg is None:
            return {"ok": False, "result": None, "error": f"server_not_found: {server_name}"}
        tool = str(tool_name or "").strip()
        if not tool:
            return {"ok": False, "result": None, "error": "tool_name_empty"}
        payload = args if isinstance(args, dict) else {}
        start = _now_ts()
        self._log_info("call_tool server=%s tool=%s", cfg.name, tool)

        attempts = [
            ("tools/call", {"name": tool, "arguments": payload}),
            ("call_tool", {"tool_name": tool, "args": payload}),
        ]
        last_err = ""
        for method, params in attempts:
            ok, result, err = self._run_rpc(cfg, method, params, timeout=max(float(timeout or 30.0), 0.1))
            if not ok:
                last_err = str(err or "rpc_failed")
                continue
            if isinstance(result, dict):
                # MCP native tool error shape.
                if _safe_bool(result.get("isError"), False):
                    msg = str(result.get("error") or result.get("message") or "tool_error")
                    self._log_warn("call_tool tool_error server=%s tool=%s err=%s", cfg.name, tool, msg)
                    return {"ok": False, "result": result, "error": msg}
                # Many custom servers return business payload: {"ok": false, "error": "..."}.
                if ("ok" in result) and (not _safe_bool(result.get("ok"), True)):
                    msg = str(result.get("error") or result.get("message") or "tool_error")
                    self._log_warn("call_tool business_error server=%s tool=%s err=%s", cfg.name, tool, msg)
                    return {"ok": False, "result": result, "error": msg or "tool_error"}
            self._log_info(
                "call_tool ok server=%s tool=%s cost=%.2fs",
                cfg.name,
                tool,
                max(0.0, _now_ts() - start),
            )
            return {"ok": True, "result": result, "error": ""}

        self._log_error("call_tool failed server=%s tool=%s err=%s", cfg.name, tool, last_err)
        return {"ok": False, "result": None, "error": last_err or "call_failed"}

    def shutdown(self) -> None:
        # No persistent processes in current PoC implementation.
        self._log_info("shutdown noop (one-shot subprocess mode)")
