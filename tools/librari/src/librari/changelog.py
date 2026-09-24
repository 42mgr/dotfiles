"""`librari changelog add <page> <type> "<summary>"` — appends one row, dated today."""
from __future__ import annotations

import datetime as dt
import sys

from .config import KbConfig
from .sections import SectionError, _load, _section
from .tables import DATE_RE, changelog_table


def add_row(cfg: KbConfig, page_arg: str, type_: str, summary: str, date: str | None = None) -> int:
    types = cfg.settings["changelogTypes"]
    if type_ not in types:
        print(f"type `{type_}` not in {types}", file=sys.stderr)
        return 2
    date = date or dt.date.today().isoformat()
    if not DATE_RE.match(date):
        print(f"date `{date}` is not YYYY-MM-DD", file=sys.stderr)
        return 2
    summary = " ".join(summary.split()).replace("|", "\\|")
    if not summary:
        print("summary is empty", file=sys.stderr)
        return 2
    try:
        page = _load(cfg, page_arg)
        sec = _section(page, "changelog")
    except SectionError as e:
        print(f"librari changelog: {e}", file=sys.stderr)
        return 2
    t = changelog_table(page)
    if t is None:
        print(f"{page.rel}: Changelog section has no `| Date | Type | Summary |` table (C007)", file=sys.stderr)
        return 2
    header_line, rows = t
    last = rows[-1][0] if rows else header_line + 1
    row = f"| {date} | {type_} | {summary} |"
    lines = page.lines[: last + 1] + [row] + page.lines[last + 1:]
    page.path.write_text("\n".join(lines).rstrip("\n") + "\n", encoding="utf-8")
    print(f"{page.rel}: appended changelog row ({date}, {type_})")
    return 0
