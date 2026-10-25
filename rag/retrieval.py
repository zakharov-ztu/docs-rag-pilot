"""Embeddings and vector search over the Chroma index.

E5 models expect a "query: " / "passage: " prefix on the text they embed
(asymmetric retrieval); the prefixes are applied here so that indexing and
search can never disagree about them.
"""

from __future__ import annotations

import chromadb
from sentence_transformers import SentenceTransformer

from rag.config import COLLECTION_NAME, DB_DIR, EMBEDDING_MODEL


def load_embedding_model() -> SentenceTransformer:
    # Forced to CPU: PyTorch's MPS (Apple GPU) backend produced measurably
    # wrong embeddings for short strings with this model on this machine —
    # verified by comparing a query embedded on MPS vs CPU against the
    # same stored passage embedding (0.75 vs the correct 0.86 cosine
    # similarity). The model is small enough that CPU costs nothing that
    # matters for a corpus this size.
    return SentenceTransformer(EMBEDDING_MODEL, device="cpu")


def embed_passages(model: SentenceTransformer, texts: list[str]) -> list[list[float]]:
    embeddings = model.encode(["passage: " + t for t in texts], show_progress_bar=False, normalize_embeddings=True)
    return embeddings.tolist()


def embed_query(model: SentenceTransformer, question: str) -> list[float]:
    return model.encode(["query: " + question], normalize_embeddings=True)[0].tolist()


def open_collection() -> chromadb.Collection:
    return chromadb.PersistentClient(path=str(DB_DIR)).get_collection(COLLECTION_NAME)


class Retriever:
    """Loads the embedding model and opens the index once; search() can then
    be called for many questions without reloading anything."""

    def __init__(self) -> None:
        self.model = load_embedding_model()
        self.collection = open_collection()

    def search(self, question: str, k: int = 5, where: dict | None = None) -> list[dict]:
        """Top-k chunks for a question, best first, each as
        {"text", "meta", "similarity"}; meta holds the chunk metadata stored
        by scripts/build_index.py (doc_id, title, section_path, ...).
        `where` is a Chroma metadata filter, e.g. {"category": "..."}."""
        results = self.collection.query(
            query_embeddings=[embed_query(self.model, question)],
            n_results=k,
            where=where,
            include=["documents", "metadatas", "distances"],
        )
        return [
            {"text": doc, "meta": meta, "similarity": 1 - dist}
            for doc, meta, dist in zip(results["documents"][0], results["metadatas"][0], results["distances"][0])
        ]

    def search_documents(
        self, question: str, n_docs: int = 10, category: str | None = None, k_chunks: int = 60
    ) -> list[dict]:
        """Documents relevant to a question, best first: the top k_chunks
        chunks grouped by document, each document ranked by its best chunk.
        Returns {"meta", "similarity", "chunks"} per document, where chunks
        are that document's matching chunks, best first."""
        chunks = self.search(question, k_chunks, where={"category": category} if category else None)
        docs: dict[str, dict] = {}
        for c in chunks:
            doc_id = c["meta"]["doc_id"]
            if doc_id not in docs:
                docs[doc_id] = {"meta": c["meta"], "similarity": c["similarity"], "chunks": []}
            docs[doc_id]["chunks"].append(c)
        return list(docs.values())[:n_docs]

    def categories(self) -> list[str]:
        metas = self.collection.get(include=["metadatas"])["metadatas"]
        return sorted({m["category"] for m in metas if m["category"]})
