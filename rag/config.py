"""Paths and model names shared by the whole pipeline."""

from __future__ import annotations

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
WIKI_DIR = REPO_ROOT / "wiki-pages"
CHUNKS_PATH = REPO_ROOT / "data" / "chunks.jsonl"
DB_DIR = REPO_ROOT / "data" / "chroma_db"
COLLECTION_NAME = "ztu_docs"
CONTRADICTIONS_PATH = REPO_ROOT / "data" / "contradiction_shortlist.md"

EMBEDDING_MODEL = "intfloat/multilingual-e5-base"

# The Jekyll site (GitHub Pages) that renders wiki-pages/; citations link here.
SITE_URL = "https://zakharov-ztu.github.io/docs-rag-pilot"
CONSTRUCTOR_URL = SITE_URL + "/constructor/"

OLLAMA_URL = "http://localhost:11434/api/chat"
DEFAULT_LLM = "qwen2.5:7b"
