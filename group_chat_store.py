import copy
import json
import os
import re
import threading
import time
import uuid
from typing import Any, Dict, List, Optional, Tuple


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


def _safe_int(value: Any, default: int = 0, min_v: Optional[int] = None, max_v: Optional[int] = None) -> int:
    try:
        out = int(float(str(value).strip()))
    except Exception:
        out = int(default)
    if min_v is not None:
        out = max(int(min_v), out)
    if max_v is not None:
        out = min(int(max_v), out)
    return out


def _norm_mode(value: Any) -> str:
    token = _safe_str(value, "semi_active").lower()
    if token not in {"strict", "semi_active", "active", "silent"}:
        return "semi_active"
    return token


def _norm_reply_mode(value: Any) -> str:
    token = _safe_str(value, "normal").lower()
    if token not in {"short", "normal", "tool", "expand"}:
        return "normal"
    return token


def _norm_list(values: Any, max_items: int = 50, max_len: int = 64) -> List[str]:
    src = values
    if isinstance(src, str):
        src = [x for x in re.split(r"[,\n，;；\s]+", src) if str(x or "").strip()]
    out: List[str] = []
    seen = set()
    for raw in list(src or []):
        text = _safe_str(raw)
        if not text:
            continue
        if len(text) > max_len:
            text = text[:max_len].rstrip()
        if not text:
            continue
        key = text.casefold()
        if key in seen:
            continue
        seen.add(key)
        out.append(text)
        if len(out) >= max(1, int(max_items)):
            break
    return out


def _norm_group_id(value: Any) -> str:
    token = re.sub(r"[^0-9a-zA-Z_\-]+", "_", _safe_str(value)).strip("_")
    if token:
        return token[:80]
    return f"group_{int(time.time())}_{uuid.uuid4().hex[:6]}"


def _norm_member_type(value: Any) -> str:
    token = _safe_str(value, "user").lower()
    if token in {"manager", "owner"}:
        return "admin"
    if token not in {"user", "agent", "admin"}:
        return "user"
    return token


def _deepcopy(data: Any) -> Any:
    return copy.deepcopy(data)


def _norm_trigger_rules_mode(value: Any, default: str = "semi_active") -> str:
    return _norm_mode(value if value is not None else default)


