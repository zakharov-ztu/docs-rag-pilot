#!/usr/bin/env python3
"""Assign category/subgroup to wiki-pages/*.md frontmatter, mirroring the
taxonomy already used by the real docs.ztu.edu.ua site (as shown by the
user: 8 top-level sections, some split into tabs for structural units and
collegial bodies).

Rule-based on title/filename keywords, checked in order — first match
wins. Like `status`, an existing category is preserved on re-run unless
`--force` is passed, so manual corrections survive future extraction runs.

Usage:
    .venv/bin/python scripts/categorize.py [--force] [--dry-run]
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
WIKI_DIR = ROOT / "wiki-pages"

# (category, subgroup-or-None, [regex patterns tried against title+filename, case-insensitive])
# Order matters: more specific/narrower rules must come before broader ones,
# since the first match wins. Reflects the real 16-category taxonomy shown
# by the university's own docs.ztu.edu.ua site.
RULES: list[tuple[str, str | None, list[str]]] = [
    # --- Доброчесність та антикорупція (checked early: narrower than the
    # generic "академічна" terms used elsewhere) ---
    ("Доброчесність та антикорупція", None, [
        r"академічн\w+ доброчесн", r"антикорупційн\w+ програм", r"дорожн\w+ карт\w+.*корупці",
        r"корпоративної культури", r"комісі\w+ з академічної доброчесності",
        r"уповноважен\w+ (особ|підрозділ).*корупці", r"запобіганн\w+.*корупці",
    ]),

    # --- Міжнародна діяльність ---
    ("Міжнародна діяльність", None, [
        r"gender equality", r"гендерн\w+ рівност", r"міжнародн\w+ асоціаці\w+ науковц",
        r"освітньо-культурний центр", r"language hub", r"мовної підготовки",
        r"центр міжнародної освіти", r"чеськ\w+ центр освіти", r"відділ міжнародних зв.?язків",
        r"академічн\w+ мобільн", r"erazmus", r"еразмус", r"кредитн\w+ мобільн",
    ]),

    # --- Гуртожитки. Соціальні питання ---
    ("Гуртожитки. Соціальні питання", None, [
        r"житлов\w+ комісі", r"користуванн\w+ гуртожит", r"внутрішнього розпорядку в студентських гуртожит",
    ]),

    # --- Охорона праці, безпека життєдіяльності, пожежна безпека ---
    ("Охорона праці, безпека життєдіяльності, пожежна безпека", None, [
        r"безпеки життєдіяльності.*канікул", r"охорони праці", r"цивільного захисту",
        r"пожежної безпеки", r"навчання, інструктаж і перевірку знань", r"розробку інструкцій з охорони праці",
        r"службу охорони праці", r"вступного інструктажу", r"підготовки працівників до дій у надзвичайних",
    ]),

    # --- Інформаційно-бібліотечна та видавнича діяльність ---
    ("Інформаційно-бібліотечна та видавнича діяльність", None, [
        r"структури, змісту та обсягів підручник", r"^положенн\w+ про бібліотек",
        r"платформи zenodo", r"наукові фахові видання", r"наукові та навчальні видання",
        r"формуванн\w+ фонду бібліотеки", r"редакційно-видавничий сектор",
    ]),

    # --- Позанавчальна діяльність. Студентське самоврядування ---
    ("Позанавчальна діяльність. Студентське самоврядування", None, [
        r"концепці\w+ молодіжної політики", r"первинн\w+ профспілков\w+ організаці\w+ студент",
        r"центр культури студентської молоді",
        r"куратор\w+ академічн\w+ груп", r"ментор\w+ академічн\w+ груп",
        r"організаці\w+ роботи спортивних секцій", r"підтягуванн\w+ на перекладині",
        r"старост\w+ академічн\w+ груп", r"студентське самоврядування", r"дебатний клуб",
    ]),

    # --- Фінансово-економічна діяльність ---
    ("Фінансово-економічна діяльність", None, [
        r"норм часу викладача", r"бухгалтерську службу", r"виплату соціальних стипендій",
        r"додаткових освітніх послуг", r"планово-фінансовий відділ", r"стипендії bgv",
        r"стипендіальні комісії", r"стипендію ректора", r"стипендію роботодавця",
        r"тендерний комітет", r"уповноважену особу\b", r"використанн\w+ коштів",
        r"нарахування та сплати пені", r"призначенн\w+ академічних стипендій",
    ]),

    # --- Управління персоналом ---
    ("Управління персоналом", None, [
        r"атестаці\w+ педагогічних працівник", r"первинн\w+ профспілков\w+ організаці\w+ виклада",
        r"визнанн\w+ здобутих в іноземних закладах.*наукових ступен", r"обробки та захисту персональних даних",
        r"конкурс\w+ на заміщенн\w+ вакантних посад",
    ]),

    # --- Структурні підрозділи (tabbed) ---
    ("Структурні підрозділи", "Вчена рада факультету", [r"вчен\w+ рад\w+ факультет"]),
    ("Структурні підрозділи", "Факультети", [r"^положенн\w* про факультет", r"_fakul_?tet", r"pro fakultet\b"]),
    ("Структурні підрозділи", "Кафедри", [r"\bкафедр"]),
    ("Структурні підрозділи", "Центри", [r"\bцентр[ауі]?\b", r"\bцентру\b", r"\bхаб\b"]),
    ("Структурні підрозділи", "Лабораторії", [r"лаборатор"]),
    ("Структурні підрозділи", "Відділи", [
        r"\bвідділ(?!ення)", r"\bсектор\b", r"деканат", r"юридичну клініку",
        r"оздоровпункт", r"спортивно-оздоровч",
    ]),

    # --- Колегіальні органи (tabbed) ---
    ("Колегіальні органи", "Вибори ректора 2026", [r"вибор\w* ректор", r"вибор\w* комісі", r"організаційн\w+ комітет.*вибор", r"спостерігач"]),
    ("Колегіальні органи", "Вчена рада університету", [
        r"вчен\w+ рад\w+ (державного )?університет", r"вчену раду_", r"почесн\w+ ректор",
        r"почесн\w+ звання", r"вчен\w+ звань", r"виборних представників до складу вчен",
    ]),
    ("Колегіальні органи", None, [
        r"наглядов\w+ рад", r"рад\w+ ректорів", r"науково-методичн\w+ рад",
        r"науково-технічн\w+ рад\w+ (державного )?університ", r"ректорат",
        r"конференці\w+ трудового колективу",
    ]),

    # --- Система управління якістю ---
    ("Система управління якістю", None, [
        r"актуаліза", r"настанова щодо якості", r"стейкхолдер", r"політика у сфері якості",
        r"реєстраці\w+ наказів", r"реєстраці\w+ договорів", r"реєстр процесів",
        r"swot", r"коригувальн", r"моніторинг досягненн\w+ ціл", r"внутрішній аудит",
        r"стратегічне управління", r"невідповідностя", r"управління ризиками",
        r"цілі у сфері якості", r"управління документованою інформацією",
        r"план заходів щодо забезпечення якості", r"аналіз системи управління якістю",
        r"виконання плану заходів",
    ]),

    # --- Формування контингенту студентів. Правила прийому ---
    ("Формування контингенту студентів. Правила прийому", None, [
        r"правил\w+ прийом", r"олімпіад", r"апеляційн\w+ комісі", r"приймальн\w+ комісі",
        r"творч\w+ конкурс", r"фахов\w+ атестаційн\w+ (та|і) предметн\w+ комісі",
        r"вступн\w+ кампані",
    ]),

    # --- Наукова, науково-технічна та інноваційна діяльність ---
    ("Наукова, науково-технічна та інноваційна діяльність", None, [
        r"аспірантур", r"докторантур", r"науково-дослідн\w+ сектор", r"атестаці\w+ д\.?ф", r"доктор\w+ філософі",
        r"доктор\w+ наук", r"кандидатськ\w+ іспит", r"молодих вчен", r"разов\w+ спецрад",
        r"спеціалізован\w+ вчен\w+ рад", r"інтелектуальн\w+ власност", r"академічн\w+ довідк\w+.*phd",
        r"наукове товариство", r"науков\w+ гурток", r"публікаці\w+ у.*(scopus|web of science)",
        r"організаці\w+ наукової",
    ]),

    # --- Освітня діяльність ---
    ("Освітня діяльність", None, [
        r"оцінюванн\w+ результат", r"організаці\w+ освітнього процесу", r"проведенн\w+ практик",
        r"індивідуальн\w+ графік", r"вибіркови?х? дисциплін", r"переведенн\w+ здобувач",
        r"порядок атестації для визнання", r"підвищенн\w+ кваліфікаці", r"екзаменаційн\w+ комісі",
        r"алгоритм\w+ розробки.*освітніх програм",
        r"зразки документів про вищу освіту", r"професійних кваліфікацій", r"розклад проведенн\w+ занять",
        r"комісі\w+ закладу вищої освіти.*визнання",
        r"атестаційн\w+ комісі\w+.*(енергетичн|енергоефективн)",
    ]),

    # --- Загальні організаційні питання ---
    ("Загальні організаційні питання", None, [
        r"діловодств", r"стипендіальн\w+ комісі", r"організаційн\w+ структур",
        r"індексаці\w+ освітніх програм", r"^положенн\w+ про архів", r"службов\w+ інформаці",
        r"підготовку та проведенн\w+ наукових.*конференц", r"звернень здобувачів",
        r"психічне здоров",
    ]),
]

# Anything unmatched by a rule above falls into this catch-all — the same
# bucket "Загальна нормативна база" uses on the real site for statute-level
# and cross-cutting documents (statute, license, policies, strategies).
DEFAULT_CATEGORY = "Загальна нормативна база"


# Titles that are boilerplate the extraction script picked up instead of
# the real title (page-header text, a bare document-type word, a "Наказ..."
# line) — these are long enough to dodge a pure length check, so detect
# them by shape instead.
_GARBAGE_TITLE_PATTERNS = [
    r"^міністерство освіти",
    r"^житомирськ\w* міністерство",
    r"^наказ\b",
    r"^система управління я",
    r"^ержавн",  # OCR-dropped leading "Д" of "Державного"
    r"^ерневжовного",
    r"^до державного університету",
    r"^№\s*\d",
    r"^[а-яіїєґ]-\s*\d",  # bare document control code like "Ф-05.01..."
    r"^\d",
]


def _is_garbage_title(title: str) -> bool:
    t = title.strip()
    if len(t) < 15:
        return True
    return any(re.search(p, t, re.IGNORECASE) for p in _GARBAGE_TITLE_PATTERNS)


def classify(title: str, body_snippet: str) -> tuple[str, str | None]:
    # Prefer the title alone: words like "кафедра"/"центр"/"відділ" are
    # generic institutional nouns that show up in the body of almost any
    # document (e.g. "затверджується на засіданні кафедри"), so scanning a
    # large body prefix produces mostly false positives for the
    # "Структурні підрозділи" rules. Only fall back to a body prefix (where
    # the real "ПОЛОЖЕННЯ про X" line lives, per extract_to_markdown's own
    # approval-slice logic — same 600-char window) when the title itself
    # looks like extraction picked up boilerplate instead of a real title.
    if not _is_garbage_title(title):
        haystack = title.lower()
        for category, subgroup, patterns in RULES:
            for pat in patterns:
                if re.search(pat, haystack, re.IGNORECASE):
                    return category, subgroup

    haystack = f"{title} {body_snippet[:600]}".lower()
    for category, subgroup, patterns in RULES:
        for pat in patterns:
            if re.search(pat, haystack, re.IGNORECASE):
                return category, subgroup

    return DEFAULT_CATEGORY, None


def process(path: Path, force: bool, dry_run: bool) -> tuple[str, str, str | None]:
    raw = path.read_text(encoding="utf-8")
    if not raw.startswith("---\n"):
        return (path.name, "SKIPPED (no frontmatter)", None)

    _, fm_text, body = raw.split("---\n", 2)
    fm = yaml.safe_load(fm_text) or {}

    existing = fm.get("category")
    if existing and not force:
        return (path.name, f"kept: {existing}", fm.get("subgroup"))

    category, subgroup = classify(fm.get("title", ""), body[:2500])
    fm["category"] = category
    if subgroup:
        fm["subgroup"] = subgroup
    elif "subgroup" in fm:
        del fm["subgroup"]

    if not dry_run:
        fm_yaml = yaml.dump(fm, allow_unicode=True, sort_keys=False, default_flow_style=False)
        path.write_text(f"---\n{fm_yaml}---\n{body}", encoding="utf-8")

    return (path.name, category, subgroup)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--force", action="store_true", help="Recompute even if category already set")
    parser.add_argument("--dry-run", action="store_true", help="Print assignments without writing files")
    args = parser.parse_args()

    counts: dict[str, int] = {}
    for path in sorted(WIKI_DIR.glob("*.md")):
        name, category, subgroup = process(path, args.force, args.dry_run)
        label = category if not subgroup else f"{category} / {subgroup}"
        counts[label] = counts.get(label, 0) + 1
        print(f"{name}: {label}")

    print("\n=== Розподіл за категоріями ===")
    for label, n in sorted(counts.items(), key=lambda kv: -kv[1]):
        print(f"{n:4d}  {label}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
