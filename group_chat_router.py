import hashlib
import re
import threading
import time
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


def _norm_text(value: Any) -> str:
    return re.sub(r"\s+", " ", _safe_str(value)).strip()


def _norm_text_key(value: Any) -> str:
    return _norm_text(value).casefold()


def _norm_list(values: Any, max_items: int = 64) -> List[str]:
    src = values
    if isinstance(src, str):
        src = [x for x in re.split(r"[,\n，;；\s]+", src) if _safe_str(x)]
    out: List[str] = []
    seen = set()
    for raw in list(src or []):
        text = _safe_str(raw)
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


def _has_nested_key(row: Any, keys: List[str]) -> bool:
    node = row
    for key in keys:
        if not isinstance(node, dict) or key not in node:
            return False
        node = node.get(key)
    return True


def _trigger_rules_default(seed: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    src = seed if isinstance(seed, dict) else {}
    mode = _norm_mode(src.get("mode"))
    keyword_enabled = _safe_bool(src.get("keyword_enabled"), True)
    proactive_enabled = _safe_bool(src.get("proactive_enabled"), False)
    followup_enabled = _safe_bool(src.get("followup_enabled"), False)
    if mode == "strict":
        keyword_enabled = False
        proactive_enabled = False
    elif mode == "semi_active":
        proactive_enabled = False
    elif mode == "silent":
        keyword_enabled = False
        proactive_enabled = False
        followup_enabled = False

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
            "enabled": bool(keyword_enabled),
            "terms": _norm_list(src.get("keyword_terms"), max_items=60),
        },
        "proactive": {
            "enabled": bool(proactive_enabled),
        },
        "guard": {
            "cooldown_seconds": _safe_int(src.get("cooldown_seconds"), 8, min_v=0, max_v=7200),
            "anti_conflict_enabled": _safe_bool(src.get("anti_conflict_enabled"), True),
        },
        "followup": {
            "enabled": bool(followup_enabled),
            "window_seconds": _safe_int(src.get("followup_window_seconds"), 20, min_v=3, max_v=240),
        },
    }


