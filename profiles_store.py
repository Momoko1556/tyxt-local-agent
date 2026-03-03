"""
profiles_store.py

Phase 4 基础数据层：
- 按 user_id 维护 profiles/<user_id>/memory_strips.json 与 profile.json
- 屏蔽 JSON 读写细节，统一默认结构与字段补全
- 预留用户画像自动更新入口（当前为 no-op）
"""

from __future__ import annotations

import json
import os
import re
import time
import uuid
from typing import Any, Dict, List, Optional


PROFILE_VERSION = 1
PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))
DEFAULT_PROFILE_DIR = os.getenv(
    "TYXT_PROFILE_DIR",
    os.path.join(PROJECT_ROOT, "profiles"),
)
DEFAULT_PROFILE_DIR = os.path.abspath(str(DEFAULT_PROFILE_DIR))

MEMORY_STRIPS_FILENAME = "memory_strips.json"
USER_PROFILE_FILENAME = "profile.json"


def _now_ts() -> int:
    return int(time.time())


def _safe_int(v: Any, default: int) -> int:
    try:
        if v is None:
            return int(default)
        return int(float(v))
    except Exception:
        return int(default)


def _safe_float(v: Any, default: float) -> float:
    try:
        if v is None:
            return float(default)
        return float(v)
    except Exception:
        return float(default)


def _safe_token(v: Any, default: str = "unknown") -> str:
    s = str(v or "").strip()
    if not s:
        return default
    s = re.sub(r"[^0-9a-zA-Z_\-]+", "_", s)
    s = re.sub(r"_+", "_", s).strip("_")
    return s or default


def _normalize_text_for_dedupe(text: str) -> str:
    """
    文本查重键归一化：
    - 小写
    - 压缩空白
    - 去掉大部分标点/分隔符，仅保留中英文与数字
    """
    s = str(text or "").strip().lower()
    if not s:
        return ""
    s = re.sub(r"\s+", " ", s)
    s = re.sub(r"[^\w\u4e00-\u9fff]+", "", s, flags=re.UNICODE)
    return s


def normalize_strip_subject_text(text: str) -> str:
    """
    记忆条主体规范化（中英双语）：
    - 中文：将用户自称“我”统一改为“用户”；将指向模型的“你”统一改为“AI”
    - 英文：将第一人称 I/my/... 统一改为 User/User's；
            将第二人称 you/your/... 统一改为 AI/AI's
    说明：仅在“写入记忆条 JSON”时执行，避免注入 prompt 时主体混淆。
    """
    s = str(text or "").strip()
    if not s:
        return ""

    # 1) 中文：先做较明确的短语替换，再做单字兜底
    zh_phrase_rules = [
        ("我是", "用户是"),
        ("我的", "用户的"),
        ("我会", "用户会"),
        ("我想", "用户想"),
        ("我希望", "用户希望"),
        ("我要", "用户要"),
        ("你是", "AI是"),
        ("你叫", "AI叫"),
        ("你的", "AI的"),
        ("你会", "AI会"),
        ("你要", "AI要"),
    ]
    for old, new in zh_phrase_rules:
        s = s.replace(old, new)

    # 2) 英文：短语/缩写优先，避免直接替换 I/you 造成语法怪异
    en_phrase_rules = [
        (r"\bmy name is\b", "User name is"),
        (r"\bI am\b", "User is"),
        (r"\bI was\b", "User was"),
        (r"\bI have\b", "User has"),
        (r"\bI can\b", "User can"),
        (r"\bI will\b", "User will"),
        (r"\bI would\b", "User would"),
        (r"\bI want\b", "User wants"),
        (r"\bI need\b", "User needs"),
        (r"\bI like\b", "User likes"),
        (r"\bI prefer\b", "User prefers"),
        (r"\bI[’']m\b", "User is"),
        (r"\bI[’']ve\b", "User has"),
        (r"\bI[’']ll\b", "User will"),
        (r"\bI[’']d\b", "User would"),
        (r"\byou are\b", "AI is"),
        (r"\byou were\b", "AI was"),
        (r"\byou have\b", "AI has"),
        (r"\byou can\b", "AI can"),
        (r"\byou will\b", "AI will"),
        (r"\byou would\b", "AI would"),
        (r"\byou should\b", "AI should"),
        (r"\byou need\b", "AI needs"),
        (r"\byou[’']re\b", "AI is"),
        (r"\byou[’']ve\b", "AI has"),
        (r"\byou[’']ll\b", "AI will"),
        (r"\byou[’']d\b", "AI would"),
        (r"\bmy\b", "User's"),
        (r"\bmine\b", "User's"),
        (r"\byour\b", "AI's"),
        (r"\byours\b", "AI's"),
    ]
    for pat, repl in en_phrase_rules:
        s = re.sub(pat, repl, s, flags=re.IGNORECASE)

    # 3) 单字兜底（最后做，避免覆盖上面的短语替换）
    s = s.replace("我", "用户")
    s = s.replace("你", "AI")
    s = re.sub(r"\bmyself\b", "User", s, flags=re.IGNORECASE)
    s = re.sub(r"\bme\b", "User", s, flags=re.IGNORECASE)
    s = re.sub(r"\byourself\b", "AI", s, flags=re.IGNORECASE)
    s = re.sub(r"\bI\b", "User", s, flags=re.IGNORECASE)
    s = re.sub(r"\byou\b", "AI", s, flags=re.IGNORECASE)

    # 语法修正：例如“用户的属马” -> “用户属马”
    s = re.sub(r"用户的属([鼠牛虎兔龙蛇马羊猴鸡狗猪])", r"用户属\1", s)
    s = s.replace("用户的属相", "用户属相")
    s = s.replace("用户的生肖", "用户生肖")

    # 压缩多余空白
    s = re.sub(r"\s+", " ", s).strip()
    return s


