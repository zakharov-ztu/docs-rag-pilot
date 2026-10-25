"""Streamlit demo of the RAG pilot: document search, answers with citations,
the contradiction shortlist and a link to the document constructor.

Usage:
    uv run streamlit run app/demo.py

Needs the index (scripts/build_index.py) and, for answers, Ollama running
locally with at least one model pulled.
"""

from __future__ import annotations

import sys
from pathlib import Path
from urllib.parse import quote

import streamlit as st

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from rag.answer import stream_answer  # noqa: E402
from rag.config import CONSTRUCTOR_URL, DEFAULT_LLM, SITE_URL  # noqa: E402
from rag.contradictions import load_shortlist  # noqa: E402
from rag.llm import OllamaError, list_models  # noqa: E402
from rag.retrieval import Retriever  # noqa: E402

DISCLAIMER = (
    "Пілотна система. Відповіді генерує мовна модель і вони можуть містити помилки — "
    "перевіряйте за посиланням на оригінал документа."
)


@st.cache_resource(show_spinner="Завантаження моделі пошуку…")
def get_retriever() -> Retriever:
    return Retriever()


@st.cache_data(show_spinner=False)
def get_categories() -> list[str]:
    return get_retriever().categories()


def document_url(wiki_page: str) -> str:
    # Jekyll renders wiki-pages/<name>.md as wiki-pages/<name>.html.
    return f"{SITE_URL}/{quote(wiki_page.removesuffix('.md') + '.html')}"


def order_label(meta: dict) -> str:
    return f"№{meta['order_number'] or '—'} від {meta['order_date'] or '—'}"


def snippet(text: str, limit: int = 300) -> str:
    """One-line Markdown quote: chunk text may span lines and contain headings."""
    flat = " ".join(text.split()).lstrip("#").strip()
    return "> " + flat[:limit] + ("…" if len(flat) > limit else "")


def sidebar() -> dict:
    st.sidebar.header("Налаштування")
    try:
        models = list_models()
    except OllamaError:
        models = []
        st.sidebar.warning("Ollama не запущена — відповіді недоступні. Запустіть `ollama serve`.")
    if not models:
        models = [DEFAULT_LLM]

    default = models.index(DEFAULT_LLM) if DEFAULT_LLM in models else 0
    model = st.sidebar.selectbox("Модель", models, index=default)
    compare = st.sidebar.checkbox("Порівняти з другою моделлю", disabled=len(models) < 2)
    second_model = None
    if compare:
        others = [m for m in models if m != model]
        second_model = st.sidebar.selectbox("Друга модель", others)
    k = st.sidebar.slider("Фрагментів у контексті", min_value=3, max_value=10, value=5)
    st.sidebar.caption(DISCLAIMER)
    return {"models": [m for m in (model, second_model) if m], "k": k}


def documents_tab() -> None:
    st.subheader("Пошук документів")
    st.caption("Які документи регулюють питання — з найрелевантнішими пунктами кожного.")
    col_query, col_category = st.columns([3, 1])
    query = col_query.text_input("Що шукаємо?", placeholder="напр. поселення в гуртожиток")
    category = col_category.selectbox("Категорія", ["Усі", *get_categories()])
    if not query:
        return

    docs = get_retriever().search_documents(query, category=None if category == "Усі" else category)
    if not docs:
        st.info("Нічого не знайдено.")
        return
    for doc in docs:
        meta = doc["meta"]
        with st.container(border=True):
            st.markdown(f"**[{meta['title']}]({document_url(meta['wiki_page'])})**")
            st.caption(
                f"{meta['category'] or 'Без категорії'} · {order_label(meta)} · "
                f"схожість {doc['similarity']:.3f} · відповідних фрагментів: {len(doc['chunks'])}"
            )
            for c in doc["chunks"][:3]:
                st.markdown(snippet(c["text"]))


def show_fragments(chunks: list[dict]) -> None:
    with st.expander(f"Використані фрагменти ({len(chunks)})"):
        for i, c in enumerate(chunks, 1):
            meta = c["meta"]
            st.markdown(
                f"**[{i}] [{meta['title']}]({document_url(meta['wiki_page'])})** — "
                f"{meta['section_path'] or '—'}  \n{order_label(meta)} · схожість {c['similarity']:.3f}"
            )
            st.text(c["text"][:700] + ("…" if len(c["text"]) > 700 else ""))


def ask_tab(settings: dict) -> None:
    st.subheader("Питання до нормативної бази")
    question = st.text_area("Питання", placeholder="напр. До котрої години в гуртожиток можуть приходити гості?")

    if st.button("Відповісти", type="primary", disabled=not question.strip()):
        chunks = get_retriever().search(question, settings["k"])
        answers = {}
        columns = st.columns(len(settings["models"]))
        for col, model in zip(columns, settings["models"]):
            with col:
                st.markdown(f"**{model}**")
                try:
                    answers[model] = st.write_stream(stream_answer(question, chunks, model))
                except OllamaError as exc:
                    answers[model] = None
                    st.error(f"Модель не відповіла: {exc}")
        st.session_state.last_answer = {"question": question, "chunks": chunks, "answers": answers}
        show_fragments(chunks)
    elif last := st.session_state.get("last_answer"):
        st.caption(f"Останнє питання: {last['question']}")
        columns = st.columns(len(last["answers"]))
        for col, (model, answer) in zip(columns, last["answers"].items()):
            with col:
                st.markdown(f"**{model}**")
                if answer is None:
                    st.error("Модель не відповіла.")
                else:
                    st.markdown(answer)
        show_fragments(last["chunks"])


def contradictions_tab() -> None:
    st.subheader("Можливі суперечності між документами")
    summary, pairs = load_shortlist()
    if not pairs:
        st.info("Список ще не сформовано: запустіть `uv run scripts/find_contradictions.py`.")
        return
    st.warning(
        "Це **кандидати для перевірки людиною**: пари пунктів із різних документів про одне й те саме, "
        "які мовна модель позначила як можливу суперечність. Модель помиляється."
    )
    st.caption(summary)
    for n, pair in enumerate(pairs, 1):
        with st.container(border=True):
            st.markdown(f"**{n}. {pair['verdict']}** · схожість {pair['similarity']:.3f}")
            st.markdown(f"*Пояснення моделі:* {pair['explanation']}")
            col_a, col_b = st.columns(2)
            for col, side in ((col_a, pair["a"]), (col_b, pair["b"])):
                with col:
                    st.markdown(f"**[{side['title']}]({document_url(side['wiki_page'])})**")
                    st.caption(side["section"])
                    st.markdown(snippet(side["text"], limit=400))


def generate_tab() -> None:
    st.subheader("Генерація документів")
    st.markdown(
        "**Конструктор** оформлює наявний документ на бланку ISO університету й формує PDF "
        "просто в браузері."
    )
    st.link_button("Відкрити конструктор", CONSTRUCTOR_URL)
    st.divider()
    st.markdown(
        "**Чернетка нового документа за шаблоном** (напр. робочої програми дисципліни) "
        "з урахуванням чинних положень — у розробці."
    )


def main() -> None:
    st.set_page_config(page_title="Нормативна база — демо", page_icon="📚", layout="wide")
    st.title("Нормативна база Житомирської політехніки")
    settings = sidebar()
    documents, ask, contradictions, generate = st.tabs(["Документи", "Питання", "Суперечності", "Генерація"])
    with documents:
        documents_tab()
    with ask:
        ask_tab(settings)
    with contradictions:
        contradictions_tab()
    with generate:
        generate_tab()


main()
