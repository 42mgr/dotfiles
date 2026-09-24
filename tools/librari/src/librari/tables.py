"""Section-scoped table helpers shared by the rules and the edit API."""
from __future__ import annotations

import re

from .model import Page
from .parse import find_tables

DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
CODE_SPAN_RE = re.compile(r"`([^`]+)`")


def section_tables(page: Page, anchor: str):
    sec = page.section(anchor)
    if sec is None:
        return []
    return find_tables(page.lines, sec.body_start, sec.end)


def header_matches(header: list[str], expected: list[str]) -> bool:
    norm = [h.strip().lower() for h in header]
    return len(norm) >= len(expected) and all(n.startswith(e.lower()) for n, e in zip(norm, expected))


def changelog_table(page: Page):
    """(header_line, rows) of the Changelog table: `Date | Type | <anything>`."""
    for hl, header, rows in section_tables(page, "changelog"):
        if header_matches(header, ["Date", "Type"]) and len(header) >= 3:
            return hl, rows
    return None


def _pathish_cell(cell: str) -> bool:
    return bool(code_spans(cell)) or "](" in cell


def key_files_table(page: Page):
    """The first table of the Key files section whose first column is keyed by
    paths — at least half of its cells hold a backticked span or a link. The
    header text is free (`File | Role`, `Mount | Purpose`, `Store | Holds`)."""
    for hl, header, rows in section_tables(page, "key-files"):
        if len(header) >= 2 and rows and sum(_pathish_cell(c[0]) for _, c in rows if c) * 2 >= len(rows):
            return hl, rows
    return None


def code_spans(cell: str) -> list[str]:
    return [m.group(1).strip() for m in CODE_SPAN_RE.finditer(cell)]