def normalize_profile_user_id(user_id: str) -> str:
    """
    将业务 user_id 归一化到 profiles 目录命名规范：
    - local_admin
    - qq_<qq号>
    - group_<group_id>
    """
    uid = str(user_id or "").strip()
    if not uid:
        return "local_admin"

    low = uid.lower()
    if low in {"anonymous", "none", "null", "system", "local", "local_ui"}:
        return "local_admin"
    if low == "local_admin":
        return "local_admin"

    if low.startswith("qq_"):
        return "qq_" + _safe_token(uid[3:], "unknown")
    if low.startswith("group_"):
        return "group_" + _safe_token(uid[6:], "unknown")
    if low.startswith("qq:"):
        return "qq_" + _safe_token(uid.split(":", 1)[1], "unknown")
    if low.startswith("group:"):
        return "group_" + _safe_token(uid.split(":", 1)[1], "unknown")

    if re.fullmatch(r"\d{5,20}", uid):
        return f"qq_{uid}"

    # 兜底按“私聊用户”处理
    safe = _safe_token(uid, "local_admin")
    if safe == "local_admin":
        return safe
    return f"qq_{safe}"


def get_profile_base_dir(profile_base_dir: Optional[str] = None) -> str:
    base = str(profile_base_dir or os.getenv("TYXT_PROFILE_DIR") or DEFAULT_PROFILE_DIR).strip()
    if not base:
        base = DEFAULT_PROFILE_DIR
    os.makedirs(base, exist_ok=True)
    return base


def get_user_profile_dir(user_id: str, profile_base_dir: Optional[str] = None) -> str:
    base = get_profile_base_dir(profile_base_dir)
    norm_uid = normalize_profile_user_id(user_id)
    return os.path.join(base, norm_uid)


def _memory_strips_path(user_id: str, profile_base_dir: Optional[str] = None) -> str:
    return os.path.join(get_user_profile_dir(user_id, profile_base_dir), MEMORY_STRIPS_FILENAME)


def _profile_path(user_id: str, profile_base_dir: Optional[str] = None) -> str:
    return os.path.join(get_user_profile_dir(user_id, profile_base_dir), USER_PROFILE_FILENAME)


def _default_memory_strips(user_id: str) -> Dict[str, Any]:
    return {
        "user_id": normalize_profile_user_id(user_id),
        "version": PROFILE_VERSION,
        "updated_at": _now_ts(),
        "strips": [],
    }


