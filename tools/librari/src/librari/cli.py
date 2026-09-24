"""`librari` command line. Exit codes follow the repo's verdict vocabulary:
0 GREEN, 1 RED, 2 NO-VERDICT (could not check / bad invocation)."""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

from . import __version__
from .config import find_root, load


def _cfg(args):
    start = None
    if getattr(args, "page", None):
        start = Path(args.page)
    elif getattr(args, "paths", None):
        start = Path(args.paths[0])
    return load(find_root(start, args.kb))


def cmd_check(args) -> int:
    from .check import format_json, format_text, run
    cfg = _cfg(args)
    rules = set(args.rule) if args.rule else None
    report = run(cfg, args.paths or None, changed=args.changed, use_baseline=not args.no_baseline, rules=rules)
    if args.format == "json":
        print(format_json(report))
    else:
        print(format_text(report))
    return report.exit_code


def cmd_explain(args) -> int:
    from .rules import all_rules
    rules = {r.id: r for r in all_rules()}
    if args.rule == "kinds":
        cfg = _cfg(args)
        for kind, spec in cfg.kinds.items():
            req = [a for a, r in spec["anchors"] if r]
            opt = [a for a, r in spec["anchors"] if not r]
            fm = spec.get("frontmatter") or []
            print(f"{kind}: required {req}; optional {opt}" + (f"; front matter {fm}" if fm else ""))
        return 0
    if args.rule == "all":
        for r in rules.values():
            print(f"{r.id}  {r.severity:7} {r.title}")
        return 0
    r = rules.get(args.rule.upper())
    if r is None:
        print(f"unknown rule {args.rule}; `librari explain all` lists them", file=sys.stderr)
        return 2
    print(f"{r.id} ({r.tier}, {r.severity}): {r.title}\n\n{r.explain}")
    return 0


def cmd_section(args) -> int:
    from . import sections
    cfg = _cfg(args)
    return sections.cli(cfg, args)


def cmd_changelog(args) -> int:
    from .changelog import add_row
    cfg = _cfg(args)
    return add_row(cfg, args.page, args.type, args.summary, args.date)


def cmd_new(args) -> int:
    from .scaffold import new_page
    cfg = _cfg(args)
    return new_page(cfg, args.slug, args.kind, args.title, args.group, args.description, args.keywords)


def cmd_templates(args) -> int:
    from .scaffold import export_templates
    return export_templates(_cfg(args))


def cmd_nav(args) -> int:
    from .scaffold import nav_add
    cfg = _cfg(args)
    return nav_add(cfg, args.group, args.slug)


def cmd_owner(args) -> int:
    from .index import owner
    cfg = _cfg(args)
    for score, slug, title in owner(cfg, " ".join(args.query), args.limit):
        print(f"{score:5.1f}  {slug}  — {title}")
    return 0


def cmd_pages_for(args) -> int:
    from .index import pages_for
    cfg = _cfg(args)
    hits = pages_for(cfg, args.path)
    for slug, entry in hits:
        print(f"{slug}  ({entry})")
    return 0 if hits else 1


def cmd_search(args) -> int:
    from .search import cli as search_cli
    return search_cli(_cfg(args), args.query, args.limit, args.kind or "", args.format)


def cmd_index(args) -> int:
    from .index import build_index, write_index
    cfg = _cfg(args)
    data = build_index(cfg)
    if args.write:
        out = write_index(cfg, data)
        print(f"wrote {out} ({len(data['pages'])} pages)")
    else:
        import json
        print(json.dumps(data, indent=2, ensure_ascii=False))
    return 0


