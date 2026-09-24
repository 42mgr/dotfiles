"""Machine-readable page index + the two deterministic lookups built on it:
`librari owner <query>` (which page owns a topic) and `librari pages-for <path>`
(which pages list a repo path in Key files)."""
from __future__ import annotations

import fnmatch
import json
import re
from pathlib import Path

from .config import KbConfig
from .parse import parse_file
from .tables import code_spans, key_files_table

WORD_RE = re.compile(r"[a-z0-9][a-z0-9_.-]*[a-z0-9]|[a-z0-9]", re.I)


def lead_of(page, limit: int = 400) -> str:
    """The lead paragraph(s): text between the front matter and the first
    heading, comments and directive markers dropped. One definition for the
    page index and the site search."""
    lines = []
    for l in page.lines[page.frontmatter_end:page.first_heading_line()]:
        t = l.strip()
        if t and not t.startswith("<!--") and not t.startswith(":::"):
            lines.append(t)
    return " ".join(lines)[:limit]


def _key_files(page) -> list[str]:
    t = key_files_table(page)
    if t is None:
        return []
    out = []
    for _, cells in t[1]:
        out.extend(re.sub(r":\d+(-\d+)?$", "", s) for s in code_spans(cells[0] if cells else "")
                   if not any(ch in s for ch in "<>{}$… "))
    return out


def build_index(cfg: KbConfig) -> dict:
    pages = []
    for p in cfg.all_pages():
        pg = parse_file(p, cfg.root, cfg.settings["directives"])
        fm = pg.frontmatter or {}
        lead = lead_of(pg, 400)
        pages.append({
            "slug": pg.slug, "path": pg.rel, "kind": pg.kind,
            "title": fm.get("title", ""), "description": fm.get("description", ""),
            "keywords": fm.get("keywords", []) if isinstance(fm.get("keywords"), list) else [],
            "status": fm.get("status"), "group": cfg.group_of(pg.slug),
            "lead": lead,
            "sections": [{"anchor": s.anchor, "heading": s.heading.text, "lines": [s.start + 1, s.end]}
                         for s in pg.sections],
            "keyFiles": _key_files(pg),
            "lines": len(pg.lines),
        })
    return {"kb": cfg.name, "pages": pages}


def write_index(cfg: KbConfig, data: dict) -> Path:
    out = cfg.root / "index.json"
    out.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return out


def _tokens(s: str) -> set[str]:
    return {w.lower() for w in WORD_RE.findall(s or "")}


def owner(cfg: KbConfig, query: str, limit: int = 5) -> list[tuple[float, str, str]]:
    """Deterministic ranking: exact keyword phrase 5, keyword word 3, title word 2,
    slug word 2, description/lead word 1, section heading word 1. Ties by slug."""
    q = _tokens(query)
    phrase = query.strip().lower()
    scored = []
    for e in build_index(cfg)["pages"]:
        kw = {k.lower() for k in e["keywords"]}
        score = 0.0
        score += 5 if phrase in kw else 0
        score += 3 * len(q & _tokens(" ".join(e["keywords"])))
        score += 2 * len(q & _tokens(e["title"]))
        score += 2 * len(q & _tokens(e["slug"].replace("/", " ")))
        score += 1 * len(q & _tokens(e["description"] + " " + e["lead"]))
        score += 1 * len(q & _tokens(" ".join(s["heading"] for s in e["sections"])))
        if score:
            scored.append((score, e["slug"], e["title"]))
    scored.sort(key=lambda t: (-t[0], t[1]))
    return scored[:limit]


def pages_for(cfg: KbConfig, path: str) -> list[tuple[str, str]]:
    """Pages whose Key files table lists `path` (repo-relative), a parent
    directory of it, or a glob matching it."""
    path = path.strip().removeprefix("./")
    hits = []
    for e in build_index(cfg)["pages"]:
        for kf in e["keyFiles"]:
            k = kf.rstrip("/")
            if k == path or path.startswith(k + "/") or ("*" in k and fnmatch.fnmatch(path, k)):
                hits.append((e["slug"], kf))
                break
    return sorted(hits)
