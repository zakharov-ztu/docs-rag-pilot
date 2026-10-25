"""Retrieve the most relevant chunks for a question from the local Chroma
index built by build_index.py. Retrieval-only — no generation — so
retrieval quality can be checked directly.

Usage:
    uv run scripts/query_rag.py "Як подати апеляцію на результати вступних іспитів?"
    uv run scripts/query_rag.py "..." --k 8
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from rag.retrieval import Retriever  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("question", help="Question to search for")
    parser.add_argument("--k", type=int, default=5, help="Number of chunks to return")
    args = parser.parse_args()

    chunks = Retriever().search(args.question, args.k)

    print(f"Питання: {args.question}\n")
    for i, c in enumerate(chunks, 1):
        meta, doc = c["meta"], c["text"]
        print(f"--- #{i} (similarity {c['similarity']:.3f}) ---")
        print(f"Документ: {meta['title']}")
        print(f"Категорія: {meta['category']}" + (f" / {meta['subgroup']}" if meta["subgroup"] else ""))
        print(f"Статус: {meta['status']}  №{meta['order_number']} від {meta['order_date']}")
        print(f"Розділ: {meta['section_path']}")
        print(f"Файл: {meta['wiki_page']}")
        print(doc[:500] + ("..." if len(doc) > 500 else ""))
        print()


if __name__ == "__main__":
    main()
