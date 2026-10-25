"""Embed data/chunks.jsonl and load them into a local, persistent vector
store (Chroma). Everything runs on-device — no chunk text is sent
anywhere — since part of the corpus is access-restricted internal
material.

The embedding model and its query/passage prefixes are defined in
rag/retrieval.py, shared with search, so the index and the queries always
use the same model.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import chromadb

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from rag.config import CHUNKS_PATH, COLLECTION_NAME, DB_DIR, EMBEDDING_MODEL, REPO_ROOT  # noqa: E402
from rag.retrieval import embed_passages, load_embedding_model  # noqa: E402

BATCH_SIZE = 64


def load_chunks() -> list[dict]:
    with CHUNKS_PATH.open(encoding="utf-8") as f:
        return [json.loads(line) for line in f]


def main() -> None:
    chunks = load_chunks()
    print(f"Loaded {len(chunks)} chunks from {CHUNKS_PATH.relative_to(REPO_ROOT)}")

    print(f"Loading model {EMBEDDING_MODEL} (local, first run downloads it once)...")
    model = load_embedding_model()

    client = chromadb.PersistentClient(path=str(DB_DIR))
    try:
        client.delete_collection(COLLECTION_NAME)
    except Exception:
        pass
    collection = client.create_collection(COLLECTION_NAME, metadata={"hnsw:space": "cosine"})

    texts = [c["embedding_text"] for c in chunks]
    ids = [c["chunk_id"] for c in chunks]
    metadatas = [
        {
            "doc_id": c["doc_id"],
            "wiki_page": c["wiki_page"],
            "title": c.get("title") or "",
            "category": c.get("category") or "",
            "subgroup": c.get("subgroup") or "",
            "status": c.get("status") or "невідомо",
            "order_number": c.get("order_number") or "",
            "order_date": c.get("order_date") or "",
            "section_path": c.get("section_path") or "",
        }
        for c in chunks
    ]
    documents = [c["text"] for c in chunks]

    print(f"Embedding {len(texts)} chunks in batches of {BATCH_SIZE}...")
    for start in range(0, len(texts), BATCH_SIZE):
        end = start + BATCH_SIZE
        collection.add(
            ids=ids[start:end],
            embeddings=embed_passages(model, texts[start:end]),
            metadatas=metadatas[start:end],
            documents=documents[start:end],
        )
        print(f"  {min(end, len(texts))}/{len(texts)}")

    print(f"Indexed {collection.count()} chunks into {DB_DIR.relative_to(REPO_ROOT)} (collection '{COLLECTION_NAME}')")


if __name__ == "__main__":
    main()