def _normalize_trigger_rules_v1(raw: Any, fallback: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
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

    mode = _norm_mode(src.get("mode") if ("mode" in src) else base.get("mode"))
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

    return {
        "version": 1,
        "mode": mode,
        "explicit": {
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
        },
        "keyword": {
            "enabled": bool(keyword_enabled),
            "terms": _norm_list(keyword_src.get("terms"), max_items=60)
            if ("terms" in keyword_src)
            else _norm_list((base.get("keyword") or {}).get("terms"), max_items=60),
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


def _legacy_trigger_seed(cfg: Dict[str, Any]) -> Dict[str, Any]:
    triggers = cfg.get("trigger_settings") if isinstance(cfg.get("trigger_settings"), dict) else {}
    return {
        "mode": cfg.get("group_mode"),
        "at_reply": triggers.get("at_reply"),
        "name_reply": triggers.get("name_reply"),
        "nickname_reply": triggers.get("nickname_reply"),
        "quote_reply": triggers.get("quote_reply"),
        "admin_force_wakeup": triggers.get("admin_force_wakeup"),
        "keyword_enabled": triggers.get("keyword_trigger"),
        "keyword_terms": cfg.get("trigger_keywords"),
        "proactive_enabled": cfg.get("allow_proactive_reply"),
        "cooldown_seconds": cfg.get("cooldown_seconds"),
        "anti_conflict_enabled": cfg.get("anti_conflict_enabled"),
        "followup_enabled": cfg.get("allow_followup_short_reply"),
        "followup_window_seconds": cfg.get("followup_window_seconds"),
    }


def _get_nested_value(row: Any, keys: List[str]) -> Any:
    node = row
    for key in keys:
        if not isinstance(node, dict):
            return None
        node = node.get(key)
    return node


def _resolved_trigger_rules_v1(cfg: Dict[str, Any], meta: Dict[str, Any]) -> Dict[str, Any]:
    group_cfg = cfg if isinstance(cfg, dict) else {}
    route_meta = meta if isinstance(meta, dict) else {}

    legacy_fallback = _normalize_trigger_rules_v1({}, fallback=_trigger_rules_default(_legacy_trigger_seed(group_cfg)))

    lounge_raw = {}
    for candidate in [
        group_cfg.get("lounge_trigger_rules_v1"),
        route_meta.get("lounge_trigger_rules_v1"),
    ]:
        if isinstance(candidate, dict):
            lounge_raw = dict(candidate)
            break
    lounge_norm = _normalize_trigger_rules_v1(lounge_raw, fallback=legacy_fallback)

    group_v1 = group_cfg.get("trigger_rules_v1") if isinstance(group_cfg.get("trigger_rules_v1"), dict) else {}
    group_v1_norm = _normalize_trigger_rules_v1(group_v1, fallback=legacy_fallback)
    explicit_group = _safe_bool(group_cfg.get("trigger_rules_v1_explicit"), False)

    resolved = _normalize_trigger_rules_v1({}, fallback=legacy_fallback)
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

    source_map: Dict[str, str] = {}
    for path in fields:
        chosen_src = legacy_fallback
        src_label = "legacy"
        if explicit_group and _has_nested_key(group_v1, path):
            chosen_src = group_v1_norm
            src_label = "group_v1"
        elif _has_nested_key(lounge_raw, path):
            chosen_src = lounge_norm
            src_label = "lounge"

        source_map[".".join(path)] = src_label

        dst = resolved
        for token in path[:-1]:
            dst = dst.setdefault(token, {})
        leaf = path[-1]
        val = _get_nested_value(chosen_src, path)
        if path == ["keyword", "terms"]:
            dst[leaf] = _norm_list(val, max_items=60)
        elif path == ["mode"]:
            dst[leaf] = _norm_mode(val)
        elif path in (["guard", "cooldown_seconds"], ["followup", "window_seconds"]):
            if path == ["guard", "cooldown_seconds"]:
                dst[leaf] = _safe_int(val, 8, min_v=0, max_v=7200)
            else:
                dst[leaf] = _safe_int(val, 20, min_v=3, max_v=240)
        else:
            dst[leaf] = _safe_bool(val, bool(_get_nested_value(legacy_fallback, path)))

    out = _normalize_trigger_rules_v1(resolved, fallback=legacy_fallback)
    out["_source"] = {
        "field_sources": source_map,
        "explicit_group": bool(explicit_group),
        "has_lounge": bool(lounge_raw),
    }
    return out


def _extract_mentions(text: str) -> List[str]:
    cleaned = str(text or "")
    out = []
    for token in re.findall(r"[@＠]([^\s,，。:：；;]{1,24})", cleaned):
        name = _safe_str(token)
        if name:
            out.append(name)
    return _norm_list(out, max_items=20)


def _contains_keyword(text: str, keywords: List[str]) -> bool:
    key_text = _norm_text_key(text)
    if not key_text:
        return False
    for raw in list(keywords or []):
        token = _norm_text_key(raw)
        if token and token in key_text:
            return True
    return False


def _looks_like_agent_direct_followup(text: Any) -> bool:
    raw = _norm_text(text)
    if not raw:
        return False
    low = raw.casefold()
    has_second_person = bool(
        re.search(r"(你|您|你们|您们)", raw)
        or re.search(r"\b(you|your|yours|u)\b", low)
    )
    if not has_second_person:
        return False
    if re.search(r"[?？]|(吗|嘛|么|呢|吧|是不是|是否|为什么|为何|怎么|能否|可否|可以|能不能)", raw):
        return True
    if re.search(r"(请|帮|试试|确认|解释|看看|继续|接着|再说|再试)", raw):
        return True
    return len(raw) <= 28


def _contains_second_person(text: Any) -> bool:
    raw = _norm_text(text)
    if not raw:
        return False
    low = raw.casefold()
    return bool(
        re.search(r"(你|您|你们|您们)", raw)
        or re.search(r"\b(you|your|yours|u)\b", low)
    )


def _looks_like_backtrace_agent_reference(text: Any) -> bool:
    raw = _norm_text(text)
    if not raw:
        return False
    return bool(
        re.search(r"(刚才|上一句|上句|你提到的|你刚才说|你之前说)", raw)
        or re.search(r"(刚刚|上条|前面).{0,6}(你|您)", raw)
    )


def _relay_chain_from_meta(meta: Dict[str, Any], max_items: int = 12) -> List[str]:
    m = meta if isinstance(meta, dict) else {}
    chain = _norm_list(m.get("relay_chain"), max_items=max_items)
    return [x for x in chain if _safe_str(x)]


def _relay_chain_append(chain: List[str], agent_id: str, max_items: int = 12) -> List[str]:
    out = _norm_list(chain or [], max_items=max_items * 2)
    aid = _safe_str(agent_id)
    if not aid:
        return out[-max_items:]
    if (not out) or out[-1].casefold() != aid.casefold():
        out.append(aid)
    if len(out) > max_items:
        out = out[-max_items:]
    return out


def _norm_member_type(value: Any) -> str:
    token = _safe_str(value).lower()
    if token == "agent":
        return "agent"
    if token == "admin":
        return "admin"
    return "user"


def _strip_vocative_prefix(text: str) -> str:
    raw = _norm_text(text)
    if not raw:
        return ""
    trimmed = re.sub(r"^[@＠]\s*[^\s,，。:：；;]+\s*[,，:：]?\s*", "", raw)
    trimmed = re.sub(r"^[^\s,，。:：；;]{1,16}\s*[,，:：]\s*", "", trimmed)
    trimmed = re.sub(r"^(收到|好的|明白|了解|嗯|哈|好)\s*[,，。!！?？]?\s*", "", trimmed)
    return _norm_text(trimmed)


def _token_set(text: str) -> set:
    raw = _norm_text(text)
    if not raw:
        return set()
    parts = [x for x in re.split(r"[\s,，。!！?？:：;；、/\\|()\[\]{}<>《》\"'“”‘’]+", raw.casefold()) if x]
    if parts:
        return set(parts)
    return set(raw.casefold())


def _char_ngram_set(text: str, n: int = 2) -> set:
    raw = re.sub(r"\s+", "", _norm_text(text).casefold())
    if not raw:
        return set()
    if len(raw) <= n:
        return {raw}
    return {raw[i:i + n] for i in range(0, len(raw) - n + 1)}


def _jaccard(a: set, b: set) -> float:
    if not a or not b:
        return 0.0
    inter = len(a & b)
    union = len(a | b)
    if union <= 0:
        return 0.0
    return float(inter) / float(union)


def _text_similarity_score(a_text: str, b_text: str) -> float:
    a = _strip_vocative_prefix(a_text)
    b = _strip_vocative_prefix(b_text)
    if (not a) or (not b):
        return 0.0
    if a.casefold() == b.casefold():
        return 1.0
    token_score = _jaccard(_token_set(a), _token_set(b))
    gram_score = _jaccard(_char_ngram_set(a, n=2), _char_ngram_set(b, n=2))
    return max(token_score, gram_score)


def _relay_text_is_repetitive(
    current_text: str,
    runtime: Dict[str, Any],
    sender_agent_id: str,
    selected_agent_id: str,
) -> Tuple[bool, float, str]:
    text_now = _norm_text(current_text)
    if not text_now:
        return False, 0.0, ""
    history = list(runtime.get("recent_agent_replies") or [])
    if not history:
        return False, 0.0, ""
    sender_key = _safe_str(sender_agent_id).casefold()
    selected_key = _safe_str(selected_agent_id).casefold()
    best = 0.0
    best_agent = ""
    checked = 0
    # 倒序看最近 4 条，跳过“当前消息本身”的同 hash，避免恒等误判。
    current_hash = hashlib.sha1(text_now.encode("utf-8")).hexdigest()[:16]
    for row in reversed(history):
        item = row if isinstance(row, dict) else {}
        h = _safe_str(item.get("reply_hash"))
        if h and h == current_hash:
            continue
        ref_text = _safe_str(item.get("reply_text"))
        if not ref_text:
            continue
        score = _text_similarity_score(text_now, ref_text)
        if score > best:
            best = score
            best_agent = _safe_str(item.get("agent_id"))
        checked += 1
        if checked >= 4:
            break
    if best < 0.88:
        return False, best, best_agent
    # 若高度相似且只是在 A/B 间回抛，优先终止 relay。
    if selected_key and best_agent and best_agent.casefold() == selected_key:
        return True, best, best_agent
    if sender_key and best_agent and best_agent.casefold() != sender_key:
        return True, best, best_agent
    return True, best, best_agent


def _agent_alias_tokens(agent_row: Dict[str, Any]) -> List[str]:
    row = agent_row if isinstance(agent_row, dict) else {}
    raw_parts = [
        _safe_str(row.get("agent_id")),
        _safe_str(row.get("display_name")),
        _safe_str(row.get("agent_title")),
        _safe_str(row.get("agent_name")),
    ]
    out: List[str] = []
    seen = set()
    generic_stop = {
        "agent",
        "assistant",
        "bot",
        "ai",
        "chatgpt",
        "gpt",
        "智能体",
        "助手",
    }
    for part in raw_parts:
        if not part:
            continue
        pieces = re.split(r"[\s,，;；/\\|:_\-]+", part)
        for token in [part] + pieces:
            text = _safe_str(token)
            if len(text) < 2 and (not re.search(r"[\u4e00-\u9fff]", text)):
                continue
            key = text.casefold()
            if key in generic_stop:
                continue
            if key in seen:
                continue
            seen.add(key)
            out.append(text)
    return out


def _agent_nickname_tokens(agent_row: Dict[str, Any]) -> List[str]:
    row = agent_row if isinstance(agent_row, dict) else {}
    raw_parts = [
        _safe_str(row.get("agent_nickname")),
        _safe_str(row.get("nickname")),
    ]
    out: List[str] = []
    seen = set()
    for part in raw_parts:
        if not part:
            continue
        pieces = re.split(r"[\s,，;；/\\|:_\-]+", part)
        for token in [part] + pieces:
            text = _safe_str(token)
            if len(text) < 2 and (not re.search(r"[\u4e00-\u9fff]", text)):
                continue
            key = text.casefold()
            if key in seen:
                continue
            seen.add(key)
            out.append(text)
    return out


def _contains_alias_in_text(text: str, alias: str) -> bool:
    low_text = str(text or "").casefold()
    alias_key = str(alias or "").casefold().strip()
    if (not low_text) or (not alias_key):
        return False
    if len(alias_key) <= 1:
        tail = r"($|[\s,，。！？!?:：；;、\(\)\[\]【】<>《》\"'“”‘’])"
        pattern1 = rf"(^|[\s,，。！？!?:：；;、\(\)\[\]【】<>《》\"'“”‘’]){re.escape(alias_key)}{tail}"
        if re.search(pattern1, low_text):
            return True
        # “喊某个Agent/叫某个Agent/找某个Agent”这类口语唤醒
        pattern2 = rf"(喊|叫|找|问|请|让)(的)?\s*{re.escape(alias_key)}(?=(来|回复|回答|回话|说|讲|聊|帮|处理|一下|一声|出来|在|呢|吗|呀|啊|吧|$|[\s,，。！？!?:：；;、]))"
        if re.search(pattern2, low_text):
            return True
        # “某个Agent来说句话 / 让某个Agent来 / 某个Agent回复一下”这类自然口语
        pattern3 = rf"(^|[\s,，。！？!?:：；;、\(\)\[\]【】<>《》\"'“”‘’]){re.escape(alias_key)}(?=(来|回复|回答|回话|说|讲|聊|帮|处理|一下|一声|出来|在|呢|吗|呀|啊|吧|$|[\s,，。！？!?:：；;、]))"
        if re.search(pattern3, low_text):
            return True
        # “不是某个Agent来回复 / 该某个Agent回 / 由某个Agent来”这类句中指派
        pattern4 = rf"(不是|该|由)\s*{re.escape(alias_key)}(?=(来|回复|回答|回话|说|讲|聊|帮|处理|一下|一声|出来|在|呢|吗|呀|啊|吧|$|[\s,，。！？!?:：；;、]))"
        if re.search(pattern4, low_text):
            return True
        # 句首直呼：“某个Agent在吗/某个Agent你好”
        pattern5 = rf"^\s*{re.escape(alias_key)}(?=(在|好|来|回|说|讲|聊|帮|呢|吗|呀|啊|$|[\s,，。！？!?:：；;、]))"
        return re.search(pattern5, low_text) is not None
    if re.fullmatch(r"[0-9a-z_.-]+", alias_key):
        pattern = rf"(?<![0-9a-z_.-]){re.escape(alias_key)}(?![0-9a-z_.-])"
        return re.search(pattern, low_text) is not None
    return alias_key in low_text


def _find_alias_first_pos(text: str, alias: str) -> int:
    low_text = str(text or "").casefold()
    alias_key = str(alias or "").casefold().strip()
    if (not low_text) or (not alias_key):
        return -1
    if len(alias_key) <= 1:
        sep = r"[\s,，。！？!?:：；;、\(\)\[\]【】<>《》\"'“”‘’]"
        tail = r"($|[\s,，。！？!?:：；;、\(\)\[\]【】<>《》\"'“”‘’]|来|回复|回答|回话|说|讲|聊|帮|处理|一下|一声|出来|在|呢|吗|呀|啊|吧)"
        patterns = [
            rf"(^|{sep})({re.escape(alias_key)})(?={tail})",
            rf"(喊|叫|找|问|请|让)(的)?\s*({re.escape(alias_key)})(?={tail})",
        ]
        best = -1
        for idx, pattern in enumerate(patterns):
            m = re.search(pattern, low_text)
            if not m:
                continue
            pos = m.start(2 if idx == 0 else 3)
            if best < 0 or pos < best:
                best = pos
        return best
    if re.fullmatch(r"[0-9a-z_.-]+", alias_key):
        m = re.search(rf"(?<![0-9a-z_.-]){re.escape(alias_key)}(?![0-9a-z_.-])", low_text)
        return m.start() if m else -1
    return low_text.find(alias_key)


def _ordered_agent_mentions(
    text: str,
    allowed_agents: List[str],
    agent_rows: List[Dict[str, Any]],
    group_cfg: Optional[Dict[str, Any]] = None,
) -> List[Dict[str, Any]]:
    if not text:
        return []
    rows = list(agent_rows or [])
    row_map = {
        _safe_str((row or {}).get("agent_id")).casefold(): dict(row or {})
        for row in rows
        if _safe_str((row or {}).get("agent_id"))
    }
    cfg = group_cfg if isinstance(group_cfg, dict) else {}
    members = list(cfg.get("members") or [])
    member_map: Dict[str, Dict[str, Any]] = {}
    for item in members:
        row = item if isinstance(item, dict) else {}
        if _safe_str(row.get("member_type")).lower() != "agent":
            continue
        mid = _safe_str(row.get("member_id"))
        if not mid:
            continue
        member_map[mid.casefold()] = row
    out: List[Dict[str, Any]] = []
    for aid in list(allowed_agents or []):
        agent_id = _safe_str(aid)
        if not agent_id:
            continue
        row = dict(row_map.get(agent_id.casefold()) or {"agent_id": agent_id})
        aliases = _agent_alias_tokens(row)
        member_row = dict(member_map.get(agent_id.casefold()) or {})
        member_name = _safe_str(member_row.get("member_name") or member_row.get("name"))
        if member_name:
            aliases.extend(
                _agent_alias_tokens(
                    {
                        "agent_id": agent_id,
                        "display_name": member_name,
                        "agent_title": member_name,
                        "agent_name": member_name,
                    }
                )
            )
        aliases = _norm_list(aliases, max_items=32)
        best_pos = -1
        best_alias = ""
        for alias in aliases:
            pos = _find_alias_first_pos(text, alias)
            if pos < 0:
                continue
            if best_pos < 0 or pos < best_pos or (pos == best_pos and len(alias) > len(best_alias)):
                best_pos = pos
                best_alias = alias
        if best_pos < 0:
            continue
        out.append(
            {
                "agent_id": agent_id,
                "position": int(best_pos),
                "alias": _safe_str(best_alias),
            }
        )
    out.sort(key=lambda row: (int(row.get("position", 10**9)), -len(_safe_str(row.get("alias")))))
    return out


_RUNTIME_LOCK = threading.RLock()
_RUNTIME_STATE: Dict[str, Dict[str, Any]] = {}


def _runtime_group_state(group_id: str) -> Dict[str, Any]:
    gid = _safe_str(group_id, "unknown_group")
    with _RUNTIME_LOCK:
        row = _RUNTIME_STATE.get(gid)
        if not isinstance(row, dict):
            row = {
                "last_reply_at": 0.0,
                "last_agent_id": "",
                "last_user_hash": "",
                "last_reply_hash": "",
                "last_selected_candidates": [],
                "followup_window_until": 0.0,
                "last_message_at": 0.0,
                "last_message_member_type": "",
                "last_message_user_id": "",
                "last_message_agent_id": "",
                "last_message_text": "",
                "prev_message_member_type": "",
                "prev_message_user_id": "",
                "prev_message_agent_id": "",
                "prev_message_text": "",
                "recent_agent_replies": [],
            }
            _RUNTIME_STATE[gid] = row
        else:
            row.setdefault("last_reply_at", 0.0)
            row.setdefault("last_agent_id", "")
            row.setdefault("last_user_hash", "")
            row.setdefault("last_reply_hash", "")
            row.setdefault("last_selected_candidates", [])
            row.setdefault("followup_window_until", 0.0)
            row.setdefault("last_message_at", 0.0)
            row.setdefault("last_message_member_type", "")
            row.setdefault("last_message_user_id", "")
            row.setdefault("last_message_agent_id", "")
            row.setdefault("last_message_text", "")
            row.setdefault("prev_message_member_type", "")
            row.setdefault("prev_message_user_id", "")
            row.setdefault("prev_message_agent_id", "")
            row.setdefault("prev_message_text", "")
            row.setdefault("recent_agent_replies", [])
        return dict(row)


def register_group_message(
    group_id: str,
    speaker_member_type: str,
    speaker_user_id: str = "",
    speaker_agent_id: str = "",
    message_text: str = "",
) -> None:
    gid = _safe_str(group_id)
    if not gid:
        return
    now_ts = time.time()
    with _RUNTIME_LOCK:
        row = _RUNTIME_STATE.get(gid)
        if not isinstance(row, dict):
            row = _runtime_group_state(gid)
        row = dict(row or {})
        row["prev_message_member_type"] = _norm_member_type(row.get("last_message_member_type"))
        row["prev_message_user_id"] = _safe_str(row.get("last_message_user_id"))
        row["prev_message_agent_id"] = _safe_str(row.get("last_message_agent_id"))
        row["prev_message_text"] = _norm_text(row.get("last_message_text"))
        row["last_message_at"] = now_ts
        row["last_message_member_type"] = _norm_member_type(speaker_member_type)
        row["last_message_user_id"] = _safe_str(speaker_user_id)
        row["last_message_agent_id"] = _safe_str(speaker_agent_id)
        row["last_message_text"] = _norm_text(message_text)
        _RUNTIME_STATE[gid] = row


def register_group_reply(
    group_id: str,
    selected_agent_id: str,
    user_text: str,
    reply_text: str,
    selected_candidates: Optional[List[str]] = None,
    followup_window_seconds: int = 20,
) -> None:
    gid = _safe_str(group_id)
    if not gid:
        return
    now_ts = time.time()
    user_hash = hashlib.sha1(_norm_text(user_text).encode("utf-8")).hexdigest()[:16]
    reply_hash = hashlib.sha1(_norm_text(reply_text).encode("utf-8")).hexdigest()[:16]
    with _RUNTIME_LOCK:
        row = _RUNTIME_STATE.get(gid)
        if not isinstance(row, dict):
            row = {}
        row = dict(row)
        row["last_reply_at"] = now_ts
        row["last_agent_id"] = _safe_str(selected_agent_id)
        row["last_user_hash"] = user_hash
        row["last_reply_hash"] = reply_hash
        row["last_selected_candidates"] = _norm_list(selected_candidates or [], max_items=4)
        row["followup_window_until"] = now_ts + max(0, _safe_int(followup_window_seconds, 20))
        row["prev_message_member_type"] = _norm_member_type(row.get("last_message_member_type"))
        row["prev_message_user_id"] = _safe_str(row.get("last_message_user_id"))
        row["prev_message_agent_id"] = _safe_str(row.get("last_message_agent_id"))
        row["prev_message_text"] = _norm_text(row.get("last_message_text"))
        row["last_message_at"] = now_ts
        row["last_message_member_type"] = "agent"
        row["last_message_user_id"] = _safe_str(selected_agent_id)
        row["last_message_agent_id"] = _safe_str(selected_agent_id)
        row["last_message_text"] = _norm_text(reply_text)
        hist = list(row.get("recent_agent_replies") or [])
        hist.append(
            {
                "ts": int(now_ts),
                "agent_id": _safe_str(selected_agent_id),
                "reply_hash": reply_hash,
                "reply_text": _norm_text(reply_text),
            }
        )
        if len(hist) > 8:
            hist = hist[-8:]
        row["recent_agent_replies"] = hist
        _RUNTIME_STATE[gid] = row


def _resolve_target_user(meta: Dict[str, Any]) -> Tuple[str, str, str]:
    # 优先级：
    # 1. 被回复/被引用的人
    # 2. 被 @ 的人
    # 3. 当前发消息的人
    # 4. 兜底：当前发消息的人
    m = meta if isinstance(meta, dict) else {}
    sender_uid = _safe_str(m.get("sender_user_id") or m.get("user_id"), "anonymous")
    sender_name = _safe_str(m.get("nickname") or m.get("sender_name"), sender_uid)

    reply_uid = _safe_str(m.get("reply_to_user_id") or m.get("quoted_user_id"))
    reply_name = _safe_str(m.get("reply_to_name") or m.get("quoted_user_name"))
    if reply_uid:
        return reply_uid, (reply_name or reply_uid), "reply_or_quote"

    at_uid = _safe_str(m.get("at_user_id"))
    at_name = _safe_str(m.get("at_user_name"))
    if not at_uid:
        mention_users = _norm_list(m.get("mentioned_user_ids"), max_items=10)
        if mention_users:
            at_uid = _safe_str(mention_users[0])
    if at_uid:
        return at_uid, (at_name or at_uid), "@user"

    return sender_uid, sender_name, "sender"


def _allowed_agent_ids(group_cfg: Dict[str, Any], agent_rows: List[Dict[str, Any]]) -> List[str]:
    cfg = group_cfg if isinstance(group_cfg, dict) else {}
    allowed = _norm_list(cfg.get("allowed_agent_ids"), max_items=32)
    members = list(cfg.get("members") or [])
    blocked = set()
    speak_allowed = set()
    for member in members:
        row = member if isinstance(member, dict) else {}
        if _safe_str(row.get("member_type")).lower() != "agent":
            continue
        mid = _safe_str(row.get("member_id"))
        if not mid:
            continue
        if (not _safe_bool(row.get("visible"), True)) or _safe_bool(row.get("muted"), False):
            blocked.add(mid.casefold())
            continue
        if _safe_bool(row.get("speak_enabled"), True):
            speak_allowed.add(mid.casefold())
        else:
            blocked.add(mid.casefold())

    if not allowed:
        for agent in list(agent_rows or []):
            aid = _safe_str((agent or {}).get("agent_id"))
            if aid:
                allowed.append(aid)

    out = []
    seen = set()
    for aid in allowed:
        key = aid.casefold()
        if key in seen:
            continue
        if key in blocked:
            continue
        if speak_allowed and key not in speak_allowed:
            continue
        seen.add(key)
        out.append(aid)
    return out


def decide_group_route(
    message_text: str,
    meta: Optional[Dict[str, Any]],
    group_cfg: Optional[Dict[str, Any]],
    agent_rows: Optional[List[Dict[str, Any]]] = None,
) -> Dict[str, Any]:
    m = dict(meta or {})
    cfg = dict(group_cfg or {})
    text = _norm_text(message_text)
    group_id = _safe_str(cfg.get("group_id") or m.get("group_id"))
    now_ts = time.time()
    runtime = _runtime_group_state(group_id)

    mode = _norm_mode(cfg.get("group_mode"))
    trigger_rules_v1 = _resolved_trigger_rules_v1(cfg, m)
    explicit_rules = trigger_rules_v1.get("explicit") if isinstance(trigger_rules_v1.get("explicit"), dict) else {}
    keyword_rules = trigger_rules_v1.get("keyword") if isinstance(trigger_rules_v1.get("keyword"), dict) else {}
    proactive_rules = trigger_rules_v1.get("proactive") if isinstance(trigger_rules_v1.get("proactive"), dict) else {}
    guard_rules = trigger_rules_v1.get("guard") if isinstance(trigger_rules_v1.get("guard"), dict) else {}
    followup_rules = trigger_rules_v1.get("followup") if isinstance(trigger_rules_v1.get("followup"), dict) else {}
    mode = _norm_mode(trigger_rules_v1.get("mode"))
    cooldown_seconds = _safe_int(guard_rules.get("cooldown_seconds"), _safe_int(cfg.get("cooldown_seconds"), 8), min_v=0, max_v=7200)
    anti_conflict_enabled = _safe_bool(guard_rules.get("anti_conflict_enabled"), _safe_bool(cfg.get("anti_conflict_enabled"), True))
    max_reply_length = _safe_int(cfg.get("max_reply_length"), 260, min_v=60, max_v=1600)
    context_turn_n = _safe_int(cfg.get("context_turn_n"), 10, min_v=1, max_v=20)
    default_agent_id = _safe_str(cfg.get("default_agent_id"))
    group_keywords = _norm_list(keyword_rules.get("terms"), max_items=60)
    force_reply = _safe_bool(m.get("group_force_reply"), False)
    admin_force_wakeup = _safe_bool(m.get("admin_force_wakeup"), False)
    relay_chain_call = _safe_bool(m.get("relay_chain_call"), False)
    relay_chain = _relay_chain_from_meta(m, max_items=16)
    relay_round = _safe_int(m.get("relay_round"), 0, min_v=0, max_v=32)
    max_relay_round = _safe_int(cfg.get("max_relay_round"), 4, min_v=1, max_v=12)
    followup_window_seconds = _safe_int(
        followup_rules.get("window_seconds"),
        _safe_int(cfg.get("followup_window_seconds"), 20),
        min_v=3,
        max_v=240,
    )
    sender_user_id = _safe_str(m.get("sender_user_id") or m.get("user_id") or m.get("sender_id"))
    sender_member_type = _safe_str(m.get("sender_member_type")).lower()
    sender_agent_id = _safe_str(m.get("sender_agent_id"))

    at_me = _safe_bool(m.get("at_me"), False)
    called_name = _safe_bool(m.get("call_name"), False)
    called_nickname = _safe_bool(m.get("call_nickname"), _safe_bool(m.get("called_nickname"), False))
    quoted = _safe_bool(m.get("quoted"), False)
    explicit_trigger = bool(
        (_safe_bool(explicit_rules.get("at_reply"), True) and at_me)
        or (_safe_bool(explicit_rules.get("name_reply"), True) and called_name)
        or (
            _safe_bool(
                explicit_rules.get("nickname_reply"),
                _safe_bool(explicit_rules.get("name_reply"), True),
            )
            and called_nickname
        )
        or (_safe_bool(explicit_rules.get("quote_reply"), True) and quoted)
    )
    keyword_trigger = bool(_safe_bool(keyword_rules.get("enabled"), True) and _contains_keyword(text, group_keywords))
    triggered = False
    trigger_reason = "none"

    if force_reply:
        triggered = True
        trigger_reason = "force_reply"
    elif mode == "silent":
        triggered = False
        trigger_reason = "mode_silent"
    elif admin_force_wakeup and _safe_bool(explicit_rules.get("admin_force_wakeup"), True):
        triggered = True
        trigger_reason = "admin_force_wakeup"
    elif mode == "strict":
        triggered = explicit_trigger
        trigger_reason = "explicit_trigger" if explicit_trigger else "strict_no_trigger"
    elif mode == "semi_active":
        triggered = explicit_trigger or keyword_trigger
        if explicit_trigger:
            trigger_reason = "explicit_trigger"
        elif keyword_trigger:
            trigger_reason = "keyword_trigger"
        else:
            trigger_reason = "semi_no_trigger"
    else:  # active
        if explicit_trigger:
            triggered = True
            trigger_reason = "explicit_trigger"
        elif keyword_trigger:
            triggered = True
            trigger_reason = "keyword_trigger"
        elif _safe_bool(proactive_rules.get("enabled"), False):
            triggered = True
            trigger_reason = "active_proactive"
        else:
            trigger_reason = "active_no_trigger"

    target_user_id, target_name, target_source = _resolve_target_user(m)
    mentioned_agent_ids = _norm_list(m.get("mentioned_agent_ids"), max_items=10)
    mention_names = _extract_mentions(text)
    allowed_agents = _allowed_agent_ids(cfg, list(agent_rows or []))
    agent_member_status: Dict[str, Dict[str, Any]] = {}
    all_agent_ids: List[str] = []
    all_agent_seen = set()
    for item in list(cfg.get("members") or []):
        row = item if isinstance(item, dict) else {}
        if _safe_str(row.get("member_type")).lower() != "agent":
            continue
        mid = _safe_str(row.get("member_id"))
        if not mid:
            continue
        key = mid.casefold()
        if key not in all_agent_seen:
            all_agent_seen.add(key)
            all_agent_ids.append(mid)
        agent_member_status[key] = {
            "visible": _safe_bool(row.get("visible"), True),
            "muted": _safe_bool(row.get("muted"), False),
            "speak_enabled": _safe_bool(row.get("speak_enabled"), True),
        }
    for row in list(agent_rows or []):
        aid = _safe_str((row or {}).get("agent_id"))
        if not aid:
            continue
        key = aid.casefold()
        if key in all_agent_seen:
            continue
        all_agent_seen.add(key)
        all_agent_ids.append(aid)
    if not sender_member_type and sender_user_id:
        for member in list(cfg.get("members") or []):
            row = member if isinstance(member, dict) else {}
            mid = _safe_str(row.get("member_id"))
            if mid and mid == sender_user_id:
                sender_member_type = _safe_str(row.get("member_type")).lower()
                if sender_member_type == "agent" and not sender_agent_id:
                    sender_agent_id = mid
                break
    sender_member_type = _norm_member_type(sender_member_type)
    sender_is_agent = sender_member_type == "agent"
    if sender_is_agent and (not sender_agent_id):
        sender_agent_id = sender_user_id
    sender_agent_key = _safe_str(sender_agent_id).casefold()
    if sender_agent_key:
        mentioned_agent_ids = [x for x in mentioned_agent_ids if _safe_str(x).casefold() != sender_agent_key]
    if not allowed_agents and default_agent_id:
        allowed_agents = [default_agent_id]
    mention_agent_order_all = [
        _safe_str(item.get("agent_id"))
        for item in _ordered_agent_mentions(text, all_agent_ids, list(agent_rows or []), group_cfg=cfg)
        if _safe_str(item.get("agent_id"))
    ]
    if sender_agent_key:
        mention_agent_order_all = [x for x in mention_agent_order_all if _safe_str(x).casefold() != sender_agent_key]
    explicit_named_probe: List[str] = []
    explicit_named_probe_seen = set()
    for source_list in (mention_agent_order_all, mentioned_agent_ids):
        for aid in list(source_list or []):
            token = _safe_str(aid)
            if not token:
                continue
            key = token.casefold()
            if key in explicit_named_probe_seen:
                continue
            explicit_named_probe_seen.add(key)
            explicit_named_probe.append(token)
    explicit_named_muted_target_id = ""
    for token in explicit_named_probe:
        status = dict(agent_member_status.get(_safe_str(token).casefold()) or {})
        if not status:
            continue
        if _safe_bool(status.get("muted"), False):
            explicit_named_muted_target_id = _safe_str(token)
        break

    previous_agent = _safe_str(runtime.get("last_agent_id"))
    previous_speaker_type = _norm_member_type(runtime.get("last_message_member_type"))
    previous_speaker_user_id = _safe_str(runtime.get("last_message_user_id"))
    previous_speaker_agent_id = _safe_str(runtime.get("last_message_agent_id"))
    previous_speaker_text = _safe_str(runtime.get("last_message_text"))
    if (
        sender_is_agent
        and relay_chain_call
        and sender_agent_key
        and previous_speaker_agent_id.casefold() == sender_agent_key
        and _norm_text(previous_speaker_text) == text
    ):
        previous_speaker_type = _norm_member_type(runtime.get("prev_message_member_type"))
        previous_speaker_user_id = _safe_str(runtime.get("prev_message_user_id"))
        previous_speaker_agent_id = _safe_str(runtime.get("prev_message_agent_id"))
        previous_speaker_text = _safe_str(runtime.get("prev_message_text"))
    relay_chain_runtime = list(relay_chain or [])
    if sender_is_agent and sender_agent_id:
        relay_chain_runtime = _relay_chain_append(relay_chain_runtime, sender_agent_id, max_items=16)
    previous_non_sender_agent = _safe_str(previous_agent)
    if sender_agent_key and previous_non_sender_agent and previous_non_sender_agent.casefold() == sender_agent_key:
        for aid in reversed(relay_chain_runtime[:-1]):
            token = _safe_str(aid)
            if token and token.casefold() != sender_agent_key:
                previous_non_sender_agent = token
                break
    if sender_is_agent and relay_chain_call and (not explicit_trigger) and trigger_reason in {"keyword_trigger", "active_proactive"}:
        triggered = False
        trigger_reason = "relay_no_trigger"

    # Agent priority: explicit @mention > explicit name mention > keyword trigger > followup window > default
    rank_rows: List[Tuple[int, int, int, str, str]] = []
    followup_open = bool(_safe_bool(followup_rules.get("enabled"), False)) and (now_ts <= float(runtime.get("followup_window_until") or 0.0))
    agent_row_map: Dict[str, Dict[str, Any]] = {
        _safe_str((row or {}).get("agent_id")).casefold(): dict(row or {})
        for row in list(agent_rows or [])
        if _safe_str((row or {}).get("agent_id"))
    }
    member_map: Dict[str, Dict[str, Any]] = {}
    for item in list(cfg.get("members") or []):
        row = item if isinstance(item, dict) else {}
        if _safe_str(row.get("member_type")).lower() != "agent":
            continue
        mid = _safe_str(row.get("member_id"))
        if mid:
            member_map[mid.casefold()] = row
    alias_cache: Dict[str, List[str]] = {}
    nickname_alias_cache: Dict[str, List[str]] = {}
    for aid in list(allowed_agents or []):
        aid_key = _safe_str(aid).casefold()
        if not aid_key:
            continue
        row = dict(agent_row_map.get(aid_key) or {"agent_id": aid})
        aliases = _agent_alias_tokens(row)
        nickname_aliases = _agent_nickname_tokens(row)
        member_row = dict(member_map.get(aid_key) or {})
        member_name = _safe_str(member_row.get("member_name") or member_row.get("name"))
        if member_name:
            aliases.extend(
                _agent_alias_tokens(
                    {
                        "agent_id": aid,
                        "display_name": member_name,
                        "agent_title": member_name,
                        "agent_name": member_name,
                    }
                )
            )
        member_nickname = _safe_str(member_row.get("member_nickname") or member_row.get("nickname"))
        if member_nickname:
            nickname_aliases.extend(
                _agent_nickname_tokens(
                    {
                        "agent_nickname": member_nickname,
                        "nickname": member_nickname,
                    }
                )
            )
        alias_cache[aid_key] = _norm_list(aliases, max_items=32)
        nickname_alias_cache[aid_key] = _norm_list(nickname_aliases, max_items=24)

    at_mentioned_agents: List[str] = []
    at_mentioned_nickname_agents: List[str] = []
    at_mentioned_seen = set()
    at_mentioned_nickname_seen = set()
    for name in list(mention_names or []):
        nk = _safe_str(name).casefold()
        if not nk:
            continue
        for aid in list(allowed_agents or []):
            aid_key = _safe_str(aid).casefold()
            if not aid_key:
                continue
            if sender_agent_key and aid_key == sender_agent_key:
                continue
            aliases = alias_cache.get(aid_key) or []
            nickname_aliases = nickname_alias_cache.get(aid_key) or []
            matched_alias = any(nk == _safe_str(alias).casefold() for alias in aliases)
            matched_nickname = any(nk == _safe_str(alias).casefold() for alias in nickname_aliases)
            if matched_alias:
                if aid_key not in at_mentioned_seen:
                    at_mentioned_seen.add(aid_key)
                    at_mentioned_agents.append(_safe_str(aid))
            if matched_nickname:
                if aid_key not in at_mentioned_nickname_seen:
                    at_mentioned_nickname_seen.add(aid_key)
                    at_mentioned_nickname_agents.append(_safe_str(aid))
            if matched_alias or matched_nickname:
                break
    at_mentioned_set = {x.casefold() for x in at_mentioned_agents if _safe_str(x)}
    at_mentioned_nickname_set = {x.casefold() for x in at_mentioned_nickname_agents if _safe_str(x)}
    for idx, aid in enumerate(allowed_agents):
        rank_level = 1
        mention_score = 0

        rank_reason = "default"
        if aid.casefold() in {x.casefold() for x in mentioned_agent_ids}:
            rank_level = 4
            mention_score += 4
            rank_reason = "explicit_mentioned_agent_id"

        if aid.casefold() in at_mentioned_set:
            rank_level = max(rank_level, 5)
            mention_score += 8
            rank_reason = "explicit_at_mentioned_agent"
        if aid.casefold() in at_mentioned_nickname_set:
            rank_level = max(rank_level, 5)
            mention_score += 8
            rank_reason = "explicit_at_mentioned_agent_nickname"

        aliases = alias_cache.get(aid.casefold()) or []
        for alias in aliases:
            alias_key = alias.casefold()
            if not alias_key:
                continue
            if _contains_alias_in_text(text, alias_key):
                rank_level = max(rank_level, 4)
                mention_score += 1
                rank_reason = "explicit_mentioned_agent_name"
        for name in mention_names:
            name_key = name.casefold()
            if not name_key:
                continue
            if any(name_key == alias.casefold() for alias in aliases):
                rank_level = max(rank_level, 4)
                mention_score += 2
                rank_reason = "explicit_mentioned_agent_name"
        nickname_aliases = nickname_alias_cache.get(aid.casefold()) or []
        for alias in nickname_aliases:
            alias_key = alias.casefold()
            if not alias_key:
                continue
            if _contains_alias_in_text(text, alias_key):
                rank_level = max(rank_level, 4)
                mention_score += 2
                rank_reason = "explicit_mentioned_agent_nickname"
        for name in mention_names:
            name_key = name.casefold()
            if not name_key:
                continue
            if any(name_key == alias.casefold() for alias in nickname_aliases):
                rank_level = max(rank_level, 4)
                mention_score += 3
                rank_reason = "explicit_mentioned_agent_nickname"

        if rank_level < 4 and keyword_trigger:
            rank_level = max(rank_level, 3)
            mention_score += 1
            rank_reason = "keyword_trigger"
        if rank_level < 3 and followup_open and previous_agent and previous_agent.casefold() == aid.casefold():
            rank_level = max(rank_level, 2)
            mention_score += 1
            rank_reason = "followup_window"

        stable_order = max(0, 9999 - int(idx))
        rank_rows.append((rank_level, mention_score, stable_order, aid, rank_reason))

    rank_rows.sort(key=lambda row: (row[0], row[1], row[2]), reverse=True)
    selected_agent_id = ""
    selected_priority = 1
    selected_reason = "ranked_match"
    if rank_rows:
        top_priority = rank_rows[0][0]
        selected_priority = top_priority
        top_rows = [row for row in rank_rows if row[0] == top_priority]
        if len(top_rows) == 1:
            selected_agent_id = _safe_str(top_rows[0][3])
            selected_reason = _safe_str(top_rows[0][4], "ranked_match")
        else:
            selected_tie = top_rows[0]
            selected_agent_id = _safe_str(selected_tie[3])
            selected_reason = _safe_str(selected_tie[4], "ranked_match")

    if (not selected_agent_id) and allowed_agents:
        if previous_agent and any(previous_agent.casefold() == _safe_str(a).casefold() for a in allowed_agents):
            selected_agent_id = _safe_str(previous_agent)
            selected_reason = "followup_previous_agent"
        else:
            selected_agent_id = _safe_str(allowed_agents[0])
        if not selected_reason:
            selected_reason = "default_allowed_agent"

    ordered_mentions = _ordered_agent_mentions(text, allowed_agents, list(agent_rows or []), group_cfg=cfg)
    mention_agent_order = [_safe_str(item.get("agent_id")) for item in ordered_mentions if _safe_str(item.get("agent_id"))]
    if sender_agent_key:
        mention_agent_order = [x for x in mention_agent_order if _safe_str(x).casefold() != sender_agent_key]
    nickname_mentions: List[Tuple[int, int, str]] = []
    for aid in list(allowed_agents or []):
        aid_key = _safe_str(aid).casefold()
        if not aid_key:
            continue
        if sender_agent_key and aid_key == sender_agent_key:
            continue
        aliases = nickname_alias_cache.get(aid_key) or []
        best_pos = -1
        best_len = 0
        for alias in aliases:
            pos = _find_alias_first_pos(text, alias)
            if pos < 0:
                continue
            alias_len = len(_safe_str(alias))
            if best_pos < 0 or pos < best_pos or (pos == best_pos and alias_len > best_len):
                best_pos = pos
                best_len = alias_len
        if best_pos >= 0:
            nickname_mentions.append((best_pos, -best_len, _safe_str(aid)))
    nickname_mentions.sort(key=lambda row: (row[0], row[1]))
    mention_agent_order_nickname = [_safe_str(row[2]) for row in nickname_mentions if _safe_str(row[2])]
    explicit_named_candidates: List[str] = []
    explicit_named_seen = set()
    for source_list in (
        mentioned_agent_ids,
        at_mentioned_agents,
        at_mentioned_nickname_agents,
        mention_agent_order,
        mention_agent_order_nickname,
    ):
        for aid in list(source_list or []):
            token = _safe_str(aid)
            if not token:
                continue
            key = token.casefold()
            if key in explicit_named_seen:
                continue
            explicit_named_seen.add(key)
            explicit_named_candidates.append(token)
    explicit_named_target = bool(explicit_named_candidates)
    if sender_is_agent and sender_agent_key:
        explicit_named_other_target = any(_safe_str(aid).casefold() != sender_agent_key for aid in explicit_named_candidates)
    else:
        explicit_named_other_target = bool(explicit_named_target)
    has_explicit_at_token = bool(at_me or mention_names or mentioned_agent_ids)
    at_named_match = bool(
        at_me
        or at_mentioned_agents
        or at_mentioned_nickname_agents
        or (has_explicit_at_token and mentioned_agent_ids)
    )
    name_named_match = bool(called_name or ((not has_explicit_at_token) and mention_agent_order))
    nickname_named_match = bool(called_nickname or ((not has_explicit_at_token) and mention_agent_order_nickname))
    named_wakeup_enabled = bool(
        (_safe_bool(explicit_rules.get("at_reply"), True) and at_named_match)
        or (_safe_bool(explicit_rules.get("name_reply"), True) and name_named_match)
        or (
            _safe_bool(
                explicit_rules.get("nickname_reply"),
                _safe_bool(explicit_rules.get("name_reply"), True),
            )
            and nickname_named_match
        )
    )
    if mention_agent_order and (selected_priority < 4 or (not selected_agent_id)):
        top_mentioned = _safe_str(mention_agent_order[0])
        if top_mentioned:
            selected_agent_id = top_mentioned
            selected_reason = "explicit_mentioned_agent_name"
            selected_priority = max(4, int(selected_priority))
    # Agent 说话时若点名了“其他 Agent”，优先路由到被点名对象，避免回落到自己。
    if sender_is_agent and sender_agent_key and mention_agent_order:
        mention_other = [aid for aid in mention_agent_order if _safe_str(aid) and _safe_str(aid).casefold() != sender_agent_key]
        if mention_other:
            selected_agent_id = _safe_str(mention_other[0])
            selected_reason = "explicit_mentioned_agent_other"
            selected_priority = max(5, int(selected_priority))

    agent_self_named_only = bool(
        sender_is_agent
        and sender_agent_key
        and explicit_named_target
        and (not explicit_named_other_target)
    )
    if (not triggered) and mode != "silent" and explicit_named_target and named_wakeup_enabled and (not agent_self_named_only):
        triggered = True
        trigger_reason = "explicit_named_target"
    priority_named_trigger = bool(
        mode != "silent"
        and bool(selected_agent_id)
        and selected_priority >= 4
        and named_wakeup_enabled
        and (
            (not sender_is_agent)
            or (not sender_agent_key)
            or selected_agent_id.casefold() != sender_agent_key
        )
    )
    if (not triggered) and priority_named_trigger:
        triggered = True
        trigger_reason = "priority_named_target"

    has_second_person = _contains_second_person(text)
    context_pronoun_trigger = False
    if mode != "silent" and (not explicit_named_target) and has_second_person:
        pronoun_target_agent = ""
        direct_followup_like = _looks_like_agent_direct_followup(text)
        backtrace_like = _looks_like_backtrace_agent_reference(text)
        if not sender_is_agent:
            # 用户发言里的“你”优先指向上一条实际发言的 Agent；
            # 若上一条不是 Agent，再回退到最近一个已回复 Agent。
            if (
                previous_speaker_type == "agent"
                and previous_speaker_agent_id
                and any(previous_speaker_agent_id.casefold() == _safe_str(a).casefold() for a in list(allowed_agents or []))
                and (direct_followup_like or backtrace_like)
            ):
                pronoun_target_agent = _safe_str(previous_speaker_agent_id)
            elif (
                previous_agent
                and any(previous_agent.casefold() == _safe_str(a).casefold() for a in list(allowed_agents or []))
                and (direct_followup_like or backtrace_like)
            ):
                pronoun_target_agent = _safe_str(previous_agent)
            elif (
                backtrace_like
                and previous_non_sender_agent
                and any(previous_non_sender_agent.casefold() == _safe_str(a).casefold() for a in list(allowed_agents or []))
            ):
                pronoun_target_agent = _safe_str(previous_non_sender_agent)
        else:
            # Agent 接力：优先按“上一条发言者身份”解析“你”。
            if (
                previous_speaker_type == "agent"
                and previous_speaker_agent_id
                and previous_speaker_agent_id.casefold() != sender_agent_key
                and any(previous_speaker_agent_id.casefold() == _safe_str(a).casefold() for a in list(allowed_agents or []))
            ):
                pronoun_target_agent = _safe_str(previous_speaker_agent_id)
            elif (
                _looks_like_backtrace_agent_reference(text)
                and previous_non_sender_agent
                and previous_non_sender_agent.casefold() != sender_agent_key
                and any(previous_non_sender_agent.casefold() == _safe_str(a).casefold() for a in list(allowed_agents or []))
            ):
                # 只有出现“刚才你说/你上一句”这类承接语义，才追溯上一位 Agent。
                pronoun_target_agent = _safe_str(previous_non_sender_agent)
        if pronoun_target_agent:
            selected_agent_id = pronoun_target_agent
            selected_reason = "context_pronoun_previous_speaker"
            if (not sender_is_agent) and previous_speaker_type == "agent":
                selected_priority = max(4, int(selected_priority))
            else:
                selected_priority = max(3, int(selected_priority))
            triggered = True
            context_pronoun_trigger = True
            trigger_reason = "context_pronoun_followup"

    context_relevance_trigger = bool(
        mode != "silent"
        and (not sender_is_agent)
        and followup_open
        and selected_priority >= 2
        and bool(selected_agent_id)
    )
    if (not triggered) and context_relevance_trigger:
        triggered = True
        trigger_reason = "context_relevance"

    # 支持 Agent 在群聊中显式点名其他 Agent 的相互唤醒。
    agent_to_agent_trigger = bool(
        sender_is_agent
        and bool(text)
        and selected_priority >= 4
        and bool(selected_agent_id)
        and (not sender_agent_id or selected_agent_id.casefold() != sender_agent_id.casefold())
    )
    if (not triggered) and agent_to_agent_trigger:
        triggered = True
        trigger_reason = "agent_to_agent_call"

    agent_explicit_named_other = bool(
        sender_is_agent
        and explicit_named_other_target
        and bool(selected_agent_id)
        and (not sender_agent_id or selected_agent_id.casefold() != sender_agent_id.casefold())
    )
    agent_self_mention_noop = bool(
        sender_is_agent
        and sender_agent_key
        and (called_name or explicit_named_target)
        and (not explicit_named_other_target)
    )
    relay_user_pronoun_noop = bool(
        sender_is_agent
        and relay_chain_call
        and has_second_person
        and previous_speaker_type in {"user", "admin"}
        and (not explicit_named_other_target)
        and (not context_pronoun_trigger)
    )

    hard_blocked = False
    blocked_reply_text = ""
    blocked_target_agent_id = ""
    should_reply = bool(triggered)
    suppress_reason = ""
    cooldown_left = 0
    if explicit_named_muted_target_id:
        hard_blocked = True
        blocked_target_agent_id = explicit_named_muted_target_id
        blocked_reply_text = "该Agent处于禁言中，无法回复。"
        selected_agent_id = explicit_named_muted_target_id
        selected_reason = "explicit_muted_target"
        selected_priority = max(5, int(selected_priority))
        should_reply = False
        suppress_reason = "target_agent_muted"
        trigger_reason = "explicit_named_target_muted"
        triggered = False
    if should_reply and agent_self_mention_noop and (not force_reply) and (not admin_force_wakeup):
        should_reply = False
        suppress_reason = "agent_self_mention_noop"
    if should_reply and relay_user_pronoun_noop and (not force_reply) and (not admin_force_wakeup):
        should_reply = False
        suppress_reason = "relay_user_target_pronoun"
    if should_reply and sender_is_agent and relay_chain_call and relay_round >= max_relay_round:
        should_reply = False
        suppress_reason = "relay_round_limit"
    if should_reply and sender_is_agent and sender_agent_key and selected_agent_id and selected_agent_id.casefold() == sender_agent_key:
        should_reply = False
        suppress_reason = "relay_self_target"
    explicit_bypass = bool(
        force_reply
        or admin_force_wakeup
        or relay_chain_call
        or explicit_trigger
        or explicit_named_target
        or context_pronoun_trigger
        or agent_to_agent_trigger
        or agent_explicit_named_other
    )
    if should_reply and cooldown_seconds > 0:
        elapsed = now_ts - float(runtime.get("last_reply_at") or 0.0)
        if elapsed < cooldown_seconds:
            cooldown_left = max(0, int(cooldown_seconds - elapsed))
            if not explicit_bypass:
                should_reply = False
                suppress_reason = "cooldown"

    user_hash = hashlib.sha1(_norm_text(text).encode("utf-8")).hexdigest()[:16] if text else ""
    if should_reply and anti_conflict_enabled and (not explicit_bypass) and user_hash and runtime.get("last_user_hash") == user_hash:
        elapsed = now_ts - float(runtime.get("last_reply_at") or 0.0)
        if elapsed < max(8, cooldown_seconds // 2):
            should_reply = False
            suppress_reason = "anti_conflict_duplicate"
    relay_similarity_score = 0.0
    relay_similarity_ref_agent = ""
    if should_reply and sender_is_agent and relay_chain_call:
        repetitive, sim_score, ref_agent = _relay_text_is_repetitive(
            current_text=text,
            runtime=runtime,
            sender_agent_id=sender_agent_id,
            selected_agent_id=selected_agent_id,
        )
        relay_similarity_score = float(sim_score or 0.0)
        relay_similarity_ref_agent = _safe_str(ref_agent)
        if repetitive and (not explicit_named_other_target):
            should_reply = False
            suppress_reason = "relay_similar_content"
    if should_reply and sender_is_agent and relay_chain_call and selected_agent_id:
        chain_keys = {_safe_str(x).casefold() for x in list(relay_chain_runtime or []) if _safe_str(x)}
        if selected_agent_id.casefold() in chain_keys and (not explicit_named_other_target):
            should_reply = False
            suppress_reason = "relay_loop_guard"

    followup_candidates: List[str] = []
    allow_followup_short_reply = _safe_bool(cfg.get("allow_followup_short_reply"), False)
    allow_followup_multi_agent = _safe_bool(cfg.get("allow_followup_multi_agent"), False)
    followup_max_agents = _safe_int(cfg.get("followup_max_agents"), 1, min_v=1, max_v=4)
    if allow_followup_short_reply and allow_followup_multi_agent and rank_rows:
        seen_followup = {x.casefold() for x in followup_candidates if x}
        for row in rank_rows:
            aid = _safe_str(row[3])
            if not aid or aid.casefold() == selected_agent_id.casefold():
                continue
            if aid.casefold() in seen_followup:
                continue
            seen_followup.add(aid.casefold())
            followup_candidates.append(aid)
            if len(followup_candidates) >= followup_max_agents:
                break

    should_record_only = bool(mode == "silent" or (trigger_reason.endswith("no_trigger")))
    if suppress_reason:
        should_record_only = True

    selected_candidates_out = []
    selected_key = selected_agent_id.casefold()
    if selected_agent_id:
        selected_candidates_out.append(selected_agent_id)
    for row in rank_rows[:6]:
        token = _safe_str(row[3])
        if not token:
            continue
        key = token.casefold()
        if key == selected_key or token in selected_candidates_out:
            continue
        selected_candidates_out.append(token)
        if len(selected_candidates_out) >= 4:
            break

    relay_chain_out = list(relay_chain_runtime or [])
    relay_chain_next = list(relay_chain_out)
    relay_round_next = int(relay_round)
    if should_reply and selected_agent_id:
        relay_chain_next = _relay_chain_append(relay_chain_out, selected_agent_id, max_items=16)
        if sender_is_agent and relay_chain_call:
            relay_round_next = int(relay_round + 1)
        elif relay_chain_call:
            relay_round_next = max(1, int(relay_round + 1))
    reply_mode = "skip"
    if should_reply:
        reply_mode = "relay" if (sender_is_agent and relay_chain_call) else "direct"
    final_reason = suppress_reason or trigger_reason or "default"
    return {
        "should_reply": bool(should_reply),
        "should_record_only": bool(should_record_only),
        "reply_mode": reply_mode,
        "skip_reason": suppress_reason,
        "hard_blocked": bool(hard_blocked),
        "blocked_reply_text": blocked_reply_text,
        "blocked_target_agent_id": blocked_target_agent_id,
        "reason": final_reason,
        "triggered": bool(triggered),
        "trigger_reason": trigger_reason,
        "group_mode": mode,
        "trigger_rules_v1": {k: v for k, v in trigger_rules_v1.items() if k != "_source"},
        "trigger_rules_v1_source": dict(trigger_rules_v1.get("_source") or {}),
        "cooldown_left_seconds": int(cooldown_left),
        "selected_agent_id": selected_agent_id,
        "selected_by": selected_reason,
        "selected_priority": int(selected_priority),
        "selected_agent_candidates": selected_candidates_out,
        "mentioned_agent_ids_ordered": mention_agent_order[:6],
        "sender_is_agent": bool(sender_is_agent),
        "sender_member_type": sender_member_type,
        "sender_agent_id": sender_agent_id,
        "priority_named_trigger": bool(priority_named_trigger),
        "context_pronoun_trigger": bool(context_pronoun_trigger),
        "explicit_named_other_target": bool(explicit_named_other_target),
        "agent_self_mention_noop": bool(agent_self_mention_noop),
        "relay_user_pronoun_noop": bool(relay_user_pronoun_noop),
        "relay_chain_call": bool(relay_chain_call),
        "relay_chain": relay_chain_out,
        "relay_chain_next": relay_chain_next,
        "relay_round": int(relay_round),
        "relay_round_next": int(relay_round_next),
        "max_relay_round": int(max_relay_round),
        "relay_similarity_score": float(relay_similarity_score),
        "relay_similarity_ref_agent": relay_similarity_ref_agent,
        "previous_speaker_type": previous_speaker_type,
        "previous_speaker_user_id": previous_speaker_user_id,
        "previous_speaker_agent_id": previous_speaker_agent_id,
        "previous_speaker_text": previous_speaker_text[:160],
        "followup_candidate_agent_ids": followup_candidates,
        "allow_followup_short_reply": bool(allow_followup_short_reply),
        "allow_followup_multi_agent": bool(allow_followup_multi_agent),
        "target_user_id": target_user_id,
        "target_name": target_name,
        "target_source": target_source,
        "max_reply_length": max_reply_length,
        "context_turn_n": context_turn_n,
        "group_memory_enabled": _safe_bool(cfg.get("group_memory_enabled"), True),
        "allow_group_rag": _safe_bool(cfg.get("allow_group_rag"), True),
        "allow_cross_domain_analysis": _safe_bool(cfg.get("allow_cross_domain_analysis"), True),
        "default_agent_id": default_agent_id,
        "allowed_agent_ids": allowed_agents,
        "timestamp": int(now_ts),
    }
