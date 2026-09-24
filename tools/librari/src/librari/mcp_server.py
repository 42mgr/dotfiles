"""`librari mcp` — the same operations as the CLI, as MCP tools over stdio.

Registered in the repo's `.mcp.json`; every tool works on kb-relative page
paths (`identity/users` or `identity/users.md`) and returns the CLI's text.
Writes go through the same guards as the CLI (no-detail-loss, no new errors).
"""
from __future__ import annotations

import contextlib
import io
import threading
from types import SimpleNamespace as NS

# mcp runs sync tools on a thread pool; the CLI helpers print to the
# process-global stdout and edit pages read-modify-write, so every tool call
# is serialised through this lock (sync-only by design).
_LOCK = threading.Lock()

from .config import KbConfig


def _tmp(body: str) -> str:
    import tempfile
    with tempfile.NamedTemporaryFile("w", suffix=".md", delete=False, encoding="utf-8") as f:
        f.write(body)
    return f.name


def _twin_note(cfg: KbConfig, page: str) -> str:
    """MCP writes bypass the PostToolUse hooks, so say here what the
    librari-pages-for hook would say: keep the docs/ twin in step."""
    from .gitutil import repo_root
    repo = repo_root(cfg.root)
    slug = page[:-3] if page.endswith(".md") else page
    if repo and (repo / "docs" / (slug + ".mdx")).is_file():
        return f"\nnote: docs/{slug}.mdx is this page's twin — mirror the change there (docs-page skill) until cutover."
    return ""


def _capture(fn, *a, **kw) -> str:
    out, err = io.StringIO(), io.StringIO()
    with _LOCK, contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        try:
            rc = fn(*a, **kw)
        except SystemExit as e:  # argparse-style exits inside helpers
            rc = int(e.code or 0)
    text = (out.getvalue() + err.getvalue()).strip()
    return f"{text}\n[exit {rc}]" if rc else text