def _normalize_strip_item(
    item: Dict[str, Any],
    now_ts: int,
    default_created_by: str = "user",
) -> Optional[Dict[str, Any]]:
    if not isinstance(item, dict):
        return None
    text = normalize_strip_subject_text(str(item.get("text") or ""))
    if not text:
        return None

    sid = str(item.get("id") or "").strip() or f"m_{now_ts}_{uuid.uuid4().hex[:8]}"
    # Phase 4.1: 显式记忆条统一固定为最高重要度
    importance = 10.0

    created_at = _safe_int(item.get("created_at"), now_ts)
    updated_at = _safe_int(item.get("updated_at"), now_ts)
    if updated_at < created_at:
        updated_at = created_at

    created_by = str(item.get("created_by") or default_created_by or "user").strip().lower()
    if created_by not in {"user", "admin", "agent"}:
        created_by = str(default_created_by or "user").strip().lower() or "user"
        if created_by not in {"user", "admin", "agent"}:
            created_by = "user"

    tags_raw = item.get("tags")
    tags: List[str] = []
    if isinstance(tags_raw, list):
        for t in tags_raw:
            ts = str(t or "").strip()
            if ts:
                tags.append(ts)
    elif isinstance(tags_raw, str):
        for t in re.split(r"[，,;；\s]+", tags_raw):
            ts = str(t or "").strip()
            if ts:
                tags.append(ts)

    return {
        "id": sid,
        "text": text,
        "tags": tags,
        "importance": float(round(importance, 3)),
        "created_at": int(created_at),
        "updated_at": int(updated_at),
        "created_by": created_by,
    }


