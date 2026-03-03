# -*- coding: utf-8 -*-
"""
search_engine.py  — 统一的“上网 + 本地记忆”检索器

特性：
1) 上网搜索（DuckDuckGo HTML 抓取，免 Key） -> 返回 title / link / snippet
2) 本地记忆检索（Chroma + Ollama Embeddings；默认 bge-m3）
3) 模式可选：
   - "web"   只上网
   - "local" 只本地
   - "auto"  先上网成功即返回，否则回退本地（默认）

配置优先级：环境变量 > config.yaml > 代码默认
"""

from __future__ import annotations
from typing import List, Dict, Any
import os, time, html, requests
from memory_store import ChromaMemoryStore

# --------------------- 读取配置 ---------------------
try:
    import yaml
except Exception:
    yaml = None

PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))
CFG_PATH = os.getenv("SEARCH_CONFIG", os.path.join(PROJECT_ROOT, "config.yaml"))

_cfg_yaml = {}
if yaml and os.path.exists(CFG_PATH):
    try:
        with open(CFG_PATH, "r", encoding="utf-8") as f:
            _cfg_yaml = yaml.safe_load(f) or {}
    except Exception:
        _cfg_yaml = {}

def _cfg(path: str, default=None):
    """从环境变量 -> yaml -> 默认值 读取配置，path 形如 a.b.c"""
    # 环境变量优先（使用大写下划线）
    env_key = path.upper().replace(".", "_")
    if env_key in os.environ:
        return os.environ[env_key]
    # yaml 次之
    cur = _cfg_yaml
    try:
        for k in path.split("."):
            cur = cur[k]
        return cur
    except Exception:
        return default

def _norm_path(p: str, default_abs: str) -> str:
    s = str(p or "").strip()
    if not s:
        return default_abs
    if os.path.isabs(s):
        return s
    return os.path.abspath(os.path.join(PROJECT_ROOT, s))

# Ollama / Embedding / Chroma
OLLAMA_BASE_URL   = _cfg("ollama.base_url",   "http://localhost:11434/v1")
EMBED_MODEL       = _cfg("embedding.model",   "bge-m3")
CHROMA_PATH       = _norm_path(_cfg("chromadb.persist_path", "memory_db"), os.path.join(PROJECT_ROOT, "memory_db"))
CHROMA_COLLECTION = _cfg("chromadb.collection_name", "tyxt_memory")

# 搜索默认参数
DEFAULT_TOPK  = int(_cfg("search.default_top_k", 10))
DEFAULT_MODE  = (_cfg("search.default_mode", "auto") or "auto").lower()

# 请求头
HEADERS = {
    "User-Agent": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                   "AppleWebKit/537.36 (KHTML, like Gecko) "
                   "Chrome/124.0 Safari/537.36")
}
TIMEOUT = int(_cfg("network.timeout", 60))

# --------------------- 上网搜索（DuckDuckGo HTML） ---------------------
from bs4 import BeautifulSoup  # pip install beautifulsoup4

def _ddg_html_page(q: str, s: int = 0) -> List[Dict[str, str]]:
    """抓 DuckDuckGo HTML 结果页；返回 [{title, link, snippet}]"""
    url = "https://duckduckgo.com/html/"
    r = requests.get(url, params={"q": q, "s": str(s)}, headers=HEADERS, timeout=TIMEOUT)
    r.raise_for_status()
    soup = BeautifulSoup(r.text, "html.parser")
    items: List[Dict[str, str]] = []
    for res in soup.select(".result"):
        a = res.select_one(".result__a")
        if not a:
            continue
        title = a.get_text(" ", strip=True)
        link = a.get("href") or ""
        snippet = res.select_one(".result__snippet")
        snippet = snippet.get_text(" ", strip=True) if snippet else ""
        items.append({
            "title": html.unescape(title),
            "link": link,
            "snippet": html.unescape(snippet)
        })
    return items

