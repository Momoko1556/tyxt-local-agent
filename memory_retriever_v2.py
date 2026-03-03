# -*- coding: utf-8 -*-
"""
memory_retriever_v2.py
统一记忆检索入口（多租户 MemoryStore + 连续重要度 + 每周衰减）
"""

from __future__ import annotations

import json
import os
import re
import time
from typing import Any, Dict, List, Optional, Tuple

from memory_store import (
    CHROMA_PERSIST_DIR,
    LOCAL_OWNER_ID,
    MemoryRecord,
    MultiTenantChromaMemoryStore,
)

# ========= 配置 =========
PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))
KEYWORDS_FILE = os.getenv("KEYWORDS_FILE", os.path.join(PROJECT_ROOT, "trigger_keywords.json"))
KEYWORDS_FILE = os.path.abspath(str(KEYWORDS_FILE))
DEFAULT_TOPK = int(os.getenv("MEM_TOPK", "20"))
LIGHT_TOPK = max(0, min(5, DEFAULT_TOPK))

IMPORTANCE_HIT_BOOST = float(os.getenv("IMPORTANCE_HIT_BOOST", "0.1"))
IMPORTANCE_MAX = float(os.getenv("IMPORTANCE_MAX", "10.0"))
DECAY_GRACE_DAYS = int(os.getenv("DECAY_GRACE_DAYS", "30"))
DECAY_STEP_DAYS = int(os.getenv("DECAY_STEP_DAYS", "7"))
DECAY_PER_STEP = float(os.getenv("DECAY_PER_STEP", "0.1"))
LEXICAL_FALLBACK_MAX_SCAN = max(500, int(os.getenv("LEXICAL_FALLBACK_MAX_SCAN", "8000")))
ENABLE_LEXICAL_FALLBACK_SCAN = str(os.getenv("ENABLE_LEXICAL_FALLBACK_SCAN", "0")).strip().lower() in {"1", "true", "yes", "on"}

CHAT_MEM_STORE = MultiTenantChromaMemoryStore(
    persist_dir=CHROMA_PERSIST_DIR,
)
# 兼容旧引用名称
MEM_STORE = CHAT_MEM_STORE


def resolve_channel_owner(meta: Optional[Dict[str, Any]]) -> Tuple[str, str]:
    m = dict(meta or {})
    scene = str(m.get("scene") or "").strip().lower()
    gid = str(m.get("group_id") or "").strip()
    uid = str(m.get("user_id") or "").strip()
    channel_type = str(m.get("channel_type") or "").strip().lower()
    owner_id = str(m.get("owner_id") or "").strip()

    if channel_type and owner_id:
        if channel_type == "group":
            return "group", owner_id
        if channel_type == "local":
            return "local", owner_id
        return "private", owner_id

    if scene.startswith("qq_group:"):
        return "group", scene.split(":", 1)[1].strip() or (gid or "unknown_group")
    if scene.startswith("qq_private:"):
        owner = scene.split(":", 1)[1].strip()
        if owner:
            return "private", owner

    if scene in {"group"} or gid:
        return "group", (gid or "unknown_group")

    if scene in {"local", "local_ui", "ui", "chat"}:
        return "local", LOCAL_OWNER_ID

    if scene == "private":
        if uid and uid.lower() != "anonymous":
            return "private", uid
        return "local", LOCAL_OWNER_ID

    if uid and uid.lower() != "anonymous":
        return "private", uid
    return "local", LOCAL_OWNER_ID


def _sim_from_score(raw_score: Optional[float]) -> float:
    # Chroma 常见返回是 distance，越小越相似。
    # 统一映射到 (0,1] 近似相似度。
    if raw_score is None:
        return 0.0
    try:
        d = float(raw_score)
    except Exception:
        return 0.0
    d = abs(d)
    return 1.0 / (1.0 + d)


