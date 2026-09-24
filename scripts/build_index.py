"""Embed data/chunks.jsonl and load them into a local, persistent vector
store (Chroma). Everything runs on-device — no chunk text is sent
anywhere — since part of the corpus is access-restricted internal
material.

Model: intfloat/multilingual-e5-base. E5 models expect a "query: " /
"passage: " prefix on the text they embed (asymmetric retrieval) — chunks
are indexed as passages, questions are embedded as queries at query time
(see query_rag.py).
"""

from __future__ import annotations

import json
from pathlib import Path

import chromadb
from sentence_transformers import SentenceTransformer

REPO_ROOT = Path(__file__).resolve().parent.parent
CHUNKS_PATH = REPO_ROOT / "data" / "chunks.jsonl"
DB_DIR = REPO_ROOT / "data" / "chroma_db"
COLLECTION_NAME = "ztu_docs"
MODEL_NAME = "intfloat/multilingual-e5-base"
BATCH_SIZE = 64


def load_chunks() -> list[dict]:
    with CHUNKS_PATH.open(encoding="utf-8") as f:
        return [json.loads(line) for line in f]


def main() -> None:
    chunks = load_chunks()
    print(f"Loaded {len(chunks)} chunks from {CHUNKS_PATH.relative_to(REPO_ROOT)}")

    print(f"Loading model {MODEL_NAME} (local, first run downloads it once)...")
    model = SentenceTransformer(MODEL_NAME)

    client = chromadb.PersistentClient(path=str(DB_DIR))
    try:
        client.delete_collection(COLLECTION_NAME)
    except Exception:
        pass
    collection = client.create_collection(COLLECTION_NAME, metadata={"hnsw:space": "cosine"})

    texts = ["passage: " + c["embedding_text"] for c in chunks]
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
        embeddings = model.encode(texts[start:end], show_progress_bar=False, normalize_embeddings=True)
        collection.add(
            ids=ids[start:end],
            embeddings=embeddings.tolist(),
            metadatas=metadatas[start:end],
            documents=documents[start:end],
        )
        print(f"  {min(end, len(texts))}/{len(texts)}")

    print(f"Indexed {collection.count()} chunks into {DB_DIR.relative_to(REPO_ROOT)} (collection '{COLLECTION_NAME}')")


if __name__ == "__main__":
    main()
