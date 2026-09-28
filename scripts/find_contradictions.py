"""Scan the corpus for candidate contradictions between documents: pairs
of chunks from DIFFERENT documents that are highly similar (same topic,
same specific procedure/threshold) — worth a human look, since it's
exactly the shape a real conflict takes (e.g. two documents both
describing "how a degree defense is submitted" where one says paper and
the other says digital).

This is a candidate finder, not a verdict — high similarity means "these
two chunks are about the same specific thing", not "these two chunks
disagree". A human (or a follow-up LLM pass) still has to read each pair
and decide.

Boilerplate control: many documents in this corpus share a literal
template (e.g. nearly every "Положення про кафедру/центр/відділ" opens
with the same "Це положення встановлює правовий статус, структуру..."
sentence). That's expected reuse, not a contradiction, and would drown
out real findings — so a chunk that matches many *different* documents
(not just one or two) is treated as template boilerplate and skipped.

Usage:
    python3 scripts/find_contradictions.py
    python3 scripts/find_contradictions.py --threshold 0.9 --max-fanout 2
"""

from __future__ import annotations

import argparse
import json
import re
import urllib.error
import urllib.request
from pathlib import Path

import chromadb

OLLAMA_URL = "http://localhost:11434/api/chat"
DEFAULT_OLLAMA_MODEL = "qwen2.5:7b"
JUDGE_SYSTEM_PROMPT = """Ти аналізуєш два фрагменти з різних офіційних документів університету, які обрані автоматично через семантичну схожість і можуть стосуватися однієї теми чи процедури.

Визнач одне з трьох:
- СУПЕРЕЧНІСТЬ — фрагменти дають різні або протилежні інструкції/факти щодо одного й того самого конкретного питання (наприклад один каже "паперова заява", інший — "електронна заявка"; різні строки, суми, умови для одного й того самого випадку).
- НЕ_СУПЕРЕЧНІСТЬ — фрагменти узгоджені, доповнюють один одного, або просто про різні речі попри схожість формулювань.
- НЕПЕВНО — не вистачає контексту, щоб точно визначити.

Відповідай РІВНО в такому форматі, без нічого зайвого:
ВЕРДИКТ: <СУПЕРЕЧНІСТЬ|НЕ_СУПЕРЕЧНІСТЬ|НЕПЕВНО>
ПОЯСНЕННЯ: <одне речення>"""

_TITLE_STOPWORDS = {
    "державного", "державний", "університету", "університет", "житомирська",
    "житомирської", "політехніка", "політехніки", "положення", "порядок",
    "процедура", "правила", "інструкція", "програма", "про", "щодо", "для",
    "та", "і", "в", "у", "з", "на", "як",
}
_TITLE_WORD_RE = re.compile(r"[а-яіїєґ'’ʼ]{3,}", re.IGNORECASE)


def _title_signature(title: str) -> set[str]:
    words = _TITLE_WORD_RE.findall(title.lower())
    return {w for w in words if w not in _TITLE_STOPWORDS}


def _same_template(title_a: str, title_b: str, jaccard_threshold: float = 0.55) -> bool:
    """True if two document titles look like the same template applied to
    a different subject (e.g. "...Вчену раду факультету X" vs "...
    факультету Y", or "...під час літніх канікул" vs "...зимових
    канікул") — the dominant source of high cross-document similarity in
    this corpus, and not what a contradiction search is after."""
    sig_a, sig_b = _title_signature(title_a), _title_signature(title_b)
    if not sig_a or not sig_b:
        return False
    overlap = len(sig_a & sig_b)
    union = len(sig_a | sig_b)
    return (overlap / union) >= jaccard_threshold if union else False

REPO_ROOT = Path(__file__).resolve().parent.parent
DB_DIR = REPO_ROOT / "data" / "chroma_db"
COLLECTION_NAME = "ztu_docs"
OUT_PATH = REPO_ROOT / "data" / "contradiction_candidates.md"

DEFAULT_THRESHOLD = 0.90
# Near-1.0 similarity is the OPPOSITE of a contradiction — it means the two
# chunks are the same text, just legitimately reused verbatim across two
# documents (e.g. the summer/winter safety instructions share whole
# sections). A real contradiction needs "same topic" but *not* "same
# wording", so those get excluded rather than counted as candidates.
DEFAULT_MAX_THRESHOLD = 0.97
DEFAULT_MAX_FANOUT = 3  # matches this many *different* other documents -> boilerplate, skip
# Pulled wide on purpose: a template clause reused across many faculty/
# department documents (e.g. the Вчена рада факультету quota formula,
# identical in every faculty's own council regulation) needs a big enough
# neighbor sample to actually show up as high-fanout — a narrow sample
# can land on just 2-3 of those many documents by chance and miss it.
DEFAULT_NEIGHBORS = 40