def _dedupe_strip_items(items: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    key_to_idx: Dict[str, int] = {}
    for it in items:
        if not isinstance(it, dict):
            continue
        key = _normalize_text_for_dedupe(str(it.get("text") or ""))
        if not key:
            continue
        hit = key_to_idx.get(key)
        if hit is None:
            key_to_idx[key] = len(out)
            out.append(it)
            continue

        cur = out[hit]
        # 合并重复项：保留首条 id 与正文，更新时间取较新，创建时间取较早，tags 去重合并
        cur_created = _safe_int(cur.get("created_at"), _now_ts())
        cur_updated = _safe_int(cur.get("updated_at"), cur_created)
        it_created = _safe_int(it.get("created_at"), cur_created)
        it_updated = _safe_int(it.get("updated_at"), it_created)
        cur["created_at"] = int(min(cur_created, it_created))
        cur["updated_at"] = int(max(cur_updated, it_updated))
        cur["importance"] = 10.0

        merged_tags: List[str] = []
        seen_tags: set[str] = set()
        for raw_tags in (cur.get("tags"), it.get("tags")):
            if not isinstance(raw_tags, list):
                continue
            for t in raw_tags:
                ts = str(t or "").strip()
                if not ts or ts in seen_tags:
                    continue
                seen_tags.add(ts)
                merged_tags.append(ts)
        cur["tags"] = merged_tags
        out[hit] = cur
    return out


def normalize_memory_strips_data(
    user_id: str,
    data: Optional[Dict[str, Any]],
    default_created_by: str = "user",
) -> Dict[str, Any]:
    now_ts = _now_ts()
    base = _default_memory_strips(user_id)
    src = data if isinstance(data, dict) else {}

    out = dict(base)
    out["version"] = _safe_int(src.get("version"), PROFILE_VERSION)
    out["updated_at"] = _safe_int(src.get("updated_at"), now_ts)

    raw_list = src.get("strips")
    if not isinstance(raw_list, list):
        raw_list = []

    strips: List[Dict[str, Any]] = []
    for item in raw_list:
        normalized = _normalize_strip_item(item if isinstance(item, dict) else {}, now_ts, default_created_by)
        if normalized:
            strips.append(normalized)

    out["strips"] = _dedupe_strip_items(strips)
    out["user_id"] = normalize_profile_user_id(user_id)
    return out


def load_memory_strips(user_id: str, profile_base_dir: Optional[str] = None) -> Dict[str, Any]:
    path = _memory_strips_path(user_id, profile_base_dir)
    if not os.path.exists(path):
        return _default_memory_strips(user_id)
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except Exception:
        data = {}
    return normalize_memory_strips_data(user_id, data, default_created_by="user")


def save_memory_strips(
    user_id: str,
    data: Dict[str, Any],
    profile_base_dir: Optional[str] = None,
    default_created_by: str = "user",
) -> Dict[str, Any]:
    user_dir = get_user_profile_dir(user_id, profile_base_dir)
    os.makedirs(user_dir, exist_ok=True)

    normalized = normalize_memory_strips_data(
        user_id=user_id,
        data=data,
        default_created_by=default_created_by,
    )
    # Phase 4.1: 落盘前再次确保每条 strip 的 importance 固定为 10.0
    for s in (normalized.get("strips") or []):
        if isinstance(s, dict):
            s["importance"] = 10.0
    normalized["updated_at"] = _now_ts()

    path = _memory_strips_path(user_id, profile_base_dir)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(normalized, f, ensure_ascii=False, indent=2)
    os.replace(tmp, path)
    return normalized


def append_memory_strip(
    user_id: str,
    text: str,
    importance: float = 5.0,
    created_by: str = "agent",
    tags: Optional[List[str]] = None,
    profile_base_dir: Optional[str] = None,
) -> Optional[Dict[str, Any]]:
    txt = normalize_strip_subject_text(text)
    if not txt:
        return None

    now_ts = _now_ts()
    data = load_memory_strips(user_id, profile_base_dir)
    strips = list(data.get("strips") or [])
    key = _normalize_text_for_dedupe(txt)

    # 查重：若同义文本已存在，则不新增，仅刷新 updated_at（并可合并 tags）
    if key:
        for idx, cur in enumerate(strips):
            if not isinstance(cur, dict):
                continue
            cur_key = _normalize_text_for_dedupe(str(cur.get("text") or ""))
            if cur_key != key:
                continue
            cur["updated_at"] = now_ts
            cur["importance"] = 10.0
            if isinstance(tags, list) and tags:
                cur_tags = cur.get("tags") if isinstance(cur.get("tags"), list) else []
                seen = {str(x).strip() for x in cur_tags if str(x).strip()}
                for t in tags:
                    ts = str(t or "").strip()
                    if ts and ts not in seen:
                        cur_tags.append(ts)
                        seen.add(ts)
                cur["tags"] = cur_tags
            strips[idx] = cur
            saved = save_memory_strips(
                user_id=user_id,
                data={"strips": strips},
                profile_base_dir=profile_base_dir,
                default_created_by=str(created_by or "agent").strip().lower() or "agent",
            )
            out = next((x for x in saved.get("strips", []) if str(x.get("id")) == str(cur.get("id"))), None)
            return out if isinstance(out, dict) else cur

    item = {
        "id": f"m_{now_ts}_{uuid.uuid4().hex[:8]}",
        "text": txt,
        # Phase 4.1: 忽略外部传入，统一固定值
        "importance": 10.0,
        "tags": list(tags or []),
        "created_at": now_ts,
        "updated_at": now_ts,
        "created_by": str(created_by or "agent").strip().lower() or "agent",
    }
    strips.append(item)
    saved = save_memory_strips(
        user_id=user_id,
        data={"strips": strips},
        profile_base_dir=profile_base_dir,
        default_created_by=str(created_by or "agent").strip().lower() or "agent",
    )
    out = next((x for x in saved.get("strips", []) if str(x.get("id")) == str(item["id"])), None)
    return out if isinstance(out, dict) else item


def _default_user_profile(user_id: str) -> Dict[str, Any]:
    return {
        "user_id": normalize_profile_user_id(user_id),
        "version": PROFILE_VERSION,
        "updated_at": _now_ts(),
        "location": {
            "city": "",
            "lat": None,
            "lon": None,
            "source": "",
            "updated_at": 0,
        },
        "traits": {
            "temperament": "",
            "communication_style": "",
        },
        "preferences": {
            "likes": [],
            "dislikes": [],
        },
        "facts": [],
    }


def _normalize_fact_item(item: Dict[str, Any], now_ts: int) -> Optional[Dict[str, Any]]:
    if not isinstance(item, dict):
        return None
    text = str(item.get("text") or "").strip()
    if not text:
        return None
    fid = str(item.get("id") or "").strip() or f"f_{now_ts}_{uuid.uuid4().hex[:8]}"
    confidence = _safe_float(item.get("confidence"), 0.7)
    confidence = max(0.0, min(1.0, confidence))
    created_at = _safe_int(item.get("created_at"), now_ts)
    last_seen_at = _safe_int(item.get("last_seen_at"), now_ts)
    if last_seen_at < created_at:
        last_seen_at = created_at
    source = str(item.get("source") or "conversation").strip() or "conversation"
    return {
        "id": fid,
        "text": text,
        "confidence": float(round(confidence, 3)),
        "source": source,
        "created_at": int(created_at),
        "last_seen_at": int(last_seen_at),
    }


def _dedupe_fact_items(items: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    key_to_idx: Dict[str, int] = {}
    for it in items:
        if not isinstance(it, dict):
            continue
        key = _normalize_text_for_dedupe(str(it.get("text") or ""))
        if not key:
            continue
        hit = key_to_idx.get(key)
        if hit is None:
            key_to_idx[key] = len(out)
            out.append(it)
            continue

        cur = out[hit]
        cur_conf = _safe_float(cur.get("confidence"), 0.7)
        it_conf = _safe_float(it.get("confidence"), cur_conf)
        cur["confidence"] = float(round(max(cur_conf, it_conf), 3))

        cur_created = _safe_int(cur.get("created_at"), _now_ts())
        it_created = _safe_int(it.get("created_at"), cur_created)
        cur_seen = _safe_int(cur.get("last_seen_at"), cur_created)
        it_seen = _safe_int(it.get("last_seen_at"), it_created)
        cur["created_at"] = int(min(cur_created, it_created))
        cur["last_seen_at"] = int(max(cur_seen, it_seen))

        if not str(cur.get("source") or "").strip():
            cur["source"] = str(it.get("source") or "conversation").strip() or "conversation"
        out[hit] = cur
    return out


def normalize_user_profile_data(user_id: str, data: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    now_ts = _now_ts()
    base = _default_user_profile(user_id)
    src = data if isinstance(data, dict) else {}

    out = dict(base)
    out["version"] = _safe_int(src.get("version"), PROFILE_VERSION)
    out["updated_at"] = _safe_int(src.get("updated_at"), now_ts)

    loc = src.get("location") if isinstance(src.get("location"), dict) else {}
    city = str(loc.get("city") or "").strip()
    lat_raw = loc.get("lat")
    lon_raw = loc.get("lon")
    lat = None
    lon = None
    if lat_raw not in (None, ""):
        try:
            lat = float(lat_raw)
        except Exception:
            lat = None
    if lon_raw not in (None, ""):
        try:
            lon = float(lon_raw)
        except Exception:
            lon = None
    source = str(loc.get("source") or "").strip()
    loc_updated_at = _safe_int(loc.get("updated_at"), 0)
    out["location"] = {
        "city": city,
        "lat": lat,
        "lon": lon,
        "source": source,
        "updated_at": int(loc_updated_at),
    }

    traits = src.get("traits") if isinstance(src.get("traits"), dict) else {}
    out["traits"] = {
        "temperament": str(traits.get("temperament") or "").strip(),
        "communication_style": str(traits.get("communication_style") or "").strip(),
    }

    prefs = src.get("preferences") if isinstance(src.get("preferences"), dict) else {}
    likes_raw = prefs.get("likes")
    dislikes_raw = prefs.get("dislikes")
    likes = [str(x).strip() for x in (likes_raw if isinstance(likes_raw, list) else []) if str(x).strip()]
    dislikes = [str(x).strip() for x in (dislikes_raw if isinstance(dislikes_raw, list) else []) if str(x).strip()]
    out["preferences"] = {
        "likes": likes,
        "dislikes": dislikes,
    }

    facts_raw = src.get("facts")
    if not isinstance(facts_raw, list):
        facts_raw = []
    facts: List[Dict[str, Any]] = []
    for item in facts_raw:
        normalized = _normalize_fact_item(item if isinstance(item, dict) else {}, now_ts)
        if normalized:
            facts.append(normalized)
    out["facts"] = _dedupe_fact_items(facts)
    out["user_id"] = normalize_profile_user_id(user_id)
    return out


def load_user_profile(user_id: str, profile_base_dir: Optional[str] = None) -> Dict[str, Any]:
    path = _profile_path(user_id, profile_base_dir)
    if not os.path.exists(path):
        return _default_user_profile(user_id)
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except Exception:
        data = {}
    return normalize_user_profile_data(user_id, data)


def save_user_profile(user_id: str, profile: Dict[str, Any], profile_base_dir: Optional[str] = None) -> Dict[str, Any]:
    user_dir = get_user_profile_dir(user_id, profile_base_dir)
    os.makedirs(user_dir, exist_ok=True)
    normalized = normalize_user_profile_data(user_id, profile)
    normalized["updated_at"] = _now_ts()

    path = _profile_path(user_id, profile_base_dir)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(normalized, f, ensure_ascii=False, indent=2)
    os.replace(tmp, path)
    return normalized


def maybe_update_user_profile_from_turn(
    user_id: str,
    turn_summary: str,
    profile_base_dir: Optional[str] = None,
) -> bool:
    """
    预留给 Phase 4.x 的画像自动更新入口。
    当前仅做 no-op（返回 False）。
    """
    _ = (normalize_profile_user_id(user_id), str(turn_summary or "").strip(), get_profile_base_dir(profile_base_dir))
    return False


def update_user_location(
    user_id: str,
    city: str,
    lat: float,
    lon: float,
    source: str = "user",
    profile_base_dir: Optional[str] = None,
) -> Dict[str, Any]:
    """
    更新指定用户的 location 信息并写回 profile.json。
    返回更新后的 location 字典。
    """
    profile = load_user_profile(user_id, profile_base_dir=profile_base_dir)
    now_ts = _now_ts()
    location = {
        "city": str(city or "").strip(),
        "lat": float(lat),
        "lon": float(lon),
        "source": str(source or "user").strip() or "user",
        "updated_at": now_ts,
    }
    profile["location"] = location
    save_user_profile(user_id, profile, profile_base_dir=profile_base_dir)
    return location


def apply_profile_note(
    user_id: str,
    note: str,
    confidence: float = 0.8,
    source: str = "conversation",
    profile_base_dir: Optional[str] = None,
) -> Optional[Dict[str, Any]]:
    txt = re.sub(r"\s+", " ", str(note or "")).strip()
    if not txt:
        return None

    now_ts = _now_ts()
    conf = max(0.0, min(1.0, _safe_float(confidence, 0.8)))
    src = str(source or "conversation").strip() or "conversation"

    profile = load_user_profile(user_id, profile_base_dir=profile_base_dir)
    facts = list(profile.get("facts") or [])

    norm = _normalize_text_for_dedupe(txt)
    hit_idx = -1
    for idx, f in enumerate(facts):
        if not isinstance(f, dict):
            continue
        ftxt = str(f.get("text") or "")
        if _normalize_text_for_dedupe(ftxt) == norm:
            hit_idx = idx
            break

    if hit_idx >= 0:
        cur = facts[hit_idx]
        old_conf = _safe_float(cur.get("confidence"), conf)
        cur["confidence"] = float(round(max(old_conf, conf), 3))
        cur["last_seen_at"] = now_ts
        if not str(cur.get("source") or "").strip():
            cur["source"] = src
        facts[hit_idx] = cur
        out = cur
    else:
        out = {
            "id": f"f_{now_ts}_{uuid.uuid4().hex[:8]}",
            "text": txt,
            "confidence": float(round(conf, 3)),
            "source": src,
            "created_at": now_ts,
            "last_seen_at": now_ts,
        }
        facts.append(out)

    profile["facts"] = facts
    save_user_profile(user_id, profile, profile_base_dir=profile_base_dir)
    return out


__all__ = [
    "DEFAULT_PROFILE_DIR",
    "PROFILE_VERSION",
    "normalize_profile_user_id",
    "get_user_profile_dir",
    "load_memory_strips",
    "save_memory_strips",
    "append_memory_strip",
    "load_user_profile",
    "save_user_profile",
    "update_user_location",
    "apply_profile_note",
    "maybe_update_user_profile_from_turn",
]
