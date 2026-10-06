"""Render wiki-pages/*.md into a print-ready PDF on the university's
ISO-9001 document form (header stamp on every page, cover page with the
ЗАТВЕРДЖЕНО block, signature block, and the standard tracking sheets).

The .md stays content-only: the form — and the parsing of the .md itself —
lives in one Typst template (templates/iso_document.typ), shared with the
in-browser constructor (constructor/index.html). Per-document form details
(document code, issue number, signatories) come from an optional `print:`
block in the .md frontmatter.

Usage:
    python3 scripts/render_pdf.py wiki-pages/<doc>.md
    python3 scripts/render_pdf.py wiki-pages/<doc>.md --copy 2 --uncontrolled
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
TEMPLATE = REPO_ROOT / "templates" / "iso_document.typ"
BUILD_DIR = REPO_ROOT / "build"


def render(md_path: Path, copy_no: int, controlled: bool) -> Path:
    BUILD_DIR.mkdir(exist_ok=True)
    pdf_path = BUILD_DIR / f"{md_path.stem}.pdf"
    subprocess.run(
        [
            "typst", "compile",
            "--root", str(REPO_ROOT),
            "--input", f"doc=/{md_path.relative_to(REPO_ROOT)}",
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
