"""Fix leftover structural defects directly in wiki-pages/*.md.

The .md files are the source of truth now (hand-corrected on GitHub; PDF
extraction is no longer re-run), so this edits them in place and touches
only two narrow patterns, leaving everything else byte-for-byte as is:

1. A table of contents ("ЗМІСТ") whose leftover entries became real
   "### N." headings, duplicating the body's own sections and stealing the
   text that follows them.
2. A heading (or paragraph) wrapped over several physical PDF lines, where
   each wrapped line became its own paragraph:
       ### 7. ВИЗНАННЯ РЕЗУЛЬТАТІВ НАВЧАННЯ ЗА
       ПРОГРАМАМИ АКАДЕМІЧНОЇ МОБІЛЬНОСТІ
   or a mid-sentence break that resumes in lowercase — sometimes on a line
   that happens to start with a number and so was mistaken for a пункт
   ("#### 6.2. ... впродовж" / "### 14. робочих днів:").

Usage:
    python3 scripts/clean_markdown.py            # dry run: print a diff
    python3 scripts/clean_markdown.py --write    # apply
"""

from __future__ import annotations

import argparse
import difflib
import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
WIKI_DIR = REPO_ROOT / "wiki-pages"

RE_HEADING = re.compile(r"^(#{2,6}) (.*)$")
RE_SECTION = re.compile(r"^([IVXLCDM]{1,6})\.\s+(\S.*)$")
RE_POINT = re.compile(r"^(\d{1,3}(?:\.\d{1,3}){0,3})\.?\s+(\S.*)$")
# Lines that open a new block of their own: numbered/lettered/bulleted list
# items, and Markdown syntax (lists, tables, quotes, images, HTML).
RE_BLOCK_MARKER = re.compile(
    r"^(?:[IVXLCDM]{1,6}\.\s|\d{1,3}(?:\.\d{1,3}){0,3}\.?\s|\d{1,2}\)\s|[а-яіїєґ]\)\s"
    r"|[-−–—•·*+‒]\s|[|>!<])"
)
RE_TOC_HEADER = re.compile(r"^З\s*М\s*І\s*С\s*Т$", re.IGNORECASE)
_MONTHS = (
    "січня", "лютого", "березня", "квітня", "травня", "червня",
    "липня", "серпня", "вересня", "жовтня", "листопада", "грудня",
)
# The body starts at the first line no TOC entry could be: a sub-point
# ("1.1. ...") or a line longer than any TOC entry wraps to (the longest
# leftover TOC line in the corpus is ~80 chars).
TOC_BODY_LINE_MIN_CHARS = 150
# No body start found this far in -> drop only the ЗМІСТ line itself.
TOC_MAX_LINES = 80
# A real TOC opens the body; a "Зміст" further in is the word used in the
# text itself ("Зміст – це перелік заголовків ..." in the publishing rules).
TOC_MAX_START_LINE = 15
TERMINAL_PUNCT = ".;:!?"
HEADING_CONTINUATION_MAX_CHARS = 120


def _plain(line: str) -> str:
    m = RE_HEADING.match(line)
    return m.group(2) if m else line


def _point_number(text: str) -> str | None:
    m = RE_SECTION.match(text)
    if m:
        return m.group(1)
    m = RE_POINT.match(text)
    if m and m.group(2).split(maxsplit=1)[0].lower().rstrip(",.") not in _MONTHS:
        return m.group(1)
    return None


def _is_mostly_uppercase(text: str) -> bool:
    letters = [ch for ch in text if ch.isalpha()]
    return bool(letters) and sum(ch.isupper() for ch in letters) / len(letters) > 0.8


