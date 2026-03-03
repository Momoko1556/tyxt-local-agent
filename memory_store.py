# -*- coding: utf-8 -*-
from __future__ import annotations

import json
import logging
import os
import re
import time
import uuid
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple

import chromadb
import requests

try:
    from dotenv import load_dotenv  # type: ignore
except Exception:
    load_dotenv = None

if load_dotenv:
    _DOTENV_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env")
    load_dotenv(_DOTENV_PATH, override=False)

PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))
CHROMA_PERSIST_DIR = os.getenv(
    "TYXT_CHROMA_DIR",
    os.path.join(PROJECT_ROOT, "memory_db"),
)
CHROMA_PERSIST_DIR = os.path.abspath(str(CHROMA_PERSIST_DIR))
CHROMA_COLLECTION_NAME = os.getenv(
    "TYXT_CHROMA_COLLECTION",
    "tyxt_memory",
)
TYXT_FALLBACK_COLLECTION = os.getenv(
    "TYXT_CHROMA_FALLBACK_COLLECTION",
    "tyxt_misc",
)
LOCAL_OWNER_ID = os.getenv("TYXT_LOCAL_OWNER_ID", "local_admin").strip() or "local_admin"
IMPORTANCE_MAX = float(os.getenv("IMPORTANCE_MAX", "10.0"))

"""
TYXT 记忆系统 · metadata 规范表（schema_version = 1）

每条向量记忆的 metadata 至少应包含：

- user_id: str
    - 逻辑用户 ID
    - 格式：
        - "qq_<qq号>"（私聊用户）
        - "group_<群号>"（群聊汇总）
        - "local_admin"（本地 UI 管理员）
    - 例："qq_12345678"

- channel_type: str
    - 渠道类型（枚举）
    - 允许值：
        - "private"  私聊
        - "group"    群聊
        - "local"    本地 UI

- owner_id: str
    - 渠道内的“所有者”标识
    - 对应 QQ 号或群号等（不带前缀）
    - 例："12345678"、"123456789"、"local_admin"

- collection_name: str
    - Chroma collection 名
    - 命名规则：
        - 私聊： "tyxt_u_<owner_id>"
        - 群聊： "tyxt_g_<owner_id>"
        - 本地： "tyxt_u_local_admin"

- scene: str
    - 触发来源场景（枚举，后续可扩展）
    - 推荐值：
        - "ui_chat"        本地 UI 对话
        - "qq_private"     NapCat 私聊
        - "qq_group"       NapCat 群聊
        - "system_task"    系统后台任务
        - "import_tool"    导入工具脚本

- source: str
    - 写入来源（更细的来源标识）
    - 推荐值：
        - "online_conv"       在线对话（/chat）
        - "chatgpt_export"    ChatGPT 导出导入
        - "kb_file"           知识库文件导入
        - "runtime_log"       runtime_logs 导出
        - "manual_fix"        管理员手工补录

- layer: str
    - 所属“记忆层”（逻辑分层）
    - 枚举：
        - "raw"         原始日志（RAW 仓库）
        - "conv"        对话类长期记忆（在线对话）
        - "kb"          知识库
        - "bookshelf"   书架层
        - "vault"       金库层
        - "online"      在线生成（online 仓库）

- importance: float
    - 重要度（0.0 ~ 10.0）
    - 初始值规则：
        - 在线对话：按 _online_initial_importance 规则
        - ChatGPT 导入：7.0
        - 知识库导入：6.0
        - 通用 add_memories 未指定时：5.0
    - 后续会按“命中次数 + 衰减”动态调整

- timestamp: float | int
    - Unix 时间戳（秒）

- deleted: bool
    - 软删除标记
    - False：正常可用
    - True：已软删，默认检索会排除
- deleted_at: float | None
    - 被软删除的时间戳（可选）
- deleted_by: str | None
    - 谁发起的删除（当前约定为 "admin"）

可选扩展字段（按场景出现）：

- emotion: str            # 情绪枚举："positive" / "negative" / "neutral" / "mixed"
- topic_tags: List[str]   # 主题标签数组，例如 ["本地部署", "NapCat"]
- fingerprint: str        # 内容指纹，用于查重
- conversation_id: str    # ChatGPT 导入的会话 ID
- turn_index: int         # 对话轮次序号
- file_path: str          # 知识库文件绝对路径
- file_name: str          # 知识库文件名
- page: int               # 文档页码（如 PDF）
- kb_namespace: str       # 知识库命名空间（预留）

所有写入 metadata 的代码路径必须遵守以上规范：
- 枚举字段使用固定字符串，不随意造新值。
- 未给 importance 时，最终应落成 5.0（见 add_memories 逻辑）。
"""

TYXT_SCHEMA_VERSION = 1

