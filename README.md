# docs-rag-pilot

Pilot retrieval-augmented generation (RAG) system over the regulations of
Zhytomyr Polytechnic State University (Державний університет «Житомирська
політехніка»): положення, накази, інструкції, політики.

The pipeline turns source PDFs into clean, structured Markdown, splits it into
clause-level chunks, indexes them in a local vector store and answers questions
in Ukrainian with citations to the exact document and пункт. Everything —
embeddings, vector store, LLM — runs on the local machine; no document text is
sent to an external API.

The Markdown is also published as a Jekyll site (GitHub Pages) with a document
index and an in-browser constructor that renders a document onto the
university's ISO form.

## Repository layout

| Path | Contents |
|---|---|
| `source-pdfs/` | Original PDF/DOCX documents |
| `wiki-pages/` | Extracted Markdown, one file per document, with YAML frontmatter (title, status, order number/date, category). **Source of truth** — hand-corrected, extraction is no longer re-run over it |
| `data/chunks.jsonl` | Retrieval chunks produced from `wiki-pages/` |
| `data/chroma_db/` | Local Chroma vector index (generated, git-ignored) |
| `rag/` | Shared RAG code used by the scripts and the eval: configuration, embeddings and search, the Ollama client, answer generation |
| `scripts/` | Pipeline and audit scripts (see below) |
| `app/` | Streamlit demo app |
| `eval/` | Evaluation set (`questions.yaml`), its checker, the retrieval evaluation and recorded results |
| `templates/iso_document.typ` | Typst template for the ISO document form |
| `constructor/`, `_layouts/`, `_includes/`, `index.md` | Jekyll site |

## Requirements

- [uv](https://docs.astral.sh/uv/) — manages Python (3.11–3.13) and dependencies
- [Ollama](https://ollama.com/) — local LLM, needed for answer generation and the contradiction judge
- Only for re-extracting PDFs: Tesseract with Ukrainian language data, and Poppler
- Only for rendering PDFs: [Typst](https://typst.app/)

On macOS:

```sh
brew install uv ollama
brew install tesseract tesseract-lang poppler   # optional: PDF extraction / OCR
brew install typst                              # optional: PDF rendering
```

## Installation

```sh
git clone git@github.com:zakharov-ztu/docs-rag-pilot.git
cd docs-rag-pilot
uv sync
```

`uv sync` creates `.venv/` with the pinned Python version (`.python-version`)
and installs the dependencies from `pyproject.toml` / `uv.lock`.

Pull the LLM once:

```sh
ollama pull qwen2.5:7b
```

## Running

### 1. Build the index

```sh
uv run scripts/chunk_documents.py   # wiki-pages/*.md -> data/chunks.jsonl
uv run scripts/build_index.py       # data/chunks.jsonl -> data/chroma_db/
```

The first `build_index.py` run downloads the embedding model
(`intfloat/multilingual-e5-base`, ~1 GB) into the Hugging Face cache. Embedding
runs on CPU on purpose (the MPS backend produced wrong embeddings on Apple
Silicon) and takes a few minutes for the current ~6,400 chunks.

Re-run both steps whenever `wiki-pages/` changes.

### 2. Ask questions

Retrieval only — inspect which chunks come back:

```sh
uv run scripts/query_rag.py "Як подати апеляцію на результати вступних іспитів?" --k 5
```

Retrieval + generated answer with citations (Ollama must be running —
`ollama serve`, or the Ollama desktop app):

```sh
uv run scripts/generate_answer.py "Як подати апеляцію на результати вступних іспитів?"
uv run scripts/generate_answer.py "Як подати апеляцію на результати вступних іспитів?" --k 8 --model qwen2.5:14b
```

### 3. Demo app

```sh
uv run streamlit run app/demo.py
```

Opens in the browser with four tabs: document search, questions with cited
answers (choose any model pulled into Ollama, or compare two side by side),
the contradiction shortlist, and a link to the document constructor. Needs
the index from step 1; answers need Ollama running.

### Other scripts

| Command | Purpose |
|---|---|
| `uv run scripts/extract_to_markdown.py` | Re-extract `source-pdfs/` into `wiki-pages/` (text layer + per-page OCR fallback). **Overwrites hand corrections** in `wiki-pages/` — use only for new documents |
| `uv run scripts/clean_markdown.py [--write]` | Fix leftover ЗМІСТ entries and wrapped headings in `wiki-pages/` (dry run by default) |
| `uv run scripts/categorize.py [--dry-run] [--force]` | Assign `category`/`subgroup` in frontmatter |
| `uv run scripts/find_contradictions.py [--no-judge]` | Find highly similar chunks across different documents, optionally judged by the local LLM; writes `data/contradiction_candidates.md` and `data/contradiction_shortlist.md`. Needs the index from step 1 |
| `uv run scripts/audit_cluster.py [--threshold 0.2]` | Cluster documents by TF-IDF similarity for a duplication/obsolescence review |
| `uv run scripts/render_pdf.py wiki-pages/<doc>.md [--copy N] [--uncontrolled]` | Render a document onto the ISO form into `build/` (needs Typst) |

### Jekyll site (optional)

The site is built by GitHub Pages from `main`. To preview locally with Ruby
and the `github-pages` gem installed:

```sh
jekyll serve --baseurl /docs-rag-pilot
```

## Status and limitations

This is a proof of concept. Known issues, the plan to fix them, and what a
working system would additionally need are in
[DEVELOPMENT_PLAN.md](DEVELOPMENT_PLAN.md).
