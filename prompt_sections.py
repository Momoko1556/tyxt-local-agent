# -*- coding: utf-8 -*-
"""
prompt_sections.py

Prompt section 基础层：
- 定义 section 数据结构
- 提供统一 resolve 能力
- 先做最小版，不绑定具体业务逻辑
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, List, Optional, Sequence


@dataclass
class PromptSection:
    """
    单个 prompt section
    - name: section 名称，便于后续调试
    - resolver: 返回字符串内容；返回空字符串/None 视为跳过
    - enabled: 是否启用
    """

    name: str
    resolver: Callable[[], Optional[str]]
    enabled: bool = True


def prompt_section(
    name: str,
    resolver: Callable[[], Optional[str]],
    enabled: bool = True,
) -> PromptSection:
    return PromptSection(name=name, resolver=resolver, enabled=enabled)


def resolve_prompt_sections(
    sections: Sequence[PromptSection],
) -> List[str]:
    """
    顺序解析 sections，过滤空内容，返回干净的字符串列表
    """

    out: List[str] = []
    for sec in list(sections or []):
        try:
            if not sec.enabled:
                continue
            value = sec.resolver()
            text = str(value or "").strip()
            if not text:
                continue
            out.append(text)
        except Exception:
            # 最小版先吞掉 section 异常，避免影响主链路
            continue
    return out
