"""`librari diff` — per-section semantic diff of a page against git.

For PR review: which sections changed, how many bullets/lines moved, which
code blocks or identifiers were DROPPED (the no-detail-loss signal), which
changelog rows were added. Text, Markdown (paste into a PR comment) or JSON.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field

from .config import KbConfig
from .model import Page
from .parse import parse_text
from .sections import _trim, fingerprint
from .tables import changelog_table

BULLET_RE = re.compile(r"^\s*[-*+]\s+\S")


@dataclass
class SectionDiff:
    anchor: str
    status: str                       # added | removed | changed | unchanged
    lines_old: int = 0
    lines_new: int = 0
    bullets_old: int = 0
    bullets_new: int = 0
    code_added: int = 0
    code_dropped: list[str] = field(default_factory=list)
    idents_dropped: list[str] = field(default_factory=list)


def _bodies(page: Page | None) -> dict[str, list[str]]:
    if page is None:
        return {}
    return {s.anchor: _trim(page.lines[s.body_start:s.end]) for s in page.sections}


def _norm(lines: list[str]) -> list[str]:
    return [l.rstrip() for l in lines if l.strip()]


def page_diff(old_text: str | None, new_text: str, rel: str, directives: list[str]) -> dict:
    new = parse_text(new_text, rel, directives=directives)
    old = parse_text(old_text, rel, directives=directives) if old_text is not None else None
    ob, nb = _bodies(old), _bodies(new)
    whole = re.sub(r"\s+", " ", new_text)
    out: list[SectionDiff] = []
    for anchor in list(dict.fromkeys([*ob, *nb])):
        o, n = ob.get(anchor), nb.get(anchor)
        if o is None:
            d = SectionDiff(anchor, "added", lines_new=len(n), bullets_new=sum(bool(BULLET_RE.match(l)) for l in n))
            d.code_added = len(fingerprint(n)[0])
        elif n is None:
            d = SectionDiff(anchor, "removed", lines_old=len(o), bullets_old=sum(bool(BULLET_RE.match(l)) for l in o))
            codes, idents = fingerprint(o)
            # dropped only when gone from the WHOLE page (a moved block is not a loss)
            d.code_dropped = [c[:70] for c in codes if c and c not in whole]
            d.idents_dropped = sorted(i for i in idents if i not in new_text)
        else:
            status = "unchanged" if _norm(o) == _norm(n) else "changed"
            d = SectionDiff(anchor, status, len(o), len(n),
                            sum(bool(BULLET_RE.match(l)) for l in o), sum(bool(BULLET_RE.match(l)) for l in n))
            if status == "changed":
                oc, oi = fingerprint(o)
                nc, ni = fingerprint(n)
                ntext = "\n".join(n)
                d.code_added = max(0, len(nc) - len(oc))
                d.code_dropped = [c[:70] for c in oc if c and c not in nc and c not in whole]
                d.idents_dropped = sorted(i for i in oi - ni if i not in new_text)
        out.append(d)
    old_rows = [cells for _, cells in changelog_table(old)[1]] if old and changelog_table(old) else []
    new_rows = [cells for _, cells in changelog_table(new)[1]] if changelog_table(new) else []
    added_rows = [" | ".join(r) for r in new_rows[len(old_rows):]] if new_rows[: len(old_rows)] == old_rows else ["<rows rewritten — C009>"]
    fm_old, fm_new = (old.frontmatter or {}) if old else {}, new.frontmatter or {}
    fm_changed = sorted(k for k in set(fm_old) | set(fm_new) if fm_old.get(k) != fm_new.get(k))
    return {
        "page": rel, "new_page": old is None,
        "frontmatter_changed": fm_changed,
        "sections": [d.__dict__ for d in out],
        "changelog_rows_added": added_rows,
        "detail_lost": any(d.code_dropped or d.idents_dropped for d in out),
    }


def format_diff(d: dict, fmt: str = "text") -> str:
    if fmt == "json":
        return json.dumps(d, indent=2, ensure_ascii=False)
    md = fmt == "md"
    lines = [f"{'### ' if md else ''}{d['page']}" + (" (new page)" if d["new_page"] else "")]
    if d["frontmatter_changed"]:
        lines.append(f"- front matter: {', '.join(d['frontmatter_changed'])}")
    if md:
        lines += ["", "| section | status | lines | bullets | code | dropped |", "|---|---|---|---|---|---|"]
    for s in d["sections"]:
        if s["status"] == "unchanged":
            continue
        dropped = "; ".join([f"code: {c}" for c in s["code_dropped"]] + [f"`{i}`" for i in s["idents_dropped"]]) or "—"
        if md:
            lines.append(f"| `agent:{s['anchor']}` | {s['status']} | {s['lines_old']}→{s['lines_new']} | "
                         f"{s['bullets_old']}→{s['bullets_new']} | +{s['code_added']} | {dropped} |")
        else:
            lines.append(f"  agent:{s['anchor']:<22} {s['status']:<9} lines {s['lines_old']}→{s['lines_new']}  "
                         f"bullets {s['bullets_old']}→{s['bullets_new']}  code +{s['code_added']}"
                         + (f"\n      DROPPED: {dropped}" if dropped != "—" else ""))
    rows = d["changelog_rows_added"]
    lines.append(("- " if md else "  ") + (f"changelog rows added: {len(rows)}" if rows else "changelog: NO new row"))
    for r in rows:
        lines.append(("  - " if md else "      ") + r)
    if d["detail_lost"]:
        lines.append(("- " if md else "  ") + "⚠ actionable detail dropped — check against the no-detail-loss rule")
    return "\n".join(lines)


def cli(cfg: KbConfig, paths: list[str], changed: bool, base: str | None, fmt: str) -> int:
    from .check import select_pages
    from .gitutil import head_text, merge_base, repo_root
    repo = repo_root(cfg.root)
    if repo is None:
        print("librari diff: not inside a git repository", file=__import__("sys").stderr)
        return 2
    ref = base or (merge_base(repo) if changed else "HEAD") or "HEAD"
    import subprocess
    if subprocess.run(["git", "--no-optional-locks", "rev-parse", "--verify", "--quiet", ref + "^{commit}"],
                      cwd=repo, capture_output=True).returncode != 0:
        print(f"librari diff: unknown base ref `{ref}`", file=__import__("sys").stderr)
        return 2
    pages = select_pages(cfg, paths or None, changed or not paths, ref if changed else None)
    lost = False
    for p in pages:
        rel = p.resolve().relative_to(repo.resolve()).as_posix()
        old = head_text(repo, rel, ref)
        d = page_diff(old, p.read_text(encoding="utf-8"), cfg.slug_of(p) + ".md", cfg.settings["directives"])
        if old is not None and not d["frontmatter_changed"] and all(s["status"] == "unchanged" for s in d["sections"]) \
                and not d["changelog_rows_added"]:
            continue
        print(format_diff(d, fmt))
        print()
        lost = lost or d["detail_lost"]
    return 1 if lost else 0
