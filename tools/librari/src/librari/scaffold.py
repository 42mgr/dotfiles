"""`librari new` (page from kind template + nav registration) and `librari nav add`."""
from __future__ import annotations

import datetime as dt
import sys
from pathlib import Path

import yaml

from .config import KbConfig

TEMPLATES = Path(__file__).parent / "templates"   # packaged defaults; kb/_templates/<kind>.md overrides


def template_for(cfg: KbConfig, kind: str) -> Path:
    for cand in (cfg.root / "_templates" / f"{kind}.md", TEMPLATES / f"{kind}.md"):
        if cand.is_file():
            return cand
    raise FileNotFoundError(f"no template for kind `{kind}` (looked in {cfg.root / '_templates'} and {TEMPLATES})")


def export_templates(cfg: KbConfig) -> int:
    """Copy the packaged templates into <kb>/_templates/ for local customisation."""
    dest = cfg.root / "_templates"
    dest.mkdir(exist_ok=True)
    n = 0
    for f in sorted(TEMPLATES.glob("*.md")):
        target = dest / f.name
        if target.exists():
            print(f"kept {target.relative_to(cfg.root)} (exists)")
            continue
        target.write_text(f.read_text(encoding="utf-8"), encoding="utf-8")
        n += 1
    print(f"exported {n} template(s) to {dest.relative_to(cfg.root)}/")
    return 0


def nav_add(cfg: KbConfig, group: str, slug: str) -> int:
    slug = slug.strip("/")
    if slug in cfg.nav_pages():
        print(f"{slug} already in nav group `{cfg.group_of(slug)}`")
        return 0
    for g in cfg.groups:
        if g["group"] == group:
            g.setdefault("pages", []).append(slug)
            break
    else:
        print(f"nav group `{group}` does not exist; groups: " + ", ".join(g["group"] for g in cfg.groups),
              file=sys.stderr)
        return 2
    cfg.save()
    print(f"nav: added {slug} to `{group}`")
    return 0


def new_page(cfg: KbConfig, slug: str, kind: str, title: str, group: str,
             description: str = "", keywords: str = "") -> int:
    slug = slug.strip("/")
    if kind not in cfg.kinds:
        print(f"unknown kind `{kind}`; kinds: {', '.join(cfg.kinds)}", file=sys.stderr)
        return 2
    target = cfg.page_path(slug)
    if target.exists():
        print(f"{target} already exists — enrich it instead (`librari section set …`)", file=sys.stderr)
        return 2
    if not any(g["group"] == group for g in cfg.groups):
        print(f"nav group `{group}` does not exist; groups: " + ", ".join(g["group"] for g in cfg.groups),
              file=sys.stderr)
        return 2
    tpl = template_for(cfg, kind).read_text(encoding="utf-8")
    body = tpl.split("\n---\n", 1)[1] if tpl.startswith("---\n") else tpl
    fm = {"title": title, "description": description or f"What {title} is and how to work with it.",
          "keywords": [k.strip() for k in keywords.split(",") if k.strip()] or [slug.rsplit("/", 1)[-1]],
          "kind": kind}
    if kind == "roadmap":
        fm["status"] = "open"
    today = dt.date.today().isoformat()
    body = body.replace("YYYY-MM-DD", today)
    text = "---\n" + yaml.safe_dump(fm, sort_keys=False, allow_unicode=True, width=1000).rstrip() + "\n---\n" + body.lstrip("\n")
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(text, encoding="utf-8")
    print(f"created {target.relative_to(cfg.root)} (kind {kind})")
    return nav_add(cfg, group, slug)