def _judge_pair(model: str, meta_a: dict, text_a: str, meta_b: dict, text_b: str) -> tuple[str, str]:
    """Returns (verdict, explanation). verdict is one of СУПЕРЕЧНІСТЬ /
    НЕ_СУПЕРЕЧНІСТЬ / НЕПЕВНО / ПОМИЛКА (the last if Ollama couldn't be
    reached or the response didn't parse)."""
    user = (
        f"[Фрагмент A] Документ: {meta_a['title']} (розділ {meta_a['section_path'] or '—'})\n"
        f"{text_a[:800]}\n\n"
        f"[Фрагмент B] Документ: {meta_b['title']} (розділ {meta_b['section_path'] or '—'})\n"
        f"{text_b[:800]}"
    )
    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": JUDGE_SYSTEM_PROMPT},
            {"role": "user", "content": user},
        ],
        "stream": False,
    }
    req = urllib.request.Request(
        OLLAMA_URL,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=120) as resp:
            body = json.loads(resp.read().decode("utf-8"))
        content = body["message"]["content"]
    except (urllib.error.URLError, KeyError, json.JSONDecodeError):
        return "ПОМИЛКА", "не вдалося отримати відповідь від Ollama"

    verdict_match = re.search(r"ВЕРДИКТ:\s*(\S+)", content)
    explanation_match = re.search(r"ПОЯСНЕННЯ:\s*(.+)", content)
    verdict = verdict_match.group(1).strip().upper() if verdict_match else "НЕПЕВНО"
    explanation = explanation_match.group(1).strip() if explanation_match else content.strip()[:200]
    return verdict, explanation


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--threshold", type=float, default=DEFAULT_THRESHOLD)
    parser.add_argument("--max-threshold", type=float, default=DEFAULT_MAX_THRESHOLD)
    parser.add_argument("--max-fanout", type=int, default=DEFAULT_MAX_FANOUT)
    parser.add_argument(
        "--cross-category-only",
        action="store_true",
        default=True,
        help="Only keep pairs whose documents are in different categories (default on — "
        "same-category pairs are almost always the same structural template, e.g. two "
        "faculties' own council regulations).",
    )
    parser.add_argument(
        "--include-same-category",
        dest="cross_category_only",
        action="store_false",
        help="Also consider pairs within the same category (much noisier).",
    )
    parser.add_argument(
        "--judge",
        action="store_true",
        default=True,
        help="Also send each candidate pair to the local Ollama model to classify "
        "СУПЕРЕЧНІСТЬ/НЕ_СУПЕРЕЧНІСТЬ/НЕПЕВНО (default on) — turns the raw embedding "
        "candidates into a short, curated shortlist instead of a list to read by hand.",
    )
    parser.add_argument("--no-judge", dest="judge", action="store_false")
    parser.add_argument("--judge-model", default=DEFAULT_OLLAMA_MODEL)
    parser.add_argument(
        "--limit",
        type=int,
        default=200,
        help="Only LLM-judge the top N candidates by similarity (default 200) — judging "
        "is the slow part; raise this to cover more of the raw candidate list.",
    )
    args = parser.parse_args()

    client = chromadb.PersistentClient(path=str(DB_DIR))
    collection = client.get_collection(COLLECTION_NAME)

    all_chunks = collection.get(include=["embeddings", "metadatas", "documents"])
    ids = all_chunks["ids"]
    embeddings = all_chunks["embeddings"]
    metadatas = all_chunks["metadatas"]
    documents = all_chunks["documents"]
    id_to_index = {chunk_id: i for i, chunk_id in enumerate(ids)}
    print(f"Loaded {len(ids)} chunks from the index")

    seen_pairs: set[frozenset[str]] = set()
    candidates: list[tuple[float, int, int]] = []  # (similarity, i, j)

    for idx, (chunk_id, embedding, meta) in enumerate(zip(ids, embeddings, metadatas)):
        result = collection.query(
            query_embeddings=[embedding],
            n_results=DEFAULT_NEIGHBORS + 1,  # +1 since the chunk matches itself
            include=["metadatas", "distances"],
        )
        own_doc = meta["doc_id"]
        neighbor_docs = set()
        matches = []
        for neighbor_id, neighbor_meta, dist in zip(
            result["ids"][0], result["metadatas"][0], result["distances"][0]
        ):
            if neighbor_id == chunk_id:
                continue
            similarity = 1 - dist
            if similarity < args.threshold or similarity > args.max_threshold:
                continue
            if neighbor_meta["doc_id"] == own_doc:
                continue
            neighbor_docs.add(neighbor_meta["doc_id"])
            matches.append((neighbor_id, similarity))

        if len(neighbor_docs) > args.max_fanout:
            continue  # matches too many different documents -> boilerplate template

        for neighbor_id, similarity in matches:
            pair_key = frozenset((chunk_id, neighbor_id))
            if pair_key in seen_pairs:
                continue
            seen_pairs.add(pair_key)
            j = id_to_index[neighbor_id]
            if _same_template(meta["title"], metadatas[j]["title"]):
                continue
            if args.cross_category_only and meta["category"] == metadatas[j]["category"]:
                continue
            candidates.append((similarity, idx, j))

        if (idx + 1) % 500 == 0:
            print(f"  scanned {idx + 1}/{len(ids)}")

    candidates.sort(key=lambda c: -c[0])
    print(f"Found {len(candidates)} candidate cross-document pairs above {args.threshold} similarity")

    lines = [
        "# Кандидати на суперечності між документами",
        "",
        f"Поріг схожості: {args.threshold}–{args.max_threshold} | максимум інших документів на фрагмент: {args.max_fanout}",
        f"Знайдено пар: {len(candidates)}",
        "",
        "Це кандидати для ручної перевірки — висока схожість означає «про те саме», не «суперечать».",
        "",
    ]
    for similarity, i, j in candidates:
        m1, m2 = metadatas[i], metadatas[j]
        lines.append(f"## Схожість {similarity:.3f}")
        lines.append("")
        lines.append(f"**[A]** {m1['title']} — {m1['section_path'] or '—'} ({m1['wiki_page']})")
        lines.append(f"> {documents[i][:400]}")
        lines.append("")
        lines.append(f"**[B]** {m2['title']} — {m2['section_path'] or '—'} ({m2['wiki_page']})")
        lines.append(f"> {documents[j][:400]}")
        lines.append("")
        lines.append("---")
        lines.append("")

    OUT_PATH.write_text("\n".join(lines), encoding="utf-8")
    print(f"Wrote {OUT_PATH.relative_to(REPO_ROOT)}")

    if not args.judge or not candidates:
        return

    to_judge = candidates[: args.limit]
    print(f"Judging top {len(to_judge)} candidates with {args.judge_model} (local)...")
    verdicts_count = {"СУПЕРЕЧНІСТЬ": 0, "НЕ_СУПЕРЕЧНІСТЬ": 0, "НЕПЕВНО": 0, "ПОМИЛКА": 0}
    shortlist = []
    for n, (similarity, i, j) in enumerate(to_judge, 1):
        m1, m2 = metadatas[i], metadatas[j]
        verdict, explanation = _judge_pair(args.judge_model, m1, documents[i], m2, documents[j])
        verdicts_count[verdict] = verdicts_count.get(verdict, 0) + 1
        if verdict in ("СУПЕРЕЧНІСТЬ", "НЕПЕВНО"):
            shortlist.append((similarity, i, j, verdict, explanation))
        if n % 20 == 0:
            print(f"  judged {n}/{len(to_judge)}")

    print(f"Verdicts: {verdicts_count}")

    shortlist_path = REPO_ROOT / "data" / "contradiction_shortlist.md"
    shortlist_lines = [
        "# Суперечності — перевірено локальною моделлю",
        "",
        f"Оцінено {len(to_judge)} кандидатів моделлю {args.judge_model}. "
        f"У списку — тільки СУПЕРЕЧНІСТЬ і НЕПЕВНО (не відкинуто як узгоджені).",
        f"СУПЕРЕЧНІСТЬ: {verdicts_count.get('СУПЕРЕЧНІСТЬ', 0)} | "
        f"НЕПЕВНО: {verdicts_count.get('НЕПЕВНО', 0)} | "
        f"НЕ_СУПЕРЕЧНІСТЬ (відкинуто): {verdicts_count.get('НЕ_СУПЕРЕЧНІСТЬ', 0)} | "
        f"ПОМИЛКА: {verdicts_count.get('ПОМИЛКА', 0)}",
        "",
        "Модель може помилятися — це звужений список для перевірки, не остаточний вердикт.",
        "",
    ]
    shortlist.sort(key=lambda s: (s[3] != "СУПЕРЕЧНІСТЬ", -s[0]))
    for similarity, i, j, verdict, explanation in shortlist:
        m1, m2 = metadatas[i], metadatas[j]
        shortlist_lines.append(f"## {verdict} (схожість {similarity:.3f})")
        shortlist_lines.append("")
        shortlist_lines.append(f"Пояснення моделі: {explanation}")
        shortlist_lines.append("")
        shortlist_lines.append(f"**[A]** {m1['title']} — {m1['section_path'] or '—'} ({m1['wiki_page']})")
        shortlist_lines.append(f"> {documents[i][:400]}")
        shortlist_lines.append("")
        shortlist_lines.append(f"**[B]** {m2['title']} — {m2['section_path'] or '—'} ({m2['wiki_page']})")
        shortlist_lines.append(f"> {documents[j][:400]}")
        shortlist_lines.append("")
        shortlist_lines.append("---")
        shortlist_lines.append("")

    shortlist_path.write_text("\n".join(shortlist_lines), encoding="utf-8")
    print(f"Wrote {shortlist_path.relative_to(REPO_ROOT)} ({len(shortlist)} pairs worth a look)")


if __name__ == "__main__":
    main()