TYXT_CHANNEL_PRIVATE = "private"
TYXT_CHANNEL_GROUP = "group"
TYXT_CHANNEL_LOCAL = "local"
TYXT_CHANNEL_TYPES = [TYXT_CHANNEL_PRIVATE, TYXT_CHANNEL_GROUP, TYXT_CHANNEL_LOCAL]

TYXT_LAYER_VALUES = ["raw", "conv", "kb", "bookshelf", "vault", "online"]

TYXT_SCENE_UI_CHAT = "ui_chat"
TYXT_SCENE_QQ_PRIVATE = "qq_private"
TYXT_SCENE_QQ_GROUP = "qq_group"
TYXT_SCENE_SYSTEM_TASK = "system_task"
TYXT_SCENE_IMPORT_TOOL = "import_tool"
TYXT_SCENE_LOCAL_UI_LEGACY = "local_ui"  # 兼容历史数据

TYXT_SOURCE_ONLINE_CONV = "online_conv"
TYXT_SOURCE_CHATGPT_EXPORT = "chatgpt_export"
TYXT_SOURCE_KB_FILE = "kb_file"
TYXT_SOURCE_RUNTIME_LOG = "runtime_log"
TYXT_SOURCE_MANUAL_FIX = "manual_fix"


logger = logging.getLogger(__name__)


@dataclass
class MemoryRecord:
    id: str
    text: str
    metadata: Dict[str, Any]
    score: Optional[float] = None


class MemoryStore:
    def add(self, texts: List[str], metadatas: Optional[List[Dict[str, Any]]] = None) -> List[str]:
        raise NotImplementedError

    def search(
        self,
        query: str,
        top_k: int = 20,
        filters: Optional[Dict[str, Any]] = None,
    ) -> List[MemoryRecord]:
        raise NotImplementedError

    def search_raw(
        self,
        query: str,
        top_k: int = 20,
        filters: Optional[Dict[str, Any]] = None,
    ) -> List[MemoryRecord]:
        raise NotImplementedError

    def delete(self, ids: List[str], **kwargs: Any) -> int:
        raise NotImplementedError

    def bump_importance(self, ids: List[str], delta: float, **kwargs: Any) -> int:
        raise NotImplementedError


def _to_bool(v: Any, default: bool = False) -> bool:
    if isinstance(v, bool):
        return v
    if v is None:
        return bool(default)
    if isinstance(v, (int, float)):
        return bool(v)
    s = str(v).strip().lower()
    if s in {"1", "true", "yes", "y", "on"}:
        return True
    if s in {"0", "false", "no", "n", "off"}:
        return False
    return bool(default)


class _OllamaEmbeddingFunction:
    def __init__(self):
        base = (os.getenv("OLLAMA_BASE_URL", "http://127.0.0.1:11434/v1") or "").strip().rstrip("/")
        if base.endswith("/v1"):
            base = base[:-3]
        self.url = f"{base.rstrip('/')}/api/embeddings"
        self.model = os.getenv("MEM_EMBED_MODEL", "bge-m3")
        self.timeout = int(os.getenv("EMBED_TIMEOUT_S", "60"))
        self.dim = int(os.getenv("EMBED_DIM_DEFAULT", "1024"))
        self._session = requests.Session()

    def __call__(self, input: List[str]) -> List[List[float]]:
        vectors: List[List[float]] = []
        for text in list(input or []):
            try:
                resp = self._session.post(
                    self.url,
                    json={"model": self.model, "prompt": str(text)},
                    timeout=self.timeout,
                )
                resp.raise_for_status()
                emb = (resp.json() or {}).get("embedding") or []
                if isinstance(emb, list) and emb:
                    self.dim = len(emb)
                    vectors.append(emb)
                else:
                    vectors.append([0.0] * self.dim)
            except Exception:
                vectors.append([0.0] * self.dim)
        return vectors


def _safe_token(v: Any, default: str = "unknown", max_len: int = 96) -> str:
    s = str(v or "").strip()
    if not s:
        return default
    s = re.sub(r"[^0-9A-Za-z_\-]+", "_", s).strip("._")
    if not s:
        return default
    if len(s) > max_len:
        s = s[:max_len].rstrip("._")
    return s or default


def make_collection_name(channel_type: str, owner_id: str) -> str:
    """
    根据 channel_type 和 owner_id 生成 collection 名称。
    - private: tyxt_u_<qq>
    - group:   tyxt_g_<group_id>
    - local:   tyxt_u_local_admin
    """
    c = str(channel_type or "").strip().lower()
    owner = _safe_token(owner_id, default=LOCAL_OWNER_ID)
    if c == TYXT_CHANNEL_GROUP:
        return f"tyxt_g_{owner}"
    if c == TYXT_CHANNEL_LOCAL:
        return f"tyxt_u_{_safe_token(owner or LOCAL_OWNER_ID, default=LOCAL_OWNER_ID)}"
    return f"tyxt_u_{owner}"


