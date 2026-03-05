# -*- coding: utf-8 -*-
"""
Minimal fake MCP server for local Phase X testing.

Supported methods:
- tools/list
- list_tools
- tools/call
- call_tool
"""

from __future__ import annotations

import json
import sys
from typing import Any, Dict, Optional, Tuple


def _read_all_stdin() -> bytes:
    try:
        return sys.stdin.buffer.read()
    except Exception:
        return b""


def _try_json_load(raw: bytes) -> Optional[Dict[str, Any]]:
    try:
        obj = json.loads(raw.decode("utf-8", errors="ignore"))
        return obj if isinstance(obj, dict) else None
    except Exception:
        return None


def _parse_request(raw: bytes) -> Dict[str, Any]:
    data = raw or b""
    if not data:
        return {}

    # framed Content-Length
    h_end = data.find(b"\r\n\r\n")
    delim = 4
    if h_end < 0:
        h_end = data.find(b"\n\n")
        delim = 2
    if h_end >= 0:
        header = data[:h_end].decode("utf-8", errors="ignore").lower()
        if "content-length" in header:
            clen = -1
            for ln in header.splitlines():
                if ":" not in ln:
                    continue
                k, v = ln.split(":", 1)
                if k.strip() == "content-length":
                    try:
                        clen = int(v.strip())
                    except Exception:
                        clen = -1
                    break
            if clen >= 0:
                body = data[h_end + delim : h_end + delim + clen]
                obj = _try_json_load(body)
                if isinstance(obj, dict):
                    return obj

    # line JSON
    for ln in data.decode("utf-8", errors="ignore").splitlines():
        s = ln.strip()
        if not s:
            continue
        obj = _try_json_load(s.encode("utf-8"))
        if isinstance(obj, dict):
            return obj
    obj = _try_json_load(data)
    return obj if isinstance(obj, dict) else {}


def _jsonrpc_ok(req_id: Any, result: Any) -> Dict[str, Any]:
    return {"jsonrpc": "2.0", "id": req_id, "result": result}


def _jsonrpc_err(req_id: Any, msg: str, code: int = -32000) -> Dict[str, Any]:
    return {"jsonrpc": "2.0", "id": req_id, "error": {"code": code, "message": str(msg or "error")}}


def _handle(method: str, params: Dict[str, Any]) -> Tuple[bool, Any]:
    m = str(method or "").strip()
    p = params if isinstance(params, dict) else {}
    if m in {"tools/list", "list_tools"}:
        return True, {
            "tools": [
                {
                    "name": "echo",
                    "title": "MCP Echo",
                    "description": "Echo back input arguments.",
                    "inputSchema": {
                        "type": "object",
                        "required": ["text"],
                        "properties": {
                            "text": {"type": "string", "description": "Text to echo"},
                            "times": {"type": "integer", "default": 1, "minimum": 1, "maximum": 5},
                        },
                    },
                }
            ]
        }
    if m in {"tools/call", "call_tool"}:
        name = str(p.get("name") or p.get("tool_name") or "").strip()
        args = p.get("arguments")
        if not isinstance(args, dict):
            args = p.get("args")
        if not isinstance(args, dict):
            args = {}
        if name != "echo":
            return False, f"unknown_tool: {name}"
        text = str(args.get("text") or "")
        times = args.get("times", 1)
        try:
            t = int(times)
        except Exception:
            t = 1
        t = max(1, min(5, t))
        return True, {"tool": "echo", "echo": text, "times": t, "joined": " ".join([text] * t)}
    return False, f"unsupported_method: {m}"


def main() -> int:
    req = _parse_request(_read_all_stdin())
    req_id = req.get("id")
    method = str(req.get("method") or "").strip()
    params = req.get("params") if isinstance(req.get("params"), dict) else {}

    if not method:
        resp = _jsonrpc_err(req_id, "missing method", code=-32600)
    else:
        ok, result = _handle(method, params)
        if ok:
            resp = _jsonrpc_ok(req_id, result)
        else:
            resp = _jsonrpc_err(req_id, str(result), code=-32601)

    payload = json.dumps(resp, ensure_ascii=False).encode("utf-8")
    out = f"Content-Length: {len(payload)}\r\n\r\n".encode("utf-8") + payload
    try:
        sys.stdout.buffer.write(out)
        sys.stdout.buffer.flush()
    except Exception:
        pass
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
