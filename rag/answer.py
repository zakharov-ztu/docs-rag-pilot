"""Grounded answer generation: retrieved chunks -> prompt -> local LLM."""

from __future__ import annotations

from collections.abc import Iterator

from rag.llm import chat, chat_stream

SYSTEM_PROMPT = """Ти — асистент нормативної бази Державного університету «Житомирська політехніка».
Відповідай ВИКЛЮЧНО на основі фрагментів документів, наданих нижче в контексті. Не використовуй жодних знань поза цим контекстом, навіть якщо вони здаються тобі правильними.

Правила:
1. Кожне твердження у відповіді обов'язково супроводжуй посиланням на джерело — назву документа, статус, номер і дату наказу та розділ, як вони вказані в метаданих фрагмента. Формат посилання: (Джерело: «<назва документа>», <статус>, №<наказ> від <дата>, розділ <розділ>).
2. Якщо в наданих фрагментах немає відповіді на питання — чесно скажи, що в наявних документах цієї інформації немає, і не вигадуй та не здогадуйся. Не намагайся "натягнути" часткову відповідь, якщо вона прямо не випливає з тексту фрагментів.
3. Якщо фрагменти містять суперечливу інформацію з різних документів — обов'язково повідом про цю суперечність користувачу, а не мовчки обирай одну версію.
4. Відповідай українською мовою, стисло і по суті."""


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


def build_user_prompt(question: str, chunks: list[dict]) -> str:
    return f"Контекст (фрагменти документів):\n\n{build_context(chunks)}\n\n---\n\nПитання: {question}"


def generate_answer(question: str, chunks: list[dict], model: str) -> str:
    """Raises rag.llm.OllamaError if the model can't be reached."""
    return chat(model, SYSTEM_PROMPT, build_user_prompt(question, chunks))


def stream_answer(question: str, chunks: list[dict], model: str) -> Iterator[str]:
    """Like generate_answer(), but yields the answer as it is generated."""
    return chat_stream(model, SYSTEM_PROMPT, build_user_prompt(question, chunks))
