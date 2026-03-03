# -*- coding: utf-8 -*-
"""
import_kb_files.py

离线导入：知识库文件（txt/md/docx/pdf）-> 多租户 Chroma MemoryStore

功能：
1) 递归扫描指定目录
2) 读取文本并按 chunk 分段（默认 900 字，重叠 150）
3) 先写 RAW JSONL 到 memory_warehouse/import_kb/raw
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
from typing import Any, Dict, Iterable, Iterator, List, Optional, Tuple

import docx
import fitz

from memory_store import CHROMA_PERSIST_DIR, LOCAL_OWNER_ID, MultiTenantChromaMemoryStore


PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))
WAREHOUSE_BASE_DIR = os.getenv(
    "TYXT_WAREHOUSE_DIR",
    os.path.join(PROJECT_ROOT, "memory_warehouse"),
)
WAREHOUSE_BASE_DIR = os.path.abspath(str(WAREHOUSE_BASE_DIR))
RAW_DIR = os.path.join(WAREHOUSE_BASE_DIR, "import_kb", "raw")

SUPPORTED_EXTS = {".txt", ".md", ".docx", ".pdf"}


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


def _looks_like_structured_noise(text: str) -> bool:
    s = str(text or "").strip()
    if not s:
        return True
    sl = s.lower()
    if "image_asset_pointer" in sl or "asset_pointer" in sl:
        return True
    if "content_type" in sl and "metadata" in sl and len(s) > 120:
        return True
    if len(s) >= 300 and s.count(":") >= 10 and (s.count("{") + s.count("}")) >= 8:
        return True
    return False


def _signal_density_ok(text: str) -> bool:
    s = str(text or "")
    if not s:
        return False
    # 中英文与数字的占比过低，通常是乱码或结构化噪声
    alpha_num = len(re.findall(r"[A-Za-z0-9\u4e00-\u9fff]", s))
    density = alpha_num / max(1, len(s))
    if len(s) >= 240 and density < 0.10:
        return False
    return True


def _clean_kb_chunk(text: str) -> str:
    raw = str(text or "").replace("\r", "\n")
    raw = raw.replace("\u200b", "").replace("\ufeff", "")
    lines = []
    for ln in raw.split("\n"):
        s = re.sub(r"\s+", " ", str(ln or "")).strip()
        if not s:
            continue
        if _looks_like_structured_noise(s):
            continue
        lines.append(s)
    out = "\n".join(lines).strip()
    out = re.sub(r"\n{3,}", "\n\n", out)
    if not _signal_density_ok(out):
        return ""
    return out


def _fingerprint(owner_id: str, text: str) -> str:
    seed = f"{owner_id}|{_normalize_ws(text)}"
    return hashlib.sha256(seed.encode("utf-8", errors="ignore")).hexdigest()[:16]


def _write_jsonl(path: str, rows: Iterable[Dict[str, Any]]) -> int:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    cnt = 0
    with open(path, "w", encoding="utf-8") as f:
        for row in rows:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")
            cnt += 1
    return cnt


def _iter_files(root_dir: str) -> List[str]:
    out: List[str] = []
    root_abs = os.path.abspath(root_dir)
    if not os.path.isdir(root_abs):
        return out
    for root, _dirs, files in os.walk(root_abs):
        for fn in files:
            ext = os.path.splitext(fn)[1].lower()
            if ext in SUPPORTED_EXTS:
                out.append(os.path.join(root, fn))
    out.sort()
    return out


def _read_text_file(path: str, max_chars: int = 2_000_000) -> str:
    with open(path, "rb") as f:
        raw = f.read()
    if not raw:
        return ""
    for enc in ("utf-8-sig", "utf-8", "utf-16", "utf-16-le", "utf-16-be", "gb18030", "gbk", "big5", "shift_jis"):
        try:
            data = raw.decode(enc)
            return str(data or "")[:max_chars]
        except Exception:
            continue
    data = raw.decode("utf-8", errors="ignore")
    return str(data or "")[:max_chars]


def _read_docx_file(path: str, max_chars: int = 2_000_000) -> str:
    text = "\n".join(p.text for p in docx.Document(path).paragraphs if str(p.text or "").strip())
    return text[:max_chars]


def _read_pdf_pages(path: str, max_chars: int = 2_000_000) -> List[Tuple[int, str]]:
    out: List[Tuple[int, str]] = []
    total = 0
    with fitz.open(path) as pdf:
        for i, page in enumerate(pdf, start=1):
            txt = str(page.get_text() or "").strip()
            if not txt:
                continue
            out.append((i, txt))
            total += len(txt)
            if total > max_chars:
                break
    return out


def _split_chunks(text: str, chunk_size: int = 900, overlap: int = 150) -> Iterator[str]:
    s = str(text or "").strip()
    if not s:
        return
    size = max(200, int(chunk_size or 900))
    ov = max(0, min(int(overlap or 150), size - 1))
    start = 0
    n = len(s)
    while start < n:
        end = min(n, start + size)
        chunk = s[start:end].strip()
        if chunk:
            yield chunk
        if end >= n:
            break
        start = max(0, end - ov)


def _estimate_chunk_count(text: str, chunk_size: int = 900, overlap: int = 150) -> int:
    s = str(text or "").strip()
    if not s:
        return 0
    size = max(200, int(chunk_size or 900))
    ov = max(0, min(int(overlap or 150), size - 1))
    n = len(s)
    if n <= size:
        return 1
    step = max(1, size - ov)
    return 1 + int((n - size + step - 1) // step)


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


def _load_file_segments(path: str) -> List[Dict[str, Any]]:
    ext = os.path.splitext(path)[1].lower()
    segments: List[Dict[str, Any]] = []
    if ext in {".txt", ".md"}:
        text = _read_text_file(path)
        segments.append({"page": 0, "text": text})
    elif ext == ".docx":
        text = _read_docx_file(path)
        segments.append({"page": 0, "text": text})
    elif ext == ".pdf":
        for page_no, text in _read_pdf_pages(path):
            segments.append({"page": int(page_no), "text": text})
    return segments


def _build_record_id(ts: int) -> str:
    return f"kb_{time.strftime('%Y%m%d_%H%M%S', time.localtime(ts))}_{uuid.uuid4().hex[:8]}"


def import_kb_records(
    root_dir: str,
    owner_type: str = "local",
    owner_id: str = "org_shared",
    max_records: int = 0,
    chunk_size: int = 900,
    chunk_overlap: int = 150,
    progress_callback: Optional[callable] = None,
    should_pause: Optional[callable] = None,
    should_stop: Optional[callable] = None,
) -> Dict[str, Any]:
    root_abs = os.path.abspath(str(root_dir or "").strip())
    if not os.path.isdir(root_abs):
        return {
            "ok": False,
            "error": f"root 目录不存在：{root_dir}",
            "root_dir": root_dir,
            "files": [],
        }

    channel_type = str(owner_type or "local").strip().lower()
    if channel_type not in {"local", "private", "group"}:
        return {
            "ok": False,
            "error": f"owner-type 非法：{channel_type}（可选 local/private/group）",
            "root_dir": root_dir,
            "files": [],
        }

    owner = str(owner_id or "").strip() or ("org_shared" if channel_type != "local" else LOCAL_OWNER_ID)
    limit = int(max_records or 0)
    if limit < 0:
        limit = 0

    files = _iter_files(root_abs)
    if not files:
        return {
            "ok": True,
            "mode": "kb_files",
            "root_dir": root_abs,
            "owner_type": channel_type,
            "owner_id": owner,
            "file_count": 0,
            "files": [],
            "scanned_records": 0,
            "imported_records": 0,
            "skipped_duplicates": 0,
            "skipped_empty": 0,
            "errors": 0,
            "warnings": 0,
            "failed_files": 0,
            "total_chunks": 0,
            "max_records": int(limit),
            "stopped_by_limit": False,
            "raw_path": "",
            "raw_count": 0,
            "file_logs": [],
        }

    store = MultiTenantChromaMemoryStore(persist_dir=CHROMA_PERSIST_DIR)
    os.makedirs(RAW_DIR, exist_ok=True)

    scanned_files = len(files)
    failed_files = 0
    total_chunks = 0
    processed = 0
    written = 0
    skipped_dup = 0
    skipped_empty = 0
    warn_count = 0
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

    for abs_path in files:
        if not _wait_if_paused(should_pause=should_pause, should_stop=should_stop):
            stopped_by_control = True
            break
        if limit > 0 and processed >= limit:
            break
        rel_path = os.path.relpath(abs_path, root_abs).replace("\\", "/")
        file_name = os.path.basename(abs_path)
        file_log: Dict[str, Any] = {
            "path": rel_path.replace("\\", "/"),
            "status": "pending",
            "segments": 0,
            "chunks": 0,
            "scanned_records": 0,
            "imported_records": 0,
            "skipped_duplicates": 0,
            "skipped_empty": 0,
            "errors": 0,
            "message": "",
            "progress_pct": 0.0,
            "chunks_total": 0,
        }
        _emit(dict(file_log))
        try:
            file_ts = int(os.path.getmtime(abs_path))
        except Exception:
            file_ts = int(time.time())

        try:
            segments = _load_file_segments(abs_path)
            file_log["segments"] = int(len(segments))
            file_log["status"] = "running"
            file_log["progress_pct"] = 5.0 if file_log["segments"] > 0 else 100.0
            est_chunks = 0
            for seg in segments:
                est_chunks += _estimate_chunk_count(
                    seg.get("text") or "",
                    chunk_size=chunk_size,
                    overlap=chunk_overlap,
                )
            file_log["chunks_total"] = int(est_chunks)
            _emit(dict(file_log))
        except Exception as e:
            failed_files += 1
            file_log["status"] = "error"
            file_log["errors"] = 1
            file_log["message"] = f"读取失败：{e}"
            file_log["progress_pct"] = 100.0
            file_logs.append(file_log)
            _emit(dict(file_log))
            print(f"[WARN] 读取文件失败，跳过：{rel_path} | {e}")
            continue

        local_scanned = 0
        local_imported = 0
        local_skipped_dup = 0
        local_skipped_empty = 0

        for seg in segments:
            if not _wait_if_paused(should_pause=should_pause, should_stop=should_stop):
                stopped_by_control = True
                break
            if limit > 0 and processed >= limit:
                break
            page_no = int(seg.get("page") or 0)
            seg_text = str(seg.get("text") or "").strip()
            if not seg_text:
                continue

            for chunk in _split_chunks(seg_text, chunk_size=chunk_size, overlap=chunk_overlap):
                if not _wait_if_paused(should_pause=should_pause, should_stop=should_stop):
                    stopped_by_control = True
                    break
                if limit > 0 and processed >= limit:
                    break
                total_chunks += 1
                file_log["chunks"] = int(file_log.get("chunks") or 0) + 1
                processed += 1
                local_scanned += 1
                clean_chunk = _clean_kb_chunk(str(chunk or ""))
                if len(_normalize_ws(clean_chunk)) < 2:
                    skipped_empty += 1
                    local_skipped_empty += 1
                    if local_scanned == 1 or (local_scanned % 20 == 0):
                        den = max(1, int(file_log.get("chunks_total") or local_scanned))
                        file_log["progress_pct"] = max(5.0, min(95.0, (local_scanned / den) * 100.0))
                        _emit(dict(file_log))
                    continue

                fp = _fingerprint(owner, clean_chunk)
                rec_id = _build_record_id(file_ts)
                metadata = {
                    "source": "kb_file",
                    "layer": "kb",
                    "channel_type": channel_type,
                    "owner_id": owner,
                    "timestamp": file_ts,
                    "importance": 6.0,
                    "file_path": rel_path.replace("\\", "/"),
                    "file_name": file_name,
                    "page": page_no,
                    "fingerprint": fp,
                    "deleted": False,
                    "id": rec_id,
                }

                raw_rows.append(
                    {
                        "id": rec_id,
                        "timestamp": file_ts,
                        "owner_type": channel_type,
                        "owner_id": owner,
                        "file_path": rel_path.replace("\\", "/"),
                        "file_name": file_name,
                        "page": page_no,
                        "text": clean_chunk,
                        "metadata": metadata,
                    }
                )

                try:
                    duplicated = store.has_fingerprint(channel_type, owner, fp)
                except Exception as e:
                    duplicated = False
                    warn_count += 1
                    print(f"[WARN] 查重失败，按非重复处理：{rel_path} | {e}")

                if duplicated:
                    skipped_dup += 1
                    local_skipped_dup += 1
                    if local_scanned == 1 or (local_scanned % 20 == 0):
                        den = max(1, int(file_log.get("chunks_total") or local_scanned))
                        file_log["progress_pct"] = max(5.0, min(95.0, (local_scanned / den) * 100.0))
                        _emit(dict(file_log))
                    continue

                try:
                    store.add([clean_chunk], [metadata])
                    written += 1
                    local_imported += 1
                except Exception as e:
                    warn_count += 1
                    print(f"[WARN] 写入 Chroma 失败：{rel_path} page={page_no} | {e}")
                if local_scanned == 1 or (local_scanned % 20 == 0):
                    den = max(1, int(file_log.get("chunks_total") or local_scanned))
                    file_log["progress_pct"] = max(5.0, min(95.0, (local_scanned / den) * 100.0))
                    _emit(dict(file_log))
            if stopped_by_control:
                break
        if stopped_by_control:
            file_log["status"] = "stopped"
            file_log["message"] = "导入被手动停止"
            den = max(1, int(file_log.get("chunks_total") or local_scanned))
            file_log["progress_pct"] = max(5.0, min(99.0, (local_scanned / den) * 100.0))
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
        if int(file_log["segments"]) <= 0:
            file_log["status"] = "empty"
            file_log["message"] = "未提取到可读文本"
            file_log["progress_pct"] = 100.0
        elif limit > 0 and processed >= limit and local_scanned < int(file_log["chunks"]):
            file_log["status"] = "partial"
            file_log["message"] = "达到导入上限，部分处理"
            file_log["progress_pct"] = 100.0
        else:
            file_log["status"] = "done"
            file_log["progress_pct"] = 100.0
        file_logs.append(file_log)
        _emit(dict(file_log))

    now_ts = int(time.time())
    date_tag = time.strftime("%Y%m%d_%H%M%S", time.localtime(now_ts))
    raw_name = f"{channel_type}_{_safe_token(owner, default='owner')}_{date_tag}.jsonl"
    raw_path = os.path.join(RAW_DIR, raw_name)
    raw_count = _write_jsonl(raw_path, raw_rows)

    return {
        "ok": True,
        "mode": "kb_files",
        "root_dir": root_abs,
        "owner_type": channel_type,
        "owner_id": owner,
        "file_count": int(scanned_files),
        "files": files,
        "scanned_records": int(processed),
        "imported_records": int(written),
        "skipped_duplicates": int(skipped_dup),
        "skipped_empty": int(skipped_empty),
        "errors": int(failed_files),
        "warnings": int(warn_count),
        "failed_files": int(failed_files),
        "total_chunks": int(total_chunks),
        "max_records": int(limit),
        "stopped_by_limit": bool(limit > 0 and processed >= limit),
        "stopped_by_control": bool(stopped_by_control),
        "raw_path": raw_path,
        "raw_count": int(raw_count),
        "file_logs": file_logs,
    }


def run_import(
    root_dir: str,
    owner_type: str = "local",
    owner_id: str = "org_shared",
    max_records: int = 0,
    chunk_size: int = 900,
    chunk_overlap: int = 150,
) -> int:
    result = import_kb_records(
        root_dir=root_dir,
        owner_type=owner_type,
        owner_id=owner_id,
        max_records=max_records,
        chunk_size=chunk_size,
        chunk_overlap=chunk_overlap,
    )
    if not result.get("ok"):
        print(f"[ERROR] {result.get('error') or '导入失败'}")
        return 2
    print("===== 知识库文件导入完成 =====")
    print(f"扫描文件数: {result.get('file_count', 0)}")
    print(f"解析失败文件数: {result.get('failed_files', 0)}")
    print(f"生成 chunk 总数: {result.get('total_chunks', 0)}")
    print(
        f"本次处理记录(受 max-records 限制): "
        f"{result.get('scanned_records', 0)} / "
        f"{result.get('max_records', 0) if int(result.get('max_records', 0) or 0) > 0 else '无限制'}"
    )
    print(f"RAW 写入行数: {result.get('raw_count', 0)} -> {result.get('raw_path', '')}")
    print(f"写入 Chroma: {result.get('imported_records', 0)}")
    print(f"跳过重复: {result.get('skipped_duplicates', 0)}")
    print(f"跳过空内容: {result.get('skipped_empty', 0)}")
    print(f"告警数: {result.get('warnings', 0)}")
    if result.get("stopped_by_limit"):
        print(f"[INFO] 已达到 --max-records={result.get('max_records', 0)}，提前停止。")
    return 0


def parse_args(argv: Optional[List[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="导入知识库文件到 TYXT MemoryStore")
    parser.add_argument("--root", required=True, help="知识库根目录")
    parser.add_argument("--owner-type", default="local", choices=["local", "private", "group"])
    parser.add_argument("--owner-id", default="org_shared")
    parser.add_argument("--max-records", type=int, default=0, help="0 表示不限制")
    parser.add_argument("--chunk-size", type=int, default=900)
    parser.add_argument("--chunk-overlap", type=int, default=150)
    return parser.parse_args(argv)


def main(argv: Optional[List[str]] = None) -> int:
    args = parse_args(argv)
    return run_import(
        root_dir=args.root,
        owner_type=args.owner_type,
        owner_id=args.owner_id,
        max_records=args.max_records,
        chunk_size=args.chunk_size,
        chunk_overlap=args.chunk_overlap,
    )


if __name__ == "__main__":
    sys.exit(main())
