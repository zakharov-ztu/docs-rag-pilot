"""Validate eval/questions.yaml against data/chunks.jsonl.

Every expected answer is labelled with a doc_id and a verbatim quote of the
answering text, not with a chunk id, so the labels survive re-chunking. This
script checks that each quote still occurs in a chunk of that document and
fills in the chunk's section_path, so the set stays readable for reviewers.

Also checks the structure of the set (unique ids, known types, answers present
or absent as the type requires) and flags questions that share most of their
words with the quote, since those flatter retrieval.

Usage:
    uv run eval/check_questions.py           # check only
    uv run eval/check_questions.py --write   # also write section_path back
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from collections import Counter
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from rag.config import CHUNKS_PATH, REPO_ROOT  # noqa: E402

QUESTIONS_PATH = REPO_ROOT / "eval" / "questions.yaml"

TYPES = ("factual", "identifier", "multi_doc", "unanswerable")
# Share of the question's content words found in the quote above which the
# question is reported as copying the regulation's wording.
MAX_OVERLAP = 0.6
WORD_RE = re.compile(r"[а-яіїєґa-z0-9]+", re.IGNORECASE)


def normalize(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def stems(text: str) -> set[str]:
    # Crude stemming: the first 5 letters of each word of 4+ letters. Enough to
    # match Ukrainian word forms ("апеляції" / "апеляцію") for an overlap check.
    return {w.lower()[:5] for w in WORD_RE.findall(text) if len(w) >= 4}


def load_chunks() -> dict[str, list[dict]]:
    by_doc: dict[str, list[dict]] = {}
    with CHUNKS_PATH.open(encoding="utf-8") as f:
        for line in f:
            chunk = json.loads(line)
            chunk["norm_text"] = normalize(chunk["text"])
            by_doc.setdefault(chunk["doc_id"], []).append(chunk)
    return by_doc


def check(questions: list[dict], chunks_by_doc: dict[str, list[dict]]) -> tuple[list[str], list[str]]:
    errors: list[str] = []
    warnings: list[str] = []

    for qid, n in Counter(q.get("id") for q in questions).items():
        if n > 1:
            errors.append(f"{qid}: duplicate id")

    for q in questions:
        qid = q.get("id", "?")
        qtype = q.get("type")
        answers = q.get("answers") or []
        if qtype not in TYPES:
            errors.append(f"{qid}: unknown type {qtype!r}")
        if not q.get("question") or not q.get("reference_answer"):
            errors.append(f"{qid}: missing question or reference_answer")
        if qtype == "unanswerable" and answers:
            errors.append(f"{qid}: unanswerable question has answers")
        if qtype != "unanswerable" and not answers:
            errors.append(f"{qid}: no answers")
        if qtype == "multi_doc" and len({a.get("doc_id") for a in answers}) < 2:
            errors.append(f"{qid}: multi_doc question cites fewer than 2 documents")

        for a in answers:
            doc_chunks = chunks_by_doc.get(a.get("doc_id"))
            if doc_chunks is None:
                errors.append(f"{qid}: unknown doc_id {a.get('doc_id')!r}")
                continue
            quote = normalize(a.get("quote") or "")
            match = next((c for c in doc_chunks if quote and quote in c["norm_text"]), None)
            if match is None:
                errors.append(f"{qid}: quote not found in {a['doc_id']}: {quote[:60]!r}")
                continue
            a["section_path"] = match["section_path"]

        question_stems = stems(q.get("question") or "")
        for a in answers:
            if question_stems:
                overlap = len(question_stems & stems(a.get("quote") or "")) / len(question_stems)
                if overlap > MAX_OVERLAP:
                    warnings.append(f"{qid}: question shares {overlap:.0%} of its words with the quote")
                    break

    return errors, warnings


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--write", action="store_true", help="Write section_path back into questions.yaml")
    args = parser.parse_args()

    questions = yaml.safe_load(QUESTIONS_PATH.read_text(encoding="utf-8"))
    errors, warnings = check(questions, load_chunks())

    counts = Counter(q.get("type") for q in questions)
    print(f"{len(questions)} questions: " + ", ".join(f"{t} {counts[t]}" for t in TYPES))
    for w in warnings:
        print(f"warning: {w}")
    for e in errors:
        print(f"error: {e}")

    if args.write:
        QUESTIONS_PATH.write_text(
            yaml.safe_dump(questions, allow_unicode=True, sort_keys=False, width=100),
            encoding="utf-8",
        )
        print(f"Wrote {QUESTIONS_PATH.relative_to(REPO_ROOT)}")

    sys.exit(1 if errors else 0)


if __name__ == "__main__":
    main()
