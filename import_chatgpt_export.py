# -*- coding: utf-8 -*-
"""
import_chatgpt_export.py

离线导入：ChatGPT 导出 JSON -> 多租户 Chroma MemoryStore

功能：
1) 读取 JSON 文件或目录下 JSON 文件
2) 归一化为 (conversation_id, turn_index, user_text, assistant_text, timestamp)
3) 先写 RAW JSONL 到 memory_warehouse/import_chatgpt/raw
4) 指纹查重后写入 MultiTenantChromaMemoryStore
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
import time
import uuid
import zipfile
from typing import Any, Dict, Iterable, List, Optional

from memory_store import CHROMA_PERSIST_DIR, LOCAL_OWNER_ID, MultiTenantChromaMemoryStore


PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))
WAREHOUSE_BASE_DIR = os.getenv(
    "TYXT_WAREHOUSE_DIR",
    os.path.join(PROJECT_ROOT, "memory_warehouse"),
)
WAREHOUSE_BASE_DIR = os.path.abspath(str(WAREHOUSE_BASE_DIR))
RAW_DIR = os.path.join(WAREHOUSE_BASE_DIR, "import_chatgpt", "raw")

_NOISE_TOKENS = (
    "image_asset_pointer",
    "asset_pointer",
    "container_pixel_height",
    "container_pixel_width",
    "watermarked_asset_pointer",
    "lpe_",
    "is_no_auth_placeholder",
    "metadata':",
    "\"metadata\":",
)


def _safe_token(value: Any, default: str = "unknown", max_len: int = 96) -> str:
    s = str(value or "").strip()
    if not s:
        return default
    s = re.sub(r"[^0-9A-Za-z_\-]+", "_", s).strip("._")
    if not s:
        return default
    if len(s) > max_len:
        s = s[:max_len].rstrip("._")
    return s or default


def _normalize_ws(text: str) -> str:
    t = str(text or "").replace("\r", "\n")
    t = re.sub(r"\s+", " ", t).strip()
    return t


def _looks_like_noise_line(line: str) -> bool:
    s = str(line or "").strip()
    if not s:
        return True
    sl = s.lower()
    if any(tok in sl for tok in _NOISE_TOKENS):
        return True
    # 形如 Python/JSON 字典串，且字段很多，通常是导出中的结构化元数据噪声
    if len(s) >= 120 and s.count(":") >= 5 and (s.count("{") + s.count("}")) >= 2:
        quoted = s.count("'") + s.count('"')
        if quoted >= 8:
            return True
    return False


def _clean_import_text(text: str) -> str:
    raw = str(text or "").replace("\r", "\n")
    raw = raw.replace("\u200b", "").replace("\ufeff", "")
    lines = []
    for ln in raw.split("\n"):
        s = re.sub(r"\s+", " ", str(ln or "")).strip()
        if not s:
            continue
        if _looks_like_noise_line(s):
            continue
        lines.append(s)
    out = "\n".join(lines).strip()
    out = re.sub(r"\n{3,}", "\n\n", out)
    return out


def _fingerprint(owner_id: str, text: str) -> str:
    seed = f"{owner_id}|{_normalize_ws(text)}"
    return hashlib.sha256(seed.encode("utf-8", errors="ignore")).hexdigest()[:16]


def _extract_content_text(content: Any) -> str:
    if content is None:
        return ""
    if isinstance(content, str):
        return _clean_import_text(content)
    if isinstance(content, list):
        parts: List[str] = []
        for item in content:
            if isinstance(item, (dict, list)):
                txt = _extract_content_text(item)
            else:
                txt = _clean_import_text(str(item or ""))
            if txt:
                parts.append(txt)
        return "\n".join(parts).strip()
    if isinstance(content, dict):
        ctype = str(content.get("content_type") or content.get("type") or "").strip().lower()
        if ctype in {"image_asset_pointer", "asset_pointer", "tool_result", "tool_call"}:
            return ""
        if isinstance(content.get("parts"), list):
            parts: List[str] = []
            for item in content.get("parts", []) or []:
                if isinstance(item, (dict, list)):
                    txt = _extract_content_text(item)
                else:
                    txt = _clean_import_text(str(item or ""))
                if txt:
                    parts.append(txt)
            return "\n".join(parts).strip()
        if isinstance(content.get("text"), str):
            return _clean_import_text(str(content.get("text") or ""))
        if isinstance(content.get("content"), str):
            return _clean_import_text(str(content.get("content") or ""))
        if isinstance(content.get("value"), str):
            return _clean_import_text(str(content.get("value") or ""))
        return ""
    return _clean_import_text(str(content))


def _to_unix_ts(value: Any) -> int:
    now_ts = int(time.time())
    if value is None:
        return now_ts
    try:
        ts = float(value)
    except Exception:
        return now_ts
    # 兼容毫秒时间戳
    if ts > 1e12:
        ts = ts / 1000.0
    if ts <= 0:
        return now_ts
    return int(ts)


def _iter_import_sources(input_path: str) -> List[Dict[str, str]]:
    p = os.path.abspath(str(input_path or "").strip())
    if not p:
        return []
    if os.path.isfile(p):
        ext = os.path.splitext(p)[1].lower()
        if ext in {".json", ".zip"}:
            return [{"path": p, "kind": ext.lstrip(".")}]
        return []
    if not os.path.isdir(p):
        return []
    out: List[Dict[str, str]] = []
    for root, _dirs, files in os.walk(p):
        for fn in files:
            ext = os.path.splitext(fn)[1].lower()
            if ext not in {".json", ".zip"}:
                continue
            out.append({"path": os.path.join(root, fn), "kind": ext.lstrip(".")})
    out.sort(key=lambda x: str(x.get("path") or ""))
    return out


def _decode_json_bytes(raw: bytes) -> str:
    if not raw:
        return ""
    for enc in ("utf-8-sig", "utf-8", "utf-16", "utf-16-le", "utf-16-be", "gb18030", "gbk"):
        try:
            return raw.decode(enc)
        except Exception:
            continue
    return raw.decode("utf-8", errors="ignore")


def _wait_if_paused(
    should_pause: Optional[callable] = None,
    should_stop: Optional[callable] = None,
) -> bool:
    while True:
        try:
            if should_stop and bool(should_stop()):
                return False
        except Exception:
            pass
        paused = False
        try:
            paused = bool(should_pause and should_pause())
        except Exception:
            paused = False
        if not paused:
            return True
        time.sleep(0.2)


def _parse_messages_from_mapping(mapping_obj: Any) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    if not isinstance(mapping_obj, dict):
        return out
    for _node_id, node in mapping_obj.items():
        if not isinstance(node, dict):
            continue
        msg = node.get("message")
        if not isinstance(msg, dict):
            continue
        author = msg.get("author") if isinstance(msg.get("author"), dict) else {}
        role = str(author.get("role") or msg.get("role") or "").strip().lower()
        if role not in {"user", "assistant"}:
            continue
        text = _extract_content_text(msg.get("content"))
        if not text:
            continue
        create_time = msg.get("create_time")
        if create_time is None:
            create_time = node.get("create_time")
        out.append(
            {
                "role": role,
                "text": text,
                "timestamp": _to_unix_ts(create_time),
            }
        )
    out.sort(key=lambda x: int(x.get("timestamp") or 0))
    return out


def _parse_messages_from_list(messages_obj: Any) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    if not isinstance(messages_obj, list):
        return out
    for item in messages_obj:
        if not isinstance(item, dict):
            continue
        role = str(item.get("role") or "").strip().lower()
        if role not in {"user", "assistant"}:
            continue
        text = _extract_content_text(item.get("content"))
        if not text:
            continue
        ts = _to_unix_ts(item.get("create_time") or item.get("timestamp") or item.get("time"))
        out.append({"role": role, "text": text, "timestamp": ts})
    out.sort(key=lambda x: int(x.get("timestamp") or 0))
    return out


def _messages_to_turns(messages: List[Dict[str, Any]], conversation_id: str) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    pending_user: Optional[Dict[str, Any]] = None
    turn_index = 0
    for msg in messages:
        role = str(msg.get("role") or "").strip().lower()
        text = _clean_import_text(str(msg.get("text") or ""))
        ts = int(msg.get("timestamp") or time.time())
        if role == "user":
            pending_user = {"text": text, "timestamp": ts}
            continue
        if role == "assistant" and pending_user and text:
            out.append(
                {
                    "conversation_id": conversation_id,
                    "turn_index": turn_index,
                    "user_text": str(pending_user.get("text") or "").strip(),
                    "assistant_text": text,
                    "timestamp": int(pending_user.get("timestamp") or ts),
                }
            )
            turn_index += 1
            pending_user = None
    return out


def _parse_one_conversation(conv_obj: Dict[str, Any], source_tag: str) -> List[Dict[str, Any]]:
    conversation_id = str(
        conv_obj.get("conversation_id")
        or conv_obj.get("id")
        or conv_obj.get("conversationId")
        or f"conv_{source_tag}_{uuid.uuid4().hex[:8]}"
    ).strip()
    messages = _parse_messages_from_mapping(conv_obj.get("mapping"))
    if not messages:
        messages = _parse_messages_from_list(conv_obj.get("messages"))
    return _messages_to_turns(messages, conversation_id=conversation_id)


def normalize_chatgpt_export(obj: Any, source_tag: str) -> List[Dict[str, Any]]:
    turns: List[Dict[str, Any]] = []
    if isinstance(obj, dict):
        # 单个对话对象
        if isinstance(obj.get("mapping"), dict) or isinstance(obj.get("messages"), list):
            turns.extend(_parse_one_conversation(obj, source_tag=source_tag))
        # 包裹结构
        if isinstance(obj.get("conversations"), list):
            for idx, conv in enumerate(obj.get("conversations") or []):
                if isinstance(conv, dict):
                    turns.extend(_parse_one_conversation(conv, source_tag=f"{source_tag}_{idx}"))
    elif isinstance(obj, list):
        for idx, conv in enumerate(obj):
            if isinstance(conv, dict):
                turns.extend(_parse_one_conversation(conv, source_tag=f"{source_tag}_{idx}"))
    return turns


def _write_jsonl(path: str, rows: Iterable[Dict[str, Any]]) -> int:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    cnt = 0
    with open(path, "w", encoding="utf-8") as f:
        for row in rows:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")
            cnt += 1
    return cnt


def _build_record_id(ts: int) -> str:
    return f"conv_{time.strftime('%Y%m%d_%H%M%S', time.localtime(ts))}_{uuid.uuid4().hex[:8]}"


def import_chatgpt_export_records(
    input_path: str,
    owner_type: str = "local",
    owner_id: str = LOCAL_OWNER_ID,
    max_records: int = 0,
    progress_callback: Optional[callable] = None,
    should_pause: Optional[callable] = None,
    should_stop: Optional[callable] = None,
) -> Dict[str, Any]:
    input_abs = os.path.abspath(str(input_path or "").strip())
    sources = _iter_import_sources(input_path)
    if not sources:
        return {
            "ok": False,
            "error": f"未找到可导入输入（json/zip）：{input_path}",
            "input": input_path,
            "files": [],
        }

    channel_type = str(owner_type or "local").strip().lower()
    if channel_type not in {"local", "private", "group"}:
        return {
            "ok": False,
            "error": f"owner-type 非法：{channel_type}（可选 local/private/group）",
            "input": input_path,
            "files": [str(x.get("path") or "") for x in sources],
        }

    owner = str(owner_id or "").strip() or (LOCAL_OWNER_ID if channel_type == "local" else "unknown")
    limit = int(max_records or 0)
    if limit < 0:
        limit = 0
    os.makedirs(RAW_DIR, exist_ok=True)

    store = MultiTenantChromaMemoryStore(persist_dir=CHROMA_PERSIST_DIR)

    total_turns = 0
    processed = 0
    written = 0
    skipped_dup = 0
    skipped_empty = 0
    parse_warn = 0
    file_logs: List[Dict[str, Any]] = []

    raw_rows: List[Dict[str, Any]] = []
    stopped_by_control = False

    def _emit(evt: Dict[str, Any]) -> None:
        if not progress_callback:
            return
        try:
            progress_callback(evt)
        except Exception:
            pass

    for src in sources:
        if not _wait_if_paused(should_pause=should_pause, should_stop=should_stop):
            stopped_by_control = True
            break
        file_path = str(src.get("path") or "").strip()
        file_kind = str(src.get("kind") or "").strip().lower()
        if limit > 0 and processed >= limit:
            break
        try:
            rel_path = (
                os.path.relpath(file_path, input_abs).replace("\\", "/")
                if os.path.isdir(input_abs)
                else os.path.basename(file_path)
            )
        except Exception:
            rel_path = os.path.basename(file_path)
        file_log: Dict[str, Any] = {
            "path": rel_path,
            "kind": file_kind or "json",
            "status": "pending",
            "normalized_records": 0,
            "scanned_records": 0,
            "imported_records": 0,
            "skipped_duplicates": 0,
            "skipped_empty": 0,
            "errors": 0,
            "message": "",
            "progress_pct": 0.0,
        }
        _emit(dict(file_log))
        try:
            if file_kind == "zip":
                with zipfile.ZipFile(file_path, "r") as z:
                    conv_name = ""
                    for n in z.namelist():
                        ns = str(n or "").replace("\\", "/").lower()
                        if ns == "conversations.json" or ns.endswith("/conversations.json"):
                            conv_name = n
                            break
                    if not conv_name:
                        raise ValueError("zip 内未找到 conversations.json")
                    raw = z.read(conv_name)
                    obj = json.loads(_decode_json_bytes(raw))
            else:
                with open(file_path, "rb") as f:
                    raw = f.read()
                obj = json.loads(_decode_json_bytes(raw))
        except Exception as e:
            parse_warn += 1
            file_log["status"] = "error"
            file_log["errors"] = 1
            file_log["message"] = f"读取/解析失败：{e}"
            file_log["progress_pct"] = 100.0
            file_logs.append(file_log)
            _emit(dict(file_log))
            print(f"[WARN] 读取/解析失败，已跳过：{file_path} | {e}")
            continue

        source_tag = os.path.splitext(os.path.basename(file_path))[0]
        turns = normalize_chatgpt_export(obj, source_tag=source_tag)
        file_log["normalized_records"] = int(len(turns))
        file_log["status"] = "running"
        file_log["progress_pct"] = 2.0 if file_log["normalized_records"] > 0 else 100.0
        _emit(dict(file_log))
        total_turns += len(turns)

        local_scanned = 0
        local_imported = 0
        local_skipped_dup = 0
        local_skipped_empty = 0

        for t in turns:
            if not _wait_if_paused(should_pause=should_pause, should_stop=should_stop):
                stopped_by_control = True
                break
            if limit > 0 and processed >= limit:
                break
            processed += 1
            local_scanned += 1

            user_text = _clean_import_text(str(t.get("user_text") or ""))
            assistant_text = _clean_import_text(str(t.get("assistant_text") or ""))
            if len(_normalize_ws(user_text)) < 2 and len(_normalize_ws(assistant_text)) < 2:
                skipped_empty += 1
                local_skipped_empty += 1
                if local_scanned == 1 or (local_scanned % 20 == 0):
                    den = max(1, int(file_log.get("normalized_records") or 0))
                    file_log["progress_pct"] = max(2.0, min(95.0, (local_scanned / den) * 100.0))
                    _emit(dict(file_log))
                continue
            merged_text = f"用户说：{user_text}\nAI 回复：{assistant_text}".strip()

            ts = _to_unix_ts(t.get("timestamp"))
            conv_id = str(t.get("conversation_id") or "").strip() or f"conv_{source_tag}"
            turn_index = int(t.get("turn_index") or 0)
            fp = _fingerprint(owner, merged_text)
            rec_id = _build_record_id(ts)

            metadata = {
                "source": "chatgpt_export",
                "layer": "imported_conv",
                "channel_type": channel_type,
                "owner_id": owner,
                "timestamp": ts,
                "importance": 7.0,
                "conversation_id": conv_id,
                "turn_index": turn_index,
                "fingerprint": fp,
                "deleted": False,
                "id": rec_id,
            }

            raw_rows.append(
                {
                    "id": rec_id,
                    "conversation_id": conv_id,
                    "turn_index": turn_index,
                    "timestamp": ts,
                    "source_file": os.path.basename(file_path),
                    "owner_type": channel_type,
                    "owner_id": owner,
                    "text": merged_text,
                    "metadata": metadata,
                }
            )

            try:
                duplicated = store.has_fingerprint(channel_type, owner, fp)
            except Exception as e:
                duplicated = False
                print(f"[WARN] 查重失败，按非重复处理：{e}")

            if duplicated:
                skipped_dup += 1
                local_skipped_dup += 1
                if local_scanned == 1 or (local_scanned % 20 == 0):
                    den = max(1, int(file_log.get("normalized_records") or 0))
                    file_log["progress_pct"] = max(2.0, min(95.0, (local_scanned / den) * 100.0))
                    _emit(dict(file_log))
                continue

            try:
                store.add([merged_text], [metadata])
                written += 1
                local_imported += 1
            except Exception as e:
                print(f"[WARN] 写入 Chroma 失败，已跳过：conv={conv_id} turn={turn_index} | {e}")
            if local_scanned == 1 or (local_scanned % 20 == 0):
                den = max(1, int(file_log.get("normalized_records") or 0))
                file_log["progress_pct"] = max(2.0, min(95.0, (local_scanned / den) * 100.0))
                _emit(dict(file_log))

        if stopped_by_control:
            file_log["status"] = "stopped"
            file_log["message"] = "导入被手动停止"
            file_log["progress_pct"] = max(
                2.0,
                min(
                    99.0,
                    (local_scanned / max(1, int(file_log.get("normalized_records") or 0))) * 100.0,
                ),
            )
            file_log["scanned_records"] = int(local_scanned)
            file_log["imported_records"] = int(local_imported)
            file_log["skipped_duplicates"] = int(local_skipped_dup)
            file_log["skipped_empty"] = int(local_skipped_empty)
            file_logs.append(file_log)
            _emit(dict(file_log))
            break

        file_log["scanned_records"] = int(local_scanned)
        file_log["imported_records"] = int(local_imported)
        file_log["skipped_duplicates"] = int(local_skipped_dup)
        file_log["skipped_empty"] = int(local_skipped_empty)
        if file_log["normalized_records"] <= 0:
            file_log["status"] = "empty"
            file_log["message"] = "无可解析对话记录"
            file_log["progress_pct"] = 100.0
        elif limit > 0 and processed >= limit and local_scanned < file_log["normalized_records"]:
            file_log["status"] = "partial"
            file_log["message"] = "达到导入上限，部分处理"
            file_log["progress_pct"] = 100.0
        else:
            file_log["status"] = "done"
            file_log["progress_pct"] = 100.0
        file_logs.append(file_log)
        _emit(dict(file_log))

        if limit > 0 and processed >= limit:
            break

    now_ts = int(time.time())
    date_tag = time.strftime("%Y%m%d_%H%M%S", time.localtime(now_ts))
    raw_name = f"{channel_type}_{_safe_token(owner, default='owner')}_{date_tag}.jsonl"
    raw_path = os.path.join(RAW_DIR, raw_name)
    raw_count = _write_jsonl(raw_path, raw_rows)

    return {
        "ok": True,
        "mode": "chatgpt_export",
        "input": input_path,
        "owner_type": channel_type,
        "owner_id": owner,
        "file_count": len(sources),
        "files": [str(x.get("path") or "") for x in sources],
        "normalized_records": int(total_turns),
        "scanned_records": int(processed),
        "imported_records": int(written),
        "skipped_duplicates": int(skipped_dup),
        "skipped_empty": int(skipped_empty),
        "warnings": int(parse_warn),
        "errors": int(parse_warn),
        "max_records": int(limit),
        "stopped_by_limit": bool(limit > 0 and processed >= limit),
        "stopped_by_control": bool(stopped_by_control),
        "raw_path": raw_path,
        "raw_count": int(raw_count),
        "file_logs": file_logs,
    }


def run_import(
    input_path: str,
    owner_type: str = "local",
    owner_id: str = LOCAL_OWNER_ID,
    max_records: int = 0,
) -> int:
    result = import_chatgpt_export_records(
        input_path=input_path,
        owner_type=owner_type,
        owner_id=owner_id,
        max_records=max_records,
    )
    if not result.get("ok"):
        print(f"[ERROR] {result.get('error') or '导入失败'}")
        return 2
    print("===== ChatGPT 导出导入完成 =====")
    print(f"输入文件数: {result.get('file_count', 0)}")
    print(f"归一化总记录: {result.get('normalized_records', 0)}")
    print(
        f"本次处理记录(受 max-records 限制): "
        f"{result.get('scanned_records', 0)} / "
        f"{result.get('max_records', 0) if int(result.get('max_records', 0) or 0) > 0 else '无限制'}"
    )
    print(f"RAW 写入行数: {result.get('raw_count', 0)} -> {result.get('raw_path', '')}")
    print(f"写入 Chroma: {result.get('imported_records', 0)}")
    print(f"跳过重复: {result.get('skipped_duplicates', 0)}")
    print(f"跳过空内容: {result.get('skipped_empty', 0)}")
    print(f"解析告警: {result.get('warnings', 0)}")
    if result.get("stopped_by_limit"):
        print(f"[INFO] 已达到 --max-records={result.get('max_records', 0)}，提前停止。")
    return 0


def parse_args(argv: Optional[List[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="导入 ChatGPT 导出 JSON 到 TYXT MemoryStore")
    parser.add_argument("--input", required=True, help="JSON 文件或目录")
    parser.add_argument("--owner-type", default="local", choices=["local", "private", "group"])
    parser.add_argument("--owner-id", default=LOCAL_OWNER_ID)
    parser.add_argument("--max-records", type=int, default=0, help="0 表示不限制")
    return parser.parse_args(argv)


def main(argv: Optional[List[str]] = None) -> int:
    args = parse_args(argv)
    return run_import(
        input_path=args.input,
        owner_type=args.owner_type,
        owner_id=args.owner_id,
        max_records=args.max_records,
    )


if __name__ == "__main__":
    sys.exit(main())
