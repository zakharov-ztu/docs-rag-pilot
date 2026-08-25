#!/usr/bin/env python3
"""Extract text from PDFs in source-pdfs/ into structured Markdown in wiki-pages/.

For each PDF:
  1. Try to extract the text layer with pdfplumber.
  2. If the text layer is missing or looks broken (too little text, or mostly
     garbage characters), fall back to OCR (pdf2image -> tesseract, ukr+eng).
  3. Split the text into logical blocks by document structure (roman-numeral
     sections, numbered "punkty"/"pidpunkty", etc.) using Markdown headings.
  4. Try to recognize order number / date from the text.
  5. Write <pdf_stem>.md into wiki-pages/ with a YAML frontmatter header.

Usage:
    .venv/bin/python scripts/extract_to_markdown.py
"""

from __future__ import annotations

import logging
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path

import pdfplumber
import pytesseract
import yaml
from pdf2image import convert_from_path

ROOT = Path(__file__).resolve().parent.parent
SOURCE_DIR = ROOT / "source-pdfs"
OUTPUT_DIR = ROOT / "wiki-pages"

OCR_LANGS = "ukr+eng"
OCR_DPI = 300

# Below this many characters per page (on average) we treat the text layer
# as missing/broken and fall back to OCR.
MIN_CHARS_PER_PAGE = 40

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
log = logging.getLogger("extract_to_markdown")


@dataclass
class ExtractionResult:
    pdf_path: Path
    text: str
    used_ocr: bool
    pages: int
    error: str | None = None


@dataclass
class RunStats:
    total: int = 0
    succeeded: int = 0
    used_ocr: int = 0
    failed: list[tuple[str, str]] = field(default_factory=list)


# --------------------------------------------------------------------------
# Text extraction
# --------------------------------------------------------------------------

def extract_with_pdfplumber(pdf_path: Path) -> tuple[str, int]:
    pages_text = []
    with pdfplumber.open(pdf_path) as pdf:
        n_pages = len(pdf.pages)
        for page in pdf.pages:
            pages_text.append(page.extract_text() or "")
    return "\n\n".join(pages_text), n_pages


def extract_with_ocr(pdf_path: Path) -> tuple[str, int]:
    images = convert_from_path(str(pdf_path), dpi=OCR_DPI)
    pages_text = [pytesseract.image_to_string(img, lang=OCR_LANGS) for img in images]
    return "\n\n".join(pages_text), len(images)


def is_text_layer_broken(text: str, n_pages: int) -> bool:
    if not text or not text.strip():
        return True
    stripped = text.strip()
    if n_pages > 0 and len(stripped) / n_pages < MIN_CHARS_PER_PAGE:
        return True
    # Mostly non-letter characters usually means a garbled/font-mapped layer.
    letters = sum(ch.isalpha() for ch in stripped)
    if letters / max(len(stripped), 1) < 0.3:
        return True
    return False


def extract_pdf(pdf_path: Path) -> ExtractionResult:
    try:
        text, n_pages = extract_with_pdfplumber(pdf_path)
    except Exception as exc:  # pdfplumber can choke on malformed PDFs
        log.warning("pdfplumber failed for %s (%s), falling back to OCR", pdf_path.name, exc)
        text, n_pages = "", 0

    if is_text_layer_broken(text, n_pages):
        log.info("%s: text layer missing/weak, running OCR (ukr+eng)...", pdf_path.name)
        ocr_text, ocr_pages = extract_with_ocr(pdf_path)
        return ExtractionResult(pdf_path, ocr_text, used_ocr=True, pages=ocr_pages or n_pages)

    return ExtractionResult(pdf_path, text, used_ocr=False, pages=n_pages)


# --------------------------------------------------------------------------
# Structure detection / Markdown formatting
# --------------------------------------------------------------------------

# Roman-numeral top-level sections, e.g. "I. ЗАГАЛЬНІ ПОЛОЖЕННЯ"
RE_SECTION = re.compile(r"^([IVXLCDM]{1,6})\.\s+(\S.*)$")
# Numbered points, e.g. "1. Текст" or "1.2. Текст"
RE_POINT = re.compile(r"^(\d{1,3}(?:\.\d{1,3}){0,3})\.?\s+(\S.*)$")
# Sub-points like "1.2.3." handled by RE_POINT via dot count.


def split_into_blocks(text: str) -> str:
    """Reflow raw extracted text into Markdown headings for sections/points."""
    lines = [ln.rstrip() for ln in text.split("\n")]
    out: list[str] = []

    for raw_line in lines:
        line = raw_line.strip()
        if not line:
            out.append("")
            continue

        m_section = RE_SECTION.match(line)
        if m_section:
            out.append(f"\n## {m_section.group(1)}. {m_section.group(2)}\n")
            continue

        m_point = RE_POINT.match(line)
        if m_point:
            depth = m_point.group(1).count(".") + 1  # 1 -> level3, 1.2 -> level4, ...
            heading_level = min(3 + (depth - 1), 6)
            out.append(f"\n{'#' * heading_level} {m_point.group(1)}. {m_point.group(2)}")
            continue

        out.append(line)

    # Collapse 3+ blank lines into a single blank line.
    result = re.sub(r"\n{3,}", "\n\n", "\n".join(out))
    return result.strip() + "\n"