def drop_table_of_contents(lines: list[str]) -> list[str]:
    """Remove the ЗМІСТ block: from the ЗМІСТ line up to where the body
    begins. The body begins at the first sub-point or long paragraph — or,
    if that is directly preceded by the body's own first section heading
    ("1. ЗАГАЛЬНІ ПОЛОЖЕННЯ", possibly wrapped), at that heading. A
    preceding heading numbered anything else ("4. Організація ...") is the
    TOC's last entry, and the body opens with an unnumbered preamble."""
    non_blank = [i for i, ln in enumerate(lines) if ln.strip()][:TOC_MAX_START_LINE]
    start = next((i for i in non_blank if RE_TOC_HEADER.match(_plain(lines[i]).strip())), None)
    if start is None:
        return lines

    body = None
    for i in range(start + 1, min(len(lines), start + 1 + TOC_MAX_LINES)):
        text = _plain(lines[i]).strip()
        number = _point_number(text)
        if (number and "." in number) or len(text) > TOC_BODY_LINE_MIN_CHARS:
            body = i
            break
    if body is None:
        return lines[:start] + lines[start + 1:]

    first_part = (_point_number(_plain(lines[body]).strip()) or "").split(".")[0]
    for j in range(body - 1, start, -1):
        text = _plain(lines[j]).strip()
        if not text:
            continue
        number = _point_number(text)
        if number is None:
            if RE_BLOCK_MARKER.match(text):
                body = j  # TOC entries are never list items
                continue
            if len(text) <= TOC_BODY_LINE_MIN_CHARS:
                continue  # wrapped continuation of a heading
            break
        if number in ("1", "I") or number == first_part:
            body = j
        break

    return lines[:start] + lines[body:]


def _is_heading_continuation(heading_text: str, line: str) -> bool:
    """An ALL-CAPS heading continues with further short ALL-CAPS lines
    until it reaches terminal punctuation. (The mixed-case wrap, which
    resumes in lowercase, is covered by _continues_sentence.)"""
    if heading_text[-1] in TERMINAL_PUNCT:
        return False
    if len(line) > HEADING_CONTINUATION_MAX_CHARS or RE_BLOCK_MARKER.match(line):
        return False
    # The running page header is also ALL-CAPS and sometimes leaked right
    # after a heading at a page top.
    if line.startswith(("ДЕРЖАВНИЙ УНІВЕРСИТЕТ", "МІНІСТЕРСТВО ОСВІТИ")):
        return False
    return _is_mostly_uppercase(heading_text) and _is_mostly_uppercase(line)


def _continues_sentence(prev_text: str, text: str) -> bool:
    """A sentence cut by a wrap or page break resumes on a line starting
    in lowercase — no new paragraph, point or heading here does."""
    return prev_text[-1] not in TERMINAL_PUNCT and text[0].islower()


def join_wrapped_lines(lines: list[str]) -> list[str]:
    out: list[str] = []
    last_idx: int | None = None  # index in `out` of the last non-blank line
    last_is_heading = False

    for line in lines:
        stripped = line.strip()
        if not stripped:
            out.append(line)
            continue

        if last_idx is not None:
            prev = _plain(out[last_idx]).strip()
            text = _plain(stripped)
            number = _point_number(text)
            # "14. робочих днів:" — body after the number, for the check.
            resumed = text[len(number) + 1:].lstrip(". ") if number else text
            glue = False
            if prev and not prev.startswith("|") and resumed:
                if number is not None or not RE_BLOCK_MARKER.match(text):
                    glue = _continues_sentence(prev, resumed)
            if not glue and last_is_heading and number is None and not RE_HEADING.match(stripped):
                glue = _is_heading_continuation(prev, text)
            if glue:
                out[last_idx] = out[last_idx].rstrip() + " " + text
                del out[last_idx + 1:]  # the blank lines between the halves
                continue

        out.append(line)
        last_idx = len(out) - 1
        last_is_heading = bool(RE_HEADING.match(stripped))

    return out


def clean(md: str) -> str:
    if md.startswith("---\n"):
        end = md.index("\n---\n", 4) + len("\n---\n")
        frontmatter, body = md[:end], md[end:]
    else:
        frontmatter, body = "", md
    lines = join_wrapped_lines(drop_table_of_contents(body.split("\n")))
    return frontmatter + "\n".join(lines)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--write", action="store_true", help="apply changes (default: dry run)")
    args = ap.parse_args()

    changed = 0
    for path in sorted(WIKI_DIR.glob("*.md")):
        old = path.read_text(encoding="utf-8")
        new = clean(old)
        if new == old:
            continue
        changed += 1
        if args.write:
            path.write_text(new, encoding="utf-8")
        else:
            diff = difflib.unified_diff(
                old.splitlines(), new.splitlines(), f"a/{path.name}", f"b/{path.name}", lineterm="", n=0
            )
            print("\n".join(diff))
    print(f"\n{'Changed' if args.write else 'Would change'}: {changed} file(s)")


if __name__ == "__main__":
    main()