def _trigger_rules_default(seed: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    src = seed if isinstance(seed, dict) else {}
    mode = _norm_trigger_rules_mode(src.get("mode"), "semi_active")
    keyword_enabled_seed = _safe_bool(src.get("keyword_enabled"), True)
    proactive_enabled_seed = _safe_bool(src.get("proactive_enabled"), False)
    if mode == "strict":
        keyword_enabled_seed = False
        proactive_enabled_seed = False
    elif mode == "semi_active":
        proactive_enabled_seed = False
    elif mode == "silent":
        keyword_enabled_seed = False
        proactive_enabled_seed = False

    followup_enabled_seed = _safe_bool(src.get("followup_enabled"), False)
    if mode == "silent":
        followup_enabled_seed = False

    return {
        "version": 1,
        "mode": mode,
        "explicit": {
            "at_reply": _safe_bool(src.get("at_reply"), True),
            "name_reply": _safe_bool(src.get("name_reply"), True),
            "nickname_reply": _safe_bool(src.get("nickname_reply"), _safe_bool(src.get("name_reply"), True)),
            "quote_reply": _safe_bool(src.get("quote_reply"), True),
            "admin_force_wakeup": _safe_bool(src.get("admin_force_wakeup"), True),
        },
        "keyword": {
            "enabled": bool(keyword_enabled_seed),
            "terms": _norm_list(src.get("keyword_terms"), max_items=60, max_len=24),
        },
        "proactive": {
            "enabled": bool(proactive_enabled_seed),
        },
        "guard": {
            "cooldown_seconds": _safe_int(src.get("cooldown_seconds"), 8, min_v=0, max_v=7200),
            "anti_conflict_enabled": _safe_bool(src.get("anti_conflict_enabled"), True),
        },
        "followup": {
            "enabled": bool(followup_enabled_seed),
            "window_seconds": _safe_int(src.get("followup_window_seconds"), 20, min_v=3, max_v=240),
        },
    }


def _has_nested_key(row: Any, keys: List[str]) -> bool:
    node = row
    for key in keys:
        if not isinstance(node, dict) or key not in node:
            return False
        node = node.get(key)
    return True


def _has_legacy_trigger_override(row: Any) -> bool:
    src = row if isinstance(row, dict) else {}
    for key in [
        "group_mode",
        "trigger_keywords",
        "allow_proactive_reply",
        "cooldown_seconds",
        "anti_conflict_enabled",
        "allow_followup_short_reply",
        "followup_window_seconds",
    ]:
        if key in src:
            return True
    trigger_settings = src.get("trigger_settings") if isinstance(src.get("trigger_settings"), dict) else {}
    for key in ["at_reply", "name_reply", "nickname_reply", "quote_reply", "keyword_trigger", "admin_force_wakeup"]:
        if key in trigger_settings:
            return True
    return False


def _resolve_trigger_rules_v1(
    group_input: Optional[Dict[str, Any]] = None,
    prev_group: Optional[Dict[str, Any]] = None,
    lounge_rules: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    row = group_input if isinstance(group_input, dict) else {}
    prev = prev_group if isinstance(prev_group, dict) else {}
    lounge_raw = lounge_rules if isinstance(lounge_rules, dict) else {}

    triggers_prev = prev.get("trigger_settings") if isinstance(prev.get("trigger_settings"), dict) else {}
    triggers_in = row.get("trigger_settings") if isinstance(row.get("trigger_settings"), dict) else {}

    # 历史字段兜底（最低优先级）
    legacy_seed = {
        "mode": prev.get("group_mode") if ("group_mode" in prev) else "semi_active",
        "at_reply": triggers_prev.get("at_reply") if ("at_reply" in triggers_prev) else True,
        "name_reply": triggers_prev.get("name_reply") if ("name_reply" in triggers_prev) else True,
        "nickname_reply": (
            triggers_prev.get("nickname_reply")
            if ("nickname_reply" in triggers_prev)
            else (triggers_prev.get("name_reply") if ("name_reply" in triggers_prev) else True)
        ),
        "quote_reply": triggers_prev.get("quote_reply") if ("quote_reply" in triggers_prev) else True,
        "admin_force_wakeup": triggers_prev.get("admin_force_wakeup") if ("admin_force_wakeup" in triggers_prev) else True,
        "keyword_enabled": triggers_prev.get("keyword_trigger") if ("keyword_trigger" in triggers_prev) else True,
        "keyword_terms": prev.get("trigger_keywords") if ("trigger_keywords" in prev) else [],
        "proactive_enabled": prev.get("allow_proactive_reply") if ("allow_proactive_reply" in prev) else False,
        "cooldown_seconds": prev.get("cooldown_seconds") if ("cooldown_seconds" in prev) else 8,
        "anti_conflict_enabled": prev.get("anti_conflict_enabled") if ("anti_conflict_enabled" in prev) else True,
        "followup_enabled": prev.get("allow_followup_short_reply") if ("allow_followup_short_reply" in prev) else False,
        "followup_window_seconds": prev.get("followup_window_seconds") if ("followup_window_seconds" in prev) else 20,
    }
    fallback = _trigger_rules_default(legacy_seed)

    explicit_v1_prev = _safe_bool(prev.get("trigger_rules_v1_explicit"), False)
    if "trigger_rules_v1_explicit" in row:
        explicit_v1 = _safe_bool(row.get("trigger_rules_v1_explicit"), explicit_v1_prev)
    else:
        explicit_v1 = explicit_v1_prev
    if (not explicit_v1) and ("trigger_rules_v1" in row) and isinstance(row.get("trigger_rules_v1"), dict):
        explicit_v1 = True
    if (not explicit_v1) and _has_legacy_trigger_override(row):
        explicit_v1 = True

    lounge_norm = _normalize_trigger_rules_v1_payload(lounge_raw, fallback=fallback)

    # 未显式启用群级规则时：仅 lounge 默认 > 历史兜底
    if not explicit_v1:
        return lounge_norm

    # 显式启用群级规则时：群级(旧字段) > lounge > fallback
    legacy_full = {
        "mode": row.get("group_mode") if ("group_mode" in row) else prev.get("group_mode"),
        "explicit": {
            "at_reply": triggers_in.get("at_reply") if ("at_reply" in triggers_in) else triggers_prev.get("at_reply"),
            "name_reply": triggers_in.get("name_reply") if ("name_reply" in triggers_in) else triggers_prev.get("name_reply"),
            "nickname_reply": (
                triggers_in.get("nickname_reply")
                if ("nickname_reply" in triggers_in)
                else (
                    triggers_prev.get("nickname_reply")
                    if ("nickname_reply" in triggers_prev)
                    else (
                        triggers_in.get("name_reply")
                        if ("name_reply" in triggers_in)
                        else triggers_prev.get("name_reply")
                    )
                )
            ),
            "quote_reply": triggers_in.get("quote_reply") if ("quote_reply" in triggers_in) else triggers_prev.get("quote_reply"),
            "admin_force_wakeup": triggers_in.get("admin_force_wakeup") if ("admin_force_wakeup" in triggers_in) else triggers_prev.get("admin_force_wakeup"),
        },
        "keyword": {
            "enabled": triggers_in.get("keyword_trigger") if ("keyword_trigger" in triggers_in) else triggers_prev.get("keyword_trigger"),
            "terms": row.get("trigger_keywords") if ("trigger_keywords" in row) else prev.get("trigger_keywords"),
        },
        "proactive": {
            "enabled": row.get("allow_proactive_reply") if ("allow_proactive_reply" in row) else prev.get("allow_proactive_reply"),
        },
        "guard": {
            "cooldown_seconds": row.get("cooldown_seconds") if ("cooldown_seconds" in row) else prev.get("cooldown_seconds"),
            "anti_conflict_enabled": row.get("anti_conflict_enabled") if ("anti_conflict_enabled" in row) else prev.get("anti_conflict_enabled"),
        },
        "followup": {
            "enabled": row.get("allow_followup_short_reply") if ("allow_followup_short_reply" in row) else prev.get("allow_followup_short_reply"),
            "window_seconds": row.get("followup_window_seconds") if ("followup_window_seconds" in row) else prev.get("followup_window_seconds"),
        },
    }
    resolved = _normalize_trigger_rules_v1_payload(legacy_full, fallback=lounge_norm)

    # v1 字段优先于旧字段（仅覆盖本次输入中显式出现的键）
    trigger_rules_in = row.get("trigger_rules_v1") if isinstance(row.get("trigger_rules_v1"), dict) else {}
    if isinstance(trigger_rules_in, dict) and trigger_rules_in:
        v1_normalized = _normalize_trigger_rules_v1_payload(trigger_rules_in, fallback=resolved)
        fields = [
            ["mode"],
            ["explicit", "at_reply"],
            ["explicit", "name_reply"],
            ["explicit", "nickname_reply"],
            ["explicit", "quote_reply"],
            ["explicit", "admin_force_wakeup"],
            ["keyword", "enabled"],
            ["keyword", "terms"],
            ["proactive", "enabled"],
            ["guard", "cooldown_seconds"],
            ["guard", "anti_conflict_enabled"],
            ["followup", "enabled"],
            ["followup", "window_seconds"],
        ]
        for key_path in fields:
            if not _has_nested_key(trigger_rules_in, key_path):
                continue
            dst = resolved
            src = v1_normalized
            for token in key_path[:-1]:
                dst = dst.setdefault(token, {}) if isinstance(dst, dict) else {}
                src = src.get(token) if isinstance(src, dict) else {}
            leaf = key_path[-1]
            if isinstance(dst, dict) and isinstance(src, dict) and leaf in src:
                if key_path == ["keyword", "terms"]:
                    dst[leaf] = _norm_list(src.get(leaf), max_items=60, max_len=24)
                else:
                    dst[leaf] = src.get(leaf)

    return _normalize_trigger_rules_v1_payload(resolved)


def _normalize_trigger_rules_v1_payload(raw: Any, fallback: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    src = raw if isinstance(raw, dict) else {}
    base_seed = fallback if isinstance(fallback, dict) else _trigger_rules_default()
    base = _trigger_rules_default(
        {
            "mode": base_seed.get("mode"),
            "at_reply": ((base_seed.get("explicit") or {}).get("at_reply") if isinstance(base_seed.get("explicit"), dict) else True),
            "name_reply": ((base_seed.get("explicit") or {}).get("name_reply") if isinstance(base_seed.get("explicit"), dict) else True),
            "nickname_reply": (
                (base_seed.get("explicit") or {}).get("nickname_reply")
                if isinstance(base_seed.get("explicit"), dict) and ("nickname_reply" in (base_seed.get("explicit") or {}))
                else ((base_seed.get("explicit") or {}).get("name_reply") if isinstance(base_seed.get("explicit"), dict) else True)
            ),
            "quote_reply": ((base_seed.get("explicit") or {}).get("quote_reply") if isinstance(base_seed.get("explicit"), dict) else True),
            "admin_force_wakeup": ((base_seed.get("explicit") or {}).get("admin_force_wakeup") if isinstance(base_seed.get("explicit"), dict) else True),
            "keyword_enabled": ((base_seed.get("keyword") or {}).get("enabled") if isinstance(base_seed.get("keyword"), dict) else True),
            "keyword_terms": ((base_seed.get("keyword") or {}).get("terms") if isinstance(base_seed.get("keyword"), dict) else []),
            "proactive_enabled": ((base_seed.get("proactive") or {}).get("enabled") if isinstance(base_seed.get("proactive"), dict) else False),
            "cooldown_seconds": ((base_seed.get("guard") or {}).get("cooldown_seconds") if isinstance(base_seed.get("guard"), dict) else 8),
            "anti_conflict_enabled": ((base_seed.get("guard") or {}).get("anti_conflict_enabled") if isinstance(base_seed.get("guard"), dict) else True),
            "followup_enabled": ((base_seed.get("followup") or {}).get("enabled") if isinstance(base_seed.get("followup"), dict) else False),
            "followup_window_seconds": ((base_seed.get("followup") or {}).get("window_seconds") if isinstance(base_seed.get("followup"), dict) else 20),
        }
    )

    explicit_src = src.get("explicit") if isinstance(src.get("explicit"), dict) else {}
    keyword_src = src.get("keyword") if isinstance(src.get("keyword"), dict) else {}
    proactive_src = src.get("proactive") if isinstance(src.get("proactive"), dict) else {}
    guard_src = src.get("guard") if isinstance(src.get("guard"), dict) else {}
    followup_src = src.get("followup") if isinstance(src.get("followup"), dict) else {}

    mode = _norm_trigger_rules_mode(src.get("mode"), base.get("mode"))

    explicit = {
        "at_reply": _safe_bool(explicit_src.get("at_reply"), _safe_bool((base.get("explicit") or {}).get("at_reply"), True)),
        "name_reply": _safe_bool(explicit_src.get("name_reply"), _safe_bool((base.get("explicit") or {}).get("name_reply"), True)),
        "nickname_reply": _safe_bool(
            explicit_src.get("nickname_reply"),
            _safe_bool(
                (base.get("explicit") or {}).get("nickname_reply"),
                _safe_bool((base.get("explicit") or {}).get("name_reply"), True),
            ),
        ),
        "quote_reply": _safe_bool(explicit_src.get("quote_reply"), _safe_bool((base.get("explicit") or {}).get("quote_reply"), True)),
        "admin_force_wakeup": _safe_bool(
            explicit_src.get("admin_force_wakeup"),
            _safe_bool((base.get("explicit") or {}).get("admin_force_wakeup"), True),
        ),
    }
    keyword_enabled = _safe_bool(keyword_src.get("enabled"), _safe_bool((base.get("keyword") or {}).get("enabled"), True))
    proactive_enabled = _safe_bool(proactive_src.get("enabled"), _safe_bool((base.get("proactive") or {}).get("enabled"), False))
    followup_enabled = _safe_bool(followup_src.get("enabled"), _safe_bool((base.get("followup") or {}).get("enabled"), False))

    if mode == "strict":
        keyword_enabled = False
        proactive_enabled = False
    elif mode == "semi_active":
        proactive_enabled = False
    elif mode == "silent":
        keyword_enabled = False
        proactive_enabled = False
        followup_enabled = False

    out = {
        "version": 1,
        "mode": mode,
        "explicit": explicit,
        "keyword": {
            "enabled": bool(keyword_enabled),
            "terms": _norm_list(keyword_src.get("terms"), max_items=60, max_len=24)
            if ("terms" in keyword_src)
            else _norm_list((base.get("keyword") or {}).get("terms"), max_items=60, max_len=24),
        },
        "proactive": {
            "enabled": bool(proactive_enabled),
        },
        "guard": {
            "cooldown_seconds": _safe_int(
                guard_src.get("cooldown_seconds"),
                _safe_int((base.get("guard") or {}).get("cooldown_seconds"), 8),
                min_v=0,
                max_v=7200,
            ),
            "anti_conflict_enabled": _safe_bool(
                guard_src.get("anti_conflict_enabled"),
                _safe_bool((base.get("guard") or {}).get("anti_conflict_enabled"), True),
            ),
        },
        "followup": {
            "enabled": bool(followup_enabled),
            "window_seconds": _safe_int(
                followup_src.get("window_seconds"),
                _safe_int((base.get("followup") or {}).get("window_seconds"), 20),
                min_v=3,
                max_v=240,
            ),
        },
    }
    return out


def _trigger_rules_to_legacy_fields(trigger_rules: Dict[str, Any]) -> Dict[str, Any]:
    rules = _normalize_trigger_rules_v1_payload(trigger_rules)
    explicit = rules.get("explicit") if isinstance(rules.get("explicit"), dict) else {}
    keyword = rules.get("keyword") if isinstance(rules.get("keyword"), dict) else {}
    proactive = rules.get("proactive") if isinstance(rules.get("proactive"), dict) else {}
    guard = rules.get("guard") if isinstance(rules.get("guard"), dict) else {}
    followup = rules.get("followup") if isinstance(rules.get("followup"), dict) else {}
    followup_enabled = _safe_bool(followup.get("enabled"), False)
    return {
        "group_mode": _norm_mode(rules.get("mode")),
        "trigger_settings": {
            "at_reply": _safe_bool(explicit.get("at_reply"), True),
            "name_reply": _safe_bool(explicit.get("name_reply"), True),
            "nickname_reply": _safe_bool(
                explicit.get("nickname_reply"),
                _safe_bool(explicit.get("name_reply"), True),
            ),
            "quote_reply": _safe_bool(explicit.get("quote_reply"), True),
            "keyword_trigger": _safe_bool(keyword.get("enabled"), True),
            "admin_force_wakeup": _safe_bool(explicit.get("admin_force_wakeup"), True),
        },
        "trigger_keywords": _norm_list(keyword.get("terms"), max_items=60, max_len=24),
        "allow_proactive_reply": _safe_bool(proactive.get("enabled"), False),
        "cooldown_seconds": _safe_int(guard.get("cooldown_seconds"), 8, min_v=0, max_v=7200),
        "anti_conflict_enabled": _safe_bool(guard.get("anti_conflict_enabled"), True),
        "allow_followup_short_reply": bool(followup_enabled),
        "followup_window_seconds": _safe_int(followup.get("window_seconds"), 20, min_v=3, max_v=240),
    }


class GroupChatStore:
    def __init__(self, store_path: str, group_memory_root: str):
        self.store_path = os.path.abspath(str(store_path or "").strip())
        self.group_memory_root = os.path.abspath(str(group_memory_root or "").strip())
        self._lock = threading.RLock()
        os.makedirs(os.path.dirname(self.store_path), exist_ok=True)
        os.makedirs(self.group_memory_root, exist_ok=True)
        self._state = self._load_state()

    def _default_state(self) -> Dict[str, Any]:
        return {
            "version": 1,
            "updated_at": int(time.time()),
            "groups": [],
        }

    def _group_memory_default_path(self, group_id: str) -> str:
        gid = _norm_group_id(group_id)
        path = os.path.join(self.group_memory_root, gid)
        os.makedirs(path, exist_ok=True)
        return path

    def _normalize_member(self, raw: Any) -> Dict[str, Any]:
        row = raw if isinstance(raw, dict) else {}
        member_id = _safe_str(row.get("member_id") or row.get("id"))
        member_type = _norm_member_type(row.get("member_type") or row.get("type"))
        if not member_id:
            member_id = f"{member_type}_{uuid.uuid4().hex[:8]}"
        return {
            "member_id": member_id,
            "member_name": _safe_str(row.get("member_name") or row.get("name") or member_id),
            "member_type": member_type,
            "is_admin": _safe_bool(row.get("is_admin"), member_type == "admin"),
            "is_default_agent": _safe_bool(row.get("is_default_agent"), False),
            "muted": _safe_bool(row.get("muted"), False),
            "speak_enabled": _safe_bool(row.get("speak_enabled"), member_type != "user"),
            "visible": _safe_bool(row.get("visible"), True),
            "trigger_keywords": _norm_list(row.get("trigger_keywords"), max_items=20, max_len=32),
            "updated_at": int(time.time()),
        }

    def _normalize_group(self, raw: Any, keep_created: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        row = raw if isinstance(raw, dict) else {}
        prev = keep_created if isinstance(keep_created, dict) else {}
        group_id = _norm_group_id(row.get("group_id") or prev.get("group_id"))

        raw_members = list(row.get("members") or prev.get("members") or [])
        members: List[Dict[str, Any]] = []
        seen_member = set()
        for item in raw_members:
            member = self._normalize_member(item)
            key = _safe_str(member.get("member_id")).casefold()
            if not key or key in seen_member:
                continue
            seen_member.add(key)
            members.append(member)

        default_agent_id = _safe_str(
            row.get("default_agent_id")
            or row.get("defaultAgentId")
            or prev.get("default_agent_id")
        )
        allowed_agent_ids = _norm_list(
            row.get("allowed_agent_ids") or row.get("allowedAgentIds") or prev.get("allowed_agent_ids"),
            max_items=32,
            max_len=64,
        )

        # Keep allowed agents aligned with visible/speak-enabled agent members.
        agent_member_ids = []
        for member in members:
            if _safe_str(member.get("member_type")).lower() != "agent":
                continue
            if not _safe_bool(member.get("visible"), True):
                continue
            if not _safe_bool(member.get("speak_enabled"), True):
                continue
            agent_member_ids.append(_safe_str(member.get("member_id")))

        if not allowed_agent_ids:
            allowed_agent_ids = list(agent_member_ids)
        else:
            allowed_set = {x.casefold() for x in allowed_agent_ids}
            for aid in agent_member_ids:
                if aid.casefold() not in allowed_set:
                    allowed_agent_ids.append(aid)
                    allowed_set.add(aid.casefold())

        if not default_agent_id:
            default_agent_id = _safe_str(prev.get("default_agent_id"))

        explicit_v1_prev = _safe_bool(prev.get("trigger_rules_v1_explicit"), False)
        if "trigger_rules_v1_explicit" in row:
            explicit_v1_flag = _safe_bool(row.get("trigger_rules_v1_explicit"), explicit_v1_prev)
        elif ("trigger_rules_v1" in row) and isinstance(row.get("trigger_rules_v1"), dict):
            explicit_v1_flag = True
        elif _has_legacy_trigger_override(row):
            explicit_v1_flag = True
        else:
            explicit_v1_flag = explicit_v1_prev

        trigger_rules_v1 = _resolve_trigger_rules_v1(row, prev)
        legacy_mirror = _trigger_rules_to_legacy_fields(trigger_rules_v1)
        group_mode = _norm_mode(legacy_mirror.get("group_mode"))
        trigger_settings = legacy_mirror.get("trigger_settings") if isinstance(legacy_mirror.get("trigger_settings"), dict) else {}

        group_name = _safe_str(row.get("group_name") or row.get("groupName") or prev.get("group_name"), group_id)
        group_intro = _safe_str(row.get("group_intro") or row.get("groupIntro") or prev.get("group_intro"))
        group_topic = _safe_str(row.get("group_topic") or row.get("groupTopic") or prev.get("group_topic"))
        group_memory_enabled = _safe_bool(row.get("group_memory_enabled"), _safe_bool(prev.get("group_memory_enabled"), True))
        raw_group_memory_path = _safe_str(row.get("group_memory_path") or row.get("groupMemoryPath") or prev.get("group_memory_path"))
        group_memory_path = os.path.abspath(raw_group_memory_path) if raw_group_memory_path else self._group_memory_default_path(group_id)
        os.makedirs(group_memory_path, exist_ok=True)

        record = {
            "group_id": group_id,
            "group_name": group_name,
            "group_intro": group_intro,
            "group_topic": group_topic,
            "group_mode": group_mode,
            "default_agent_id": default_agent_id,
            "members": members,
            "allowed_agent_ids": allowed_agent_ids,
            "trigger_rules_v1": trigger_rules_v1,
            "trigger_rules_v1_explicit": bool(explicit_v1_flag),
            "trigger_keywords": _norm_list(legacy_mirror.get("trigger_keywords"), max_items=60, max_len=24),
            "cooldown_seconds": _safe_int(legacy_mirror.get("cooldown_seconds"), 8, min_v=0, max_v=7200),
            "anti_conflict_enabled": _safe_bool(legacy_mirror.get("anti_conflict_enabled"), True),
            "max_reply_length": _safe_int(row.get("max_reply_length"), _safe_int(prev.get("max_reply_length"), 260), min_v=60, max_v=1600),
            "context_turn_n": _safe_int(row.get("context_turn_n"), _safe_int(prev.get("context_turn_n"), 3), min_v=1, max_v=20),
            "group_memory_enabled": group_memory_enabled,
            "group_memory_path": group_memory_path,
            "allow_group_rag": _safe_bool(row.get("allow_group_rag"), _safe_bool(prev.get("allow_group_rag"), True)),
            "allow_cross_domain_analysis": _safe_bool(
                row.get("allow_cross_domain_analysis"),
                _safe_bool(prev.get("allow_cross_domain_analysis"), True),
            ),
            "allow_proactive_reply": _safe_bool(legacy_mirror.get("allow_proactive_reply"), False),
            "allow_followup_short_reply": _safe_bool(legacy_mirror.get("allow_followup_short_reply"), False),
            "allow_followup_multi_agent": _safe_bool(
                row.get("allow_followup_multi_agent"),
                _safe_bool(prev.get("allow_followup_multi_agent"), False),
            ),
            "followup_max_agents": _safe_int(
                row.get("followup_max_agents"),
                _safe_int(prev.get("followup_max_agents"), 1),
                min_v=1,
                max_v=4,
            ),
            "followup_window_seconds": _safe_int(
                legacy_mirror.get("followup_window_seconds"),
                20,
                min_v=3,
                max_v=240,
            ),
            "allow_followup_attack": _safe_bool(
                row.get("allow_followup_attack"),
                _safe_bool(prev.get("allow_followup_attack"), False),
            ),
            "followup_max_reply_length": _safe_int(
                row.get("followup_max_reply_length"),
                _safe_int(prev.get("followup_max_reply_length"), 0),
                min_v=0,
                max_v=None,
            ),
            "response_mode": _norm_reply_mode(row.get("response_mode") or prev.get("response_mode")),
            "trigger_settings": trigger_settings,
            "created_by": _safe_str(row.get("created_by") or prev.get("created_by")),
            "created_at": _safe_int(row.get("created_at"), _safe_int(prev.get("created_at"), int(time.time())), min_v=1),
            "updated_at": int(time.time()),
        }
        return record

    def _ensure_actor_member(self, group: Dict[str, Any], actor_user_id: str, actor_role: str = "user") -> Dict[str, Any]:
        gid = _safe_str(group.get("group_id"))
        if not gid:
            return group
        uid = _safe_str(actor_user_id)
        role = _safe_str(actor_role, "user").lower()
        if not uid:
            return group
        members = list(group.get("members") or [])
        exists = None
        for idx, member in enumerate(members):
            if _safe_str(member.get("member_id")).casefold() == uid.casefold():
                exists = idx
                break
        if exists is None:
            members.append(
                {
                    "member_id": uid,
                    "member_name": uid,
                    "member_type": "admin" if role == "admin" else "user",
                    "is_admin": role == "admin",
                    "is_default_agent": False,
                    "muted": False,
                    "speak_enabled": True,
                    "visible": True,
                    "trigger_keywords": [],
                    "updated_at": int(time.time()),
                }
            )
        else:
            row = dict(members[exists] or {})
            if role == "admin":
                row["member_type"] = "admin"
                row["is_admin"] = True
            row["updated_at"] = int(time.time())
            members[exists] = row
        group["members"] = members
        if not _safe_str(group.get("created_by")):
            group["created_by"] = uid
        return group

    def _load_state(self) -> Dict[str, Any]:
        if not os.path.exists(self.store_path):
            state = self._default_state()
            self._write_state(state)
            return state
        try:
            with open(self.store_path, "r", encoding="utf-8") as f:
                raw = json.load(f)
        except Exception:
            raw = self._default_state()
        groups = []
        lounge_rules = {}
        if isinstance(raw, dict):
            lounge_obj = raw.get("lounge_trigger_rules_v1")
            if isinstance(lounge_obj, dict):
                lounge_rules = _normalize_trigger_rules_v1_payload(lounge_obj)
        for item in list(raw.get("groups") if isinstance(raw, dict) else []):
            normalized = self._normalize_group(item)
            if _safe_bool(normalized.get("trigger_rules_v1_explicit"), False):
                groups.append(normalized)
                continue
            patch = _resolve_trigger_rules_v1({}, normalized, lounge_rules=lounge_rules)
            normalized["trigger_rules_v1"] = patch
            legacy = _trigger_rules_to_legacy_fields(patch)
            normalized["group_mode"] = _norm_mode(legacy.get("group_mode"))
            normalized["trigger_settings"] = dict(legacy.get("trigger_settings") or {})
            normalized["trigger_keywords"] = _norm_list(legacy.get("trigger_keywords"), max_items=60, max_len=24)
            normalized["allow_proactive_reply"] = _safe_bool(legacy.get("allow_proactive_reply"), False)
            normalized["cooldown_seconds"] = _safe_int(legacy.get("cooldown_seconds"), 8, min_v=0, max_v=7200)
            normalized["anti_conflict_enabled"] = _safe_bool(legacy.get("anti_conflict_enabled"), True)
            normalized["allow_followup_short_reply"] = _safe_bool(legacy.get("allow_followup_short_reply"), False)
            normalized["followup_window_seconds"] = _safe_int(legacy.get("followup_window_seconds"), 20, min_v=3, max_v=240)
            groups.append(normalized)
        state = {
            "version": 1,
            "updated_at": int(time.time()),
            "groups": groups,
        }
        self._write_state(state)
        return state

    def _write_state(self, state: Dict[str, Any]) -> None:
        payload = {
            "version": 1,
            "updated_at": int(time.time()),
            "groups": list(state.get("groups") or []),
        }
        tmp = self.store_path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False, indent=2)
        os.replace(tmp, self.store_path)

    def _save_locked(self) -> None:
        self._state["updated_at"] = int(time.time())
        self._write_state(self._state)

    def _find_group_index_locked(self, group_id: str) -> int:
        gid = _norm_group_id(group_id)
        rows = list(self._state.get("groups") or [])
        for idx, row in enumerate(rows):
            if _safe_str((row or {}).get("group_id")).casefold() == gid.casefold():
                return idx
        return -1

    def list_groups(self, user_id: str = "", role: str = "user") -> List[Dict[str, Any]]:
        uid = _safe_str(user_id)
        is_admin = _safe_str(role).lower() == "admin"
        with self._lock:
            rows = []
            for row in list(self._state.get("groups") or []):
                if is_admin:
                    rows.append(_deepcopy(row))
                    continue
                if not uid:
                    continue
                created_by = _safe_str((row or {}).get("created_by"))
                if created_by and created_by.casefold() == uid.casefold():
                    rows.append(_deepcopy(row))
                    continue
                members = list((row or {}).get("members") or [])
                if any(_safe_str((m or {}).get("member_id")).casefold() == uid.casefold() for m in members):
                    rows.append(_deepcopy(row))
            rows.sort(key=lambda item: _safe_int(item.get("updated_at"), 0), reverse=True)
            return rows

    def get_group(self, group_id: str) -> Optional[Dict[str, Any]]:
        gid = _norm_group_id(group_id)
        with self._lock:
            idx = self._find_group_index_locked(gid)
            if idx < 0:
                return None
            return _deepcopy((self._state.get("groups") or [])[idx])

    def ensure_group(
        self,
        group_id: str,
        default_agent_id: str = "",
        actor_user_id: str = "",
        actor_role: str = "user",
        fallback_name: str = "",
    ) -> Dict[str, Any]:
        gid = _norm_group_id(group_id)
        with self._lock:
            idx = self._find_group_index_locked(gid)
            if idx >= 0:
                row = _deepcopy((self._state.get("groups") or [])[idx])
                if default_agent_id and (not _safe_str(row.get("default_agent_id"))):
                    row["default_agent_id"] = _safe_str(default_agent_id)
                    row = self._normalize_group(row, keep_created=row)
                    (self._state.get("groups") or [])[idx] = row
                    self._save_locked()
                return _deepcopy(row)
            base = self._normalize_group(
                {
                    "group_id": gid,
                    "group_name": _safe_str(fallback_name, gid),
                    "default_agent_id": _safe_str(default_agent_id),
                    "members": [],
                }
            )
            base = self._ensure_actor_member(base, actor_user_id=actor_user_id, actor_role=actor_role)
            groups = list(self._state.get("groups") or [])
            groups.append(base)
            self._state["groups"] = groups
            self._save_locked()
            return _deepcopy(base)

    def upsert_group(self, payload: Dict[str, Any], actor_user_id: str = "", actor_role: str = "user") -> Dict[str, Any]:
        row = payload if isinstance(payload, dict) else {}
        gid = _norm_group_id(row.get("group_id"))
        with self._lock:
            idx = self._find_group_index_locked(gid)
            prev = None
            if idx >= 0:
                prev = _deepcopy((self._state.get("groups") or [])[idx])
            merged = self._normalize_group(row, keep_created=prev)
            merged = self._ensure_actor_member(merged, actor_user_id=actor_user_id, actor_role=actor_role)
            groups = list(self._state.get("groups") or [])
            if idx >= 0:
                groups[idx] = merged
            else:
                groups.append(merged)
            self._state["groups"] = groups
            self._save_locked()
            return _deepcopy(merged)

    def patch_group(self, group_id: str, patch: Dict[str, Any], actor_user_id: str = "", actor_role: str = "user") -> Optional[Dict[str, Any]]:
        gid = _norm_group_id(group_id)
        diff = patch if isinstance(patch, dict) else {}
        with self._lock:
            idx = self._find_group_index_locked(gid)
            if idx < 0:
                return None
            current = _deepcopy((self._state.get("groups") or [])[idx])
            merged = self._normalize_group(diff, keep_created=current)
            merged = self._ensure_actor_member(merged, actor_user_id=actor_user_id, actor_role=actor_role)
            (self._state.get("groups") or [])[idx] = merged
            self._save_locked()
            return _deepcopy(merged)

    def rename_group(self, group_id: str, new_name: str, actor_user_id: str = "", actor_role: str = "user") -> Optional[Dict[str, Any]]:
        clean = _safe_str(new_name)
        if not clean:
            return None
        return self.patch_group(group_id, {"group_name": clean}, actor_user_id=actor_user_id, actor_role=actor_role)

    def delete_group(self, group_id: str) -> bool:
        gid = _norm_group_id(group_id)
        with self._lock:
            idx = self._find_group_index_locked(gid)
            if idx < 0:
                return False
            groups = list(self._state.get("groups") or [])
            groups.pop(idx)
            self._state["groups"] = groups
            self._save_locked()
            return True

    def add_member(self, group_id: str, member: Dict[str, Any], actor_user_id: str = "", actor_role: str = "user") -> Optional[Dict[str, Any]]:
        gid = _norm_group_id(group_id)
        with self._lock:
            idx = self._find_group_index_locked(gid)
            if idx < 0:
                return None
            row = _deepcopy((self._state.get("groups") or [])[idx])
            normalized = self._normalize_member(member)
            members = list(row.get("members") or [])
            exists = False
            for m_idx, old in enumerate(members):
                if _safe_str((old or {}).get("member_id")).casefold() == _safe_str(normalized.get("member_id")).casefold():
                    members[m_idx] = normalized
                    exists = True
                    break
            if not exists:
                members.append(normalized)
            row["members"] = members
            merged = self._normalize_group(row, keep_created=row)
            merged = self._ensure_actor_member(merged, actor_user_id=actor_user_id, actor_role=actor_role)
            (self._state.get("groups") or [])[idx] = merged
            self._save_locked()
            return _deepcopy(merged)

    def remove_member(self, group_id: str, member_id: str, actor_user_id: str = "", actor_role: str = "user") -> Optional[Dict[str, Any]]:
        gid = _norm_group_id(group_id)
        mid = _safe_str(member_id)
        if not mid:
            return None
        with self._lock:
            idx = self._find_group_index_locked(gid)
            if idx < 0:
                return None
            row = _deepcopy((self._state.get("groups") or [])[idx])
            members = [
                m for m in list(row.get("members") or [])
                if _safe_str((m or {}).get("member_id")).casefold() != mid.casefold()
            ]
            row["members"] = members
            merged = self._normalize_group(row, keep_created=row)
            merged = self._ensure_actor_member(merged, actor_user_id=actor_user_id, actor_role=actor_role)
            (self._state.get("groups") or [])[idx] = merged
            self._save_locked()
            return _deepcopy(merged)

    def patch_member(
        self,
        group_id: str,
        member_id: str,
        patch: Dict[str, Any],
        actor_user_id: str = "",
        actor_role: str = "user",
    ) -> Optional[Dict[str, Any]]:
        gid = _norm_group_id(group_id)
        mid = _safe_str(member_id)
        diff = patch if isinstance(patch, dict) else {}
        if not mid:
            return None
        with self._lock:
            idx = self._find_group_index_locked(gid)
            if idx < 0:
                return None
            row = _deepcopy((self._state.get("groups") or [])[idx])
            members = list(row.get("members") or [])
            found = False
            for m_idx, member in enumerate(members):
                if _safe_str((member or {}).get("member_id")).casefold() != mid.casefold():
                    continue
                members[m_idx] = self._normalize_member({**dict(member or {}), **diff})
                found = True
                break
            if not found:
                return None
            row["members"] = members
            merged = self._normalize_group(row, keep_created=row)
            merged = self._ensure_actor_member(merged, actor_user_id=actor_user_id, actor_role=actor_role)
            (self._state.get("groups") or [])[idx] = merged
            self._save_locked()
            return _deepcopy(merged)

    def set_default_agent(self, group_id: str, agent_id: str, actor_user_id: str = "", actor_role: str = "user") -> Optional[Dict[str, Any]]:
        aid = _safe_str(agent_id)
        if not aid:
            return None
        return self.patch_group(
            group_id,
            {"default_agent_id": aid},
            actor_user_id=actor_user_id,
            actor_role=actor_role,
        )

    def list_group_ids(self) -> List[str]:
        with self._lock:
            return [_safe_str((row or {}).get("group_id")) for row in list(self._state.get("groups") or [])]

    def user_can_manage_group(self, group: Dict[str, Any], user_id: str, role: str = "user") -> bool:
        uid = _safe_str(user_id)
        if _safe_str(role).lower() == "admin":
            return True
        if not uid:
            return False
        created_by = _safe_str((group or {}).get("created_by"))
        if created_by and created_by.casefold() == uid.casefold():
            return True
        for member in list((group or {}).get("members") or []):
            if _safe_str((member or {}).get("member_id")).casefold() != uid.casefold():
                continue
            if _safe_bool((member or {}).get("is_admin"), _norm_member_type((member or {}).get("member_type")) == "admin"):
                return True
        return False

    def split_public_payload(self, group: Dict[str, Any]) -> Tuple[Dict[str, Any], Dict[str, Any]]:
        row = _deepcopy(group if isinstance(group, dict) else {})
        summary = {
            "group_id": _safe_str(row.get("group_id")),
            "group_name": _safe_str(row.get("group_name")),
            "group_intro": _safe_str(row.get("group_intro")),
            "group_topic": _safe_str(row.get("group_topic")),
            "default_agent_id": _safe_str(row.get("default_agent_id")),
            "group_mode": _safe_str(row.get("group_mode"), "semi_active"),
            "trigger_rules_v1": _deepcopy(row.get("trigger_rules_v1") if isinstance(row.get("trigger_rules_v1"), dict) else {}),
            "trigger_rules_v1_explicit": _safe_bool(row.get("trigger_rules_v1_explicit"), False),
            "updated_at": _safe_int(row.get("updated_at"), 0),
            "allow_proactive_reply": _safe_bool(row.get("allow_proactive_reply"), False),
            "allow_followup_short_reply": _safe_bool(row.get("allow_followup_short_reply"), False),
            "allow_followup_multi_agent": _safe_bool(row.get("allow_followup_multi_agent"), False),
            "group_memory_enabled": _safe_bool(row.get("group_memory_enabled"), True),
            "group_memory_path": _safe_str(row.get("group_memory_path")),
            "member_count": len(list(row.get("members") or [])),
        }
        return summary, row
