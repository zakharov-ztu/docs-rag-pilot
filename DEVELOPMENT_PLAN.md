# Development plan

## Goal

Build a proof of concept (POC) that shows the university administration how
well RAG over the university's regulations can work, so that the next steps
and the real use can be planned together with them.

The POC runs on one laptop (MacBook M4 Max, 48 GB) and demonstrates:

1. **Finding documents**: "which regulation covers X", with filters by
   category.
2. **Answers over the documents**: a question in Ukrainian, an answer with
   citations to the exact document and пункт, from a choice of local LLMs.
3. **Contradiction detection**: as an example of a further use, pairs of
   пункти from different documents that may contradict each other.
4. **Document generation**: drafting a new document from a university
   template and the current regulations, and rendering documents onto the ISO
   form (the constructor).

The second goal of the POC is to **discover requirements and limitations**.
Everything the POC deliberately leaves out is listed in
[Part 2](#part-2-after-the-poc) (quality improvements) and
[Part 3](#part-3-prerequisites-for-a-working-system) (what a working system
needs), together with the questions the administration has to answer.

Intended users of a real system: university staff only. Each university office
owns its own part of the document base.

### Decisions already made

| Decision | Reason |
|---|---|
| Documents stay in this repository for the POC | All of them are already public |
| No document uploading in the POC | A prerequisite for a working system (Part 3) |
| Everything runs locally, no external APIs | Keeps the POC free of data-protection questions; the cloud option is discussed in Part 3 |
| Retrieval stays as it is (e5-base + Chroma) | Metadata, hybrid search and reranking are deferred to Part 2 |
| Demo interface: a Streamlit app | One small Python app on top of the same code as the CLI |
| Evaluation set of 50+ questions | The administration will ask "how well does it work"; the answer must be numbers |
| Models shown: Gemma and MamayLM 12B, side by side in the app | No formal LLM comparison in the POC; speed is not a criterion for the demo |

## Current state

Already in place: PDF extraction, hand-corrected Markdown in `wiki-pages/`,
structure-aware chunking, a Chroma index with `multilingual-e5-base`, answer
generation with `qwen2.5:7b` via Ollama, the contradiction shortlist, the
corpus audit (`audit_cluster.py`), the Jekyll site and the Typst / in-browser
constructor.

## POC architecture

```
wiki-pages/*.md  (source of truth)
   │  chunk_documents.py  (by розділ > підрозділ > пункт, metadata in every chunk)
   ▼
multilingual-e5-base  ──►  Chroma
   │
   ▼
rag/ module  (search, document search, answer generation)
   │                         │
   │                         └─► Ollama: Gemma / MamayLM 12B / qwen2.5:7b
   ▼
CLI scripts, eval scripts, Streamlit app
                               ├─ Documents     (find the document)
                               ├─ Ask           (answer with citations, model choice)
                               ├─ Contradictions
                               └─ Generate      (draft from template → DOCX; ISO form)
```

---

## Part 1: POC

Each item states the issue, then what we build to fix it, then how we know it
is done. Items are ordered roughly in the order they should be done.

### 1. Evaluation set and baseline

**Issue.** Nothing measures retrieval or answer quality. We cannot tell the
administration how well the system works, or which LLM answers better.

**Development.**

| Task | Details |
|---|---|
| Write 50+ questions | Mix: plain factual (~25), by identifier such as order number or document code (~8), spanning several documents (~7), **not answerable from the corpus** (~10). Questions are drafted from the documents, then rephrased in the words staff would use rather than the wording of the regulation, so that retrieval is not flattered by word overlap |
| Label the expected answer | For each question: `doc_id`, `section_path`, a short quoted span of the answering text, and a reference answer. Labels point to text, not to chunk ids, so they survive re-chunking. A question may have several acceptable пункти. Unanswerable questions are marked as such |
| Review | A person who knows the regulations reads through the set and fixes or removes questions. The set is honest about being drafted, not collected from real users |
| Storage | `eval/questions.yaml` in the repo |
| Retrieval metrics | `eval/run_retrieval.py`: hit@5, hit@10 and MRR, also split by question type |
| Answer metrics | `eval/run_answers.py`: correct answer, correct citation (document and пункт), refusal on unanswerable questions. Scored by a person with a simple rubric first; an LLM judge can be added later |
| Baseline | Record the current setup in `eval/results.md`. Optionally a BM25-only search (`rank_bm25`), which shows cheaply whether hybrid search (Part 2) is worth doing |

**Note.** With 50 questions one question is 2 percentage points of hit@5, so
differences of a few points are noise.

**Done when:** one command prints the metrics for the current system, and the
baseline is recorded.

### 2. Source of truth and generated files

**Issue.** The hand-corrected Markdown is the source of truth, but
`extract_to_markdown.py` writes straight into `wiki-pages/` and overwrites
every correction when run.

**Development.** The Markdown stays the source of truth (the alternative, a
fully automatic extractor, would have to turn every manual correction made so
far into a code fix, and scans make that unrealistic).

- `extract_to_markdown.py` writes into a staging folder (`incoming/`), never
  into `wiki-pages/`. A document moves to `wiki-pages/` after a person has
  checked it.
- Write the rule into the README: extraction is for new documents; after that,
  edit the `.md`.

**Issue.** Generated files are committed next to the sources:

- `data/chunks.jsonl` (19 MB) is rebuilt from `wiki-pages/` by
  `chunk_documents.py` in seconds. It goes stale whenever a `.md` is edited
  (e.g. on GitHub) without re-chunking, and every re-chunk adds a large diff to
  the history;
- `data/contradiction_shortlist.md` is generated too, but by a slow,
  non-deterministic LLM run; it is a report for people to read, not an input
  of the pipeline;
- `.idea/` holds personal IDE settings;
- `_config.yml` does not exclude `data/`, so the Jekyll site publishes
  `chunks.jsonl` and the shortlist; `eval/` and this plan would be published
  too.

**Development.**

| Path | Decision |
|---|---|
| `data/chunks.jsonl` | Add to `.gitignore` and `git rm --cached`. The README says to run `chunk_documents.py` before indexing and before the eval scripts (they read it). Old copies stay in the history; not worth rewriting it |
| `data/contradiction_shortlist.md` | Keep committed as a dated report (`reports/contradictions-<date>.md`) that records which model and index produced it. A new run makes a new report instead of overwriting the old one |
| `eval/questions.yaml`, `eval/results.md` | Committed: the questions are a source, the results are a recorded measurement written on purpose. Raw output of individual runs is not committed |
| `.idea/` | Add to `.gitignore` and `git rm --cached` |
| `wiki-pages/` frontmatter written by `categorize.py` | Stays committed: like extraction, it runs once per document, after which the `.md` is the source |
| `_config.yml` | Add `data`, `eval`, `reports`, `DEVELOPMENT_PLAN.md`, `pyproject.toml` and `uv.lock` to `exclude`. `templates/` stays published, the constructor loads `templates/iso_document.typ` |

Already ignored and staying so: `data/chroma_db/`,
`data/contradiction_candidates.md`, `build/`, `_site/`.

**Done when:** running the extractor can no longer change a file in
`wiki-pages/`; after a full pipeline run (chunk, index, contradictions, eval)
`git status` shows only intended changes; the site no longer serves `data/`.

### 3. Text quality

**Issue.** The extracted text still has defects that hurt both search and
display:

- about 550 lines in 139 files contain hyphenation left over from line breaks
  ("Стратегіч- ного"); a few of these may be legitimate;
- some titles are wrong: e.g. the "Цілі у сфері якості…" document has the
  title "Державного університету «Житомирська політехніка» на 2025-2026 н.р.",
  while its source PDF says 2024-2025. Wrong titles show up directly in the
  document search;
- tables are flattened into long lines.

**Development.**

- Extend `clean_markdown.py` to join broken hyphenation (dry run first, a
  person reviews the diff).
- A check script that lists documents whose title does not match the start of
  the document or the PDF name, for manual review.
- Tables: leave as they are; a known limitation.

**Done when:** the cleanup is applied and reviewed, and the remaining title
problems are fixed by hand.

### 4. Shared module

**Issue.** Retrieval is copied in `query_rag.py`, `generate_answer.py` and
`find_contradictions.py`, and `generate_answer.py` reloads the embedding model
on every question. The eval scripts and the Streamlit app would add more
copies.

**Development.** One module (`rag/`) with search, document search and answer
generation; models loaded once. The CLI scripts, the eval scripts and the app
call it.

**Note.** Chroma's search (HNSW) is approximate, and every rebuild of the index
builds a slightly different search graph. Rebuilding the index with no other
change moved one eval question (A05: its document went from outside the top 10
to rank 4). So eval numbers can shift by a question or two after a rebuild
alone. With ~6,400 chunks exact search costs milliseconds; switching to it
(or raising Chroma's search breadth to cover the whole index) would make the
numbers change only when something real changed. Not done yet; if done, save
the baseline again.

**Done when:** the CLI and eval scripts use the module and the baseline numbers
are unchanged.

### 5. Document search

**Issue.** Daily use starts with "which document covers X", but search returns
chunks, not documents.

**Development.**

- Group retrieved chunks by document and rank documents (e.g. by their best
  chunk plus the number of matching chunks); show the title, category, order
  number and the best-matching пункти as snippets.
- Also match the question against document titles directly, so a query that
  names the document finds it first.
- Filters by `category` / `subgroup`.
- Measured with the retrieval questions from item 1 at the document level
  (is the right document in the top 5).

**Known limitation.** Filters by status, validity or office need the metadata
work from Part 2; until then superseded documents appear next to current ones.

**Done when:** the right document is in the top 5 for most eval questions and
the filters work.

### 6. Demo app

**Issue.** Everything is CLI only; that cannot be shown to the administration.

**Development.** A Streamlit app on top of the `rag/` module, with tabs:

- **Documents**: document search from item 5;
- **Ask**: the answer, streamed, with citations linked to the document pages
  on the site; a selector of the models available in Ollama (e.g. Gemma and
  `MamayLM-Gemma-3-12B`, which probably has to be imported as a GGUF from
  Hugging Face), and an option to show two models' answers side by side;
- **Contradictions**: item 7;
- **Generate**: items 8 and 9.

A note in the interface: answers are not authoritative; check the linked
original.

**Done when:** the whole demo can be run from the app.

### 7. Contradiction detection

**Issue.** Contradictions and outdated duplicates between documents are a
likely use of the system, but the current shortlist is a one-off Markdown file
judged by `qwen2.5:7b`.

**Development.** Rerun `find_contradictions.py` with a stronger model and show
the shortlist in the app: both пункти side by side with the model's reasoning,
clearly labelled as **candidates for a person to check**. The point of the
demo is to show the use case, not to claim precision.

Cases found by hand while writing the evaluation set, worth checking whether
the shortlist catches them:

- Course-paper defence panel: the assessment regulation says at least two
  staff members, the supervisor *may* be one of them; the educational-process
  regulation says two or three teachers *with* the supervisor (eval question
  A10).
- Unpaid leave: the 2019 internal labour rules allow at most 15 calendar days a
  year; the draft collective agreement 2027–2031 allows 30.
- Induction briefing on general safety (БЖД) for first-year students: the
  training regulation (order 15) assigns it to the occupational safety service;
  the student programme (159/агп) to people appointed by the deans' offices.

**Done when:** the shortlist is visible in the app and a few clear examples are
picked for the demo.

### 8. Document generation from templates

**Issue.** The constructor only formats documents that already exist. Drafting
new documents from templates and the current regulations is the use that shows
what the LLM adds.

**Development.** One document type for the POC:

| Task | Details |
|---|---|
| Pick the type | Something written often with a fixed structure, e.g. a syllabus (робоча програма дисципліни) |
| Template | The official DOCX marked up with docxtpl placeholders (`{{ course_title }}`, `{% for t in topics %}`) |
| Schema | A Pydantic model of the document's fields |
| Generation | The LLM receives the user's input plus relevant regulations from the search (e.g. the grading rules) and returns JSON matching the schema (Ollama structured output). Pydantic validates it; docxtpl renders the DOCX |
| Review | Output is labelled a draft; the app shows which regulations were used |

**Done when:** a correctly formatted draft of the chosen type can be generated
from the app and cites the regulations it relied on.

### 9. Constructor

**Issue.** The constructor exists (`render_pdf.py`, `constructor/`), but has not
been checked as a demo item.

**Development.** Check it on a few documents of different kinds, fix what
breaks, link it from the Generate tab, prepare one example.

**Done when:** the demo example renders correctly.

### 10. Demo and findings for the administration

**Issue.** The POC is only useful if it leads to decisions.

**Development.**

- A demo script: 5–10 questions that show strengths (including an identifier
  question and an unanswerable one) and an honest weak case.
- The retrieval numbers from item 1.
- The questions from Part 3, to be answered by the administration.

**Done when:** the demo has been shown and the answers to Part 3 recorded.

### POC order

```
1 Eval ──► 4 Module ──► 5 Document search ──┐
2 Source of truth ─┐                         ├──► 6 App ──► 10 Demo
3 Text quality ────┘     7 Contradictions ───┤
                         8 Generation ───────┤
                         9 Constructor ──────┘
```

Items 2 and 3 run alongside item 1 and should be finished before the final
re-index. Items 7–9 can run in parallel with the app.

---

## Part 2: After the POC

Quality improvements deliberately left out of the POC. Each is measured
against the evaluation set and kept only if it helps.

### Metadata

**Issue.**

- `status` is `невідомо` in 177 of 185 documents; the other 8 are
  `затверджено` with stray whitespace, so the field is effectively empty;
- about 31% of chunks have no order number, so many citations read
  "№— від —"; 13 chunks have no category;
- there is no notion of an old version: `alhorytm.pdf` and
  `alhorytm zi zminamy.pdf`, files marked "нове" or "випуск N" are indexed
  side by side, so an answer may cite an outdated document;
- `doc_id` is derived from the file name, so renaming a file breaks citations
  and evaluation labels.

**Development.**

| Task | Details |
|---|---|
| Frontmatter schema | A Pydantic model of the frontmatter with enums for `status` and `category`; a script that validates every `.md` (later run in CI) |
| Stable `doc_id` | An explicit `doc_id` field in the frontmatter, filled once from the current file names |
| Status | `чинний` / `втратив чинність` / `невідомо` |
| Versions | `superseded_by: <doc_id>` for replaced documents; `amends: <doc_id>` for amendments ("зі змінами"), which change part of a document rather than replace it; `valid_from` / `valid_until` dates where known |
| Find version pairs | Start from the obvious names, then use `audit_cluster.py` and the contradiction shortlist to find more |
| Order numbers | A helper script proposes values found in the document text; a person approves them |
| Owner | The office that owns the document (see Part 3) |
| Carry into the index | `chunk_documents.py` copies the new fields into every chunk; search skips superseded documents by default |

**Open question.** Who can confirm that a document is no longer in force? That
is an office-ownership question (Part 3).

### Hybrid search

**Issue.** Search is vector-only. Queries by exact identifiers (order numbers
such as "наказ №274/од", document codes such as "П-21.01-…") are served
poorly. `multilingual-e5-base` also cuts off the end of 90 chunks at its
512-token limit.

**Development.**

| Step | Details |
|---|---|
| bge-m3 embeddings | Replaces `multilingual-e5-base`. Accepts 8k tokens and produces sparse (keyword-like) vectors in the same pass |
| Qdrant | Replaces Chroma. Dense + sparse vectors per chunk, searched together, with filters on metadata |
| Identifier matching | Extract order numbers and document codes from the question with a regex and match them exactly against chunk metadata |

### Reranking and context

**Issue.** The best match is not always at the top, and chunks are small
(median ~260 characters, ~570 under 100), which gives the LLM thin context.

**Development.**

- `bge-reranker-v2-m3`: fetch ~30 candidates, rerank, pass the best 5–8 to the
  LLM. Its maximum input length is much shorter than bge-m3's, so chunk size
  and parent sections must fit it.
- Parent sections: when a short chunk is selected, give the LLM its parent
  section too.

---

## Part 3: Prerequisites for a working system

Not built in the POC. Each item states what is missing and what the
administration has to decide.

### Document uploading and lifecycle

**Issue.** New documents are added by running scripts by hand, and corrections
are made by editing Markdown on GitHub. Office staff can't work that way.

**Needed.** A way for an office to upload a document, check the extracted
text, publish it, and replace or retire an old one. After publishing, the
document is re-indexed automatically (incremental: only the changed document is
re-chunked and re-embedded). This splits the system into two parts:

1. **the document base**: documents, metadata, ownership, lifecycle;
2. **the RAG service**: index, search, answers, contradiction detection and
   generation, all reading from the document base.

**Questions.**

- Does the university already have a document management system (АСКОД,
  Megapolis, SharePoint, Google Drive, the website)? If yes, we sync from it
  instead of building uploading.
- What is uploaded: signed scans, the DOCX originals, or both? DOCX makes
  extraction nearly lossless; scans need a person to check the text.
- Who checks extracted text: the uploading office or a central person?

### Office ownership

**Issue.** Each office owns its part of the documents, but nothing records
which office owns a document or prevents one office from changing another's.

**Needed.** An `owner` (office) field on every document; only that office can
replace, amend or retire its documents; an approval step before a document is
published or marked as no longer in force.

**Questions.** Is there a list of offices and who in each is responsible? Does
publishing need approval above the office?

### Read access

**Issue.** All documents in the POC are public. A real system will likely hold
internal ones (HR, finance, personal data).

**Needed.** An `access_level` field, staff login (university SSO if
available), filtering by the user's allowed levels inside the search itself.
Internal documents leave the public repository and the public site; the site
needs the same access rules as the search.

**Questions.** Are all documents readable by all staff, or are there documents
for some offices or roles only?

### Hosting and hardware

**Issue.** The POC runs on one laptop for one user.

**Needed.** A server sized from measurements on the POC laptop: memory and time
per model, multiplied by the expected load. A rough starting point: one server
with a 24–48 GB GPU runs a quantized ~30B model for several simultaneous users;
vLLM instead of Ollama when several people use it at once. Docker Compose for
the services, disk encryption, backups of the documents and the index.

**Questions.**

- How many staff, and how many at the same moment at peak?
- What answer time is acceptable?
- Who hosts and runs it: university IT or the project team?
- Are cloud LLM APIs (with a data-processing agreement) ruled out, or only
  preferred against? This decides between buying a GPU server and paying per
  request.

### API and embedding model placement

**Issue.** With several clients (the app, the site, document generation,
batch jobs) the retrieval code can't stay a Python module imported by scripts.

**Needed.** A FastAPI service (`/search`, `/ask`, `/generate`, `/health`) that
loads the embedding model once at startup. The indexer imports the same
module. The model revision is pinned and the weights are kept in a fixed local
cache. The index stores which embedding model, chunker version and document
commit built it; the service refuses to start on a mismatch, so queries and the
index can never use different models. A separate embedding service only if
several services need it.

### Index updates and rollback

**Issue.** Rebuilding the index replaces the old one; a bad rebuild is
noticed only by users.

**Needed.** Build the new index next to the old one, run the evaluation set,
switch only if the metrics did not drop, keep the previous one for rollback.

### Logging and feedback

**Issue.** Questions may contain personal data; at the same time, real
questions are the best source of new evaluation questions.

**Needed.** A policy: by default don't store questions, or store them
encrypted with a fixed retention period. A "wrong answer" button that saves the
question only with the user's consent and feeds the evaluation set.

### Content owners

**Issue.** The evaluation answers, document status, versions and access levels
all need someone with authority over the content. Technical work can't
replace that.

**Questions.** Who in each office is responsible for its documents in the
system? Which document types should generation support after the POC?

### Known limitations kept as they are

- Tables are flattened into text; questions about table contents work poorly.
- Citations point to the document and пункт, not to the PDF page.
- Answers have no conversation history; each question stands alone.