def cmd_baseline(args) -> int:
    """Migration aid: write the CURRENT error findings of the given rules into
    librari-baseline.json. The file only shrinks afterwards (B001)."""
    import json
    from .check import BASELINE_NAME, load_baseline, run
    cfg = _cfg(args)
    rules = set(r.strip().upper() for r in args.rules.split(","))
    report = run(cfg, use_baseline=False)
    base = load_baseline(cfg)
    added = 0
    for f in report.findings:
        if f.rule in rules and f.severity == "error" and f.path != "librari.json":
            if f.path not in base.setdefault(f.rule, []):
                base[f.rule].append(f.path); added += 1
    base = {k: sorted(set(v)) for k, v in sorted(base.items()) if v}
    (cfg.root / BASELINE_NAME).write_text(json.dumps(base, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"baseline: +{added} entries → " + ", ".join(f"{k}:{len(v)}" for k, v in base.items()))
    return 0


def cmd_diff(args) -> int:
    from .diff import cli as diff_cli
    return diff_cli(_cfg(args), args.paths, args.changed, args.base, args.format)


def cmd_verify(args) -> int:
    from .verify import cli as verify_cli
    return verify_cli(_cfg(args), args.page, args.run, args.timeout)


def cmd_score(args) -> int:
    from .score import cli as score_cli
    return score_cli(_cfg(args), args.format, args.verbose)


def cmd_mcp(args) -> int:
    from .mcp_server import serve
    return serve(_cfg(args))


def cmd_fix(args) -> int:
    from .fix import cli as fix_cli
    return fix_cli(_cfg(args), args.full_paths, args.backlinks, args.lead, args.fences, args.changelog)


def cmd_render(args) -> int:
    from .render import cli as render_cli
    return render_cli(_cfg(args), args.out, args.base_path, not args.no_cdn, args.strict)


def cmd_serve(args) -> int:
    from .render import serve
    return serve(_cfg(args), args.out, args.port, args.base_path, not args.no_cdn, args.watch)


def cmd_fmt(args) -> int:
    from .fmt import cli as fmt_cli
    cfg = _cfg(args)
    return fmt_cli(cfg, args.paths, args.check)


def cmd_convert(args) -> int:
    from .convert import cli as convert_cli
    cfg = _cfg(args)
    return convert_cli(cfg, args.sources, args.out, args.group, args.dry_run, args.force)


def cmd_merge_driver(args) -> int:
    from .merge import cli as merge_cli
    return merge_cli(args)                      # no kb config needed: works on the 3 temp files git hands over


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="librari", description=__doc__)
    p.add_argument("--version", action="version", version=f"librari {__version__}")
    p.add_argument("--kb", help="kb root (directory holding librari.json); default: search upward")
    sub = p.add_subparsers(dest="cmd", required=True)

    s = sub.add_parser("check", help="validate pages (syntax → contract → semantics)")
    s.add_argument("paths", nargs="*", help="pages to check; default: whole kb")
    s.add_argument("--changed", action="store_true", help="only pages changed vs the merge-base (incl. uncommitted)")
    s.add_argument("--format", choices=["text", "json"], default="text")
    s.add_argument("--rule", action="append", help="run only this rule id (repeatable)")
    s.add_argument("--no-baseline", action="store_true", help="ignore librari-baseline.json")
    s.set_defaults(func=cmd_check)

    s = sub.add_parser("explain", help="print a rule's text; `all` lists rules, `kinds` the kind contracts")
    s.add_argument("rule")
    s.set_defaults(func=cmd_explain)

    s = sub.add_parser("section", help="read or edit one section of a page by its agent:<anchor>")
    ss = s.add_subparsers(dest="action", required=True)
    a = ss.add_parser("list", help="anchors with line ranges"); a.add_argument("page")
    a = ss.add_parser("get", help="print a section body"); a.add_argument("page"); a.add_argument("anchor")
    a.add_argument("--with-heading", action="store_true")
    a = ss.add_parser("set", help="replace a section body (stdin or --from)")
    a.add_argument("page"); a.add_argument("anchor")
    a.add_argument("--from", dest="src", help="file holding the new body; default stdin")
    a.add_argument("--create", action="store_true", help="insert the section if missing (canonical position)")
    a.add_argument("--heading", help="heading text when creating")
    a.add_argument("--allow-drop", action="store_true", help="allow removing code blocks / identifiers")
    a.add_argument("--no-check", action="store_true", help="write even if the result is RED")
    a = ss.add_parser("move", help="move a section before/after another one")
    a.add_argument("page"); a.add_argument("anchor")
    g = a.add_mutually_exclusive_group(required=True)
    g.add_argument("--before"); g.add_argument("--after")
    a.add_argument("--no-check", action="store_true")
    a = ss.add_parser("reorder", help="put canonical sections into template order (content untouched)")
    a.add_argument("page"); a.add_argument("--no-check", action="store_true")
    a = ss.add_parser("dedupe", help="rename duplicate anchors to <anchor>-2, -3 …")
    a.add_argument("page"); a.add_argument("--no-check", action="store_true")
    a = ss.add_parser("append", help="append text to a section body (stdin or --from)")
    a.add_argument("page"); a.add_argument("anchor"); a.add_argument("--from", dest="src")
    a.add_argument("--no-check", action="store_true")
    s.set_defaults(func=cmd_section)

    s = sub.add_parser("changelog", help="append a Changelog row")
    ss = s.add_subparsers(dest="action", required=True)
    a = ss.add_parser("add"); a.add_argument("page"); a.add_argument("type"); a.add_argument("summary")
    a.add_argument("--date", help="YYYY-MM-DD, default today")
    s.set_defaults(func=cmd_changelog)

    s = sub.add_parser("new", help="scaffold a page from its kind template and register it in the nav")
    s.add_argument("slug", help="group/slug (no extension)")
    s.add_argument("--kind", default="topic"); s.add_argument("--title", required=True)
    s.add_argument("--group", required=True, help="nav group name"); s.add_argument("--description", default="")
    s.add_argument("--keywords", default="", help="comma-separated")
    s.set_defaults(func=cmd_new)

    s = sub.add_parser("templates", help="templates maintenance")
    ss = s.add_subparsers(dest="action", required=True)
    ss.add_parser("export", help="copy the packaged kind templates into <kb>/_templates/ to customise them")
    s.set_defaults(func=cmd_templates)

    s = sub.add_parser("nav", help="nav maintenance")
    ss = s.add_subparsers(dest="action", required=True)
    a = ss.add_parser("add"); a.add_argument("group"); a.add_argument("slug")
    s.set_defaults(func=cmd_nav)

    s = sub.add_parser("owner", help="rank pages that own a topic (title, keywords, description, anchors)")
    s.add_argument("query", nargs="+"); s.add_argument("--limit", type=int, default=5)
    s.set_defaults(func=cmd_owner)

    s = sub.add_parser("pages-for", help="pages whose Key files table lists this repo path")
    s.add_argument("path")
    s.set_defaults(func=cmd_pages_for)

    s = sub.add_parser("search", help="full-text search over every section (FTS5/bm25); prints slug#agent:anchor + snippet")
    s.add_argument("query", nargs="+"); s.add_argument("--limit", type=int, default=10)
    s.add_argument("--kind", default="", help="only pages of this kind (topic|runbook|incident|roadmap|reference)")
    s.add_argument("--format", choices=["text", "json"], default="text")
    s.set_defaults(func=cmd_search)

    s = sub.add_parser("index", help="machine-readable page index (title, description, keywords, anchors, key files)")
    s.add_argument("--write", action="store_true", help="write <kb>/index.json instead of printing")
    s.set_defaults(func=cmd_index)

    s = sub.add_parser("baseline", help="migration aid: record current errors of given rules as legacy debt")
    ss = s.add_subparsers(dest="action", required=True)
    a = ss.add_parser("write"); a.add_argument("--rules", required=True, help="comma-separated rule ids")
    s.set_defaults(func=cmd_baseline)

    s = sub.add_parser("diff", help="per-section semantic diff vs git (HEAD, --base REF, or the merge-base with --changed)")
    s.add_argument("paths", nargs="*"); s.add_argument("--changed", action="store_true")
    s.add_argument("--base", help="git ref to diff against")
    s.add_argument("--format", choices=["text", "md", "json"], default="text")
    s.set_defaults(func=cmd_diff)

    s = sub.add_parser("verify", help="list (or --run) the ```bash verify blocks of a page")
    s.add_argument("page"); s.add_argument("--run", action="store_true")
    s.add_argument("--timeout", type=int, default=60)
    s.set_defaults(func=cmd_verify)

    s = sub.add_parser("score", help="agent-readiness score of the kb, 0–100 (metric only, always exit 0): "
                                     "entry page, retrievability, verifiability, freshness, contract")
    s.add_argument("--format", choices=["table", "plain", "json"], default="table")
    s.add_argument("--verbose", action="store_true", help="list every offending page, not the first three")
    s.set_defaults(func=cmd_score)

    s = sub.add_parser("mcp", help="serve the librari tools over MCP (stdio)")
    s.set_defaults(func=cmd_mcp)

    s = sub.add_parser("fix", help="deterministic autofixes: --paths (M010) --backlinks (M008) --lead (C005) --fences (S008)")
    s.add_argument("--paths", dest="full_paths", action="store_true"); s.add_argument("--backlinks", action="store_true")
    s.add_argument("--lead", action="store_true"); s.add_argument("--fences", action="store_true")
    s.add_argument("--changelog", action="store_true", help="append a `docs` Changelog row to every page touched")
    s.set_defaults(func=cmd_fix)

    s = sub.add_parser("render", help="build the kb as a static site (default: <repo>/site)")
    s.add_argument("--out"); s.add_argument("--base-path", default="/", help="URL prefix when hosted under a sub-path")
    s.add_argument("--no-cdn", action="store_true", help="no Mermaid from the CDN (diagrams stay as code)")
    s.add_argument("--strict", action="store_true", help="exit 1 when a link has no page on this site")
    s.set_defaults(func=cmd_render)

    s = sub.add_parser("serve", help="render, then serve the site locally")
    s.add_argument("--out"); s.add_argument("--port", type=int, default=8090); s.add_argument("--base-path", default="/")
    s.add_argument("--no-cdn", action="store_true")
    s.add_argument("--no-watch", dest="watch", action="store_false", help="do not rebuild when kb/ changes")
    s.set_defaults(func=cmd_serve)

    s = sub.add_parser("fmt", help="canonical formatting (idempotent); --check reports without writing")
    s.add_argument("paths", nargs="*"); s.add_argument("--check", action="store_true")
    s.set_defaults(func=cmd_fmt)

    s = sub.add_parser("convert", help="convert Mintlify .mdx pages into kb pages")
    s.add_argument("sources", nargs="+", help=".mdx files")
    s.add_argument("--out", help="kb-relative output dir; default: mirror the docs/ path")
    s.add_argument("--group", help="nav group to register the page in")
    s.add_argument("--dry-run", action="store_true")
    s.add_argument("--force", action="store_true", help="overwrite an existing kb page")
    s.set_defaults(func=cmd_convert)

    s = sub.add_parser("merge-driver", help="git merge driver for kb pages: 3-way merge, then union conflicting "
                                            "Changelog rows (git config merge.librari.driver, see merge.py)")
    s.add_argument("base", help="%%O — common ancestor"); s.add_argument("ours", help="%%A — current side, receives the result")
    s.add_argument("theirs", help="%%B — other side"); s.add_argument("path", nargs="?", default="", help="%%P — pathname")
    s.set_defaults(func=cmd_merge_driver)
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        return int(args.func(args) or 0)
    except FileNotFoundError as e:
        print(f"librari: {e}", file=sys.stderr)
        return 2
    except BrokenPipeError:          # `librari … | head` — not an error
        try:
            sys.stdout.close()
        except Exception:
            pass
        return 0


if __name__ == "__main__":
    sys.exit(main())
