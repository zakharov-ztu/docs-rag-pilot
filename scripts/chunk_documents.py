"""Split wiki-pages/*.md into retrieval-ready chunks for the RAG pilot.

Strategy: chunk by document section (heading hierarchy ## > ### > ####,
i.e. розділ > підрозділ > пункт). Each chunk is self-sufficient: it carries
its own copy of title/category/status/order metadata and its section
breadcrumb, both as structured JSON fields and baked into an
`embedding_text` string, so a fragment retrieved on its own still says
which document and clause it came from.

Output: data/chunks.jsonl, one JSON object per chunk.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parent.parent
WIKI_DIR = REPO_ROOT / "wiki-pages"
OUT_PATH = REPO_ROOT / "data" / "chunks.jsonl"

HEADING_RE = re.compile(r"^(#{2,4})\s+(.*\S)\s*$")

# A leaf section shorter than this (no sub-heading text of its own) gets
# merged into the next sibling instead of becoming a noise-chunk on its own.
MIN_CHUNK_CHARS = 40
# A leaf section longer than this gets split further at paragraph breaks.
MAX_CHUNK_CHARS = 2500
# Target size used when splitting headingless documents into paragraph groups.
TARGET_CHARS = 1200


def split_frontmatter(text: str) -> tuple[dict, str]:
    if not text.startswith("---\n"):
        return {}, text
    end = text.find("\n---\n", 4)
    if end == -1:
        return {}, text
    fm_raw = text[4:end]
    body = text[end + 5 :]
    try:
        fm = yaml.safe_load(fm_raw) or {}
    except yaml.YAMLError:
        fm = {}
    return fm, body


def split_paragraphs(text: str) -> list[str]:
    paras = [p.strip() for p in re.split(r"\n\s*\n", text)]
    return [p for p in paras if p]


def group_paragraphs(paragraphs: list[str], target: int) -> list[str]:
    """Greedily pack paragraphs into chunks close to `target` chars."""
    groups: list[str] = []
    current: list[str] = []
    current_len = 0
    for p in paragraphs:
        if current and current_len + len(p) > target:
            groups.append("\n\n".join(current))
            current, current_len = [], 0
        current.append(p)
        current_len += len(p) + 2
    if current:
        groups.append("\n\n".join(current))
    return groups


def split_oversized(text: str) -> list[str]:
    if len(text) <= MAX_CHUNK_CHARS:
        return [text]
    paras = split_paragraphs(text)
    if len(paras) > 1:
        return group_paragraphs(paras, TARGET_CHARS)
    # single giant paragraph: hard-split on whitespace near the target size
    parts = []
    remaining = text
    while len(remaining) > MAX_CHUNK_CHARS:
        cut = remaining.rfind(" ", 0, TARGET_CHARS)
        if cut <= 0:
            cut = TARGET_CHARS
        parts.append(remaining[:cut].strip())
        remaining = remaining[cut:].strip()
    if remaining:
        parts.append(remaining)
    return parts


class Section:
    def __init__(self, level: int, title: str, parent: "Section | None"):
        self.level = level
        self.title = title
        self.parent = parent
        self.text_lines: list[str] = []
        self.children: list["Section"] = []

    def breadcrumb(self) -> str:
        parts = []
        node = self
        while node is not None and node.level > 0:
            parts.append(node.title)
            node = node.parent
        return " > ".join(reversed(parts))

    def own_text(self) -> str:
        return "\n".join(self.text_lines).strip()

    def leaves(self):
        """Yield (breadcrumb, text) for every section that has direct text,
        including a section's own preamble text before its first child."""
        own = self.own_text()
        if own:
            yield self.breadcrumb(), own
        for child in self.children:
            yield from child.leaves()


def parse_sections(body: str) -> Section:
    root = Section(level=0, title="", parent=None)
    stack = [root]
    for line in body.splitlines():
        m = HEADING_RE.match(line)
        if m:
            level = len(m.group(1)) - 1  # ## -> 1, ### -> 2, #### -> 3
            title = m.group(2).strip()
            while stack[-1].level >= level:
                stack.pop()
            node = Section(level=level, title=title, parent=stack[-1])
            stack[-1].children.append(node)
            stack.append(node)
        else:
            stack[-1].text_lines.append(line)
    return root


