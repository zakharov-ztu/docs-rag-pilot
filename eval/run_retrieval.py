"""Measure retrieval quality on the evaluation set (eval/questions.yaml).

Runs every question through the same search as scripts/query_rag.py and
checks where the expected answer shows up in the results. A retrieved chunk
counts as the answer when it belongs to the expected document and contains the
expected quote.

Metrics, over the questions that have an answer in the corpus:
    hit@5      share of questions whose answer is among the first 5 results
    hit@10     the same for the first 10
    MRR        mean reciprocal rank: 1 if the answer is always first, 0.5 if
               always second, ..., 0 when it is not in the top 10. Rewards
               putting the answer high, not just somewhere in the list
    doc hit@5  the right *document* is among the first 5 results, even if the
               chunk is not the one with the answer (what document search needs)

Unanswerable questions have no answer to find; for them the script reports
the similarity of the best result, to see whether a similarity threshold could
tell "nothing relevant" apart from a real match.

Usage:
    uv run eval/run_retrieval.py
    uv run eval/run_retrieval.py --verbose    # also show what came back for misses
    uv run eval/run_retrieval.py --save "baseline e5-base"   # record the run
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
import sys
from collections import defaultdict
from datetime import date
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from rag.config import CHUNKS_PATH, EMBEDDING_MODEL, REPO_ROOT  # noqa: E402
from rag.retrieval import Retriever  # noqa: E402

QUESTIONS_PATH = REPO_ROOT / "eval" / "questions.yaml"
RESULTS_PATH = REPO_ROOT / "eval" / "results.md"
RUNS_DIR = REPO_ROOT / "eval" / "runs"
K = 10
TYPES = ("factual", "identifier", "multi_doc")

RESULTS_HEADER = """# Retrieval results

One row per saved run of `eval/run_retrieval.py --save <label>`. Per-question
ranks of each run are in `eval/runs/`. Compare only rows with the same
questions hash: a different hash means a different version of the question set.

hit@5 by type: factual / identifier / multi_doc.

