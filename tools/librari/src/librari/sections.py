"""Section-level edit API: read, replace, append, create, move one section of
a page addressed by its `agent:<anchor>` — the agent never rewrites a page.

`set` runs the no-detail-loss guard: code blocks and identifier-looking code
spans present in the old body must survive in the new one, or the write is
refused (list printed) unless --allow-drop. After every write the page is
validated; a RED result is refused unless --no-check (the file is left as it
was). That turns the docs-page skill's prose rules into mechanics.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

from .config import CANONICAL_ANCHORS, KbConfig
from .model import Page
from .parse import parse_file, parse_text

IDENT_RE = re.compile(r"^[\w@./:+~$*-]+$")
HEADINGS = {
    "decision": "Why it exists", "key-files": "Key files", "how": "How it works", "config": "Config",
    "gotchas": "Gotchas", "verify": "How to detect / verify", "changelog": "Changelog", "related": "Related",
}


class SectionError(Exception):
    pass


def _load(cfg: KbConfig, page_arg: str) -> Page:
    p = Path(page_arg)
    if not p.is_absolute():
        cand = cfg.root / (page_arg if page_arg.endswith(".md") else page_arg + ".md")
        p = cand if cand.exists() else Path(page_arg).resolve()
    if not p.is_file():
        raise SectionError(f"page not found: {page_arg}")
    try:
        return parse_file(p, cfg.root, cfg.settings["directives"])
    except ValueError:
        raise SectionError(f"{p} is not inside the kb ({cfg.root})")


def _section(page: Page, anchor: str):
    anchor = anchor.removeprefix("agent:")
    hits = [s for s in page.sections if s.anchor == anchor]
    if not hits:
        raise SectionError(f"{page.rel}: no section `agent:{anchor}` (have: {', '.join(page.anchors) or 'none'})")
    if len(hits) > 1:
        raise SectionError(f"{page.rel}: `agent:{anchor}` is ambiguous (C004) — fix the page first")
    return hits[0]


def _body(page: Page, sec) -> list[str]:
    return page.lines[sec.body_start:sec.end]


def _trim(lines: list[str]) -> list[str]:
    while lines and not lines[0].strip():
        lines = lines[1:]
    while lines and not lines[-1].strip():
        lines = lines[:-1]
    return lines


def fingerprint(lines: list[str]) -> tuple[list[str], set[str]]:
    """(code blocks normalised, identifier code spans) of a section body."""
    # parse as a page so 4-space-indented code blocks (S008) are protected too
    blocks = parse_text("\n".join(lines) + "\n", "fingerprint.md").code_blocks
    codes = [re.sub(r"\s+", " ", b.content).strip() for b in blocks]
    idents: set[str] = set()
    for i, l in enumerate(lines):
        if any(b.start <= i < b.end for b in blocks):
            continue
        for m in re.finditer(r"`([^`]+)`", l):
            span = m.group(1).strip()
            if IDENT_RE.match(span) and ("/" in span or "." in span or "_" in span or "-" in span or ":" in span
                                         or re.search(r"[a-z][A-Z]", span)):
                idents.add(span)
    return codes, idents


def drop_report(old: list[str], new: list[str]) -> list[str]:
    ocodes, oidents = fingerprint(old)
    ncodes, nidents = fingerprint(new)
    ntext = "\n".join(new)
    lost = []
    for c in ocodes:
        if c and c not in ncodes and c not in re.sub(r"\s+", " ", ntext):
            lost.append("code block: " + (c[:70] + ("…" if len(c) > 70 else "")))
    for ident in sorted(oidents - nidents):
        if ident not in ntext:
            lost.append(f"identifier: `{ident}`")
    return lost


def _errors(cfg: KbConfig, page: Page) -> list:
    from .gitutil import repo_root
    from .rules import Ctx, all_rules
    ctx = Ctx(cfg, repo_root(cfg.root))
    return [f for r in all_rules() for f in r.func(page, ctx)
            if f.severity == "error" and f.rule not in ("C010", "M004")]


def _write_checked(cfg: KbConfig, page: Page, new_lines: list[str], no_check: bool) -> int:
    """Write unless the edit INTRODUCES errors. Pre-existing ones (the page was
    already RED) never block a fix; they are listed as a reminder."""
    text = "\n".join(new_lines).rstrip("\n") + "\n"
    if not no_check:
        from collections import Counter
        before = Counter(f.rule for f in _errors(cfg, page))
        after = _errors(cfg, parse_text(text, page.rel, page.path, cfg.settings["directives"]))
        # messages embed line numbers, so compare per-rule COUNTS: an edit that
        # merely shifts a pre-existing finding is not a new error
        seen: Counter = Counter()
        new = []
        for f in after:
            seen[f.rule] += 1
            if seen[f.rule] > before[f.rule]:
                new.append(f)
        if new:
            print(f"refused: this edit would add {len(new)} error(s); page unchanged", file=sys.stderr)
            for f in new[:20]:
                print(f"  {page.rel}:{f.line or '-'}: {f.rule} {f.message}", file=sys.stderr)
            print("  fix the input, or pass --no-check to write anyway", file=sys.stderr)
            return 1
        if after:
            print(f"note: {page.rel} still has {len(after)} pre-existing error(s) — `librari check {page.rel}`",
                  file=sys.stderr)
    page.path.write_text(text, encoding="utf-8")
    return 0


def _read_input(src: str | None) -> list[str]:
    data = Path(src).read_text(encoding="utf-8") if src else sys.stdin.read()
    return _trim(data.rstrip("\n").split("\n"))


def _insert_position(cfg: KbConfig, page: Page, anchor: str) -> int:
    """Line index where a new canonical section goes: after the last present
    canonical section that precedes it in template order, else before the first
    that follows it, else EOF."""
    if anchor not in CANONICAL_ANCHORS:
        return len(page.lines)
    idx = CANONICAL_ANCHORS.index(anchor)
    present = [s for s in page.sections if s.anchor in CANONICAL_ANCHORS]
    before = [s for s in present if CANONICAL_ANCHORS.index(s.anchor) < idx]
    after = [s for s in present if CANONICAL_ANCHORS.index(s.anchor) > idx]
    if before:
        return max(s.end for s in before)
    if after:
        return min(s.start for s in after)
    return len(page.lines)


def cmd_list(cfg: KbConfig, args) -> int:
    page = _load(cfg, args.page)
    for s in page.sections:
        print(f"agent:{s.anchor:<20} L{s.start + 1}-{s.end}  {'#' * s.heading.level} {s.heading.text}")
    return 0


def cmd_get(cfg: KbConfig, args) -> int:
    page = _load(cfg, args.page)
    sec = _section(page, args.anchor)
    start = sec.start if args.with_heading else sec.body_start
    print("\n".join(_trim(page.lines[start:sec.end])))
    return 0


def cmd_set(cfg: KbConfig, args) -> int:
    page = _load(cfg, args.page)
    anchor = args.anchor.removeprefix("agent:")
    new_body = _read_input(args.src)
    try:
        sec = _section(page, anchor)
    except SectionError:
        if not args.create or anchor in page.anchors:   # ambiguous anchor: never add a third
            raise
        pos = _insert_position(cfg, page, anchor)
        heading = args.heading or HEADINGS.get(anchor, anchor.replace("-", " ").capitalize())
        block = ["", f"## {heading} <!-- agent:{anchor} -->", "", *new_body, ""]
        new_lines = page.lines[:pos] + block + page.lines[pos:]
        rc = _write_checked(cfg, page, new_lines, args.no_check)
        if rc == 0:
            print(f"{page.rel}: created `agent:{anchor}` at line {pos + 2}")
        return rc
    old_body = _trim(_body(page, sec))
    if not args.allow_drop:
        lost = drop_report(old_body, new_body)
        if lost:
            print(f"refused: the new `agent:{anchor}` body drops actionable detail (no-detail-loss rule):",
                  file=sys.stderr)
            for l in lost:
                print(f"  - {l}", file=sys.stderr)
            print("  keep it (move it into How to detect / verify if it clutters), or pass --allow-drop",
                  file=sys.stderr)
            return 1
    new_lines = page.lines[:sec.body_start] + ["", *new_body, ""] + page.lines[sec.end:]
    rc = _write_checked(cfg, page, new_lines, args.no_check)
    if rc == 0:
        print(f"{page.rel}: replaced `agent:{anchor}` ({len(old_body)} → {len(new_body)} lines)")
    return rc


def cmd_append(cfg: KbConfig, args) -> int:
    page = _load(cfg, args.page)
    sec = _section(page, args.anchor)
    extra = _read_input(args.src)
    body = _trim(_body(page, sec))
    new_lines = page.lines[:sec.body_start] + ["", *body, "", *extra, ""] + page.lines[sec.end:]
    rc = _write_checked(cfg, page, new_lines, args.no_check)
    if rc == 0:
        print(f"{page.rel}: appended {len(extra)} line(s) to `agent:{sec.anchor}`")
    return rc


def cmd_move(cfg: KbConfig, args) -> int:
    page = _load(cfg, args.page)
    sec = _section(page, args.anchor)
    ref = _section(page, args.before or args.after)
    if ref.anchor == sec.anchor:
        raise SectionError("cannot move a section relative to itself")
    if sec.start <= ref.start < sec.end or ref.start <= sec.start < ref.end:
        raise SectionError(f"`agent:{sec.anchor}` and `agent:{ref.anchor}` are nested — move the outer section, "
                           "or change heading levels first")
    block = _trim(page.lines[sec.start:sec.end])
    rest = page.lines[:sec.start] + page.lines[sec.end:]
    # locate the reference on the REDUCED page, never with the old line numbers
    reduced = parse_text("\n".join(rest) + "\n", page.rel, page.path, cfg.settings["directives"])
    ref2 = _section(reduced, ref.anchor)
    pos = ref2.start if args.before else ref2.end
    new_lines = rest[:pos] + [""] + block + [""] + rest[pos:]
    rc = _write_checked(cfg, page, new_lines, args.no_check)
    if rc == 0:
        print(f"{page.rel}: moved `agent:{sec.anchor}` {'before' if args.before else 'after'} `agent:{ref.anchor}`")
    return rc


def cmd_reorder(cfg: KbConfig, args) -> int:
    """Put the canonical H2 sections into template order; page-specific sections
    keep their relative position after the canonical block they follow."""
    page = _load(cfg, args.page)
    canon = [s for s in page.sections if s.anchor in CANONICAL_ANCHORS and s.heading.level == 2]
    if len({s.anchor for s in canon}) != len(canon):
        raise SectionError(f"{page.rel}: duplicate canonical anchors (C004) — run `section dedupe` first")
    order = sorted(canon, key=lambda s: CANONICAL_ANCHORS.index(s.anchor))
    if [s.anchor for s in order] == [s.anchor for s in canon]:
        print(f"{page.rel}: already in order")
        return 0
    # Split the page into: prefix (lead + anything before the first H2), then
    # H2-delimited blocks. A block = an H2 heading up to the next H2.
    h2 = [h.line for h in page.headings if h.level == 2]
    first = h2[0] if h2 else len(page.lines)
    prefix = page.lines[:first]
    blocks = []
    for i, start in enumerate(h2):
        end = h2[i + 1] if i + 1 < len(h2) else len(page.lines)
        anchor = next((s.anchor for s in canon if s.start == start), None)
        blocks.append((anchor, _trim(page.lines[start:end])))
    # canonical blocks are re-emitted in template order at the position of the
    # first canonical block; non-canonical blocks stay where they are
    canon_blocks = {a: b for a, b in blocks if a}
    out_blocks = []
    emitted = False
    for a, b in blocks:
        if a:
            if not emitted:
                out_blocks.extend(canon_blocks[s.anchor] for s in order)
                emitted = True
            continue
        out_blocks.append(b)
    new_lines = list(prefix)
    for b in out_blocks:
        new_lines += [""] + b
    rc = _write_checked(cfg, page, new_lines, args.no_check)
    if rc == 0:
        print(f"{page.rel}: reordered canonical sections → " + " → ".join(s.anchor for s in order))
    return rc


def cmd_dedupe(cfg: KbConfig, args) -> int:
    """Rename the 2nd, 3rd … occurrence of an anchor to `<anchor>-2`, `-3`.
    Links to `#agent:<anchor>` keep pointing at the first occurrence."""
    page = _load(cfg, args.page)
    seen: dict[str, int] = {}
    lines = list(page.lines)
    renamed = []
    for s in page.sections:
        n = seen.get(s.anchor, 0) + 1
        seen[s.anchor] = n
        if n == 1:
            continue
        new = f"{s.anchor}-{n}"
        while new in seen or new in page.anchors:
            n += 1
            new = f"{s.anchor}-{n}"
        seen[new] = 1
        lines[s.start] = re.sub(r"<!--\s*agent:" + re.escape(s.anchor) + r"\s*-->", f"<!-- agent:{new} -->", lines[s.start])
        renamed.append((s.start + 1, s.anchor, new))
    if not renamed:
        print(f"{page.rel}: no duplicate anchors")
        return 0
    rc = _write_checked(cfg, page, lines, args.no_check)
    if rc == 0:
        for ln, old, new in renamed:
            print(f"{page.rel}:{ln}: agent:{old} → agent:{new}")
    return rc


def cli(cfg: KbConfig, args) -> int:
    try:
        return {"list": cmd_list, "get": cmd_get, "set": cmd_set, "append": cmd_append, "move": cmd_move,
                "reorder": cmd_reorder, "dedupe": cmd_dedupe}[args.action](cfg, args)
    except SectionError as e:
        print(f"librari section: {e}", file=sys.stderr)
        return 2
