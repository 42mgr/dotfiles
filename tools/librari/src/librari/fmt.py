"""`librari fmt` — canonical formatting so agent rewrites produce minimal diffs.

Idempotent, structure-preserving, never touches code-fence content:
  * front matter keys in fixed order (title, description, keywords, kind, status, rest)
  * heading lines: `## Text <!-- agent:x -->` with single spaces
  * directive markers: canonical colon counts (3 + nesting height), when the nesting is valid
  * pipe tables: cells padded to column width, `|---|` separators
  * trailing whitespace stripped, blank runs collapsed to one, single final newline
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

import yaml

from .config import KbConfig
from .parse import ANCHOR_RE, SEP_RE, parse_text, scan_blocks, split_row

FM_ORDER = ["title", "description", "keywords", "kind", "status"]
HEADING_RE = re.compile(r"^(#{1,6})\s+(.*?)\s*$")


def _fm_text(fm: dict) -> str:
    ordered = {k: fm[k] for k in FM_ORDER if k in fm}
    ordered.update({k: v for k, v in fm.items() if k not in ordered})
    return yaml.safe_dump(ordered, sort_keys=False, allow_unicode=True, width=1000).rstrip()


def _table(rows: list[list[str]]) -> list[str]:
    ncol = max(len(r) for r in rows)
    rows = [r + [""] * (ncol - len(r)) for r in rows]
    widths = [max([3] + [len(r[i]) for j, r in enumerate(rows) if j != 1]) for i in range(ncol)]
    out = []
    for j, r in enumerate(rows):
        if j == 1:
            cells = []
            for i, c in enumerate(r):
                left, right = c.startswith(":"), c.endswith(":")
                cells.append((":" if left else "") + "-" * max(1, widths[i] - left - right) + (":" if right else ""))
            out.append("| " + " | ".join(cells) + " |")
        else:
            out.append("| " + " | ".join(c.ljust(widths[i]) for i, c in enumerate(r)) + " |")
    return out


def _code_lines(lines: list[str]) -> set[int]:
    s: set[int] = set()
    for cb in scan_blocks(lines)[0]:
        s.update(range(cb.start, cb.end))
    return s


def format_text(text: str, directives: list[str]) -> str:
    page = parse_text(text, "fmt.md", directives=directives)
    in_code = _code_lines(page.lines)
    lines = [l if i in in_code else l.rstrip() for i, l in enumerate(page.lines)]
    code, containers, _, _ = scan_blocks(lines)
    if all(c.close_line is not None and c.auto_closed_by is None for c in containers):
        def height(c):
            return 1 + max((height(ch) for ch in c.children), default=-1)
        for c in containers:
            colons = ":" * (3 + height(c))
            indent = lines[c.open_line][: len(lines[c.open_line]) - len(lines[c.open_line].lstrip(" "))]
            lines[c.open_line] = f"{indent}{colons}{c.name}" + (f" {c.title}" if c.title else "")
            lines[c.close_line] = f"{indent}{colons}"
    out: list[str] = []
    i = 0
    fm_end = page.frontmatter_end
    while i < len(lines):
        if i in in_code or i < fm_end:
            out.append(lines[i]); i += 1; continue
        # a standalone anchor comment directly above a heading belongs ON it
        am = ANCHOR_RE.fullmatch(lines[i].strip())
        if am and i + 1 < len(lines) and HEADING_RE.match(lines[i + 1]) and (i + 1) not in in_code \
                and not ANCHOR_RE.search(lines[i + 1]):
            lines[i + 1] = lines[i + 1].rstrip() + f" <!-- agent:{am.group(1)} -->"
            i += 1; continue
        m = HEADING_RE.match(lines[i])
        if m:
            body = m.group(2)
            am = ANCHOR_RE.search(body)
            body = ANCHOR_RE.sub("", body).strip()
            out.append(f"{m.group(1)} {body}" + (f" <!-- agent:{am.group(1)} -->" if am else ""))
            i += 1; continue
        if "|" in lines[i] and i + 1 < len(lines) and SEP_RE.match(lines[i + 1]) and "|" in lines[i + 1] \
                and (i + 1) not in in_code:
            j, rows = i, []
            while j < len(lines) and lines[j].strip() and "|" in lines[j] and j not in in_code:
                rows.append(split_row(lines[j])); j += 1
            out.extend(_table(rows)); i = j; continue
        out.append(lines[i]); i += 1
    if page.frontmatter is not None and fm_end:
        out = ["---", _fm_text(page.frontmatter), "---"] + out[fm_end:]
    code_lines = _code_lines(out)
    res, blank = [], False
    for k, l in enumerate(out):
        if k in code_lines or l.strip():
            res.append(l); blank = False
        elif not blank:
            res.append(""); blank = True
    while res and not res[-1].strip():
        res.pop()
    return "\n".join(res) + "\n"


def cli(cfg: KbConfig, paths: list[str], check: bool) -> int:
    targets = [Path(p) for p in paths] if paths else cfg.all_pages()
    changed = []
    for p in targets:
        src = p.read_text(encoding="utf-8")
        dst = format_text(src, cfg.settings["directives"])
        if dst != src:
            changed.append(str(p.resolve().relative_to(cfg.root.resolve())))
            if not check:
                p.write_text(dst, encoding="utf-8")
    verb = "would reformat" if check else "reformatted"
    for r in changed:
        print(f"{verb} {r}")
    if check:
        print(f"librari fmt --check: {'RED' if changed else 'GREEN'} — {len(changed)} of {len(targets)} page(s) differ")
        return 1 if changed else 0
    print(f"librari fmt: {len(changed)} of {len(targets)} page(s) changed")
    return 0
