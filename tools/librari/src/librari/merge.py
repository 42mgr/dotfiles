"""`librari merge-driver %O %A %B %P` — git merge driver for kb pages.

Why: `changelog add` appends rows oldest-first at the bottom of the Changelog
table, so two branches that each add a row to the same page always collide on
the same line and git refuses the merge. The right answer is always "keep both
rows", which this driver does. Every other conflict (prose, code, a table
outside the Changelog section) is left exactly as `git merge-file` produced
it, markers included, and the driver exits 1 so git reports the conflict.

Wiring (per clone, shared by all worktrees of that clone):
    git config merge.librari.name   "librari kb merge (unions Changelog rows)"
    git config merge.librari.driver "uv run --project tools/librari librari merge-driver %O %A %B %P"
plus `kb/**/*.md merge=librari` in `.gitattributes` (versioned).

Exit codes follow git's contract for merge drivers: 0 = clean, 1 = conflicts
remain (the result with markers is written to %A either way), 2 = could not
run (git missing, unreadable inputs); git then falls back to a failed merge.
"""
from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

from .tables import DATE_RE

MARKER = 7
OURS_RE = re.compile(r"^<{%d}( |$)" % MARKER)
SEP_RE = re.compile(r"^={%d}$" % MARKER)
THEIRS_RE = re.compile(r"^>{%d}( |$)" % MARKER)
ROW_RE = re.compile(r"^\|\s*(\d{4}-\d{2}-\d{2})\s*\|\s*[A-Za-z][\w-]*\s*\|.*\|\s*$")
H2_RE = re.compile(r"^##\s")
CHANGELOG_H2_RE = re.compile(r"^##\s+(Changelog\b|.*<!--\s*agent:changelog\s*-->)", re.I)


def _is_row(line: str) -> bool:
    m = ROW_RE.match(line)
    return bool(m and DATE_RE.match(m.group(1)))


def _in_changelog(lines: list[str], upto: int) -> bool:
    """True when the nearest `## ` heading above line `upto` is the Changelog section."""
    for i in range(upto - 1, -1, -1):
        if H2_RE.match(lines[i]):
            return bool(CHANGELOG_H2_RE.match(lines[i]))
    return False


def _union_rows(ours: list[str], theirs: list[str]) -> list[str]:
    """Both sides' rows, duplicates dropped, stable-sorted by date (oldest first) so the
    table keeps its append-only order whichever side merges first."""
    seen: set[str] = set()
    rows: list[str] = []
    for r in ours + theirs:
        key = " ".join(r.split())
        if key not in seen:
            seen.add(key)
            rows.append(r)
    return sorted(rows, key=lambda r: ROW_RE.match(r).group(1))  # sorted() is stable


def resolve_changelog_conflicts(text: str) -> tuple[str, int]:
    """Rewrite every conflict block whose two sides are only Changelog rows into the
    union of those rows. Returns (text, number of conflict blocks left untouched)."""
    lines = text.split("\n")
    out: list[str] = []
    unresolved = 0
    i = 0
    while i < len(lines):
        if not OURS_RE.match(lines[i]):
            out.append(lines[i])
            i += 1
            continue
        start = i
        j = i + 1
        while j < len(lines) and not SEP_RE.match(lines[j]):
            j += 1
        k = j + 1
        while k < len(lines) and not THEIRS_RE.match(lines[k]):
            k += 1
        if j >= len(lines) or k >= len(lines):        # malformed block: copy verbatim
            out.extend(lines[start:])
            unresolved += 1
            break
        ours, theirs = lines[start + 1:j], lines[j + 1:k]
        # One side may be empty: when both branches appended the same row and one of them
        # appended more, git shows the shared row as context and an empty side against the rest.
        only_rows = (ours or theirs) and all(_is_row(x) for x in ours + theirs)
        if only_rows and _in_changelog(out, len(out)):
            out.extend(_union_rows(ours, theirs))
        else:
            out.extend(lines[start:k + 1])
            unresolved += 1
        i = k + 1
    return "\n".join(out), unresolved


def run_driver(base: Path, ours: Path, theirs: Path, path: str = "") -> int:
    """The git merge-driver entry point: three-way merge via `git merge-file`, then the
    Changelog union pass; the result replaces `ours` (git's %A) as git expects."""
    r = subprocess.run(
        ["git", "merge-file", "-p", f"--marker-size={MARKER}",
         "-L", "ours", "-L", "base", "-L", "theirs", str(ours), str(base), str(theirs)],
        capture_output=True, text=True)
    if r.returncode < 0 or r.returncode > 127:          # 255 = merge-file itself failed
        sys.stderr.write(f"librari merge-driver: git merge-file failed on {path or ours}: {r.stderr}")
        return 2
    if r.returncode == 0:
        ours.write_text(r.stdout, encoding="utf-8")
        return 0
    merged, left = resolve_changelog_conflicts(r.stdout)
    ours.write_text(merged, encoding="utf-8")
    resolved = r.returncode - left
    if resolved:
        sys.stderr.write(f"librari merge-driver: {path or ours.name}: unioned Changelog rows in "
              f"{resolved} conflict block(s)" + (f", {left} left for you" if left else "") + "\n")
    return 1 if left else 0


def cli(args) -> int:
    return run_driver(Path(args.base), Path(args.ours), Path(args.theirs), args.path or "")
