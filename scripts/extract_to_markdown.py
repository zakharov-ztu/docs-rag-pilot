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

# This university's documents share one ISO-9001 template: every single
# page repeats an institutional header/footer stamp, and the cover page
# carries an approval block (ЗАТВЕРДЖЕНО...) whose useful parts (title,
# наказ number/date) are already pulled into the YAML frontmatter by
# guess_title/guess_order_number/guess_order_date. Both are pure noise in
# the document body and get stripped by strip_boilerplate() below.
RUNNING_HEADER_PATTERNS = [
    re.compile(r"МІНІСТЕРСТВО ОСВІТИ І НАУКИ УКРАЇНИ"),
    re.compile(r"ДЕРЖАВНИЙ УНІВЕРСИТЕТ.*ЖИТОМИРСЬКА ПОЛІТЕХНІКА"),
    re.compile(r"Система управління якістю.*ДСТУ ISO"),
    re.compile(r"Екземпляр\s*№?\s*\d+.*Арк"),
    re.compile(r"^Випуск\s+\d+\s+Зміни\s+\d+"),
    # Document control code, e.g. "П-10.00-02.01-" / "07-2025", which some
    # pages wrap onto their own line instead of the header line above.
    re.compile(r"^[А-ЯІЇЄҐ]-[\d]+\.[\d]+-[\d]+\.[\d]+-?$"),
    re.compile(r"^\d{2}-\d{4}$"),
]
# The institution's logo text sometimes extracts as isolated lines.
STANDALONE_NOISE_LINES = {"Житомирська", "політехніка"}

# Table-of-contents dot leaders ("Загальні положення……………… 3") and bare
# page-footer numbers.
RE_DOT_LEADER = re.compile(r"[.…]{3,}\s*\d*\s*$")
RE_LONE_PAGE_NUMBER = re.compile(r"^\d{1,3}$")

RE_APPROVAL_BLOCK_START = re.compile(r"^ЗАТВЕРДЖЕНО$")
RE_BARE_YEAR = re.compile(r"^(19|20)\d{2}$")
# Safety cap: if no bare-year terminator turns up quickly, stop dropping
# lines rather than risk eating real content (e.g. an annex with its own
# ЗАТВЕРДЖЕНО stamp but a differently formatted date).
MAX_APPROVAL_BLOCK_LINES = 25

RE_TOC_LABEL = re.compile(r"^ЗМІСТ$")
# A genuine top-level section heading ("1. ЗАГАЛЬНІ ПОЛОЖЕННЯ" /
# "I. ЗАГАЛЬНІ ПОЛОЖЕННЯ") is ALL CAPS, unlike a ЗМІСТ entry for the same
# section ("1. Загальні положення………… 3"), which is mixed case. That's
# what marks the real content starting again after the table of contents.
RE_TOP_LEVEL_HEADING_CANDIDATE = re.compile(r"^(?:[IVXLCDM]{1,6}|\d{1,3})\.?\s+(\S.*)$")
MAX_TOC_BLOCK_LINES = 150


def _looks_like_toc_terminator(stripped: str) -> bool:
    m = RE_TOP_LEVEL_HEADING_CANDIDATE.match(stripped)
    return bool(m and _is_mostly_uppercase(m.group(1)))


def strip_boilerplate(text: str) -> str:
    """Remove the repeated page header/footer stamp, the cover-page
    approval block, and the dotted table of contents from raw extracted
    text, leaving just the document body."""
    out: list[str] = []
    skipping_approval_block = False
    approval_block_used = False
    approval_skipped_count = 0
    skipping_toc = False
    toc_used = False
    toc_skipped_count = 0

    for line in text.split("\n"):
        stripped = line.strip()

        if skipping_toc:
            toc_skipped_count += 1
            if _looks_like_toc_terminator(stripped) or toc_skipped_count > MAX_TOC_BLOCK_LINES:
                skipping_toc = False
            else:
                continue

        if skipping_approval_block:
            approval_skipped_count += 1
            if RE_BARE_YEAR.match(stripped) or approval_skipped_count > MAX_APPROVAL_BLOCK_LINES:
                skipping_approval_block = False
            continue

        if not approval_block_used and RE_APPROVAL_BLOCK_START.match(stripped):
            skipping_approval_block = True
            approval_block_used = True
            approval_skipped_count = 0
            continue

        if not toc_used and RE_TOC_LABEL.match(stripped):
            skipping_toc = True
            toc_used = True
            toc_skipped_count = 0
            continue

        if (
            stripped in STANDALONE_NOISE_LINES
            or RE_DOT_LEADER.search(stripped)
            or RE_LONE_PAGE_NUMBER.match(stripped)
            or any(p.search(stripped) for p in RUNNING_HEADER_PATTERNS)
        ):
            continue

        out.append(line)

    return "\n".join(out)