# --------------------------------------------------------------------------
# Metadata recognition
# --------------------------------------------------------------------------

RE_ORDER_NUMBER = re.compile(
    r"(?:наказ|розпорядженн\w*|положенн\w*)\s*(?:№|N)\s*([\w./-]+)",
    re.IGNORECASE,
)
RE_ORDER_NUMBER_FALLBACK = re.compile(r"№\s*([\w./-]+)")

MONTHS_UK = {
    "січня": "01", "лютого": "02", "березня": "03", "квітня": "04",
    "травня": "05", "червня": "06", "липня": "07", "серпня": "08",
    "вересня": "09", "жовтня": "10", "листопада": "11", "грудня": "12",
}
RE_ORDER_DATE_TEXTUAL = re.compile(
    r"(\d{1,2})\s+(" + "|".join(MONTHS_UK) + r")\s+(\d{4})",
    re.IGNORECASE,
)
RE_ORDER_DATE_NUMERIC = re.compile(r"\b(\d{2})[./](\d{2})[./](\d{4})\b")


def guess_order_number(text: str) -> str | None:
    m = RE_ORDER_NUMBER.search(text)
    if m:
        return m.group(1).strip().rstrip(".,")
    m = RE_ORDER_NUMBER_FALLBACK.search(text)
    if m:
        return m.group(1).strip().rstrip(".,")
    return None


def guess_order_date(text: str) -> str | None:
    m = RE_ORDER_DATE_TEXTUAL.search(text)
    if m:
        day, month_name, year = m.groups()
        month = MONTHS_UK[month_name.lower()]
        return f"{year}-{month}-{int(day):02d}"
    m = RE_ORDER_DATE_NUMERIC.search(text)
    if m:
        day, month, year = m.groups()
        return f"{year}-{month}-{day}"
    return None


def guess_title(text: str) -> str:
    for raw_line in text.split("\n"):
        line = raw_line.strip()
        if len(line) >= 8 and not line.isdigit():
            return line[:200]
    return ""


# --------------------------------------------------------------------------
# Markdown assembly
# --------------------------------------------------------------------------

def build_markdown(pdf_path: Path, result: ExtractionResult) -> str:
    title = guess_title(result.text)
    order_number = guess_order_number(result.text) or ""
    order_date = guess_order_date(result.text) or ""

    frontmatter = {
        "title": title,
        "status": "невідомо",
        "order_number": order_number,
        "order_date": order_date,
        "source_pdf": pdf_path.name,
    }
    fm_yaml = yaml.dump(frontmatter, allow_unicode=True, sort_keys=False, default_flow_style=False)

    body = split_into_blocks(result.text)
    return f"---\n{fm_yaml}---\n\n{body}"


# --------------------------------------------------------------------------
# Main
# --------------------------------------------------------------------------

def process_pdf(pdf_path: Path, stats: RunStats) -> None:
    stats.total += 1
    try:
        result = extract_pdf(pdf_path)
    except Exception as exc:
        log.error("FAILED %s: %s", pdf_path.name, exc)
        stats.failed.append((pdf_path.name, str(exc)))
        return

    if not result.text.strip():
        msg = "no text extracted (pdfplumber and OCR both returned empty)"
        log.error("FAILED %s: %s", pdf_path.name, msg)
        stats.failed.append((pdf_path.name, msg))
        return

    md = build_markdown(pdf_path, result)
    out_path = OUTPUT_DIR / f"{pdf_path.stem}.md"
    out_path.write_text(md, encoding="utf-8")

    stats.succeeded += 1
    if result.used_ocr:
        stats.used_ocr += 1
    log.info(
        "OK %s -> %s (%d pages, %s)",
        pdf_path.name, out_path.name, result.pages, "OCR" if result.used_ocr else "text layer",
    )


def main() -> int:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    pdf_files = sorted(SOURCE_DIR.glob("*.pdf"))
    if not pdf_files:
        log.warning("No PDF files found in %s", SOURCE_DIR)
        return 0

    stats = RunStats()
    for pdf_path in pdf_files:
        process_pdf(pdf_path, stats)

    print("\n=== Підсумок ===")
    print(f"Усього PDF:        {stats.total}")
    print(f"Оброблено успішно: {stats.succeeded}")
    print(f"Знадобився OCR:    {stats.used_ocr}")
    print(f"Помилки:           {len(stats.failed)}")
    for name, err in stats.failed:
        print(f"  - {name}: {err}")

    return 1 if stats.failed else 0


if __name__ == "__main__":
    sys.exit(main())
