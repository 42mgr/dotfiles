"""C-tier: the page template contract — front matter, sections, tables, changelog."""
from __future__ import annotations

import re

from ..config import CANONICAL_ANCHORS, DEFAULT_SETTINGS
from ..model import Finding, Page
from ..parse import parse_text
from ..tables import DATE_RE, changelog_table, code_spans, key_files_table
from . import Ctx, finding, rule


def _fm(page: Page) -> dict:
    return page.frontmatter if isinstance(page.frontmatter, dict) else {}


@rule("C001", "contract", "error", "front matter fields", """
Required keys: `title` (string), `description` (one sentence), `keywords`
(non-empty list of strings), `kind` (one of the kinds in librari.json —
topic | runbook | incident | roadmap | reference). `kind: roadmap` also needs
`status: open | executed | dropped`.
""")
def fm_fields(page: Page, ctx: Ctx) -> list[Finding]:
    if page.frontmatter is None:
        return []  # S001 already fired
    fm, out = _fm(page), []
    for key in ("title", "description"):
        v = fm.get(key)
        if not isinstance(v, str) or not v.strip():
            out.append(finding("C001", page, 0, f"front matter `{key}` missing or empty"))
    kw = fm.get("keywords")
    if not isinstance(kw, list) or not kw or not all(isinstance(k, str) and k.strip() for k in kw):
        out.append(finding("C001", page, 0, "front matter `keywords` must be a non-empty list of strings"))
    kind = fm.get("kind")
    kinds = ctx.cfg.kinds
    if not isinstance(kind, str) or kind not in kinds:
        out.append(finding("C001", page, 0,
                           f"front matter `kind` missing or unknown ({kind!r})",
                           "one of: " + ", ".join(sorted(kinds))))
        return out
    for key in ctx.cfg.required_frontmatter(kind):
        if key not in fm:
            out.append(finding("C001", page, 0, f"kind `{kind}` requires front matter `{key}`"))
    if kind == "roadmap" and "status" in fm and fm["status"] not in ctx.cfg.settings["roadmapStatuses"]:
        out.append(finding("C001", page, 0, f"`status` must be one of {ctx.cfg.settings['roadmapStatuses']}"))
    return out


@rule("C002", "contract", "error", "required section missing", """
Each kind has required sections, identified by their anchor (not the heading
text). A topic page needs at least Key files (agent:key-files), How to detect /
verify (agent:verify) and Changelog (agent:changelog). `librari explain kinds`
lists every kind's contract; `librari section set --create` inserts a missing
section at its canonical position.
""")
def required_sections(page: Page, ctx: Ctx) -> list[Finding]:
    kind = page.kind
    if kind not in ctx.cfg.kinds:
        return []
    have = set(page.anchors)
    return [finding("C002", page, None, f"kind `{kind}` requires section `agent:{a}`",
                    f"librari section set {page.rel} {a} --create --from <file>")
            for a, req in ctx.cfg.kind_anchors(kind) if req and a not in have]


@rule("C003", "contract", "error", "canonical sections out of order", """
The canonical sections keep the template order when present:
decision → key-files → how → config → gotchas → verify → changelog → related.
Page-specific anchors (agent:runbook-add …) may sit anywhere.
""")
def section_order(page: Page, ctx: Ctx) -> list[Finding]:
    present = [s for s in page.sections if s.anchor in CANONICAL_ANCHORS]
    order = [CANONICAL_ANCHORS.index(s.anchor) for s in present]
    out = []
    for i in range(1, len(order)):
        if order[i] < max(order[:i]):
            out.append(finding("C003", page, present[i].start,
                               f"`agent:{present[i].anchor}` comes after `agent:{present[i - 1].anchor}`",
                               "order: " + " → ".join(CANONICAL_ANCHORS)))
    return out


