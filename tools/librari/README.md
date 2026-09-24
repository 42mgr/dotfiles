# librari

Contract validator, section-level edit API and formatter for the agent-facing
knowledge base in `kb/`. Format: [FORMAT.md](FORMAT.md). Design record:
`kb/roadmap/librari.md`.

```bash
uv run --project tools/librari librari --kb kb <command>      # from the repo root
```

| Command | What it does |
|---|---|
| `check [pages] [--changed] [--format json] [--rule ID]` | validate: syntax → contract → semantics. Exit 0 GREEN / 1 RED / 2 NO-VERDICT |
| `explain <rule> \| all \| kinds` | rule text with a fix example; the hook points agents here |
| `section list\|get\|set\|append\|move\|reorder\|dedupe` | edit one section by `agent:<anchor>`; `set` refuses dropped code blocks / identifiers (`--allow-drop`) and edits that add errors (`--no-check`); `reorder` puts canonical sections in template order; `dedupe` renames duplicate anchors to `-2`, `-3` |
| `changelog add <page> <type> "<summary>"` | append a dated row |
| `new <group/slug> --kind K --title T --group G` | scaffold from `kb/_templates/<kind>.md` and register in the nav |
| `nav add <group> <slug>` | register an existing page |
| `search <query> [--limit N] [--kind K] [--format text\|json]` | full-text search over every region of every page — lead, anchored sections AND un-anchored H2 regions (SQLite FTS5, Porter-stemmed, bm25 on heading/title/keywords/body incl. code): `slug#anchor`, `L<start>-<end>`, page description, snippet; stopwords dropped, all words first, any word as fallback (stated); Changelog and Related rows at half weight. Exit 1 = no match |
| `owner <query>` | which page owns a topic (deterministic scoring over keywords/title/slug/lead/headings) |
| `pages-for <repo path>` | pages whose Key files list that path |
| `index [--write]` | machine-readable page index |
| `fmt [pages] [--check]` | canonical formatting, idempotent |
| `templates export` | copy the packaged kind templates to `kb/_templates/` for local overrides |
| `baseline write --rules A,B` | migration aid: record the current errors of those rules as legacy debt (the file only shrinks afterwards) |
| `diff [pages] [--changed] [--base REF] [--format text\|md\|json]` | per-section semantic diff vs git: status, lines, bullets, code blocks added/dropped, identifiers dropped, changelog rows added; exit 1 when detail was dropped |
| `verify <page> [--run]` | list (or run, with a destructive-pattern denylist) the page's ```` ```bash verify ```` blocks |
| `score [--format table\|plain\|json] [--verbose]` | agent-readiness score 0–100 (after `mint score`): entry page exists / has a task table / links resolve / fits one read / reaches every nav page in 2 hops; per-page description ≥ 8 words, ≥ 3 useful keywords, lead present, page and every section ≤ 400 lines; verify sections carry code / a runnable ```` ```bash verify ````; Changelog fresh (180 d); `check` GREEN; baseline empty; librari in `.mcp.json`. Weighted; a failed parent skips its children. Metric only: always exit 0 |
| `mcp` | the same operations as MCP tools over stdio (registered in the repo's `.mcp.json`), plus `search` and `read_page(page, anchor, force)` for reading — one section, or the whole page; a page over 400 lines returns front matter + heading index unless `force` |
| `render [--out DIR] [--base-path /p] [--no-cdn]` | static site: `<slug>/index.html` per page, nav sidebar, page TOC, `#agent:x` deep links, callouts/steps/cards/accordions, Pygments highlighting, Mermaid (CDN), client-side search (`search.json`) |
| `serve [--port 8090] [--no-watch]` | render, serve on 127.0.0.1, rebuild when `kb/` changes (like `mint dev`; reach it with `ssh -L 8090:127.0.0.1:8090 <host>`) |
| `fix --paths --backlinks --lead --fences [--changelog]` | deterministic autofixes: M010 full paths, M008 reverse links (bullet = the linking page's description), C005 lead from the description, S008 indented blocks (dedent inside a directive, fence elsewhere) |
| `convert <docs/*.mdx> [--force]` | Mintlify page → kb page (+ nav), normalises changelog types and bare fences, then checks it; refuses to overwrite |
| `merge-driver %O %A %B %P` | git merge driver for `kb/**/*.md` (`.gitattributes`): 3-way merge, then the union of both branches' Changelog rows where they collided on the table's last line; any other conflict stays marked (exit 1). Register once per clone: `git config merge.librari.driver "uv run --project tools/librari librari merge-driver %O %A %B %P"` |

Config: `kb/librari.json` (kinds, nav groups, changelog types, limits,
`legacyDocsDir`). Baseline: `kb/librari-baseline.json` — `{rule: [pages]}`,
shrink-only (a stale entry is an error, B001).

Hooks (`.claude/settings.json`, PostToolUse Edit|Write):
`librari-check.py` blocks (exit 2) on a RED kb page; `librari-pages-for.py`
reminds when an edited repo file is listed in some page's Key files.

Tests: `uv run --project tools/librari pytest`.