def parse_collection_name(collection_name: str) -> Tuple[str, str]:
    """
    反解析 collection 名 -> (channel_type, owner_id)
    - tyxt_g_<gid> -> ("group", gid)
    - tyxt_u_local_admin -> ("local", "local_admin")
    - tyxt_u_<uid> -> ("private", uid)
    """
    name = str(collection_name or "").strip()
    if name.startswith("tyxt_g_"):
        return TYXT_CHANNEL_GROUP, name[len("tyxt_g_") :] or "unknown_group"
    if name.startswith("tyxt_u_"):
        owner = name[len("tyxt_u_") :] or "unknown_user"
        if owner == LOCAL_OWNER_ID:
            return TYXT_CHANNEL_LOCAL, owner
        return TYXT_CHANNEL_PRIVATE, owner
    return TYXT_CHANNEL_PRIVATE, "unknown_user"


def _scene_to_channel_owner(meta: Dict[str, Any]) -> Tuple[str, str]:
    scene = str(meta.get("scene") or "").strip().lower()
    gid = str(meta.get("group_id") or "").strip()
    uid = str(meta.get("user_id") or "").strip()

    if scene.startswith(f"{TYXT_SCENE_QQ_GROUP}:"):
        return TYXT_CHANNEL_GROUP, _safe_token(scene.split(":", 1)[1], default=(gid or "unknown_group"))
    if scene.startswith(f"{TYXT_SCENE_QQ_PRIVATE}:"):
        owner = scene.split(":", 1)[1].strip()
        if owner:
            return TYXT_CHANNEL_PRIVATE, _safe_token(owner, default="unknown_user")

    if scene in {TYXT_CHANNEL_LOCAL, TYXT_SCENE_LOCAL_UI_LEGACY, "ui", "chat"}:
        return TYXT_CHANNEL_LOCAL, _safe_token(meta.get("owner_id") or LOCAL_OWNER_ID, default=LOCAL_OWNER_ID)

    if scene == TYXT_CHANNEL_GROUP or gid:
        return TYXT_CHANNEL_GROUP, _safe_token(gid or "unknown_group", default="unknown_group")

    if scene == TYXT_CHANNEL_PRIVATE:
        if uid and uid.lower() != "anonymous":
            return TYXT_CHANNEL_PRIVATE, _safe_token(uid, default="unknown_user")
        return TYXT_CHANNEL_LOCAL, _safe_token(LOCAL_OWNER_ID, default=LOCAL_OWNER_ID)

    if uid and uid.lower() != "anonymous":
        return TYXT_CHANNEL_PRIVATE, _safe_token(uid, default="unknown_user")

    return TYXT_CHANNEL_LOCAL, _safe_token(LOCAL_OWNER_ID, default=LOCAL_OWNER_ID)


def infer_channel_owner(meta: Optional[Dict[str, Any]]) -> Tuple[str, str]:
    m = dict(meta or {})
    channel_type = str(m.get("channel_type") or "").strip().lower()
    owner_id = str(m.get("owner_id") or "").strip()
    if channel_type and owner_id:
        if channel_type == TYXT_CHANNEL_GROUP:
            return TYXT_CHANNEL_GROUP, _safe_token(owner_id, default="unknown_group")
        if channel_type == TYXT_CHANNEL_LOCAL:
            return TYXT_CHANNEL_LOCAL, _safe_token(owner_id, default=LOCAL_OWNER_ID)
        return TYXT_CHANNEL_PRIVATE, _safe_token(owner_id, default="unknown_user")
    return _scene_to_channel_owner(m)