@rule("C004", "contract", "error", "duplicate anchor", """
An anchor identifies exactly one section; `librari section` refuses ambiguous pages.
""")
def duplicate_anchor(page: Page, ctx: Ctx) -> list[Finding]:
    seen, out = {}, []
    for s in page.sections:
        if s.anchor in seen:
            out.append(finding("C004", page, s.start, f"`agent:{s.anchor}` already used on line {seen[s.anchor] + 1}"))
        else:
            seen[s.anchor] = s.start
    return out


@rule("C005", "contract", "warning", "lead paragraph missing", """
The text between the front matter and the first heading is the lead: what the
page is, plus the concrete identifiers an agent needs (container, path, entry
point). Without it the page has no summary for the index and for `librari owner`.
""")
def lead(page: Page, ctx: Ctx) -> list[Finding]:
    if page.frontmatter is None:
        return []
    body = "".join(page.lines[page.frontmatter_end:page.first_heading_line()]).strip()
    if not body or body.startswith("<!--") and not re.sub(r"<!--.*?-->", "", body, flags=re.S).strip():
        return [finding("C005", page, page.frontmatter_end, "no lead paragraph before the first heading")]
    return []


@rule("C006", "contract", "error", "Key files table", """
The Key files section holds a table keyed by paths: at least half of the
first-column cells are backticked repo paths (or page links). Header text is
free — `File | Role` is the template, `Mount | Purpose` is fine too.

    | File | Role |
    |------|------|
    | `myscripts/deploy.sh` | applies a green master push |
""")
def key_files(page: Page, ctx: Ctx) -> list[Finding]:
    sec = page.section("key-files")
    if sec is None:
        return []
    if key_files_table(page) is None:
        return [finding("C006", page, sec.start, "Key files section has no table keyed by paths (`| File | Role |`)")]
    return []


@rule("C013", "contract", "warning", "Key files row without a path", """
A row of the Key files table whose first cell is prose (`nginx meet server
block`) cannot be opened by an agent. Name the file (`nginx/nginx.conf`) and
put the description in the Role column.
""")
def key_files_rows(page: Page, ctx: Ctx) -> list[Finding]:
    t = key_files_table(page)
    if t is None:
        return []
    return [finding("C013", page, ln, "Key files row: first cell is not a backticked path or a link")
            for ln, cells in t[1] if not cells or not (code_spans(cells[0]) or "](" in cells[0])]


@rule("C007", "contract", "error", "Changelog table", """
The Changelog section holds a table `| Date | Type | Summary |` with at least
one row. Date is ISO (YYYY-MM-DD); Type is one of the changelogTypes in
librari.json (feat fix lesson config refactor docs). Add rows with
`librari changelog add <page> <type> "<summary>"`.
""")
def changelog(page: Page, ctx: Ctx) -> list[Finding]:
    sec = page.section("changelog")
    if sec is None:
        return []
    t = changelog_table(page)
    if t is None:
        return [finding("C007", page, sec.start, "Changelog section has no `| Date | Type | Summary |` table")]
    hl, rows = t
    if not rows:
        return [finding("C007", page, hl, "Changelog table has no rows")]
    types, out = ctx.cfg.settings["changelogTypes"], []
    for ln, cells in rows:
        if len(cells) < 3:
            out.append(finding("C007", page, ln, "Changelog row needs Date | Type | Summary"))
            continue
        if not DATE_RE.match(cells[0]):
            out.append(finding("C007", page, ln, f"Changelog date `{cells[0]}` is not YYYY-MM-DD"))
        if cells[1] not in types:
            out.append(finding("C007", page, ln, f"Changelog type `{cells[1]}` not in {types}"))
        if not cells[2].strip():
            out.append(finding("C007", page, ln, "Changelog summary is empty"))
    return out


