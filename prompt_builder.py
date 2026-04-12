# -*- coding: utf-8 -*-
"""
prompt_builder.py

最小版 Prompt Builder：
- 先只接 light_chain 前半段
- 只处理 persona / policy / time / group 这几类 section
- 不侵入 memory / rag / tool_result / deepthink / rumination
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from prompt_sections import prompt_section, resolve_prompt_sections


def _safe_text(v: Any) -> str:
    return str(v or "").strip()


def _normalize_block_list(blocks: Any) -> List[str]:
    out: List[str] = []
    for item in list(blocks or []):
        text = _safe_text(item)
        if text:
            out.append(text)
    return out


def build_system_prompt(
    scene: str = "",
    mode: str = "",
    ctx: Optional[Dict[str, Any]] = None,
) -> List[str]:
    """
    通用入口（当前仍保留）
    """
    _ = dict(ctx or {})
    scene_text = _safe_text(scene)
    mode_text = _safe_text(mode)

    sections = [
        prompt_section(
            "builder_meta",
            lambda: (
                "【Prompt Builder】\n"
                f"- scene: {scene_text or 'unknown'}\n"
                f"- mode: {mode_text or 'unknown'}"
            )
        ),
    ]
    return resolve_prompt_sections(sections)


def build_light_chain_prompt_prefix(
    *,
    scene: str = "",
    agent_global_prompt: str = "",
    agent_prompt: str = "",
    policy_block: str = "",
    group_policy_block: str = "",
    system_time_block: str = "",
    group_prompt_blocks: Optional[List[str]] = None,
) -> List[str]:
    """
    light_chain 前半段专用：
    只负责以下 section 的统一组装：
    - Agent系统提示词
    - 当前Agent人格设定
    - reply policy
    - group policy
    - system time
    - group prompt blocks
    """
    scene_text = _safe_text(scene)
    group_blocks = _normalize_block_list(group_prompt_blocks)

    sections = [
        prompt_section(
            "agent_global_prompt",
            lambda: f"【Agent系统提示词】\n{agent_global_prompt}"
            if _safe_text(agent_global_prompt)
            else None,
        ),
        prompt_section(
            "agent_prompt",
            lambda: f"【当前 Agent 人格设定】\n{agent_prompt}"
            if _safe_text(agent_prompt)
            else None,
        ),
        prompt_section(
            "reply_policy",
            lambda: policy_block if _safe_text(policy_block) else None,
        ),
        prompt_section(
            "group_policy",
            lambda: group_policy_block if _safe_text(group_policy_block) else None,
        ),
        prompt_section(
            "system_time",
            lambda: system_time_block if _safe_text(system_time_block) else None,
        ),
        prompt_section(
            "group_blocks",
            lambda: "\n\n".join(group_blocks) if group_blocks else None,
            enabled=(scene_text == "group"),
        ),
    ]
    return resolve_prompt_sections(sections)


def build_light_chain_prompt_suffix(
    *,
    memory_block: str = "",
    rag_block: str = "",
    extra_blocks: Optional[List[str]] = None,
) -> List[str]:
    """
    light_chain 后半段专用：
    - memory_block：记忆类文本块（若非空则注入）
    - rag_block：RAG 类文本块（若非空则注入）
    - extra_blocks：其余已生成好的字符串块，按顺序注入
    """
    extras = _normalize_block_list(extra_blocks)

    sections = [
        prompt_section(
            "memory_block",
            lambda: memory_block if _safe_text(memory_block) else None,
        ),
        prompt_section(
            "rag_block",
            lambda: rag_block if _safe_text(rag_block) else None,
        ),
        prompt_section(
            "extra_blocks",
            lambda: "\n\n".join(extras) if extras else None,
        ),
    ]
    return resolve_prompt_sections(sections)