# Roman-numeral top-level sections, e.g. "I. ЗАГАЛЬНІ ПОЛОЖЕННЯ"
RE_SECTION = re.compile(r"^([IVXLCDM]{1,6})\.\s+(\S.*)$")
# Numbered points, e.g. "1. Текст" or "1.2. Текст"
RE_POINT = re.compile(r"^(\d{1,3}(?:\.\d{1,3}){0,3})\.?\s+(\S.*)$")
# Sub-points like "1.2.3." handled by RE_POINT via dot count.

# "N. <month name>" is a date ("15 вересня 2025 р."), not a document point.
_MONTH_NAMES_LOWER = tuple(m.lower() for m in [
    "січня", "лютого", "березня", "квітня", "травня", "червня",
    "липня", "серпня", "вересня", "жовтня", "листопада", "грудня",
])


def _looks_like_date(point_body: str) -> bool:
    first_word = point_body.split(maxsplit=1)[0].lower().rstrip(",.") if point_body else ""
    return first_word in _MONTH_NAMES_LOWER


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
        if m_point and not _looks_like_date(m_point.group(2)):
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

RE_ANY_NUMBER_SIGN = re.compile(r"№\s*([\w./-]+)")
# "№" preceded by these labels refers to a copy/page/protocol count, not the
# наказ's own registration number (e.g. document headers all carry
# "Екземпляр № 1" on every page).
NUMBER_SIGN_STOPWORDS = re.compile(
    r"(екземпляр|арк\.?|випуск|протокол)\s*$", re.IGNORECASE
)

MONTHS_UK = {
    "січня": "01", "лютого": "02", "березня": "03", "квітня": "04",
    "травня": "05", "червня": "06", "липня": "07", "серпня": "08",
    "вересня": "09", "жовтня": "10", "листопада": "11", "грудня": "12",
}
RE_ORDER_DATE_TEXTUAL = re.compile(
    r"(\d{1,2})\s+(" + "|".join(MONTHS_UK) + r")\s+(\d{4})",
    re.IGNORECASE,
)
RE_ORDER_DATE_TEXTUAL_AFTER_VID = re.compile(
    r"від\s+(\d{1,2})\s+(" + "|".join(MONTHS_UK) + r")\s+(\d{4})",
    re.IGNORECASE,
)
RE_ORDER_DATE_NUMERIC = re.compile(r"\b(\d{2})[./](\d{2})[./](\d{4})\b")


def guess_order_number(text: str) -> str | None:
    for m in RE_ANY_NUMBER_SIGN.finditer(text):
        context_before = text[max(0, m.start() - 25): m.start()]
        if NUMBER_SIGN_STOPWORDS.search(context_before):
            continue
        return m.group(1).strip().rstrip(".,")
    return None


def guess_order_date(text: str) -> str | None:
    # Prefer a date right after "від" (наказ ... від DD <місяць> YYYY р.),
    # since a document can also contain unrelated dates (e.g. a Вчена рада
    # protocol date) earlier or later in the text.
    m = RE_ORDER_DATE_TEXTUAL_AFTER_VID.search(text)
    if m:
        day, month_name, year = m.groups()
        return f"{year}-{MONTHS_UK[month_name.lower()]}-{int(day):02d}"
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


# Document-type words that typically stand alone as a heading right above
# the actual title text, e.g. a line reading just "ПОЛОЖЕННЯ".
TITLE_ANCHORS = {"ПОЛОЖЕННЯ", "НАКАЗ", "ІНСТРУКЦІЯ", "ПРАВИЛА", "ПОРЯДОК", "РЕГЛАМЕНТ"}
# Lines that signal we've run past the title into unrelated boilerplate.
TITLE_STOP_LINE = re.compile(
    r"(контрольний примірник|врахований примірник|погоджено|вченою радою|ректор|_{3,})",
    re.IGNORECASE,
)


def _is_mostly_uppercase(line: str) -> bool:
    letters = [ch for ch in line if ch.isalpha()]
    if not letters:
        return False
    return sum(ch.isupper() for ch in letters) / len(letters) > 0.8


def guess_title(text: str) -> str:
    lines = [ln.strip() for ln in text.split("\n")]

    for i, line in enumerate(lines):
        if line in TITLE_ANCHORS:
            parts = [line]
            for cont in lines[i + 1: i + 8]:
                if not cont or TITLE_STOP_LINE.search(cont) or _is_mostly_uppercase(cont):
                    break
                parts.append(cont)
            return " ".join(parts)[:300]

    # Fallback: first substantial line that isn't a repeated ALL-CAPS header.
    for line in lines:
        if len(line) >= 8 and not line.isdigit() and not _is_mostly_uppercase(line):
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

    body = split_into_blocks(strip_boilerplate(result.text))
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