def normalize_metadata(
    meta: Optional[Dict[str, Any]],
    default_timestamp: Optional[int] = None,
) -> Dict[str, Any]:
    """
    统一规范 memory metadata 字段，补默认值。

    约定字段：
      - user_id: str | None
      - scene: str | None
      - source: str | None
      - layer: str
      - channel_type: private/group/local
      - owner_id: str
      - importance: float [0.0, 10.0]
      - timestamp: int
      - fingerprint: str(可选)

    注意：如果 metadata 中完全没有 importance，会默认写成 5.0，
    并裁剪到 [0.0, 10.0]。
    """
    if meta is None:
        meta = {}
    else:
        meta = dict(meta)

    user_id = str(meta.get("user_id") or "").strip() or None
    scene = str(meta.get("scene") or "").strip() or None
    source = str(meta.get("source") or "").strip() or None
    layer = str(meta.get("layer") or "default").strip() or "default"

    channel_type, owner_id = infer_channel_owner(meta)

    if not scene:
        if channel_type == TYXT_CHANNEL_GROUP:
            scene = f"{TYXT_SCENE_QQ_GROUP}:{owner_id}"
        elif channel_type == TYXT_CHANNEL_PRIVATE:
            scene = f"{TYXT_SCENE_QQ_PRIVATE}:{owner_id}"
        else:
            scene = TYXT_SCENE_LOCAL_UI_LEGACY

    if (not user_id) and channel_type == TYXT_CHANNEL_PRIVATE and owner_id != LOCAL_OWNER_ID:
        user_id = owner_id

    try:
        importance = float(meta.get("importance", 5.0))
    except (TypeError, ValueError):
        importance = 5.0
    importance = max(0.0, min(IMPORTANCE_MAX, importance))

    ts = meta.get("timestamp")
    if isinstance(ts, str):
        try:
            ts = int(float(ts))
        except ValueError:
            ts = None
    if not isinstance(ts, int):
        ts = default_timestamp if default_timestamp is not None else int(time.time())

    out = dict(meta)
    out["user_id"] = user_id
    out["scene"] = scene
    out["source"] = source
    out["layer"] = layer
    out["channel_type"] = channel_type
    out["owner_id"] = owner_id
    out["importance"] = float(importance)
    out["timestamp"] = int(ts)
    deleted = _to_bool(meta.get("deleted", False), default=False)
    out["deleted"] = bool(deleted)
    if "deleted_at" in meta:
        try:
            out["deleted_at"] = int(float(meta.get("deleted_at")))
        except Exception:
            out["deleted_at"] = meta.get("deleted_at")
    if "deleted_by" in meta:
        out["deleted_by"] = str(meta.get("deleted_by") or "").strip() or None
    return out


def _sanitize_for_chroma(meta: Dict[str, Any]) -> Dict[str, Any]:
    out: Dict[str, Any] = {}
    for key, value in (meta or {}).items():
        if value is None:
            continue
        if isinstance(value, (str, int, float, bool)):
            out[key] = value
        else:
            try:
                out[key] = json.dumps(value, ensure_ascii=False)
            except Exception:
                out[key] = str(value)
    return out


