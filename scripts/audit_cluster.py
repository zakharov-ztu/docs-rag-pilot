#!/usr/bin/env python3
"""Group wiki-pages/*.md by topical similarity (TF-IDF + cosine), as the
first step of the consistency/duplication audit: cluster documents, then
a human/LLM reviews each cluster for contradictions, overlap, or
obsolescence, instead of comparing all C(204,2) pairs by hand.

Usage:
    .venv/bin/python scripts/audit_cluster.py [--threshold 0.2]
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

import yaml
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity

ROOT = Path(__file__).resolve().parent.parent
WIKI_DIR = ROOT / "wiki-pages"


def load_docs() -> list[dict]:
    docs = []
    for path in sorted(WIKI_DIR.glob("*.md")):
        raw = path.read_text(encoding="utf-8")
        if not raw.startswith("---\n"):
            continue
        _, fm_text, body = raw.split("---\n", 2)
        fm = yaml.safe_load(fm_text) or {}
        docs.append({
            "path": path,
            "title": fm.get("title") or path.stem,
            "status": fm.get("status") or "",
            "order_number": fm.get("order_number") or "",
            "order_date": fm.get("order_date") or "",
            "body": body,
        })
    return docs


def cluster(docs: list[dict], threshold: float) -> list[list[int]]:
    texts = [d["title"] + " \n " + d["body"] for d in docs]
    vectorizer = TfidfVectorizer(
        token_pattern=r"(?u)\b[^\W\d_]{4,}\b",  # words of 4+ letters, no digits/underscore
        max_df=0.15,  # aggressively drop shared ISO-template/legal boilerplate
        min_df=2,
        sublinear_tf=True,
        ngram_range=(1, 2),
    )
    matrix = vectorizer.fit_transform(texts)
    sim = cosine_similarity(matrix)

    n = len(docs)
    parent = list(range(n))

    def find(x: int) -> int:
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    def union(a: int, b: int) -> None:
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[ra] = rb

    edges = []
    for i in range(n):
        for j in range(i + 1, n):
            if sim[i, j] >= threshold:
                edges.append((i, j, sim[i, j]))
                union(i, j)

    groups: dict[int, list[int]] = {}
    for i in range(n):
        groups.setdefault(find(i), []).append(i)

    edge_lookup = {}
    for i, j, s in edges:
        edge_lookup.setdefault(i, []).append((j, s))
        edge_lookup.setdefault(j, []).append((i, s))

    clusters = [members for members in groups.values() if len(members) > 1]
    clusters.sort(key=len, reverse=True)
    return clusters, edge_lookup


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--threshold", type=float, default=0.2)
    args = parser.parse_args()

    docs = load_docs()
    print(f"Завантажено {len(docs)} документів\n")

    clusters, edge_lookup = cluster(docs, args.threshold)
    singletons = len(docs) - sum(len(c) for c in clusters)
    print(f"Кластерів (2+ документи): {len(clusters)}")
    print(f"Документів поза кластерами (унікальна тема): {singletons}\n")

    for idx, members in enumerate(clusters, 1):
        print(f"--- Кластер {idx} ({len(members)} документів) ---")
        for m in members:
            d = docs[m]
            best = max((s for _, s in edge_lookup.get(m, [(None, 0)])), default=0)
            print(f"  [{d['status']:10s}] {d['title'][:90]}  ({d['path'].name})")
        print()

    return 0


if __name__ == "__main__":
    sys.exit(main())
