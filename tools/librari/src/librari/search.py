"""`librari search <query>` — full-text search over every section of every kb page,
and `read_page` — the whole page (or one section) as Markdown.

`owner` ranks PAGES by front matter, slug, lead and headings; it cannot see body
text. `search` ranks SECTIONS with SQLite FTS5 (bm25, Porter-stemmed) over the body
too, so an agent that needs "where is the 502 / stale DNS gotcha" gets
`calendar/radicale#agent:gotchas` plus a snippet and line range instead of grepping
the whole tree.

Rows: the lead (front matter → first heading), every anchored section, and every
un-anchored H2 region (ref `slug#<heading-slug>`, the dialect the renderer emits) —
before 2026-09-23 those regions (11.9k lines on 92 pages) were invisible. Lines of
an anchored section nested inside a region are indexed once, under the section.

The index is built in memory from the parsed pages (no file on disk, nothing to
keep in sync); the MCP server keeps it between calls and rebuilds it when a page
changed on disk (mtime stamp, like `librari serve`).
"""
from __future__ import annotations

import json
import re
import sqlite3

from .config import KbConfig
from .model import slug_of_heading
from .parse import parse_file

WORD_RE = re.compile(r"\w[\w.:/-]*\w|\w", re.UNICODE)     # Unicode: `Postfächer` is one word
_COMMENT_RE = re.compile(r"<!--.*?-->", re.S)
_DIRECTIVE_RE = re.compile(r"^:{3,}\s*(\w+)?.*$")
_TABLE_SEP_RE = re.compile(r"^\|?\s*:?-{2,}:?\s*(\|\s*:?-{2,}:?\s*)*\|?$")
# Query words that carry no signal in a kb of this shape; dropped unless the query is nothing else.
STOPWORDS = frozenset("""a an the and or of to in on at for by with from as is are was were be been do does did
why how what when where which who whom this that these those it its into than then there here not no can
should would could will i we you my our your me us page pages kb docs doc""".split())
# A Changelog row summarises a change and Related is a link list; the section they
# point at is the answer. Rows in those sections (anchored or not) carry half weight.
PENALISED = {"changelog", "related"}
PENALTY = 0.5
TOKENIZER = "porter unicode61 remove_diacritics 2"

# FTS5 columns, in order: bm25() takes one weight per column in this order.
# Weight 0 = UNINDEXED (stored, filterable, never matched).
COLUMNS = ("slug", "anchor", "heading", "title", "keywords", "body", "kind", "description", "ref", "start", "end",
           "weight")
WEIGHTS = (0.0, 0.0, 3.0, 2.0, 2.0, 1.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0)
_BODY_COL = COLUMNS.index("body")
READ_PAGE_MAX_LINES = 400


def clean_body(lines: list[str]) -> str:
    """Section body as searchable text: anchor/HTML comments gone, directive
    markers reduced to their title, table separator rows dropped, code kept
    (identifiers are what agents search for)."""
    out = []
    for l in lines:
        l = _COMMENT_RE.sub("", l)
        m = _DIRECTIVE_RE.match(l.strip())
        if m:                                   # keep a step/accordion title, drop the directive name
            rest = l.strip().lstrip(":").strip()
            rest = rest[len(m.group(1)):].strip() if m.group(1) else rest
            if rest:
                out.append(rest)
            continue
        if l.strip() and not _TABLE_SEP_RE.match(l.strip()):
            out.append(l.rstrip())
    return "\n".join(out)


def _row_weight(anchor: str, heading: str) -> float:
    key = anchor or slug_of_heading(heading)
    return PENALTY if key in PENALISED else 1.0


def regions(page) -> list[tuple[str, str, int, int]]:
    """Un-anchored H2 regions as (heading, ref, start, end) — 0-based half-open body
    range, running to the next H1/H2."""
    top = [h for h in page.headings if h.level <= 2]
    out = []
    for i, h in enumerate(top):
        if h.level != 2 or h.anchor:
            continue
        end = top[i + 1].line if i + 1 < len(top) else len(page.lines)
        out.append((h.text, f"{page.slug}#{slug_of_heading(h.text)}", h.line + 1, end))
    return out


