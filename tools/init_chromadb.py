#!/usr/bin/env python
from __future__ import annotations

import os
import sys


PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

import chromadb
from memory_store import (
    CHROMA_COLLECTION_NAME,
    CHROMA_PERSIST_DIR,
    LOCAL_OWNER_ID,
    TYXT_CHANNEL_LOCAL,
    TYXT_FALLBACK_COLLECTION,
    make_collection_name,
)


def _collection_name_list(collections):
    names = []
    for item in collections:
        if isinstance(item, str):
            names.append(str(item))
            continue
        try:
            name = getattr(item, "name", None)
        except Exception:
            name = None
        if name:
            names.append(str(name))
        else:
            names.append(str(item))
    return names


def main() -> int:
    os.makedirs(CHROMA_PERSIST_DIR, exist_ok=True)
    client = chromadb.PersistentClient(path=CHROMA_PERSIST_DIR)

    base_collections = [
        CHROMA_COLLECTION_NAME,
        TYXT_FALLBACK_COLLECTION,
        make_collection_name(TYXT_CHANNEL_LOCAL, LOCAL_OWNER_ID),
    ]
    for cname in base_collections:
        if str(cname or "").strip():
            client.get_or_create_collection(name=str(cname).strip())

    all_names = sorted(set(_collection_name_list(client.list_collections())))
    print("[OK] ChromaDB initialized")
    print(f"      path: {CHROMA_PERSIST_DIR}")
    print(f"      collections: {', '.join(all_names) if all_names else '(none)'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
