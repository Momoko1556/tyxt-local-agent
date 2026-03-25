from typing import Any, Dict, List


def _safe_str(value: Any, default: str = "") -> str:
    text = str(value or "").strip()
    return text if text else str(default or "").strip()


def _safe_bool(value: Any, default: bool = False) -> bool:
    if isinstance(value, bool):
        return value
    if value is None:
        return bool(default)
    token = str(value).strip().lower()
    if token in {"1", "true", "yes", "y", "on", "enable", "enabled"}:
        return True
    if token in {"0", "false", "no", "n", "off", "disable", "disabled"}:
        return False
    return bool(default)


def _safe_int(value: Any, default: int = 0, min_v: int = 0, max_v: int = 100000) -> int:
    try:
        out = int(float(str(value).strip()))
    except Exception:
        out = int(default)
    out = max(int(min_v), out)
    out = min(int(max_v), out)
    return out


def _member_type_label(value: Any) -> str:
    token = _safe_str(value, "user").lower()
    if token == "agent":
        return "agent"
    if token == "admin":
        return "admin"
    return "user"


def _format_group_member_line(member: Dict[str, Any]) -> str:
    row = member if isinstance(member, dict) else {}
    mid = _safe_str(row.get("member_id") or row.get("id"), "-")
    name = _safe_str(row.get("member_name") or row.get("name"), mid)
    mtype = _member_type_label(row.get("member_type") or row.get("type"))
    is_admin = _safe_bool(row.get("is_admin"), mtype == "admin")
    muted = _safe_bool(row.get("muted"), False)
    speak_enabled = _safe_bool(row.get("speak_enabled"), mtype != "user")
    flags: List[str] = [f"type={mtype}"]
    if is_admin:
        flags.append("admin=true")
    if muted:
        flags.append("muted=true")
    if not speak_enabled:
        flags.append("speak_enabled=false")
    return f"- {name} (id={mid}; {'; '.join(flags)})"


def build_group_prompt_blocks(
    meta: Dict[str, Any],
    group_cfg: Dict[str, Any],
    route_result: Dict[str, Any],
) -> List[str]:
    m = dict(meta or {})
    cfg = dict(group_cfg or {})
    route = dict(route_result or {})
    group_id = _safe_str(cfg.get("group_id") or m.get("group_id"), "")
    group_name = _safe_str(cfg.get("group_name") or m.get("group_name"), _safe_str(group_id, "群聊"))
    group_topic = _safe_str(cfg.get("group_topic") or m.get("group_topic"))
    group_intro = _safe_str(cfg.get("group_intro") or m.get("group_intro"))
    group_mode = _safe_str(route.get("group_mode") or cfg.get("group_mode"), "semi_active")
    selected_agent_id = _safe_str(route.get("selected_agent_id") or m.get("agent_id"))
    default_agent_id = _safe_str(cfg.get("default_agent_id") or m.get("default_agent_id"))
    max_reply_length = _safe_int(route.get("max_reply_length") or cfg.get("max_reply_length"), 260, min_v=60, max_v=1600)
    response_mode = _safe_str(cfg.get("response_mode"), "normal")
    context_turn_n = _safe_int(route.get("context_turn_n") or cfg.get("context_turn_n"), 10, min_v=1, max_v=20)
    group_memory_enabled = _safe_bool(route.get("group_memory_enabled"), _safe_bool(cfg.get("group_memory_enabled"), True))
    allow_group_rag = _safe_bool(route.get("allow_group_rag"), _safe_bool(cfg.get("allow_group_rag"), True))
    trigger_reason = _safe_str(route.get("trigger_reason") or m.get("group_route_trigger_reason"))
    sender_is_agent = _safe_bool(route.get("sender_is_agent"), _safe_bool(m.get("sender_is_agent"), False))
    sender_agent_id = _safe_str(route.get("sender_agent_id") or m.get("sender_agent_id"))
    allow_cross_domain = _safe_bool(
        route.get("allow_cross_domain_analysis"),
        _safe_bool(cfg.get("allow_cross_domain_analysis"), True),
    )
    members_raw = [x for x in list(cfg.get("members") or []) if isinstance(x, dict)]
    members = members_raw[:80]
    agent_count = len([x for x in members_raw if _member_type_label((x or {}).get("member_type")) == "agent"])
    admin_count = len(
        [
            x
            for x in members_raw
            if _member_type_label((x or {}).get("member_type")) == "admin"
            or _safe_bool((x or {}).get("is_admin"), False)
        ]
    )
    user_count = max(0, len(members_raw) - agent_count - admin_count)

    blocks = []
    head_lines = [
        "【群聊会话设置】",
        f"- group_id: {group_id or '未设置'}",
        f"- group_name: {group_name}",
        f"- group_topic: {group_topic or '未设置'}",
        f"- group_intro: {group_intro or '未设置'}",
        f"- group_mode: {group_mode}",
        f"- default_agent_id: {default_agent_id or '未设置'}",
        f"- response_mode: {response_mode}",
        f"- selected_agent_id: {selected_agent_id or '未设置'}",
        f"- context_turn_n: {context_turn_n}",
        f"- max_reply_length: {max_reply_length}",
    ]
    blocks.append("\n".join(head_lines))
    member_lines = [
        "【群成员清单】",
        f"- total_members: {len(members_raw)}",
        f"- agent_members: {agent_count}",
        f"- admin_members: {admin_count}",
        f"- user_members: {user_count}",
    ]
    for row in members:
        member_lines.append(_format_group_member_line(row))
    if len(members_raw) > len(members):
        member_lines.append(f"- ... truncated: +{len(members_raw) - len(members)} members")
    member_lines.append("- 用途：用于点名识别、回复对象判断、群内角色边界判断。")
    blocks.append("\n".join(member_lines))

    blocks.append(
        "【群聊表达规则】\n"
        "保持当前 Agent 人格一致，但默认降档表达：更短、更克制、更少私人化。\n"
        "除非对方明确要求长文，不要输出冗长段落。\n"
        "优先按本轮路由结果回复；若路由给出多个 Agent，则按顺序接力。\n"
        "允许 Agent 在群聊中点名其他 Agent 进行交接；被点名 Agent 可被唤醒并继续回复。"
    )
    if sender_is_agent or trigger_reason == "agent_to_agent_call":
        blocks.append(
            "【Agent互唤醒规则】\n"
            f"- sender_agent_id: {sender_agent_id or 'unknown'}\n"
            "- 若消息中明确点名了其他 Agent，优先由被点名 Agent 回复。\n"
            "- 若未明确点名其他 Agent，则按路由继续由 selected_agent_id 回复。"
        )

    if allow_group_rag and group_memory_enabled:
        blocks.append(
            "【群聊记忆规则】\n"
            "常规群聊回复只允许检索当前群聊记忆（按 group_id 物理隔离）。\n"
            "禁止直接读取或复述私聊向量记忆。"
        )
    else:
        blocks.append(
            "【群聊记忆规则】\n"
            "本群当前关闭群聊 RAG 或群聊记忆。请仅基于当前消息和短期上下文回复。"
        )

    if allow_cross_domain:
        blocks.append(
            "【跨域分析硬规则】\n"
            "后台允许综合分析用户在私聊/群聊中的差异表现，但对外回复严禁泄露私聊敏感内容。"
        )
    else:
        blocks.append(
            "【跨域分析硬规则】\n"
            "本轮禁止跨私聊/群聊综合分析，仅按当前群聊数据作答。"
        )

    return blocks