def rows_for(page) -> list[tuple]:
    """One row per region: the lead (anchor ''), every anchored section, and every
    H2 heading WITHOUT an anchor. Rows are (slug, anchor, heading, title, keywords,
    body, kind, description, ref, start, end, weight); start/end are 1-based inclusive."""
    fm = page.frontmatter or {}
    title = str(fm.get("title", "") or "")
    description = str(fm.get("description", "") or "")
    kw = fm.get("keywords", [])
    keywords = " ".join(str(k) for k in kw) if isinstance(kw, list) else ""
    kind = page.kind or ""
    slug = page.slug

    def row(anchor, heading, ref, start, end, lines=None):
        body = clean_body(lines if lines is not None else page.lines[start:end])
        return (slug, anchor, heading, title, keywords, body, kind, description, ref, start + 1, end,
                _row_weight(anchor, heading))

    rows = []
    first = page.first_heading_line()
    if clean_body(page.lines[page.frontmatter_end:first]).strip():
        rows.append(row("", title, slug, page.frontmatter_end, first))
    for s in page.sections:
        rows.append(row(s.anchor, s.heading.text, f"{slug}#agent:{s.anchor}", s.body_start, s.end))
    for heading, ref, start, end in regions(page):
        # an anchored H3 inside the region is its own row — index its lines once
        nested = [(s.start, s.end) for s in page.sections if start <= s.start < end]
        lines = [l for i, l in enumerate(page.lines[start:end], start)
                 if not any(a <= i < b for a, b in nested)]
        rows.append(row("", heading, ref, start, end, lines))
    return rows


def build_db(cfg: KbConfig) -> sqlite3.Connection:
    # check_same_thread=False: the MCP server calls sync tools from anyio worker
    # threads that are recycled after idling; every access is serialised by its lock.
    db = sqlite3.connect(":memory:", check_same_thread=False)
    cols = ", ".join(f"{c} UNINDEXED" if WEIGHTS[i] == 0 else c for i, c in enumerate(COLUMNS))
    db.execute(f"CREATE VIRTUAL TABLE sections USING fts5({cols}, tokenize='{TOKENIZER}')")
    rows = []
    for p in cfg.all_pages():
        rows.extend(rows_for(parse_file(p, cfg.root, cfg.settings["directives"])))
    db.executemany(f"INSERT INTO sections VALUES ({', '.join('?' * len(COLUMNS))})", rows)
    db.commit()
    return db


def _terms(query: str) -> list[str]:
    """Each query word becomes a quoted FTS5 string, so `nginx.conf`, `a-b` and
    operator words (AND, NOT, NEAR) are literal phrases, never syntax."""
    words = WORD_RE.findall(query)
    kept = [w for w in words if w.lower() not in STOPWORDS] or words
    return ['"' + t.replace('"', '""') + '"' for t in kept]


def query(db: sqlite3.Connection, text: str, limit: int = 10, kind: str = "") -> list[dict]:
    """Rank regions for `text`. All words must match first (AND); when nothing
    matches, any word (OR), so a long question still returns the closest sections.
    The half-weight penalty is applied inside the SQL, before the LIMIT."""
    terms = _terms(text)
    limit = max(int(limit), 1)
    if not terms:
        return []
    where = "sections MATCH ?" + (" AND kind = ?" if kind else "")
    params = [kind] if kind else []
    sql = (f"SELECT slug, anchor, heading, title, kind, description, ref, start, end, "
           f"bm25(sections, {', '.join(map(str, WEIGHTS))}) * weight AS score, "
           f"snippet(sections, {_BODY_COL}, '[', ']', '…', 24) AS snippet FROM sections WHERE {where} "
           f"ORDER BY score, slug, anchor, start LIMIT ?")
    for joiner in (" AND ", " OR "):
        cur = db.execute(sql, [joiner.join(terms), *params, limit])
        hits = [{"ref": r[6], "slug": r[0], "anchor": r[1], "heading": r[2], "title": r[3], "kind": r[4],
                 "description": r[5], "lines": [r[7], r[8]], "score": round(-r[9], 3),
                 "snippet": " ".join(r[10].split()), "match": joiner.strip().lower()}
                for r in cur.fetchall()]
        if hits or len(terms) == 1:
            return hits
    return []


