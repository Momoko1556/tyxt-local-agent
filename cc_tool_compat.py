# -*- coding: utf-8 -*-
"""
OpenAI-compatible gateway tool-schema compatibility helper.

Purpose:
- Detect whether the current OpenAI-compatible endpoint supports CC tool schema.
- Persist result in a small local cache so TYXT bridge and local launcher can share it.
"""

from __future__ import annotations

import json
import os
import time
from typing import Any, Dict
from urllib import error, request


PROJECT_ROOT = os.path.abspath(os.path.dirname(__file__))
DEFAULT_CACHE_PATH = os.path.join(PROJECT_ROOT, "state", "cc_tool_compat_cache.json")
DEFAULT_CACHE_TTL_SEC = 1800


def _clean_text(v: Any) -> str:
    return str(v or "").strip()


def _normalize_mode(v: Any) -> str:
    s = _clean_text(v).lower()
    if s in {"safe", "full", "auto"}:
        return s
    return "auto"


def _normalize_cache_path(v: Any) -> str:
    p = _clean_text(v)
    if p:
        return os.path.abspath(p)
    return DEFAULT_CACHE_PATH


def _cache_key(base_url: str, model: str) -> str:
    b = _clean_text(base_url).rstrip("/").lower()
    m = _clean_text(model).lower()
    return f"openai::{b}::{m}"


def _read_cache(path: str) -> Dict[str, Any]:
    try:
        if not os.path.isfile(path):
            return {}
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        if isinstance(data, dict):
            return data
    except Exception:
        pass
    return {}


def _write_cache(path: str, data: Dict[str, Any]) -> None:
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        tmp = f"{path}.tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        os.replace(tmp, path)
    except Exception:
        pass


def _is_schema_incompatible_error(text: str) -> bool:
    low = _clean_text(text).lower()
    if not low:
        return False
    return (
        ("validationexception" in low and "improperly formed request" in low)
        or ("invalid_request_error" in low and "improperly formed request" in low)
    )


def _probe_openai_tools_schema(base_url: str, api_key: str, model: str, timeout_sec: int = 12) -> Dict[str, Any]:
    b = _clean_text(base_url).rstrip("/")
    k = _clean_text(api_key)
    m = _clean_text(model)
    if not b or not k or not m:
        return {"mode": "full", "reason": "missing_required", "status": 0}

    url = f"{b}/chat/completions"
    payload = {
        "model": m,
        "messages": [{"role": "user", "content": "ping"}],
        "max_tokens": 8,
        "temperature": 0,
        "stream": False,
        "tools": [
            {
                "type": "function",
                "function": {
                    "name": "dummy",
                    "description": "dummy",
                    "parameters": {"type": "object", "properties": {}},
                },
            }
        ],
        "tool_choice": "auto",
    }
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {k}",
    }
    req = request.Request(url, data=body, headers=headers, method="POST")
    try:
        with request.urlopen(req, timeout=max(3, int(timeout_sec))) as resp:
            status = int(getattr(resp, "status", 200) or 200)
            resp_body = resp.read().decode("utf-8", errors="ignore")
    except error.HTTPError as e:
        status = int(getattr(e, "code", 0) or 0)
        try:
            resp_body = e.read().decode("utf-8", errors="ignore")
        except Exception:
            resp_body = str(e)
    except Exception as e:
        return {"mode": "full", "reason": "probe_error", "status": 0, "detail": str(e)}

    if 200 <= status < 300:
        return {"mode": "full", "reason": "probe_ok", "status": status}
    if _is_schema_incompatible_error(resp_body):
        return {"mode": "safe", "reason": "schema_incompatible", "status": status}
    return {"mode": "full", "reason": f"http_{status}", "status": status}


def resolve_openai_tool_mode(
    base_url: str,
    api_key: str,
    model: str,
    preferred: str = "auto",
) -> str:
    mode = _normalize_mode(preferred)
    if mode in {"safe", "full"}:
        return mode

    cache_path = _normalize_cache_path(os.getenv("TYXT_CC_OPENAI_TOOL_MODE_CACHE_PATH"))
    ttl_sec = int(
        max(
            30,
            min(
                86400,
                int(float(str(os.getenv("TYXT_CC_OPENAI_TOOL_MODE_CACHE_TTL_SEC") or DEFAULT_CACHE_TTL_SEC))),
            ),
        )
    )
    key = _cache_key(base_url, model)
    cache = _read_cache(cache_path)
    row = cache.get(key) if isinstance(cache, dict) else None
    if isinstance(row, dict):
        row_mode = _normalize_mode(row.get("mode"))
        row_ts = float(row.get("ts") or 0)
        if row_mode in {"safe", "full"} and (time.time() - row_ts) < ttl_sec:
            return row_mode

    probed = _probe_openai_tools_schema(base_url, api_key, model)
    resolved_mode = _normalize_mode(probed.get("mode"))
    if resolved_mode not in {"safe", "full"}:
        resolved_mode = "full"
    cache[key] = {
        "mode": resolved_mode,
        "reason": _clean_text(probed.get("reason")) or "probe",
        "status": int(probed.get("status") or 0),
        "ts": time.time(),
        "base_url": _clean_text(base_url).rstrip("/"),
        "model": _clean_text(model),
    }
    _write_cache(cache_path, cache)
    return resolved_mode


def mark_openai_tool_mode(base_url: str, model: str, mode: str, reason: str = "runtime") -> None:
    resolved_mode = _normalize_mode(mode)
    if resolved_mode not in {"safe", "full"}:
        return
    cache_path = _normalize_cache_path(os.getenv("TYXT_CC_OPENAI_TOOL_MODE_CACHE_PATH"))
    key = _cache_key(base_url, model)
    cache = _read_cache(cache_path)
    cache[key] = {
        "mode": resolved_mode,
        "reason": _clean_text(reason) or "runtime",
        "status": 0,
        "ts": time.time(),
        "base_url": _clean_text(base_url).rstrip("/"),
        "model": _clean_text(model),
    }
    _write_cache(cache_path, cache)


__all__ = ["resolve_openai_tool_mode", "mark_openai_tool_mode"]

