"""`librari fix` — deterministic autofixes for findings that need no judgement.

  --paths      M010: replace an abbreviated Key files path by its unique full path
  --backlinks  M008: add the missing reverse link to the target's Related section,
               using the linking page's description as the bullet text
  --lead       C005: insert the front-matter description as the lead paragraph
  --fences     S008: an indented block inside a directive is prose that lost its
               dedent (converter artefact) → dedented; elsewhere → ```text fence

Every write goes through the same post-check as `section set` (no new errors).
Pages edited get no automatic Changelog row: the caller adds one (`--changelog`
appends `docs | librari fix: …` to every page touched).
"""
from __future__ import annotations

import datetime as dt
import re
from pathlib import Path

from .check import run
from .config import KbConfig
from .parse import parse_file
from .tables import DATE_RE, changelog_table


def _write(cfg: KbConfig, path: Path, lines: list[str], touched: set[str]) -> None:
    path.write_text("\n".join(lines).rstrip("\n") + "\n", encoding="utf-8")
    touched.add(path.resolve().relative_to(cfg.root.resolve()).as_posix())


def fix_paths(cfg: KbConfig, report, touched: set[str]) -> int:
    n = 0
    by_page: dict[str, list] = {}
    for f in report.findings:
        if f.rule == "M010":
            by_page.setdefault(f.path, []).append(f)
    for rel, fs in by_page.items():
        path = cfg.root / rel
        lines = path.read_text(encoding="utf-8").split("\n")
        for f in fs:
            m = re.search(r"`([^`]+)` is abbreviated — write `([^`]+)`", f.message)
            if not m or f.line is None:
                continue
            short, full = m.group(1), m.group(2)
            ln = f.line - 1
            if f"`{short}`" in lines[ln]:
                lines[ln] = lines[ln].replace(f"`{short}`", f"`{full}`", 1)
                n += 1
        _write(cfg, path, lines, touched)
    return n


def fix_backlinks(cfg: KbConfig, report, touched: set[str]) -> int:
    """For each M008 (A → B one-way), append `- [A title](/A) — A description` to B's Related."""
    n = 0
    pages = {p: parse_file(cfg.root / p, cfg.root, cfg.settings["directives"]) for p in report.pages}
    adds: dict[str, list[tuple[str, str, str]]] = {}
    for f in report.findings:
        if f.rule != "M008":
            continue
        m = re.search(r"`/([^`]+)` does not link back", f.message)
        if not m:
            continue
        src = pages.get(f.path)
        if src is None:
            continue
        fm = src.frontmatter or {}
        adds.setdefault(m.group(1) + ".md", []).append((src.slug, fm.get("title", src.slug), fm.get("description", "")))
    for rel, items in adds.items():
        path = cfg.root / rel
        if not path.is_file():
            continue
        page = parse_file(path, cfg.root, cfg.settings["directives"])
        sec = page.section("related")
        if sec is None:
            continue
        lines = list(page.lines)
        existing = "\n".join(lines[sec.body_start:sec.end])
        new = [f"- [{title}](/{slug}) — {desc.rstrip('.')}." if desc else f"- [{title}](/{slug})"
               for slug, title, desc in dict.fromkeys(items) if f"(/{slug})" not in existing]
        if not new:
            continue
        end = sec.end
        while end > sec.body_start and not lines[end - 1].strip():
            end -= 1
        lines[end:end] = new
        _write(cfg, path, lines, touched)
        n += len(new)
    return n


def fix_lead(cfg: KbConfig, report, touched: set[str]) -> int:
    n = 0
    for f in report.findings:
        if f.rule != "C005":
            continue
        path = cfg.root / f.path
        page = parse_file(path, cfg.root, cfg.settings["directives"])
        desc = (page.frontmatter or {}).get("description", "").strip()
        if not desc:
            continue
        lines = list(page.lines)
        lines[page.frontmatter_end:page.frontmatter_end] = ["", desc]
        _write(cfg, path, lines, touched)
        n += 1
    return n


def fix_fences(cfg: KbConfig, report, touched: set[str]) -> int:
    n = 0
    by_page: dict[str, list[int]] = {}
    for f in report.findings:
        if f.rule == "S008" and f.line:
            by_page.setdefault(f.path, []).append(f.line - 1)
    for rel, starts in by_page.items():
        path = cfg.root / rel
        page = parse_file(path, cfg.root, cfg.settings["directives"])
        lines = list(page.lines)
        for cb in sorted((c for c in page.code_blocks if c.info == "<indented>" and c.start in starts),
                         key=lambda c: -c.start):
            body = [l[4:] if l.startswith("    ") else l.lstrip("\t") for l in lines[cb.start:cb.end]]
            while body and not body[-1].strip():
                body.pop()
            enclosing = [c for c in page.containers if c.open_line < cb.start and (c.close_line or 10**9) > cb.start]
            if enclosing:
                # the converter left the whole directive body indented: dedent
                # every 4-space line up to the container's closer (closing
                # fences included), not just the lines markdown-it called code
                end = min(c.close_line for c in enclosing if c.close_line is not None) if any(c.close_line for c in enclosing) else len(lines)
                for j in range(cb.start, end):
                    if lines[j].startswith("    "):
                        lines[j] = lines[j][4:]
            else:
                lines[cb.start:cb.end] = ["```text", *body, "```"]
            n += 1
        _write(cfg, path, lines, touched)
    return n


def add_changelog_rows(cfg: KbConfig, touched: set[str], summary: str) -> int:
    n = 0
    today = dt.date.today().isoformat()
    for rel in sorted(touched):
        page = parse_file(cfg.root / rel, cfg.root, cfg.settings["directives"])
        t = changelog_table(page)
        if t is None:
            continue
        hl, rows = t
        last = rows[-1][0] if rows else hl + 1
        lines = list(page.lines)
        lines.insert(last + 1, f"| {today} | docs | {summary} |")
        (cfg.root / rel).write_text("\n".join(lines).rstrip("\n") + "\n", encoding="utf-8")
        n += 1
    return n


def cli(cfg: KbConfig, paths: bool, backlinks: bool, lead: bool, fences: bool, changelog: bool) -> int:
    report = run(cfg, use_baseline=False)
    touched: set[str] = set()
    out = []
    if paths:
        out.append(f"M010 full paths: {fix_paths(cfg, report, touched)}")
    if lead:
        out.append(f"C005 leads: {fix_lead(cfg, report, touched)}")
    if fences:
        out.append(f"S008 fences: {fix_fences(cfg, report, touched)}")
    if backlinks:
        report = run(cfg, use_baseline=False)   # re-parse after the edits above
        out.append(f"M008 back-links: {fix_backlinks(cfg, report, touched)}")
    if changelog and touched:
        out.append(f"changelog rows: {add_changelog_rows(cfg, touched, 'librari fix: ' + ', '.join(o.split(':')[0] for o in out))}")
    print("librari fix — " + "; ".join(out) + f"; pages touched: {len(touched)}")
    after = run(cfg)
    print(f"check afterwards: {after.verdict} — {len(after.errors)} error(s), {len(after.warnings)} warning(s)")
    return 0 if after.verdict == "GREEN" else 1