| date | label | setup | commit | questions (hash) | hit@5 | hit@10 | MRR | doc hit@5 | hit@5 by type |
|---|---|---|---|---|---|---|---|---|---|
"""


def normalize(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def retrieve(retriever: Retriever, question: str) -> list[dict]:
    return [
        {
            "doc_id": c["meta"]["doc_id"],
            "title": c["meta"]["title"],
            "text": normalize(c["text"]),
            "similarity": c["similarity"],
        }
        for c in retriever.search(question, K)
    ]


def answer_rank(results: list[dict], answer: dict) -> int | None:
    """1-based rank of the first result containing this answer, or None."""
    quote = normalize(answer["quote"])
    for rank, r in enumerate(results, 1):
        if r["doc_id"] == answer["doc_id"] and quote in r["text"]:
            return rank
    return None


def doc_rank(results: list[dict], doc_ids: set[str]) -> int | None:
    return next((rank for rank, r in enumerate(results, 1) if r["doc_id"] in doc_ids), None)


def metrics(rows: list[dict]) -> dict | None:
    n = len(rows)
    if n == 0:
        return None
    return {
        "n": n,
        "hit@5": sum(1 for r in rows if r["rank"] and r["rank"] <= 5) / n,
        "hit@10": sum(1 for r in rows if r["rank"]) / n,
        "mrr": sum(1 / r["rank"] for r in rows if r["rank"]) / n,
        "doc_hit@5": sum(1 for r in rows if r["doc_rank"] and r["doc_rank"] <= 5) / n,
    }


def format_metrics(m: dict | None) -> str:
    if m is None:
        return "—"
    return f"{m['n']:>3}   {m['hit@5']:>6.0%}  {m['hit@10']:>6.0%}  {m['mrr']:>5.2f}  {m['doc_hit@5']:>9.0%}"


def git_commit() -> str:
    """Short hash of HEAD, with '-dirty' if tracked files have uncommitted changes."""
    commit = subprocess.run(
        ["git", "rev-parse", "--short", "HEAD"], cwd=REPO_ROOT, capture_output=True, text=True
    ).stdout.strip()
    dirty = subprocess.run(["git", "diff", "--quiet", "HEAD"], cwd=REPO_ROOT).returncode != 0
    return commit + ("-dirty" if dirty else "")


def save_run(label: str, rows: list[dict], summary: dict, n_questions: int) -> None:
    """Append a row to eval/results.md and write per-question ranks to eval/runs/."""
    # The questions file is hashed so that results from different versions of
    # the set are never compared by accident.
    questions_hash = hashlib.sha256(QUESTIONS_PATH.read_bytes()).hexdigest()[:8]
    commit = git_commit()
    today = date.today().isoformat()
    setup = f"{EMBEDDING_MODEL}, Chroma, top {K}"

    if commit.endswith("-dirty"):
        print("warning: uncommitted changes; the saved commit does not fully describe this run")

    if not RESULTS_PATH.exists():
        RESULTS_PATH.write_text(RESULTS_HEADER, encoding="utf-8")
    m = summary["all"]
    by_type = " / ".join(f"{summary[t]['hit@5']:.0%}" if summary[t] else "—" for t in TYPES)
    with RESULTS_PATH.open("a", encoding="utf-8") as f:
        f.write(
            f"| {today} | {label} | {setup} | {commit} | {n_questions} ({questions_hash}) "
            f"| {m['hit@5']:.0%} | {m['hit@10']:.0%} | {m['mrr']:.2f} | {m['doc_hit@5']:.0%} | {by_type} |\n"
        )

    RUNS_DIR.mkdir(exist_ok=True)
    slug = re.sub(r"[^a-z0-9]+", "-", label.lower()).strip("-")
    run_path = RUNS_DIR / f"{today}-{slug}.json"
    run = {
        "date": today,
        "label": label,
        "setup": setup,
        "commit": commit,
        "questions_hash": questions_hash,
        "summary": summary,
        "questions": rows,
    }
    run_path.write_text(json.dumps(run, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"\nSaved to {RESULTS_PATH.relative_to(REPO_ROOT)} and {run_path.relative_to(REPO_ROOT)}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--verbose", action="store_true", help="Show the top results for questions that missed")
    parser.add_argument(
        "--save",
        metavar="LABEL",
        help="Record this run in eval/results.md and eval/runs/ under a short label, e.g. 'baseline'",
    )
    args = parser.parse_args()

    questions = yaml.safe_load(QUESTIONS_PATH.read_text(encoding="utf-8"))

    retriever = Retriever()

    with CHUNKS_PATH.open(encoding="utf-8") as f:
        chunk_count = sum(1 for _ in f)
    if retriever.collection.count() != chunk_count:
        print(
            f"warning: the index has {retriever.collection.count()} chunks but {CHUNKS_PATH.name} has {chunk_count}; "
            "rebuild it with scripts/build_index.py\n"
        )

    rows: list[dict] = []
    unanswerable_top: list[float] = []
    print(f"{'id':<5} {'type':<12} {'rank':>4}  {'doc':>3}  question")
    for q in questions:
        results = retrieve(retriever, q["question"])
        if q["type"] == "unanswerable":
            unanswerable_top.append(results[0]["similarity"])
            continue

        ranks = [answer_rank(results, a) for a in q["answers"]]
        found = [r for r in ranks if r]
        row = {
            "id": q["id"],
            "type": q["type"],
            "rank": min(found) if found else None,
            "doc_rank": doc_rank(results, {a["doc_id"] for a in q["answers"]}),
            "found_passages": f"{len(found)}/{len(ranks)}",
            "top_similarity": round(results[0]["similarity"], 4),
        }
        rows.append(row)

        rank_str = str(row["rank"]) if row["rank"] else "—"
        doc_str = str(row["doc_rank"]) if row["doc_rank"] else "—"
        print(f"{q['id']:<5} {q['type']:<12} {rank_str:>4}  {doc_str:>3}  {q['question']}")
        if q["type"] == "multi_doc":
            print(f"{'':<23}found {len(found)} of {len(ranks)} expected passages in the top {K}")
        if args.verbose and not row["rank"]:
            for i, r in enumerate(results[:5], 1):
                print(f"{'':<23}#{i} {r['similarity']:.3f} {r['title'][:70]}")

    print(f"\n{'':<12}  n   hit@5  hit@10    MRR  doc hit@5")
    by_type: dict[str, list[dict]] = defaultdict(list)
    for r in rows:
        by_type[r["type"]].append(r)
    summary = {t: metrics(by_type[t]) for t in TYPES}
    summary["all"] = metrics(rows)
    for t in (*TYPES, "all"):
        print(f"{t:<12}{format_metrics(summary[t])}")

    answerable_top = [r["top_similarity"] for r in rows]
    if unanswerable_top and answerable_top:
        print(
            "\nSimilarity of the best result (higher = closer match):\n"
            f"  answerable questions:   mean {sum(answerable_top) / len(answerable_top):.3f}, "
            f"min {min(answerable_top):.3f}\n"
            f"  unanswerable questions: mean {sum(unanswerable_top) / len(unanswerable_top):.3f}, "
            f"max {max(unanswerable_top):.3f}\n"
            "If the two ranges overlap, a similarity threshold cannot detect unanswerable questions;\n"
            "the LLM has to recognise them from the retrieved text."
        )

    print(
        "\nColumns: rank = position of the first passage containing the expected answer (— = not in the "
        f"top {K});\ndoc = position of the first result from the expected document."
    )

    if args.save:
        save_run(args.save, rows, summary, len(questions))


if __name__ == "__main__":
    main()
