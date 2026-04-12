# -*- coding: utf-8 -*-
"""
query_context_builder.py

最小版 query_context 层（light_chain）：
- 只做字段搬运与安全兜底
- 不做业务判断
- 为 /chat 侧收口提供统一入口
"""

from __future__ import annotations

from typing import Any


_DEFAULT_TOOL_RESULT_BLOCK = (
    "【工具结果使用要求】\n"
    "若已提供工具结果，请优先依据工具结果作答。"
    "不要再说“无法联网/无法访问本地记忆/无法访问共享目录”。"
    "若工具结果不足，请明确指出不确定点，不要编造。"
)

_DEFAULT_OUTPUT_REQUIREMENT_BLOCK = (
    "【输出要求】\n"
    "默认用自然、简洁、直接的语气回答。"
    "除非用户明确要求长文，否则优先短句和轻量表达。"
)


def _as_dict(value: Any) -> dict:
    return dict(value) if isinstance(value, dict) else {}


def _as_text(value: Any) -> str:
    return str(value or "").strip()


def _as_text_list(value: Any) -> list[str]:
    out: list[str] = []
    for item in list(value or []):
        text = _as_text(item)
        if text:
            out.append(text)
    return out


def _as_any_list(value: Any) -> list[Any]:
    return list(value) if isinstance(value, list) else []


def build_light_chain_query_context(
    *,
    meta: dict | None = None,
    light_ctx: dict | None = None,
    agent_cfg: dict | None = None,
) -> dict:
    """
    统一打包 light_chain 读值入口（最小版）
    - 仅做字段归一与兜底
    - 不引入新判断逻辑
    """

    m = _as_dict(meta)
    ctx = _as_dict(light_ctx)
    cfg = _as_dict(agent_cfg)

    scene = _as_text(m.get("scene") or "private").lower() or "private"
    target_user_id = _as_text(m.get("target_user_id"))

    return {
        "meta": m,
        "light_ctx": ctx,
        "agent_cfg": cfg,
        "scene": scene,
        "target_user_id": target_user_id,
        "recent_summary": _as_text(ctx.get("recent_summary")),
        "recent_messages": _as_any_list(ctx.get("recent_messages")),
        "current_user_block": _as_text(ctx.get("current_user_block")),
        "agent_deepthink_notebook_block": _as_text(
            ctx.get("agent_deepthink_notebook_block")
        ),
        "third_party_blocks": _as_text_list(ctx.get("third_party_blocks")),
        "recent_context_block": _as_text(ctx.get("recent_context_block")),
        "extra_blocks": _as_text_list(ctx.get("extra_blocks")),
        "planning_mode": bool(ctx.get("planning_mode", False)),
        "tool_result_block": _as_text(
            ctx.get("tool_result_block") or _DEFAULT_TOOL_RESULT_BLOCK
        ),
        "output_requirement_block": _as_text(
            ctx.get("output_requirement_block")
            or _DEFAULT_OUTPUT_REQUIREMENT_BLOCK
        ),
    }