def build(cfg: KbConfig):
    from mcp.server.mcpserver import MCPServer

    from . import sections
    from .changelog import add_row
    from .check import format_text, run
    from .diff import format_diff, page_diff
    from .index import owner as _owner, pages_for as _pages_for
    from .rules import all_rules
    from .search import LiveIndex, format_hits, read_page as _read_page

    srv = MCPServer("librari", instructions="Knowledge-base tool for kb/. For ANY question about this stack, call "
                    "`search` BEFORE grep/Read over kb/: it ranks sections (stemmed FTS5 over body text incl. code) and "
                    "returns slug#anchor + line range + snippet; then `read_page(page, anchor)` for that one section. "
                    "Prefer section_set/section_append over rewriting pages; every write is validated and refused if "
                    "it adds errors or drops detail.")
    live = LiveIndex(cfg)

    def _page(p: str) -> str:
        return p if p.endswith(".md") else p + ".md"

    @srv.tool(description="Validate a kb page (or the whole kb when page is empty). Text report + verdict.")
    def check(page: str = "") -> str:
        with _LOCK:
            rep = run(cfg, [str(cfg.root / _page(page))] if page else None)
        return format_text(rep)

    @srv.tool(description="Explain a rule id (S001…, C001…, M001…), or 'all' / 'kinds'.")
    def explain(rule: str) -> str:
        from .cli import cmd_explain
        return _capture(cmd_explain, NS(rule=rule, kb=str(cfg.root), page=None, paths=None))

    @srv.tool(description="List a page's sections (anchor, line range, heading).")
    def section_list(page: str) -> str:
        return _capture(sections.cli, cfg, NS(action="list", page=_page(page)))

    @srv.tool(description="Body of one section, addressed by its agent:<anchor>.")
    def section_get(page: str, anchor: str) -> str:
        return _capture(sections.cli, cfg, NS(action="get", page=_page(page), anchor=anchor, with_heading=False))

    @srv.tool(description="Replace a section body. Refuses when code blocks/identifiers would be dropped "
                          "(allow_drop=True overrides — only with the owner's explicit say-so) or the page would gain "
                          "errors. create=True inserts a missing canonical section.")
    def section_set(page: str, anchor: str, body: str, allow_drop: bool = False, create: bool = False) -> str:
        import os
        src = _tmp(body)
        try:
            out = _capture(sections.cli, cfg, NS(action="set", page=_page(page), anchor=anchor, src=src,
                                                 create=create, heading=None, allow_drop=allow_drop, no_check=False))
        finally:
            os.unlink(src)
        return out + ("" if "[exit" in out else _twin_note(cfg, _page(page)))

    @srv.tool(description="Append text to a section body (e.g. one more Gotchas bullet).")
    def section_append(page: str, anchor: str, text: str) -> str:
        import os
        src = _tmp(text)
        try:
            out = _capture(sections.cli, cfg, NS(action="append", page=_page(page), anchor=anchor, src=src, no_check=False))
        finally:
            os.unlink(src)
        return out + ("" if "[exit" in out else _twin_note(cfg, _page(page)))

    @srv.tool(description="Append a Changelog row (type from librari.json changelogTypes; date defaults to today).")
    def changelog_add(page: str, type: str, summary: str, date: str = "") -> str:
        return _capture(add_row, cfg, _page(page), type, summary, date or None)

    @srv.tool(description="Full-text search over every section of every page (Porter-stemmed FTS5/bm25 on heading, "
                          "title, keywords and body text incl. code; un-anchored H2 regions included). Returns "
                          "`slug#anchor`, line range, page description, score and a snippet — follow up with "
                          "read_page(page, anchor). All words must match; falls back to any word (stated).")
    def search(query: str, limit: int = 10, kind: str = "") -> str:
        with _LOCK:
            hits = live.search(query, limit, kind)
        return format_hits(hits, "text")

    @srv.tool(description="One section or region (with heading) when anchor is given — `agent:x` for an anchored "
                          "section, or the heading slug after `#` in a search ref for an un-anchored H2 region — "
                          "else the whole page as Markdown. A page over 400 lines returns front matter + a heading "
                          "index instead of the body unless force=True.")
    def read_page(page: str, anchor: str = "", force: bool = False) -> str:
        from .sections import SectionError
        with _LOCK:
            try:
                return _read_page(cfg, _page(page), anchor, force)
            except SectionError as e:
                return f"{e}\n[exit 1]"

    @srv.tool(description="Which pages own a topic — deterministic ranking over keywords/title/slug/lead/headings.")
    def owner(query: str, limit: int = 5) -> str:
        return "\n".join(f"{s:5.1f}  {slug}  — {title}" for s, slug, title in _owner(cfg, query, limit)) or "no match"

    @srv.tool(description="Pages whose Key files table lists this repo-relative path.")
    def pages_for(path: str) -> str:
        hits = _pages_for(cfg, path)
        return "\n".join(f"{slug}  ({entry})" for slug, entry in hits) or "no page lists this path"

    @srv.tool(description="Per-section semantic diff of a page against HEAD (Markdown).")
    def diff(page: str) -> str:
        from .gitutil import head_text, repo_root
        repo = repo_root(cfg.root)
        p = cfg.root / _page(page)
        rel = p.resolve().relative_to(repo.resolve()).as_posix() if repo else _page(page)
        old = head_text(repo, rel) if repo else None
        return format_diff(page_diff(old, p.read_text(encoding="utf-8"), _page(page), cfg.settings["directives"]), "md")

    @srv.tool(description="Agent-readiness score of the whole kb (0–100) with the per-check breakdown: entry page, "
                          "retrievability, verifiability, freshness, contract. Metric only — `check` is the gate.")
    def score(verbose: bool = False) -> str:
        from .score import format_table, run as score_run
        with _LOCK:
            rep = score_run(cfg)
        return format_table(rep, verbose)

    @srv.tool(description="Rule inventory: id, severity, title.")
    def rules() -> str:
        return "\n".join(f"{r.id}  {r.severity:7} {r.title}" for r in all_rules())

    return srv


def serve(cfg: KbConfig) -> int:
    build(cfg).run("stdio")
    return 0