class ChromaMemoryStore(MemoryStore):
    def __init__(
        self,
        persist_dir: str = CHROMA_PERSIST_DIR,
        collection_name: str = CHROMA_COLLECTION_NAME,
        embedding_function: Optional[Any] = None,
    ):
        os.makedirs(persist_dir, exist_ok=True)
        self._persist_dir = persist_dir
        self._collection_name = collection_name
        self._embedding_function = embedding_function if embedding_function is not None else _OllamaEmbeddingFunction()
        self._client = chromadb.PersistentClient(path=persist_dir)
        if self._embedding_function is None:
            self._collection = self._client.get_or_create_collection(name=collection_name)
        else:
            self._collection = self._client.get_or_create_collection(
                name=collection_name,
                embedding_function=self._embedding_function,
            )

    def _build_where(self, filters: Optional[Dict[str, Any]]) -> Dict[str, Any]:
        filters = dict(filters or {})
        clauses: List[Dict[str, Any]] = []

        lookback_days = filters.pop("lookback_days", None)
        if lookback_days is not None:
            try:
                days = int(lookback_days)
                if days > 0:
                    min_ts = int(time.time()) - days * 86400
                    clauses.append({"timestamp": {"$gte": min_ts}})
            except Exception:
                pass

        for key, value in filters.items():
            if value is None:
                continue
            if isinstance(value, (list, tuple, set)):
                vals = [v for v in value if v is not None]
                if vals:
                    clauses.append({key: {"$in": list(vals)}})
            else:
                clauses.append({key: value})

        # 新版 Chroma where 只接受“单表达式”或逻辑表达式；
        # 多字段并列需要显式包装为 $and，否则会报：
        # Expected where to have exactly one operator
        if not clauses:
            return {}
        if len(clauses) == 1:
            return clauses[0]
        return {"$and": clauses}

    def add(self, texts: List[str], metadatas: Optional[List[Dict[str, Any]]] = None) -> List[str]:
        now_ts = int(time.time())
        text_list = [str(t or "").strip() for t in list(texts or [])]
        if metadatas is None:
            metadatas = [{} for _ in text_list]
        if len(metadatas) < len(text_list):
            metadatas = list(metadatas) + ([{}] * (len(text_list) - len(metadatas)))

        docs: List[str] = []
        ids: List[str] = []
        norm_metas: List[Dict[str, Any]] = []
        for text, raw_meta in zip(text_list, metadatas):
            if not text:
                continue
            nm = normalize_metadata(raw_meta, default_timestamp=now_ts)
            mem_id = str(nm.get("id") or f"mem_{now_ts}_{uuid.uuid4().hex[:8]}")
            nm["id"] = mem_id
            nm["collection_name"] = self._collection_name
            docs.append(text)
            ids.append(mem_id)
            norm_metas.append(_sanitize_for_chroma(nm))

        if not docs:
            return []
        self._collection.add(ids=ids, documents=docs, metadatas=norm_metas)
        return ids

    def _records_from_result(self, res: Dict[str, Any]) -> List[MemoryRecord]:
        ids = ((res or {}).get("ids") or [[]])[0] or []
        docs = ((res or {}).get("documents") or [[]])[0] or []
        metadatas = ((res or {}).get("metadatas") or [[]])[0] or []
        distance_outer = (res or {}).get("distances")
        score_outer = (res or {}).get("scores")

        if isinstance(distance_outer, list) and distance_outer:
            score_list = distance_outer[0] or []
        elif isinstance(score_outer, list) and score_outer:
            score_list = score_outer[0] or []
        else:
            score_list = [None] * len(ids)

        records: List[MemoryRecord] = []
        for idx, mem_id in enumerate(ids):
            text = docs[idx] if idx < len(docs) else ""
            meta = metadatas[idx] if idx < len(metadatas) else {}
            score = score_list[idx] if idx < len(score_list) else None
            nm = normalize_metadata(meta, default_timestamp=None)
            nm["collection_name"] = self._collection_name
            records.append(
                MemoryRecord(
                    id=str(mem_id),
                    text=str(text or ""),
                    metadata=nm,
                    score=float(score) if isinstance(score, (int, float)) else None,
                )
            )
        return records

    def search_raw(
        self,
        query: str,
        top_k: int = 20,
        filters: Optional[Dict[str, Any]] = None,
    ) -> List[MemoryRecord]:
        if not str(query or "").strip():
            return []
        safe_top_k = max(1, int(top_k or 1))
        where = self._build_where(filters)
        try:
            res = self._collection.query(
                query_texts=[str(query)],
                n_results=safe_top_k,
                where=where or None,
            )
        except Exception as exc:
            logger.exception("memory search_raw failed: %s", exc)
            return []
        return self._records_from_result(res or {})

    def search(
        self,
        query: str,
        top_k: int = 20,
        filters: Optional[Dict[str, Any]] = None,
    ) -> List[MemoryRecord]:
        safe_top_k = max(1, int(top_k or 1))
        raw_top_k = max(safe_top_k * 3, 30)
        records = self.search_raw(query=query, top_k=raw_top_k, filters=filters)
        return self._select_memories(records, top_k=safe_top_k)

    def _select_memories(
        self,
        records: List[MemoryRecord],
        top_k: int,
        max_chars: int = 1200,
    ) -> List[MemoryRecord]:
        def sort_key(rec: MemoryRecord) -> Tuple[float, int]:
            meta = rec.metadata or {}
            try:
                imp = float(meta.get("importance", 5.0))
            except (TypeError, ValueError):
                imp = 5.0
            try:
                ts = int(meta.get("timestamp", 0))
            except (TypeError, ValueError):
                ts = 0
            return (-imp, -ts)

        records_sorted = sorted(records, key=sort_key)
        selected: List[MemoryRecord] = []
        total_chars = 0
        for rec in records_sorted:
            if len(selected) >= top_k:
                break
            text_len = len(rec.text or "")
            if total_chars + text_len > max_chars and selected:
                break
            selected.append(rec)
            total_chars += text_len
        return selected

    def delete(self, ids: List[str], **kwargs: Any) -> int:
        del kwargs
        clean_ids = [str(x).strip() for x in list(ids or []) if str(x).strip()]
        if not clean_ids:
            return 0
        try:
            self._collection.delete(ids=clean_ids)
            return len(clean_ids)
        except Exception:
            logger.exception("memory delete failed")
            return 0

    def _get_records_by_ids(self, ids: List[str]) -> List[Tuple[str, str, Dict[str, Any]]]:
        clean_ids = [str(x).strip() for x in list(ids or []) if str(x).strip()]
        if not clean_ids:
            return []
        try:
            got = self._collection.get(ids=clean_ids, include=["documents", "metadatas"])
        except Exception:
            try:
                got = self._collection.get(ids=clean_ids)
            except Exception:
                logger.exception("memory get by ids failed")
                return []

        rid_list = list((got or {}).get("ids") or [])
        docs = list((got or {}).get("documents") or [])
        metas = list((got or {}).get("metadatas") or [])
        out: List[Tuple[str, str, Dict[str, Any]]] = []
        for i, rid in enumerate(rid_list):
            doc = str(docs[i] if i < len(docs) else "")
            meta = metas[i] if i < len(metas) and isinstance(metas[i], dict) else {}
            out.append((str(rid), doc, dict(meta)))
        return out

    def bump_importance(self, ids: List[str], delta: float, **kwargs: Any) -> int:
        del kwargs
        clean_ids = [str(x).strip() for x in list(ids or []) if str(x).strip()]
        if not clean_ids:
            return 0
        try:
            d = float(delta)
        except Exception:
            d = 0.0
        if abs(d) < 1e-9:
            return 0

        rows = self._get_records_by_ids(clean_ids)
        if not rows:
            return 0

        up_ids: List[str] = []
        up_docs: List[str] = []
        up_metas: List[Dict[str, Any]] = []
        for rid, doc, meta in rows:
            nm = normalize_metadata(meta, default_timestamp=None)
            try:
                cur = float(nm.get("importance", 5.0))
            except (TypeError, ValueError):
                cur = 5.0
            nm["importance"] = max(0.0, min(IMPORTANCE_MAX, cur + d))
            nm["id"] = rid
            nm["collection_name"] = self._collection_name
            up_ids.append(rid)
            up_docs.append(doc)
            up_metas.append(_sanitize_for_chroma(nm))

        if not up_ids:
            return 0

        try:
            self._collection.upsert(ids=up_ids, documents=up_docs, metadatas=up_metas)
            return len(up_ids)
        except Exception:
            logger.exception("memory bump_importance failed")
            return 0

    def has_fingerprint(self, fingerprint: str) -> bool:
        fp = str(fingerprint or "").strip()
        if not fp:
            return False
        try:
            got = self._collection.get(where={"fingerprint": fp}, limit=1)
            ids = list((got or {}).get("ids") or [])
            if ids:
                return True
        except Exception:
            pass
        try:
            res = self._collection.query(
                query_texts=[fp],
                n_results=1,
                where={"fingerprint": fp},
            )
            ids = ((res or {}).get("ids") or [[]])[0] or []
            return bool(ids)
        except Exception:
            return False