def _web_search(query: str, top_k: int) -> List[Dict[str, str]]:
    results: List[Dict[str, str]] = []
    start = 0
    while len(results) < top_k and start < 50:  # 最多翻 5 页
        try:
            page = _ddg_html_page(query, s=start)
        except Exception:
            time.sleep(1.0)
            try:
                page = _ddg_html_page(query, s=start)
            except Exception:
                break
        if not page:
            break
        results.extend(page)
        start += 10
    return results[:top_k]

def _fmt_web(query: str, items: List[Dict[str,str]]) -> str:
    if not items:
        return f"🔎 上网搜索：{query}\n1. 无结果 未检索到有效内容。"
    lines = [f"🔎 上网搜索：{query}"]
    for i, it in enumerate(items, 1):
        title   = (it.get("title") or "").strip()
        snippet = (it.get("snippet") or "").replace("\n", " ").strip()
        link    = it.get("link") or ""
        if len(title) > 120:   title = title[:120] + "…"
        if len(snippet) > 240: snippet = snippet[:240] + "…"
        if link:
            lines.append(f"{i}. {title}\n   {snippet}\n   {link}")
        else:
            lines.append(f"{i}. {title}\n   {snippet}")
    return "\n".join(lines)

# --------------------- 本地向量检索（Ollama embeddings + Chroma） ---------------------
_LOCAL_STORE: ChromaMemoryStore | None = None


def _get_local_store() -> ChromaMemoryStore:
    global _LOCAL_STORE
    if _LOCAL_STORE is None:
        _LOCAL_STORE = ChromaMemoryStore(
            persist_dir=str(CHROMA_PATH),
            collection_name=str(CHROMA_COLLECTION),
        )
    return _LOCAL_STORE

def _local_search(query: str, top_k: int) -> List[Dict[str, Any]]:
    try:
        store = _get_local_store()
        recs = store.search(query=query, top_k=max(1, int(top_k)), filters=None)
    except Exception as e:
        return [{"doc": f"本地记忆检索失败：{e}", "meta": {}, "score": 0.0}]
    out: List[Dict[str, Any]] = []
    for r in recs:
        out.append({"doc": r.text, "meta": r.metadata or {}, "score": r.score if r.score is not None else 0.0})
    return out

def _fmt_local(query: str, rows: List[Dict[str, Any]]) -> str:
    lines = [f"📚 记忆召回：{query}"]
    if not rows:
        lines.append("（无匹配记忆）")
        return "\n".join(lines)
    seen = set()
    for i, r in enumerate(rows, 1):
        doc  = (r.get("doc") or "").replace("\n"," ").strip()
        meta = r.get("meta") or {}
        src  = meta.get("source") or meta.get("title") or ""
        if len(doc) > 180: doc = doc[:180] + "…"
        key = (src + doc)[:180]
        if key in seen: 
            continue
        seen.add(key)
        prefix = f"{src}：" if src else ""
        lines.append(f"{i}. {prefix}{doc}")
    return "\n".join(lines)

# --------------------- 对外主函数 ---------------------
def search(query: str, mode: str = None, top_k: int = None) -> str:
    """
    search("今天要关注的技术新闻", mode="auto", top_k=10)
    返回：可直接显示的多行文本
    """
    q = (query or "").strip()
    if not q:
        return "（空查询）"
    m = (mode or DEFAULT_MODE or "auto").lower()
    k = int(top_k or DEFAULT_TOPK or 10)

    if m in ("auto","web"):
        web = _web_search(q, k)
        # 有任何有效结果就直接返回
        if web:
            return _fmt_web(q, web)
        if m == "web":
            return _fmt_web(q, web)  # 把“无结果”也返回

    # local or 回退
    local = _local_search(q, k)
    return _fmt_local(q, local)

# --------------------- CLI quick test ---------------------
if __name__ == "__main__":
    import sys
    _q = " ".join(sys.argv[1:]) if len(sys.argv) > 1 else "今天要关注的技术新闻"
    print(search(_q, mode="auto", top_k=10))
