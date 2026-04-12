# -*- coding: utf-8 -*-
"""
light_extra_context_builder.py

最小共享 helper（/chat 与 /v1/chat/completions）：
- 统一归一 recent_messages
- 统一归一 extra_blocks
- 统一携带 recent_context_block（仅搬运，不做业务判断）
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional


def _as_text(value: Any) -> str:
    return str(value or "").strip()


def _as_recent_messages(value: Any) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    for item in list(value or []):
        if isinstance(item, dict):
            out.append(dict(item))
    return out


def _as_text_list(value: Any) -> List[str]:
    out: List[str] = []
    for item in list(value or []):
        text = _as_text(item)
        if text:
            out.append(text)
    return out


def build_light_extra_context(
    *,
    recent_messages: Optional[List[Dict[str, Any]]] = None,
    extra_blocks: Optional[List[str]] = None,
    recent_context_block: str = "",
) -> Dict[str, Any]:
    """
    轻量共享入口：只做准备与归一，不做业务判定。
    """
    return {
        "recent_messages": _as_recent_messages(recent_messages),
        "extra_blocks": _as_text_list(extra_blocks),
        "recent_context_block": _as_text(recent_context_block),
    }