class MultiTenantChromaMemoryStore(MemoryStore):
    def __init__(
        self,
        persist_dir: str = CHROMA_PERSIST_DIR,
        fallback_collection: str = TYXT_FALLBACK_COLLECTION,
        embedding_function: Optional[Any] = None,
    ):
        self._persist_dir = persist_dir
        self._fallback_collection = str(fallback_collection or TYXT_FALLBACK_COLLECTION).strip() or TYXT_FALLBACK_COLLECTION
        self._embedding_function = embedding_function if embedding_function is not None else _OllamaEmbeddingFunction()
        self._stores: Dict[str, ChromaMemoryStore] = {}
        os.makedirs(self._persist_dir, exist_ok=True)
        self._client = chromadb.PersistentClient(path=self._persist_dir)

    def _get_store_by_collection(self, collection_name: str) -> ChromaMemoryStore:
        cname = str(collection_name or "").strip() or self._fallback_collection
        if cname not in self._stores:
            self._stores[cname] = ChromaMemoryStore(
                persist_dir=self._persist_dir,
                collection_name=cname,
                embedding_function=self._embedding_function,
            )
        return self._stores[cname]

    def _route(self, payload: Optional[Dict[str, Any]]) -> Tuple[str, str, str]:
        data = dict(payload or {})
        raw_ct = str(data.get("channel_type") or "").strip().lower()
        raw_owner = str(data.get("owner_id") or "").strip()

        if raw_ct and raw_owner:
            channel_type, owner_id = infer_channel_owner({"channel_type": raw_ct, "owner_id": raw_owner})
            return channel_type, owner_id, make_collection_name(channel_type, owner_id)

        has_hint = bool(
            str(data.get("scene") or "").strip()
            or str(data.get("group_id") or "").strip()
            or str(data.get("user_id") or "").strip()
        )
        if has_hint:
            channel_type, owner_id = infer_channel_owner(data)
            return channel_type, owner_id, make_collection_name(channel_type, owner_id)

        logger.warning(
            "MultiTenant route missing channel_type/owner_id and hints, fallback collection=%s",
            self._fallback_collection,
        )
        return "fallback", "misc", self._fallback_collection

    def add(self, texts: List[str], metadatas: Optional[List[Dict[str, Any]]] = None) -> List[str]:
        text_list = [str(t or "").strip() for t in list(texts or [])]
        if metadatas is None:
            metadatas = [{} for _ in text_list]
        if len(metadatas) < len(text_list):
            metadatas = list(metadatas) + ([{}] * (len(text_list) - len(metadatas)))

        buckets: Dict[str, Dict[str, Any]] = {}
        for text, raw_meta in zip(text_list, metadatas):
            if not text:
                continue
            meta = dict(raw_meta or {})
            channel_type, owner_id, coll_name = self._route(meta)
            if coll_name == self._fallback_collection:
                meta["channel_type"] = "fallback"
                meta["owner_id"] = "misc"
            else:
                meta["channel_type"] = channel_type
                meta["owner_id"] = owner_id
            meta["collection_name"] = coll_name
            if coll_name not in buckets:
                buckets[coll_name] = {"texts": [], "metadatas": []}
            buckets[coll_name]["texts"].append(text)
            buckets[coll_name]["metadatas"].append(meta)

        all_ids: List[str] = []
        for coll_name, payload in buckets.items():
            store = self._get_store_by_collection(coll_name)
            ids = store.add(texts=payload["texts"], metadatas=payload["metadatas"])
            all_ids.extend(ids)
        return all_ids

    def search_raw(
        self,
        query: str,
        top_k: int = 20,
        filters: Optional[Dict[str, Any]] = None,
    ) -> List[MemoryRecord]:
        channel_type, owner_id, coll_name = self._route(filters or {})
        store = self._get_store_by_collection(coll_name)
        pass_filters = dict(filters or {})
        pass_filters.pop("channel_type", None)
        pass_filters.pop("owner_id", None)
        records = store.search_raw(query=query, top_k=top_k, filters=pass_filters)
        for rec in records:
            rec.metadata["collection_name"] = coll_name
            if coll_name == self._fallback_collection:
                rec.metadata["channel_type"] = "fallback"
                rec.metadata["owner_id"] = "misc"
            else:
                rec.metadata.setdefault("channel_type", channel_type)
                rec.metadata.setdefault("owner_id", owner_id)
        return records

    def search(
        self,
        query: str,
        top_k: int = 20,
        filters: Optional[Dict[str, Any]] = None,
    ) -> List[MemoryRecord]:
        channel_type, owner_id, coll_name = self._route(filters or {})
        store = self._get_store_by_collection(coll_name)
        pass_filters = dict(filters or {})
        pass_filters.pop("channel_type", None)
        pass_filters.pop("owner_id", None)
        records = store.search(query=query, top_k=top_k, filters=pass_filters)
        for rec in records:
            rec.metadata["collection_name"] = coll_name
            if coll_name == self._fallback_collection:
                rec.metadata["channel_type"] = "fallback"
                rec.metadata["owner_id"] = "misc"
            else:
                rec.metadata.setdefault("channel_type", channel_type)
                rec.metadata.setdefault("owner_id", owner_id)
        return records

    def delete(self, ids: List[str], **kwargs: Any) -> int:
        clean_ids = [str(x).strip() for x in list(ids or []) if str(x).strip()]
        if not clean_ids:
            return 0
        channel_type = kwargs.get("channel_type")
        owner_id = kwargs.get("owner_id")
        route_meta = {"channel_type": channel_type, "owner_id": owner_id}
        _, _, coll_name = self._route(route_meta)
        store = self._get_store_by_collection(coll_name)
        return store.delete(clean_ids)

    def bump_importance(self, ids: List[str], delta: float, **kwargs: Any) -> int:
        clean_ids = [str(x).strip() for x in list(ids or []) if str(x).strip()]
        if not clean_ids:
            return 0
        channel_type = kwargs.get("channel_type")
        owner_id = kwargs.get("owner_id")
        route_meta = {"channel_type": channel_type, "owner_id": owner_id}
        _, _, coll_name = self._route(route_meta)
        store = self._get_store_by_collection(coll_name)
        return store.bump_importance(clean_ids, delta)

    def has_fingerprint(self, channel_type: str, owner_id: str, fingerprint: str) -> bool:
        _, _, coll_name = self._route(
            {
                "channel_type": str(channel_type or "").strip().lower(),
                "owner_id": str(owner_id or "").strip(),
            }
        )
        store = self._get_store_by_collection(coll_name)
        return store.has_fingerprint(fingerprint)

    def get_record(self, channel_type: str, owner_id: str, mem_id: str) -> Optional[MemoryRecord]:
        mid = str(mem_id or "").strip()
        if not mid:
            return None
        _, _, coll_name = self._route({"channel_type": channel_type, "owner_id": owner_id})
        store = self._get_store_by_collection(coll_name)
        rows = store._get_records_by_ids([mid])
        if not rows:
            return None
        rid, doc, meta = rows[0]
        nm = normalize_metadata(meta, default_timestamp=None)
        nm["collection_name"] = coll_name
        return MemoryRecord(id=rid, text=doc, metadata=nm, score=None)

    def list_tenants(self) -> List[Dict[str, Any]]:
        out: List[Dict[str, Any]] = []
        try:
            cols = self._client.list_collections()
        except Exception:
            logger.exception("list_collections failed")
            return out

        names: List[str] = []
        for c in list(cols or []):
            try:
                name = str(getattr(c, "name"))
            except Exception:
                name = str(c or "")
            if name:
                names.append(name)

        for cname in sorted(set(names)):
            if (not cname.startswith("tyxt_u_")) and (not cname.startswith("tyxt_g_")):
                continue
            try:
                channel_type, owner_id = parse_collection_name(cname)
                store = self._get_store_by_collection(cname)
                count = int(store._collection.count())
                # 忽略空租户集合，避免管理界面出现“记录 0”的噪音项
                if count <= 0:
                    continue
                got = store._collection.get(include=["metadatas"])
                metas = list((got or {}).get("metadatas") or [])
                last_ts = 0
                deleted_count = 0
                for m in metas:
                    nm = normalize_metadata(m if isinstance(m, dict) else {}, default_timestamp=None)
                    try:
                        ts = int(nm.get("timestamp") or 0)
                    except Exception:
                        ts = 0
                    if ts > last_ts:
                        last_ts = ts
                    if bool(nm.get("deleted") is True):
                        deleted_count += 1
                out.append(
                    {
                        "channel_type": channel_type,
                        "owner_id": owner_id,
                        "collection": cname,
                        "doc_count": count,
                        "last_ts": int(last_ts) if last_ts > 0 else None,
                        "deleted_count": int(deleted_count),
                    }
                )
            except Exception:
                logger.exception("list tenant stats failed: %s", cname)
                continue
        return out

    def list_records(
        self,
        channel_type: str,
        owner_id: str,
        page: int = 1,
        page_size: int = 20,
        include_deleted: bool = False,
    ) -> Dict[str, Any]:
        p = max(1, int(page or 1))
        sz = max(1, min(100, int(page_size or 20)))
        _, _, coll_name = self._route({"channel_type": channel_type, "owner_id": owner_id})
        store = self._get_store_by_collection(coll_name)

        where = None
        if not include_deleted:
            where = {"deleted": {"$ne": True}}

        try:
            got = store._collection.get(where=where, include=["documents", "metadatas"])
        except Exception:
            logger.exception("list_records get failed")
            got = {"ids": [], "documents": [], "metadatas": []}

        ids = list((got or {}).get("ids") or [])
        docs = list((got or {}).get("documents") or [])
        metas = list((got or {}).get("metadatas") or [])

        rows: List[MemoryRecord] = []
        for i, rid in enumerate(ids):
            doc = str(docs[i] if i < len(docs) else "")
            meta = metas[i] if i < len(metas) and isinstance(metas[i], dict) else {}
            nm = normalize_metadata(meta, default_timestamp=None)
            nm["collection_name"] = coll_name
            rows.append(MemoryRecord(id=str(rid), text=doc, metadata=nm, score=None))

        rows.sort(key=lambda r: int((r.metadata or {}).get("timestamp") or 0), reverse=True)
        total = len(rows)
        st = (p - 1) * sz
        ed = st + sz
        page_rows = rows[st:ed]
        return {
            "collection": coll_name,
            "total": total,
            "page": p,
            "page_size": sz,
            "records": page_rows,
        }

    def soft_delete(
        self,
        channel_type: str,
        owner_id: str,
        mem_id: str,
        deleted: bool,
        deleted_by: Optional[str] = None,
    ) -> bool:
        rec = self.get_record(channel_type, owner_id, mem_id)
        if rec is None:
            return False
        _, _, coll_name = self._route({"channel_type": channel_type, "owner_id": owner_id})
        store = self._get_store_by_collection(coll_name)
        meta = normalize_metadata(rec.metadata, default_timestamp=None)
        meta["deleted"] = bool(deleted)
        if deleted:
            meta["deleted_at"] = int(time.time())
            if deleted_by:
                meta["deleted_by"] = str(deleted_by).strip()
        meta["id"] = rec.id
        meta["collection_name"] = coll_name
        try:
            store._collection.upsert(
                ids=[rec.id],
                documents=[rec.text],
                metadatas=[_sanitize_for_chroma(meta)],
            )
            return True
        except Exception:
            logger.exception("soft_delete upsert failed")
            return False

    def set_importance(
        self,
        channel_type: str,
        owner_id: str,
        mem_id: str,
        mode: str,
        value: float,
    ) -> Optional[float]:
        rec = self.get_record(channel_type, owner_id, mem_id)
        if rec is None:
            return None
        _, _, coll_name = self._route({"channel_type": channel_type, "owner_id": owner_id})
        store = self._get_store_by_collection(coll_name)
        meta = normalize_metadata(rec.metadata, default_timestamp=None)
        try:
            cur = float(meta.get("importance", 5.0))
        except Exception:
            cur = 5.0
        try:
            val = float(value)
        except Exception:
            val = 0.0

        m = str(mode or "delta").strip().lower()
        if m == "set":
            new_imp = val
        else:
            new_imp = cur + val
        new_imp = max(0.0, min(IMPORTANCE_MAX, float(new_imp)))

        meta["importance"] = new_imp
        meta["id"] = rec.id
        meta["collection_name"] = coll_name
        try:
            store._collection.upsert(
                ids=[rec.id],
                documents=[rec.text],
                metadatas=[_sanitize_for_chroma(meta)],
            )
            return float(new_imp)
        except Exception:
            logger.exception("set_importance upsert failed")
            return None