@rule("C008", "contract", "warning", "Changelog rows out of date order", """
Rows are appended, so dates never decrease down the table.
""")
def changelog_order(page: Page, ctx: Ctx) -> list[Finding]:
    t = changelog_table(page)
    if t is None:
        return []
    out, prev = [], ""
    for ln, cells in t[1]:
        if cells and DATE_RE.match(cells[0]):
            if cells[0] < prev:
                out.append(finding("C008", page, ln, f"date {cells[0]} is earlier than the row above ({prev})"))
            prev = cells[0]
    return out


def _rows_text(page: Page) -> list[str]:
    t = changelog_table(page)
    return ["|".join(c.strip() for c in cells) for _, cells in t[1]] if t else []


def _body_sans_changelog(page: Page) -> str:
    """Body text with the changelog section removed, fmt-normalised so that a
    `librari fmt` pass alone never counts as a content change."""
    from ..fmt import format_text
    try:
        page = parse_text(format_text(page.text, DEFAULT_SETTINGS["directives"]), page.rel, page.path)
    except Exception:  # formatting must never break a check
        pass
    sec = page.section("changelog")
    keep = []
    for i, line in enumerate(page.lines):
        if i < page.frontmatter_end:
            continue
        if sec and sec.start <= i < sec.end:
            continue
        keep.append(line.rstrip())
    return re.sub(r"\n{2,}", "\n", "\n".join(keep)).strip()


def _head_page(page: Page, ctx: Ctx) -> Page | None:
    head = ctx.head(page)
    return parse_text(head, page.rel, page.path, ctx.cfg.settings["directives"]) if head is not None else None


@rule("C009", "contract", "error", "Changelog is append-only", """
Existing Changelog rows are never edited or deleted; the rows committed at HEAD
must still be there, unchanged and in the same order. Append a new row instead.
""")
def changelog_append_only(page: Page, ctx: Ctx) -> list[Finding]:
    hp = _head_page(page, ctx)
    if hp is None or hp.section("changelog") is None:
        return []
    old, new = _rows_text(hp), _rows_text(page)
    if new[: len(old)] != old:
        sec = page.section("changelog")
        return [finding("C009", page, sec.start if sec else None,
                        "Changelog rows present at HEAD were edited, removed or reordered",
                        "restore them and append a new row for this change")]
    return []


@rule("C010", "contract", "error", "changed page without a new Changelog row", """
A page whose body changed since HEAD needs a new Changelog row describing the
change (`librari changelog add <page> <type> "<summary>"`). Whitespace-only
changes are ignored.
""")
def changelog_row_required(page: Page, ctx: Ctx) -> list[Finding]:
    if page.section("changelog") is None:
        return []
    hp = _head_page(page, ctx)
    if hp is None:
        return []  # new page: C007 demands at least one row
    if _body_sans_changelog(hp) == _body_sans_changelog(page):
        return []
    if len(_rows_text(page)) > len(_rows_text(hp)):
        return []
    return [finding("C010", page, page.section("changelog").start,
                    "page body changed since HEAD but no Changelog row was added",
                    f'librari changelog add {page.rel} <type> "<summary>"')]


@rule("C011", "contract", "warning", "page too long", """
Very long pages are read whole by agents and rarely fit one topic. Split by
topic and cross-link, or move runbook parts to their own page.
""")
def page_length(page: Page, ctx: Ctx) -> list[Finding]:
    mx = int(ctx.cfg.settings["maxLines"])
    n = len(page.lines)
    return [finding("C011", page, None, f"{n} lines (limit {mx}) — consider splitting")] if n > mx else []


@rule("C012", "contract", "warning", "heading levels", """
The title comes from the front matter, so the body has no `#` H1; canonical
sections are `##` H2 headings.
""")
def heading_levels(page: Page, ctx: Ctx) -> list[Finding]:
    out = [finding("C012", page, h.line, "H1 in the body — the title lives in the front matter")
           for h in page.headings if h.level == 1]
    out += [finding("C012", page, s.start, f"canonical section `agent:{s.anchor}` should be an H2 heading")
            for s in page.sections if s.anchor in CANONICAL_ANCHORS and s.heading.level != 2]
    return out
