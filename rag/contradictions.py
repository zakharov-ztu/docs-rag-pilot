"""Read the contradiction shortlist written by scripts/find_contradictions.py.

The shortlist is a Markdown report meant for people; this parses it back into
records for the demo app. If find_contradictions.py starts writing JSON, this
module is the only place that has to change.
"""

from __future__ import annotations

import re
from pathlib import Path

from rag.config import CONTRADICTIONS_PATH

_HEADING_RE = re.compile(r"^## (\S+) \(схожість ([\d.]+)\)$")
_FRAGMENT_RE = re.compile(r"^\*\*\[(A|B)\]\*\* (.+?) — (.+) \((wiki-pages/.+\.md)\)$")


def load_shortlist(path: Path = CONTRADICTIONS_PATH) -> tuple[str, list[dict]]:
    """Returns (summary, pairs). summary is the report's header text; each
    pair is {"verdict", "similarity", "explanation", "a", "b"}, where a and b
    are {"title", "section", "wiki_page", "text"}."""
    if not path.exists():
        return "", []

    summary_lines: list[str] = []
    pairs: list[dict] = []
    current: dict | None = None
    fragment: dict | None = None

    for line in path.read_text(encoding="utf-8").splitlines():
        if m := _HEADING_RE.match(line):
            current = {"verdict": m.group(1), "similarity": float(m.group(2)), "explanation": ""}
            pairs.append(current)
            fragment = None
        elif current is None:
            if line and not line.startswith("# "):
                summary_lines.append(line)
        elif line.startswith("Пояснення моделі:"):
            current["explanation"] = line.removeprefix("Пояснення моделі:").strip()
        elif m := _FRAGMENT_RE.match(line):
            fragment = {"title": m.group(2), "section": m.group(3), "wiki_page": m.group(4), "text": ""}
            current[m.group(1).lower()] = fragment
        elif line.startswith("> ") and fragment is not None:
            fragment["text"] = line[2:]

    return "\n".join(summary_lines), [p for p in pairs if "a" in p and "b" in p]