def _query_terms(query: str) -> List[str]:
    q = re.sub(r"\s+", " ", str(query or "")).strip().lower()
    if not q:
        return []
    pieces = re.split(r"[\s,，。！？!?:：;；/\\|()\[\]{}\"'`~@#$%^&*+=<>《》“”‘’·…-]+", q)
    terms = [p for p in pieces if p]
    if q and q not in terms:
        terms.insert(0, q)
    out: List[str] = []
    seen = set()
    for t in terms:
        if t in seen:
            continue
        seen.add(t)
        out.append(t)
    return out


def _lexical_match_score(query: str, text: str) -> Tuple[float, bool]:
    q = re.sub(r"\s+", " ", str(query or "")).strip().lower()
    t = re.sub(r"\s+", " ", str(text or "")).strip().lower()
    if not q or not t:
        return 0.0, False
    terms = _query_terms(q)
    if not terms:
        return 0.0, False

    exact_hit = q in t
    hit_count = 0
    for term in terms:
        if term and term in t:
            hit_count += 1
    ratio = hit_count / max(1, len(terms))

    score = 0.0
    if exact_hit:
        score += 0.9
    score += 0.35 * ratio
    return score, (exact_hit or hit_count > 0)


def _effective_importance(meta: Dict[str, Any], now_ts: Optional[int] = None) -> float:
    now = int(now_ts or time.time())
    try:
        imp = float((meta or {}).get("importance", 5.0))
    except (TypeError, ValueError):
        imp = 5.0
    imp = max(0.0, min(IMPORTANCE_MAX, imp))

    try:
        ts = int((meta or {}).get("timestamp", 0))
    except (TypeError, ValueError):
        ts = 0
    if ts <= 0:
        return imp

    age_days = (now - ts) / 86400.0
    if age_days <= DECAY_GRACE_DAYS:
        decay = 0.0
    else:
        extra = age_days - DECAY_GRACE_DAYS
        steps = int(extra // max(1, DECAY_STEP_DAYS))
        decay = steps * DECAY_PER_STEP
    return max(0.0, imp - decay)


def effective_importance(meta: Dict[str, Any], now_ts: Optional[int] = None) -> float:
    return _effective_importance(meta, now_ts=now_ts)


def _select_by_final_score(
    records: List[MemoryRecord],
    top_k: int,
    query: str = "",
    max_chars: int = 1200,
) -> List[MemoryRecord]:
    now_ts = int(time.time())
    query_clean = re.sub(r"\s+", " ", str(query or "")).strip()
    keyword_like = (2 <= len(query_clean) <= 24) and (re.search(r"\s", query_clean) is None)

    scored: List[Tuple[float, float, bool, int, MemoryRecord]] = []
    lexical_hit_count = 0
    for rec in records:
        meta = rec.metadata or {}
        eff_imp = _effective_importance(meta, now_ts=now_ts)
        sim_score = _sim_from_score(rec.score)
        text = str(rec.text or "")
        lex_score, lex_hit = _lexical_match_score(query_clean, text)
        if lex_hit:
            lexical_hit_count += 1

        is_structured_blob = (
            len(text) >= 2500
            and (
                ("content_type" in text and "asset_pointer" in text)
                or (text.count("{") >= 20 and text.count("}") >= 20)
            )
        )
        if is_structured_blob and (not lex_hit):
            # 过滤明显结构化噪音（导入中常见的大块 JSON 字段）。
            continue

        semantic = sim_score * (1.0 + eff_imp / 10.0)
        # 短关键词时，对完全不含关键词的候选轻微降权，减少“看似相关但没命中”。
        if (not lex_hit) and len(query_clean) >= 2:
            semantic *= 0.55
        final_score = semantic + lex_score
        try:
            ts = int(meta.get("timestamp", 0))
        except Exception:
            ts = 0
        rec.metadata["_effective_importance"] = eff_imp
        rec.metadata["_sim_score"] = sim_score
        rec.metadata["_lex_score"] = lex_score
        rec.metadata["_lex_hit"] = bool(lex_hit)
        rec.metadata["_final_score"] = final_score
        rec.score = final_score
        scored.append((final_score, lex_score, bool(lex_hit), ts, rec))

    # 若是短关键词并存在至少 1 条关键词命中，则只保留命中项，避免凑数干扰 prompt 注入。
    if keyword_like and lexical_hit_count > 0:
        scored = [row for row in scored if bool(row[2])]

    scored.sort(key=lambda x: (-x[0], -x[1], -x[3]))

    out: List[MemoryRecord] = []
    total_chars = 0
    for _fs, _lex, _hit, _ts, rec in scored:
        if len(out) >= top_k:
            break
        txt_len = len(str(rec.text or ""))
        if total_chars + txt_len > max_chars and out:
            break
        out.append(rec)
        total_chars += txt_len
    return out


def _fallback_lexical_scan_records(
    query: str,
    channel_type: str,
    owner_id: str,
    top_k: int,
    lookback_days: Optional[int],
    layer: Optional[str],
) -> List[MemoryRecord]:
    """
    关键词兜底：
    当语义候选中没有任何关键词命中时，直接在目标 tenant 的记录里做一次轻量词法扫描，
    避免“检索面板有命中、聊天端却空回/跑偏”。
    """
    q = str(query or "").strip()
    if not q:
        return []
    now_ts = int(time.time())
    min_ts: Optional[int] = None
    try:
        d = int(lookback_days) if lookback_days is not None else 0
        if d > 0:
            min_ts = now_ts - d * 86400
    except Exception:
        min_ts = None

    hits: List[MemoryRecord] = []
    scanned = 0
    page = 1
    page_size = 100

    while scanned < LEXICAL_FALLBACK_MAX_SCAN:
        got = CHAT_MEM_STORE.list_records(
            channel_type=channel_type,
            owner_id=owner_id,
            page=page,
            page_size=page_size,
            include_deleted=False,
        )
        rows = list(got.get("records") or [])
        if not rows:
            break

        for rec in rows:
            scanned += 1
            if scanned > LEXICAL_FALLBACK_MAX_SCAN:
                break
            meta = dict(getattr(rec, "metadata", {}) or {})
            if layer and str(meta.get("layer") or "").strip() != str(layer).strip():
                continue
            ts = int(meta.get("timestamp") or 0)
            if min_ts is not None and ts < min_ts:
                continue
            text = str(getattr(rec, "text", "") or "")
            _lex_score, lex_hit = _lexical_match_score(q, text)
            if not lex_hit:
                continue
            hits.append(rec)
        page += 1

        # 命中已足够时提前结束，避免不必要扫描
        if len(hits) >= max(top_k * 6, 60):
            break

    return hits


def retrieve_chat_memory_records(
    query: str,
    meta: Optional[Dict[str, Any]] = None,
    top_k: int = DEFAULT_TOPK,
    lookback_days: Optional[int] = None,
    layer: Optional[str] = None,
    max_chars: int = 1200,
) -> List[MemoryRecord]:
    q = str(query or "").strip()
    if not q:
        return []
    safe_top_k = max(1, int(top_k or 1))
    channel_type, owner_id = resolve_channel_owner(meta)
    filters: Dict[str, Any] = {
        "channel_type": channel_type,
        "owner_id": owner_id,
        "deleted": {"$ne": True},
    }
    if lookback_days is not None:
        try:
            filters["lookback_days"] = int(lookback_days)
        except Exception:
            pass
    if layer:
        filters["layer"] = str(layer).strip()

    # 先召回较多候选，再做“相似度 × 有效重要度”二次排序。
    # 关键词类查询（如“小龙虾”）需要更大的候选池，避免命中淹没在向量近邻之外。
    q_clean = str(q or "").strip()
    keyword_like = (2 <= len(q_clean) <= 24) and (re.search(r"\s", q_clean) is None)
    if keyword_like:
        raw_top_k = max(safe_top_k * 20, 240)
    else:
        raw_top_k = max(safe_top_k * 6, 80)
    candidates = CHAT_MEM_STORE.search_raw(query=q, top_k=raw_top_k, filters=filters)
    selected = _select_by_final_score(candidates, top_k=safe_top_k, query=q, max_chars=max_chars)

    # 语义候选里若无关键词命中，则回退到 tenant 内词法扫描兜底。
    selected_lex_hits = sum(1 for r in selected if bool((getattr(r, "metadata", {}) or {}).get("_lex_hit")))
    if ENABLE_LEXICAL_FALLBACK_SCAN and keyword_like and selected_lex_hits <= 0:
        fallback_rows = _fallback_lexical_scan_records(
            query=q,
            channel_type=channel_type,
            owner_id=owner_id,
            top_k=safe_top_k,
            lookback_days=lookback_days,
            layer=layer,
        )
        if fallback_rows:
            selected = _select_by_final_score(fallback_rows, top_k=safe_top_k, query=q, max_chars=max_chars)

    return selected


def retrieve_chat_memories(
    query: str,
    meta: Optional[Dict[str, Any]] = None,
    top_k: int = DEFAULT_TOPK,
    lookback_days: Optional[int] = None,
    layer: Optional[str] = None,
    max_chars: int = 1200,
) -> Dict[str, Any]:
    channel_type, owner_id = resolve_channel_owner(meta)
    records = retrieve_chat_memory_records(
        query=query,
        meta=meta,
        top_k=top_k,
        lookback_days=lookback_days,
        layer=layer,
        max_chars=max_chars,
    )
    texts = [str(r.text or "").strip() for r in records if str(r.text or "").strip()]
    ids = [str(r.id or "").strip() for r in records if str(r.id or "").strip()]
    return {
        "records": records,
        "texts": texts,
        "ids": ids,
        "channel_type": channel_type,
        "owner_id": owner_id,
    }


def bump_chat_memory_importance(
    ids: List[str],
    meta: Optional[Dict[str, Any]] = None,
    delta: float = IMPORTANCE_HIT_BOOST,
) -> int:
    clean_ids = [str(x).strip() for x in list(ids or []) if str(x).strip()]
    if not clean_ids:
        return 0
    channel_type, owner_id = resolve_channel_owner(meta)
    try:
        return CHAT_MEM_STORE.bump_importance(
            clean_ids,
            float(delta),
            channel_type=channel_type,
            owner_id=owner_id,
        )
    except Exception:
        return 0


def retrieve_memories(
    query: str,
    top_k: int = 20,
    user_id: Optional[str] = None,
    scene: Optional[str] = None,
    layer: Optional[str] = None,
    lookback_days: Optional[int] = None,
    channel_type: Optional[str] = None,
    owner_id: Optional[str] = None,
) -> List[str]:
    meta = {
        "user_id": user_id,
        "scene": scene,
        "channel_type": channel_type,
        "owner_id": owner_id,
    }
    records = retrieve_chat_memory_records(
        query=query,
        meta=meta,
        top_k=top_k,
        lookback_days=lookback_days,
        layer=layer,
    )
    return [str(r.text or "") for r in records if str(r.text or "").strip()]


def retrieve_memory_records(
    query: str,
    top_k: int = 20,
    user_id: Optional[str] = None,
    scene: Optional[str] = None,
    layer: Optional[str] = None,
    lookback_days: Optional[int] = None,
    channel_type: Optional[str] = None,
    owner_id: Optional[str] = None,
) -> List[MemoryRecord]:
    meta = {
        "user_id": user_id,
        "scene": scene,
        "channel_type": channel_type,
        "owner_id": owner_id,
    }
    return retrieve_chat_memory_records(
        query=query,
        meta=meta,
        top_k=top_k,
        lookback_days=lookback_days,
        layer=layer,
    )


def load_trigger_keywords() -> List[str]:
    try:
        if os.path.exists(KEYWORDS_FILE):
            with open(KEYWORDS_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
            if isinstance(data, list):
                out = [str(x).strip() for x in data if str(x).strip()]
                if out:
                    return out
    except Exception:
        pass
    return [
        "你还记得", "还记得", "记不记得", "想当初", "之前", "上次", "那次", "那天", "回忆", "回想",
        "remember", "do you remember", "recall", "last time", "previously", "before",
        "we talked about", "we discussed",
    ]


def fuzzy_trigger(text: str) -> bool:
    t = (text or "").strip()
    if not t:
        return False
    zh_pats = [
        r"(你)?还记得",
        r"记得(吗|不|没)",
        r"(回忆|回想)(一下)?",
        r"(上次|那次|那天).*?(说|聊|做|见|谈|发生)",
        r"(之前|过去|曾经).*?(提|聊|说|做|发生)",
    ]
    en_t = t.lower()
    en_pats = [
        r"\bdo you remember\b",
        r"\bremember (when|that|what|if)\b",
        r"\b(can you )?recall\b",
        r"\b(last time|previously|before)\b.*\b(talk|talked|discuss|discussed|say|said|happen|happened|meet|met|did)\b",
        r"\bwe (talked|discussed|mentioned|said)\b",
    ]
    return any(re.search(p, t) for p in zh_pats) or any(re.search(p, en_t) for p in en_pats)


def keyword_trigger(text: str, keys: List[str]) -> bool:
    t = (text or "").strip()
    if not t:
        return False
    t_lower = t.lower()
    for raw_k in keys:
        k = str(raw_k or "").strip()
        if not k:
            continue
        if k in t:
            return True
        # 英文关键词做大小写不敏感匹配；中文逻辑保持不变。
        if k.lower() in t_lower:
            return True
    return False


def _format_texts(texts: List[str], max_chars_per: int = 220) -> str:
    lines: List[str] = []
    for tx in texts:
        s = (tx or "").strip().replace("\n", " ")
        if not s:
            continue
        if len(s) > max_chars_per:
            s = s[:max_chars_per] + "…"
        lines.append(f"• {s}")
    return "\n".join(lines)


# 兼容旧接口：返回 (ok, text)
def retrieve(
    query: str,
    top_k: int = DEFAULT_TOPK,
    lookback_days: int = 180,
) -> Tuple[bool, str]:
    texts = retrieve_memories(
        query=query,
        top_k=top_k,
        lookback_days=lookback_days,
    )
    if not texts:
        return False, "抱歉，我想不起这段记忆了。"
    return True, _format_texts(texts)


# 兼容旧接口：触发式召回
def retrieve_with_trigger(
    user_text: str,
    lookback_days: int = 180,
    top_k: int = DEFAULT_TOPK,
) -> Tuple[bool, str]:
    keys = load_trigger_keywords()
    need = fuzzy_trigger(user_text) or keyword_trigger(user_text, keys)
    if not need:
        if LIGHT_TOPK <= 0:
            return False, ""
        ok, txt = retrieve(user_text, top_k=LIGHT_TOPK, lookback_days=lookback_days)
        return ok, txt if ok else ""

    ok, txt = retrieve(user_text, top_k=top_k, lookback_days=lookback_days)
    return ok, txt if ok else "抱歉，我想不起这段记忆了。"


if __name__ == "__main__":
    import sys

    q = " ".join(sys.argv[1:]) if len(sys.argv) > 1 else "你还记得第一次见面吗？"
    ok, text = retrieve_with_trigger(q, lookback_days=180, top_k=3)
    if not ok and not text:
        print("(未触发，且轻量模式无返回)")
    else:
        print(text)
