# Retrieval results

One row per saved run of `eval/run_retrieval.py --save <label>`. Per-question
ranks of each run are in `eval/runs/`. Compare only rows with the same
questions hash: a different hash means a different version of the question set.

hit@5 by type: factual / identifier / multi_doc.

| date | label | setup | commit | questions (hash) | hit@5 | hit@10 | MRR | doc hit@5 | hit@5 by type |
|---|---|---|---|---|---|---|---|---|---|
| 2026-10-25 | baseline e5-base | intfloat/multilingual-e5-base, Chroma, top 10 | 2fa194d-dirty | 56 (2ee16cad) | 70% | 82% | 0.61 | 91% | 79% / 75% / 38% |
