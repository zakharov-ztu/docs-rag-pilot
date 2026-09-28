"""Retrieve the most relevant chunks for a question from the local Chroma
index built by build_index.py. Retrieval-only for now — no generation —
so retrieval quality can be checked directly before wiring up an LLM.

Usage:
    python3 scripts/query_rag.py "Як подати апеляцію на результати вступних іспитів?"
    python3 scripts/query_rag.py "..." --k 8
"""

from __future__ import annotations

import argparse
from pathlib import Path

import chromadb
from sentence_transformers import SentenceTransformer

REPO_ROOT = Path(__file__).resolve().parent.parent
DB_DIR = REPO_ROOT / "data" / "chroma_db"
COLLECTION_NAME = "ztu_docs"
MODEL_NAME = "intfloat/multilingual-e5-base"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("question", help="Question to search for")
    parser.add_argument("--k", type=int, default=5, help="Number of chunks to return")
    args = parser.parse_args()

    # Forced to CPU — see build_index.py for why (MPS gave wrong embeddings
    # for short query strings with this model on this machine).
    model = SentenceTransformer(MODEL_NAME, device="cpu")
    client = chromadb.PersistentClient(path=str(DB_DIR))
    collection = client.get_collection(COLLECTION_NAME)

    query_embedding = model.encode(["query: " + args.question], normalize_embeddings=True)
    results = collection.query(
        query_embeddings=query_embedding.tolist(),
        n_results=args.k,
        include=["documents", "metadatas", "distances"],
    )

    print(f"Питання: {args.question}\n")
    for i, (doc, meta, dist) in enumerate(
        zip(results["documents"][0], results["metadatas"][0], results["distances"][0]), 1
    ):
        similarity = 1 - dist
        print(f"--- #{i} (similarity {similarity:.3f}) ---")
        print(f"Документ: {meta['title']}")
        print(f"Категорія: {meta['category']}" + (f" / {meta['subgroup']}" if meta["subgroup"] else ""))
        print(f"Статус: {meta['status']}  №{meta['order_number']} від {meta['order_date']}")
        print(f"Розділ: {meta['section_path']}")
        print(f"Файл: {meta['wiki_page']}")
        print(doc[:500] + ("..." if len(doc) > 500 else ""))
        print()


if __name__ == "__main__":
    main()
