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

        group_mode = _norm_mode(row.get("group_mode") or prev.get("group_mode"))
        group_name = _safe_str(row.get("group_name") or row.get("groupName") or prev.get("group_name"), group_id)
        group_intro = _safe_str(row.get("group_intro") or row.get("groupIntro") or prev.get("group_intro"))
        group_topic = _safe_str(row.get("group_topic") or row.get("groupTopic") or prev.get("group_topic"))
        group_memory_enabled = _safe_bool(row.get("group_memory_enabled"), _safe_bool(prev.get("group_memory_enabled"), True))
        raw_group_memory_path = _safe_str(row.get("group_memory_path") or row.get("groupMemoryPath") or prev.get("group_memory_path"))
        group_memory_path = os.path.abspath(raw_group_memory_path) if raw_group_memory_path else self._group_memory_default_path(group_id)
        os.makedirs(group_memory_path, exist_ok=True)

        triggers_prev = prev.get("trigger_settings") if isinstance(prev.get("trigger_settings"), dict) else {}
        triggers_in = row.get("trigger_settings") if isinstance(row.get("trigger_settings"), dict) else {}
        trigger_settings = {
            "at_reply": _safe_bool(triggers_in.get("at_reply"), _safe_bool(triggers_prev.get("at_reply"), True)),
            "name_reply": _safe_bool(triggers_in.get("name_reply"), _safe_bool(triggers_prev.get("name_reply"), True)),
            "quote_reply": _safe_bool(triggers_in.get("quote_reply"), _safe_bool(triggers_prev.get("quote_reply"), True)),
            "keyword_trigger": _safe_bool(triggers_in.get("keyword_trigger"), _safe_bool(triggers_prev.get("keyword_trigger"), True)),
            "admin_force_wakeup": _safe_bool(triggers_in.get("admin_force_wakeup"), _safe_bool(triggers_prev.get("admin_force_wakeup"), True)),
        }

        record = {
            "group_id": group_id,
            "group_name": group_name,
            "group_intro": group_intro,
            "group_topic": group_topic,
            "group_mode": group_mode,
            "default_agent_id": default_agent_id,
            "members": members,
            "allowed_agent_ids": allowed_agent_ids,
            "trigger_keywords": _norm_list(row.get("trigger_keywords") or prev.get("trigger_keywords"), max_items=60, max_len=24),
            "cooldown_seconds": _safe_int(row.get("cooldown_seconds"), _safe_int(prev.get("cooldown_seconds"), 8), min_v=0, max_v=7200),
            "anti_conflict_enabled": _safe_bool(row.get("anti_conflict_enabled"), _safe_bool(prev.get("anti_conflict_enabled"), True)),
            "max_reply_length": _safe_int(row.get("max_reply_length"), _safe_int(prev.get("max_reply_length"), 260), min_v=60, max_v=1600),
            "context_turn_n": _safe_int(row.get("context_turn_n"), _safe_int(prev.get("context_turn_n"), 3), min_v=1, max_v=20),
            "group_memory_enabled": group_memory_enabled,
            "group_memory_path": group_memory_path,
            "allow_group_rag": _safe_bool(row.get("allow_group_rag"), _safe_bool(prev.get("allow_group_rag"), True)),
            "allow_cross_domain_analysis": _safe_bool(
                row.get("allow_cross_domain_analysis"),
                _safe_bool(prev.get("allow_cross_domain_analysis"), True),
            ),
            "allow_proactive_reply": _safe_bool(row.get("allow_proactive_reply"), _safe_bool(prev.get("allow_proactive_reply"), False)),
            "allow_followup_short_reply": _safe_bool(
                row.get("allow_followup_short_reply"),
                _safe_bool(prev.get("allow_followup_short_reply"), False),
            ),
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
                row.get("followup_window_seconds"),
                _safe_int(prev.get("followup_window_seconds"), 20),
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
        for item in list(raw.get("groups") if isinstance(raw, dict) else []):
            groups.append(self._normalize_group(item))
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
            merged = self._normalize_group({**(prev or {}), **row}, keep_created=prev)
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
            merged = self._normalize_group({**current, **diff}, keep_created=current)
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
            "updated_at": _safe_int(row.get("updated_at"), 0),
            "allow_proactive_reply": _safe_bool(row.get("allow_proactive_reply"), False),
            "allow_followup_short_reply": _safe_bool(row.get("allow_followup_short_reply"), False),
            "allow_followup_multi_agent": _safe_bool(row.get("allow_followup_multi_agent"), False),
            "group_memory_enabled": _safe_bool(row.get("group_memory_enabled"), True),
            "group_memory_path": _safe_str(row.get("group_memory_path")),
            "member_count": len(list(row.get("members") or [])),
        }
        return summary, row
