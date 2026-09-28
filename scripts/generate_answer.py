"""Retrieve relevant chunks (query_rag) and generate a grounded answer
with a local Ollama model — no external API call, nothing leaves the
machine.

Usage:
    python3 scripts/generate_answer.py "Як подати апеляцію на результати вступних іспитів?"
    python3 scripts/generate_answer.py "..." --k 8 --model qwen2.5:7b

Requires Ollama running locally (http://localhost:11434) with the model
already pulled: `ollama pull qwen2.5:7b`.
"""

from __future__ import annotations

import argparse
import json
import sys
import urllib.error
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from query_rag import DB_DIR, COLLECTION_NAME, MODEL_NAME  # noqa: E402

import chromadb
from sentence_transformers import SentenceTransformer

OLLAMA_URL = "http://localhost:11434/api/chat"
DEFAULT_OLLAMA_MODEL = "qwen2.5:7b"

SYSTEM_PROMPT = """Ти — асистент нормативної бази Державного університету «Житомирська політехніка».
Відповідай ВИКЛЮЧНО на основі фрагментів документів, наданих нижче в контексті. Не використовуй жодних знань поза цим контекстом, навіть якщо вони здаються тобі правильними.

Правила:
1. Кожне твердження у відповіді обов'язково супроводжуй посиланням на джерело — назву документа, статус, номер і дату наказу та розділ, як вони вказані в метаданих фрагмента. Формат посилання: (Джерело: «<назва документа>», <статус>, №<наказ> від <дата>, розділ <розділ>).
2. Якщо в наданих фрагментах немає відповіді на питання — чесно скажи, що в наявних документах цієї інформації немає, і не вигадуй та не здогадуйся. Не намагайся "натягнути" часткову відповідь, якщо вона прямо не випливає з тексту фрагментів.
3. Якщо фрагменти містять суперечливу інформацію з різних документів — обов'язково повідом про цю суперечність користувачу, а не мовчки обирай одну версію.
4. Відповідай українською мовою, стисло і по суті."""


def retrieve(question: str, k: int) -> list[dict]:
    # Forced to CPU — see build_index.py for why (MPS gave wrong embeddings
    # for short query strings with this model on this machine).
    model = SentenceTransformer(MODEL_NAME, device="cpu")
    client = chromadb.PersistentClient(path=str(DB_DIR))
    collection = client.get_collection(COLLECTION_NAME)

    query_embedding = model.encode(["query: " + question], normalize_embeddings=True)
    results = collection.query(
        query_embeddings=query_embedding.tolist(),
        n_results=k,
        include=["documents", "metadatas", "distances"],
    )
    chunks = []
    for doc, meta, dist in zip(
        results["documents"][0], results["metadatas"][0], results["distances"][0]
    ):
        chunks.append({"text": doc, "meta": meta, "similarity": 1 - dist})
    return chunks


def build_context(chunks: list[dict]) -> str:
    blocks = []
    for i, c in enumerate(chunks, 1):
        m = c["meta"]
        category = m["category"] + (f" / {m['subgroup']}" if m["subgroup"] else "")
        header = (
            f"[Фрагмент {i}]\n"
            f"Документ: {m['title']}\n"
            f"Категорія: {category}\n"
            f"Статус: {m['status']}\n"
            f"№ наказу: {m['order_number'] or '—'} від {m['order_date'] or '—'}\n"
            f"Розділ: {m['section_path'] or '—'}"
        )
        blocks.append(f"{header}\n\n{c['text']}")
    return "\n\n---\n\n".join(blocks)


def call_ollama(model: str, system: str, user: str) -> str:
    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": system},
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
        with urllib.request.urlopen(req, timeout=180) as resp:
            body = json.loads(resp.read().decode("utf-8"))
    except urllib.error.URLError as exc:
        raise SystemExit(
            f"Не вдалося з'єднатися з Ollama на {OLLAMA_URL}: {exc}\n"
            f"Переконайся, що Ollama запущена (`ollama serve`) і модель завантажена (`ollama pull {model}`)."
        ) from exc
    return body["message"]["content"]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("question", help="Питання до нормативної бази")
    parser.add_argument("--k", type=int, default=5, help="Кількість фрагментів для контексту")
    parser.add_argument("--model", default=DEFAULT_OLLAMA_MODEL, help="Назва моделі в Ollama")
    args = parser.parse_args()

    chunks = retrieve(args.question, args.k)
    context = build_context(chunks)
    user_prompt = f"Контекст (фрагменти документів):\n\n{context}\n\n---\n\nПитання: {args.question}"

    answer = call_ollama(args.model, SYSTEM_PROMPT, user_prompt)

    print(f"Питання: {args.question}\n")
    print(f"Відповідь:\n{answer}\n")
    print("Використані фрагменти:")
    for i, c in enumerate(chunks, 1):
        m = c["meta"]
        section = m["section_path"] or "—"
        print(f"  [{i}] {m['title']}")
        print(f"      Пункт: {section}")
        print(f"      №{m['order_number'] or '—'} від {m['order_date'] or '—'} | {m['wiki_page']} (similarity {c['similarity']:.3f})")


if __name__ == "__main__":
    main()
