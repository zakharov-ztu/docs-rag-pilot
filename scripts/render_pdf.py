"""Render wiki-pages/*.md into a print-ready PDF on the university's
ISO-9001 document form (header stamp on every page, cover page with the
ЗАТВЕРДЖЕНО block, signature block, and the standard tracking sheets).

The .md stays content-only: the form itself lives in one Typst template
(templates/iso_document.typ), and the per-document form details — document
code, issue number, signatories — come from an optional `print:` block in
the .md frontmatter. This script parses the .md body into a flat list of
blocks (section / paragraph / bullet / table) and hands them to the
template as JSON, so document text is never interpreted as Typst markup.

Usage:
    python3 scripts/render_pdf.py wiki-pages/<doc>.md
    python3 scripts/render_pdf.py wiki-pages/<doc>.md --copy 2 --uncontrolled
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parent.parent
TEMPLATE = REPO_ROOT / "templates" / "iso_document.typ"
BUILD_DIR = REPO_ROOT / "build"

RE_HEADING = re.compile(r"^(#{2,6})\s+(.*\S)\s*$")
# Bullet glyphs seen in the corpus, incl. U+F0B7 (Symbol-font bullet that
# Word embeds as a private-use codepoint) and the various dashes.
RE_BULLET = re.compile(r"^(?:[•●▪]\s*|[*\-−–—‒˗]\s+)")
RE_LINK = re.compile(r"\[([^\]]*)\]\([^)]*\)")
# A heading line that is a whole sentence ("### 1. Згідно з Законом ...")
# is a numbered пункт, not a section title, and is printed as a paragraph.
SECTION_TITLE_MAX_CHARS = 160


def _inline(text: str) -> str:
    text = RE_LINK.sub(r"\1", text)
    text = text.replace("**", "").replace("\\.", ".")
    return text.strip()


def _split_frontmatter(md: str) -> tuple[dict, str]:
    if not md.startswith("---\n"):
        return {}, md
    end = md.index("\n---\n", 4)
    return yaml.safe_load(md[4:end]) or {}, md[end + 5:]


def parse_blocks(body: str) -> list[dict]:
    blocks: list[dict] = []
    for raw in body.split("\n"):
        line = raw.strip()
        if not line:
            continue

        if line.startswith("|"):
            if re.fullmatch(r"\|[\s:|-]+\|?", line):
                continue  # header separator row
            cells = [_inline(c) for c in line.strip("|").split("|")]
            if blocks and blocks[-1]["type"] == "table":
                blocks[-1]["rows"].append(cells)
            else:
                blocks.append({"type": "table", "rows": [cells]})
            continue

        m = RE_HEADING.match(line)
        if m:
            level, text = len(m.group(1)), _inline(m.group(2))
            is_title = (
                level <= 3
                and len(text) <= SECTION_TITLE_MAX_CHARS
                and text[-1] not in ".;"
            )
            blocks.append({"type": "section" if is_title else "para", "text": text})
            continue

        m = RE_BULLET.match(line)
        if m and len(line) > m.end():
            blocks.append({"type": "bullet", "text": _inline(line[m.end():])})
            continue

        blocks.append({"type": "para", "text": _inline(line)})
    return blocks


def render(md_path: Path, copy_no: int, controlled: bool) -> Path:
    meta, body = _split_frontmatter(md_path.read_text(encoding="utf-8"))
    BUILD_DIR.mkdir(exist_ok=True)
    data_path = BUILD_DIR / f"{md_path.stem}.json"
    pdf_path = BUILD_DIR / f"{md_path.stem}.pdf"
    data_path.write_text(
        json.dumps({"meta": meta, "blocks": parse_blocks(body)}, ensure_ascii=False, default=str),
        encoding="utf-8",
    )
    subprocess.run(
        [
            "typst", "compile",
            "--root", str(REPO_ROOT),
            "--input", f"data=/{data_path.relative_to(REPO_ROOT)}",
            "--input", f"copy={copy_no}",
            "--input", f"controlled={'true' if controlled else 'false'}",
            str(TEMPLATE), str(pdf_path),
        ],
        check=True,
    )
    return pdf_path


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("md", type=Path, nargs="+", help="wiki-pages/*.md file(s)")
    ap.add_argument("--copy", type=int, default=1, help="Екземпляр № (default 1)")
    ap.add_argument("--uncontrolled", action="store_true", help="mark as Врахований примірник")
    args = ap.parse_args()
    for md in args.md:
        pdf = render(md.resolve(), args.copy, not args.uncontrolled)
        print(f"Wrote {pdf.relative_to(REPO_ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