def search(cfg: KbConfig, text: str, limit: int = 10, kind: str = "") -> list[dict]:
    return query(build_db(cfg), text, limit, kind)


def format_hits(hits: list[dict], fmt: str = "text") -> str:
    if fmt == "json":
        return json.dumps(hits, indent=2, ensure_ascii=False)
    if not hits:
        return "no match"
    lines = []
    for h in hits:
        a, b = h["lines"]
        lines.append(f"{h['score']:6.2f}  {h['ref']}  L{a}-{b}  — {h['heading']}"
                     + (f"  [{h['title']}]" if h["ref"] != h["slug"] else ""))
        if h["description"]:
            lines.append(f"        page: {h['description']}")
        if h["snippet"]:
            lines.append(f"        {h['snippet']}")
    if hits[0]["match"] == "or":
        lines.append("(no section matches every word — ranked by any word)")
    return "\n".join(lines)


def read_page(cfg: KbConfig, page: str, anchor: str = "", force: bool = False,
              max_lines: int = READ_PAGE_MAX_LINES) -> str:
    """The page as Markdown (front matter included), or one section with its heading.
    `anchor` is `agent:<x>` (or `<x>`) for an anchored section, or the heading slug
    search returns for an un-anchored H2 region. A page longer than `max_lines`
    returns its front matter plus a heading index instead of the body unless `force`
    — so a 1,400-line page never lands in an agent's context by accident."""
    from .sections import SectionError, _load, _section, _trim
    pg = _load(cfg, page)
    if anchor:
        try:
            sec = _section(pg, anchor)
            return "\n".join(_trim(pg.lines[sec.start:sec.end]))
        except SectionError as e:
            for _, ref, start, end in regions(pg):
                if ref.split("#", 1)[1] == anchor.removeprefix("agent:"):
                    return "\n".join(_trim(pg.lines[start - 1:end]))
            raise SectionError(f"{e}; un-anchored regions: "
                               + (", ".join(r[1].split('#', 1)[1] for r in regions(pg)) or "none"))
    if force or len(pg.lines) <= max_lines:
        return pg.text
    index = [f"  L{h.line + 1:<5} {'#' * h.level} {h.text}  <"
             + (f"agent:{h.anchor}" if h.anchor else (slug_of_heading(h.text) if h.level == 2 else "-")) + ">"
             for h in pg.headings if h.level <= 3]
    return ("\n".join(pg.lines[:pg.frontmatter_end])
            + f"\n\n[{pg.rel}: {len(pg.lines)} lines > {max_lines}; body withheld. Pass anchor=<…> from the index "
            f"below for one section or region, or force=True for the whole page.]\n\n" + "\n".join(index))


class LiveIndex:
    """A search DB that follows the kb on disk: rebuilt when any page's mtime
    changed since the last call. For the long-running MCP server."""

    def __init__(self, cfg: KbConfig):
        self.cfg = cfg
        self._stamp: tuple | None = None
        self._db: sqlite3.Connection | None = None

    def _current_stamp(self) -> tuple:
        out = []
        for p in [*self.cfg.all_pages(), self.cfg.config_path]:
            try:
                out.append((str(p), p.stat().st_mtime_ns))
            except FileNotFoundError:          # a page removed between listing and stat
                continue
        return tuple(sorted(out))

    def db(self) -> sqlite3.Connection:
        stamp = self._current_stamp()
        if self._db is None or stamp != self._stamp:
            self._db = build_db(self.cfg)
            self._stamp = stamp
        return self._db

    def search(self, text: str, limit: int = 10, kind: str = "") -> list[dict]:
        return query(self.db(), text, limit, kind)


def cli(cfg: KbConfig, words: list[str], limit: int, kind: str, fmt: str) -> int:
    hits = search(cfg, " ".join(words), limit, kind)
    print(format_hits(hits, fmt))
    return 0 if hits else 1