def merge_tiny_leaves(leaves: list[tuple[str, str]]) -> list[tuple[str, str]]:
    """Merge sections too short to stand alone (e.g. a lone "ЗМІСТ" label
    before the first real heading) into a neighbor. Merges into the
    previous section when one exists, otherwise holds the fragment and
    prepends it to the next section (covers leading fragments)."""
    merged: list[tuple[str, str]] = []
    pending: str | None = None
    for breadcrumb, text in leaves:
        if pending is not None:
            text = pending + "\n\n" + text
            pending = None
        if len(text) < MIN_CHUNK_CHARS:
            if merged:
                prev_bc, prev_text = merged[-1]
                merged[-1] = (prev_bc, prev_text + "\n\n" + text)
            else:
                pending = text
        else:
            merged.append((breadcrumb, text))
    if pending is not None:
        if merged:
            prev_bc, prev_text = merged[-1]
            merged[-1] = (prev_bc, prev_text + "\n\n" + pending)
        else:
            merged.append(("", pending))
    return merged


def build_embedding_text(meta: dict, section_path: str, text: str) -> str:
    category = meta.get("category") or "—"
    subgroup = meta.get("subgroup")
    if subgroup:
        category = f"{category} / {subgroup}"
    header = (
        f"Документ: {meta.get('title') or '—'}\n"
        f"Категорія: {category}\n"
        f"Статус: {meta.get('status') or 'невідомо'}\n"
        f"№ наказу: {meta.get('order_number') or '—'} від {meta.get('order_date') or '—'}\n"
        f"Розділ: {section_path or '—'}"
    )
    return f"{header}\n\n{text}"


def chunk_document(md_path: Path) -> list[dict]:
    raw = md_path.read_text(encoding="utf-8")
    meta, body = split_frontmatter(raw)
    root = parse_sections(body)
    leaves = list(root.leaves())

    if not leaves:
        # no headings at all: fall back to paragraph grouping over the whole body
        paras = split_paragraphs(body)
        groups = group_paragraphs(paras, TARGET_CHARS)
        leaves = [("", g) for g in groups]
    else:
        leaves = merge_tiny_leaves(leaves)

    doc_id = md_path.stem
    chunks = []
    idx = 0
    for section_path, text in leaves:
        for piece in split_oversized(text):
            piece = piece.strip()
            if not piece:
                continue
            chunks.append(
                {
                    "chunk_id": f"{doc_id}::{idx}",
                    "doc_id": doc_id,
                    "wiki_page": f"wiki-pages/{md_path.name}",
                    "source_pdf": meta.get("source_pdf"),
                    "title": meta.get("title"),
                    "category": meta.get("category"),
                    "subgroup": meta.get("subgroup"),
                    "status": meta.get("status"),
                    "order_number": meta.get("order_number"),
                    "order_date": meta.get("order_date"),
                    "section_path": section_path,
                    "chunk_index": idx,
                    "text": piece,
                    "embedding_text": build_embedding_text(meta, section_path, piece),
                }
            )
            idx += 1
    return chunks


def main() -> None:
    md_files = sorted(WIKI_DIR.glob("*.md"))
    all_chunks = []
    for md_path in md_files:
        all_chunks.extend(chunk_document(md_path))

    OUT_PATH.parent.mkdir(exist_ok=True)
    with OUT_PATH.open("w", encoding="utf-8") as f:
        for chunk in all_chunks:
            f.write(json.dumps(chunk, ensure_ascii=False) + "\n")

    lengths = [len(c["text"]) for c in all_chunks]
    per_doc: dict[str, int] = {}
    for c in all_chunks:
        per_doc[c["doc_id"]] = per_doc.get(c["doc_id"], 0) + 1

    print(f"Documents processed: {len(md_files)}")
    print(f"Total chunks: {len(all_chunks)}")
    print(f"Chunk length chars: min={min(lengths)} median={sorted(lengths)[len(lengths)//2]} max={max(lengths)}")
    single = [d for d, n in per_doc.items() if n == 1]
    print(f"Docs producing a single chunk: {len(single)}")
    if single:
        print("  e.g.:", ", ".join(single[:5]))
    print(f"Wrote {OUT_PATH.relative_to(REPO_ROOT)}")


if __name__ == "__main__":
    main()
