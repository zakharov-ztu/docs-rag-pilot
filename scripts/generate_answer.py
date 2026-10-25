"""Retrieve relevant chunks and generate a grounded answer with a local
Ollama model — no external API call, nothing leaves the machine.

Usage:
    uv run scripts/generate_answer.py "Як подати апеляцію на результати вступних іспитів?"
    uv run scripts/generate_answer.py "..." --k 8 --model qwen2.5:7b

Requires Ollama running locally (http://localhost:11434) with the model
already pulled: `ollama pull qwen2.5:7b`.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from rag.answer import generate_answer  # noqa: E402
from rag.config import DEFAULT_LLM  # noqa: E402
from rag.llm import OllamaError  # noqa: E402
from rag.retrieval import Retriever  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("question", help="Питання до нормативної бази")
    parser.add_argument("--k", type=int, default=5, help="Кількість фрагментів для контексту")
    parser.add_argument("--model", default=DEFAULT_LLM, help="Назва моделі в Ollama")
    args = parser.parse_args()

    chunks = Retriever().search(args.question, args.k)
    try:
        answer = generate_answer(args.question, chunks, args.model)
    except OllamaError as exc:
        raise SystemExit(
            f"Не вдалося з'єднатися з Ollama ({exc}).\n"
            f"Переконайся, що Ollama запущена (`ollama serve`) і модель завантажена (`ollama pull {args.model}`)."
        ) from exc

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
