"""`librari score` — how ready the kb is for coding agents, as one number.

Modelled on Mintlify's `mint score` (agent-readiness checks over a public docs
site: llms.txt present/valid/sized, links resolve, skill.md, MCP discoverable,
…), transposed to a repo-local kb that agents reach through `search` →
`read_page`. Every check yields a pass ratio in [0, 1] — binary checks 0 or 1,
per-page checks the share of pages that pass — and the score is the
weight-averaged ratio × 100. A check whose parent FAILS (ratio 0) is skipped
and counts 0, like Mintlify's dependent checks.

Metric only, by design: the command always exits 0; `check` stays the gate.
Thresholds live in `librari.json` → `settings.score` (see SCORE_DEFAULTS).
"""
from __future__ import annotations

import json
import re
from collections import deque
from dataclasses import dataclass, field
from datetime import date, timedelta

from .config import KbConfig
from .index import WORD_RE, lead_of
from .model import Page
from .parse import find_tables, parse_file
from .tables import DATE_RE, changelog_table

SCORE_DEFAULTS = {
    "entryPage": "index",        # the llms.txt of the kb: where an agent starts
    "readMaxLines": 400,         # read_page withholds a longer page/section body
    "descriptionMinWords": 8,    # a description shorter than this is a title, not a summary
    "keywordsMin": 3,
    "taskTableMinRows": 5,       # the "I need to…" table on the entry page
    "reachHops": 2,              # link hops from the entry page to any nav page
    "staleDays": 180,            # newest Changelog row older than this = stale
}


@dataclass
class Check:
    id: str
    weight: int
    title: str
    ratio: float | None = None       # None = skipped because the parent failed
    detail: str = ""
    offenders: list[str] = field(default_factory=list)
    depends: str | None = None

    @property
    def status(self) -> str:
        if self.ratio is None:
            return "SKIP"
        return "PASS" if self.ratio >= 1 else ("FAIL" if self.ratio <= 0 else "PART")

    def as_dict(self) -> dict:
        return {"id": self.id, "status": self.status, "weight": self.weight,
                "ratio": None if self.ratio is None else round(self.ratio, 4),
                "title": self.title, "detail": self.detail, "offenders": self.offenders,
                "depends": self.depends}


@dataclass
class ScoreReport:
    checks: list[Check]
    pages: int
    unreadable: list[str] = field(default_factory=list)

    @property
    def score(self) -> float:
        total = sum(c.weight for c in self.checks)
        got = sum(c.weight * (c.ratio or 0.0) for c in self.checks)
        return round(100.0 * got / total, 1) if total else 0.0

    def as_dict(self) -> dict:
        return {"score": self.score, "pages": self.pages, "unreadable": self.unreadable,
                "checks": [c.as_dict() for c in self.checks]}


def _tokens(s: str) -> set[str]:
    return {w.lower() for w in WORD_RE.findall(s or "")}


def _internal_links(page: Page) -> list[str]:
    """Slugs this page links to (root-relative internal links, fragment dropped)."""
    out = []
    for lk in page.links:
        if lk.is_image or re.match(r"^[a-z][a-z0-9+.-]*:", lk.href, re.I) or lk.href.startswith("//"):
            continue
        if lk.href.startswith("/"):
            path = lk.href.partition("#")[0].strip("/")
            out.append(path or "index")
    return out


def _ratio(passed: int, total: int) -> float:
    return 1.0 if total == 0 else passed / total


def _per_page(check: Check, pages: list[Page], predicate, noun: str = "page") -> Check:
    """Fill a per-page check: predicate(page) -> None when it passes, else the
    offender label."""
    bad = []
    for p in pages:
        label = predicate(p)
        if label:
            bad.append(label)
    check.ratio = _ratio(len(pages) - len(bad), len(pages))
    check.offenders = sorted(bad)
    check.detail = f"{len(pages) - len(bad)}/{len(pages)} {noun}s"
    return check


def run(cfg: KbConfig) -> ScoreReport:
    s = {**SCORE_DEFAULTS, **(cfg.settings.get("score") or {})}
    read_max = int(s["readMaxLines"])
    pages: list[Page] = []
    unreadable: list[str] = []
    for path in cfg.all_pages():
        try:
            pages.append(parse_file(path, cfg.root, cfg.settings["directives"]))
        except (OSError, UnicodeDecodeError, ValueError) as e:
            unreadable.append(f"{path}: {e}")
    by_slug = {p.slug: p for p in pages}
    checks: list[Check] = []

    # ── Entry point (the kb's llms.txt) ───────────────────────────────────────
    entry_slug = str(s["entryPage"])
    entry = by_slug.get(entry_slug)
    c = Check("entryExists", 3, f"an entry page `{entry_slug}` exists (the kb's llms.txt)")
    c.ratio = 1.0 if entry else 0.0
    c.detail = f"{entry_slug}.md" if entry else f"no page `{entry_slug}` — agents have no starting point"
    checks.append(c)

    c = Check("entryTaskTable", 3, "the entry page holds a task table (`I need to… | Start here`) with links",
              depends="entryExists")
    if entry:
        best = 0
        for _, header, rows in find_tables(entry.lines, entry.frontmatter_end, len(entry.lines)):
            linked = sum(1 for _, cells in rows if len(cells) >= 2 and "](" in cells[1])
            best = max(best, linked)
        need = int(s["taskTableMinRows"])
        c.ratio = 1.0 if best >= need else 0.0
        c.detail = f"largest linked table has {best} row(s), need {need}"
    checks.append(c)

    c = Check("entryLinksResolve", 3, "every internal link on the entry page resolves to a page",
              depends="entryExists")
    if entry:
        targets = _internal_links(entry)
        bad = sorted({t for t in targets if t not in by_slug})
        c.ratio = _ratio(len(targets) - len(bad), len(targets))
        c.offenders = bad
        c.detail = f"{len(targets) - len(bad)}/{len(targets)} links"
    checks.append(c)

    c = Check("entrySize", 2, f"the entry page fits one read_page call (≤ {read_max} lines)", depends="entryExists")
    if entry:
        c.ratio = 1.0 if len(entry.lines) <= read_max else 0.0
        c.detail = f"{len(entry.lines)} lines"
    checks.append(c)

    hops = int(s["reachHops"])
    c = Check("entryReach", 2, f"every nav page is reachable from the entry page within {hops} link hop(s)",
              depends="entryExists")
    if entry:
        seen = {entry_slug}
        frontier = deque([(entry_slug, 0)])
        while frontier:
            slug, d = frontier.popleft()
            if d >= hops:
                continue
            for t in _internal_links(by_slug[slug]) if slug in by_slug else []:
                if t in by_slug and t not in seen:
                    seen.add(t)
                    frontier.append((t, d + 1))
        nav = [p for p in cfg.nav_pages() if p in by_slug and p != entry_slug]
        bad = sorted(p for p in nav if p not in seen)
        c.ratio = _ratio(len(nav) - len(bad), len(nav))
        c.offenders = bad
        c.detail = f"{len(nav) - len(bad)}/{len(nav)} nav pages"
    checks.append(c)

    # ── Retrievability (search → read_page) ───────────────────────────────────
    min_words = int(s["descriptionMinWords"])

    def desc(p: Page):
        d = (p.frontmatter or {}).get("description")
        n = len(WORD_RE.findall(d)) if isinstance(d, str) else 0
        return None if n >= min_words else f"{p.slug} ({n} words)"
    checks.append(_per_page(Check("descriptionWords", 2, f"front-matter description has ≥ {min_words} words"),
                            pages, desc))

    kw_min = int(s["keywordsMin"])

    def kws(p: Page):
        fm = p.frontmatter or {}
        kw = fm.get("keywords") if isinstance(fm.get("keywords"), list) else []
        kw = [k for k in kw if isinstance(k, str)]
        if len(kw) < kw_min:
            return f"{p.slug} ({len(kw)} keywords)"
        extra = _tokens(" ".join(kw)) - _tokens(str(fm.get("title", ""))) - _tokens(p.slug.replace("/", " "))
        return None if extra else f"{p.slug} (keywords only repeat the title)"
    checks.append(_per_page(Check("keywordsUseful", 2,
                                  f"≥ {kw_min} keywords, at least one beyond the title/slug words"),
                            pages, kws))

    checks.append(_per_page(Check("leadPresent", 1, "a lead paragraph before the first heading"),
                            pages, lambda p: None if lead_of(p, 40).strip() else p.slug))

    checks.append(_per_page(Check("pageFitsRead", 1,
                                  f"whole page ≤ {read_max} lines (read_page returns it whole)"),
                            pages,
                            lambda p: None if len(p.lines) <= read_max else f"{p.slug} ({len(p.lines)} lines)"))

    def sections_fit(p: Page):
        big = [f"{p.slug}#agent:{sec.anchor} ({sec.end - sec.start} lines)"
               for sec in p.sections if sec.end - sec.start > read_max]
        return ", ".join(big) if big else None
    checks.append(_per_page(Check("sectionFitsRead", 2,
                                  f"every section ≤ {read_max} lines (one read_page(page, anchor))"),
                            pages, sections_fit))

    # ── Verifiability ────────────────────────────────────────────────────────
    with_verify = [p for p in pages if p.section("verify") is not None]

    def verify_code(p: Page):
        sec = p.section("verify")
        return None if any(sec.start <= cb.start < sec.end for cb in p.code_blocks) else p.slug
    c = _per_page(Check("verifyHasCode", 2, "the verify section carries at least one code block"),
                  with_verify, verify_code, noun="verify section")
    checks.append(c)

    def verify_runnable(p: Page):
        from .verify import DENY
        sec = p.section("verify")
        for cb in p.code_blocks:
            if sec.start <= cb.start < sec.end:
                info = p.lines[cb.start].strip().lstrip("`~").split()
                if len(info) >= 2 and info[0] in ("bash", "sh") and info[1] == "verify" and not DENY.search(cb.content):
                    return None
        return p.slug
    c = Check("verifyRunnable", 1, "the verify section has a runnable ```bash verify block (librari verify --run)",
              depends="verifyHasCode")
    if checks[-1].ratio:
        _per_page(c, [p for p in with_verify if verify_code(p) is None], verify_runnable, noun="verify section")
    checks.append(c)

    # ── Freshness ────────────────────────────────────────────────────────────
    stale_days = int(s["staleDays"])
    cutoff = date.today() - timedelta(days=stale_days)
    live = [p for p in pages if not (p.kind == "roadmap" and (p.frontmatter or {}).get("status") not in (None, "open"))]

    def fresh(p: Page):
        t = changelog_table(p)
        dates = sorted(c[0].strip() for _, c in (t[1] if t else []) if c and DATE_RE.match(c[0].strip()))
        if not dates:
            return f"{p.slug} (no dated row)"
        try:
            return None if date.fromisoformat(dates[-1]) >= cutoff else f"{p.slug} ({dates[-1]})"
        except ValueError:
            return f"{p.slug} (bad date {dates[-1]})"
    checks.append(_per_page(Check("changelogFresh", 1, f"newest Changelog row within {stale_days} days "
                                  "(executed/dropped roadmap pages exempt)"), live, fresh))

    # ── Contract & tooling ───────────────────────────────────────────────────
    from .check import load_baseline, run as check_run
    rep = check_run(cfg)
    c = Check("contractGreen", 3, "`librari check` is GREEN over the whole kb")
    c.ratio = 1.0 if rep.verdict == "GREEN" else 0.0
    c.detail = f"{rep.verdict}: {len(rep.errors)} error(s), {len(rep.warnings)} warning(s)"
    c.offenders = sorted({f"{f.path} {f.rule}" for f in rep.errors})
    checks.append(c)

    entries = sum(len(v) for v in load_baseline(cfg).values())
    c = Check("baselineEmpty", 1, "no legacy debt parked in librari-baseline.json")
    c.ratio = max(0.0, 1.0 - entries / len(pages)) if pages else 1.0
    c.detail = f"{entries} baselined finding(s) over {len(pages)} pages"
    checks.append(c)

    from .gitutil import repo_root
    repo = repo_root(cfg.root)
    c = Check("mcpRegistered", 1, "the repo's .mcp.json serves librari (search/read_page reach agents)")
    mcp = (repo / ".mcp.json") if repo else None
    ok = False
    if mcp and mcp.is_file():
        try:
            servers = json.loads(mcp.read_text(encoding="utf-8")).get("mcpServers") or {}
            ok = any("librari" in json.dumps(v) for v in servers.values())
        except (ValueError, AttributeError):
            ok = False
    c.ratio = 1.0 if ok else 0.0
    c.detail = str(mcp) if ok else ("no git repo above the kb" if not repo else "no librari server in .mcp.json")
    checks.append(c)

    # dependent checks: a failed parent skips its children
    by_id = {c.id: c for c in checks}
    for c in checks:
        if c.depends and (by_id[c.depends].ratio is None or by_id[c.depends].ratio <= 0):
            c.ratio = None
            c.detail = f"skipped — {c.depends} failed"
            c.offenders = []
    return ScoreReport(checks, len(pages), unreadable)


def format_table(rep: ScoreReport, verbose: bool = False) -> str:
    lines = [f"librari score: {rep.score:.0f}/100 — {rep.pages} page(s)", ""]
    w_id = max(len(c.id) for c in rep.checks)
    for c in rep.checks:
        r = "  -  " if c.ratio is None else f"{c.ratio:5.2f}"
        lines.append(f"{c.status:<4} {c.id:<{w_id}}  w{c.weight}  {r}  {c.detail}")
        if c.offenders:
            shown = c.offenders if verbose else c.offenders[:3]
            more = "" if verbose or len(c.offenders) <= 3 else f"  … +{len(c.offenders) - 3} more (--verbose)"
            lines.append(" " * (w_id + 18) + "↳ " + "; ".join(shown) + more)
    for u in rep.unreadable:
        lines.append(f"unreadable: {u}")
    lines.append("")
    lines.append("weights: PASS = ratio 1, PART = share of pages passing, FAIL = 0, SKIP = parent failed (counts 0)")
    return "\n".join(lines)


def format_plain(rep: ScoreReport) -> str:
    rows = [f"score\t{rep.score}\t{rep.pages}\t"]
    for c in rep.checks:
        rows.append(f"{c.id}\t{c.status}\t{c.weight}\t{'' if c.ratio is None else round(c.ratio, 4)}\t{c.detail}")
    return "\n".join(rows)


def format_json(rep: ScoreReport) -> str:
    return json.dumps(rep.as_dict(), indent=2, ensure_ascii=False)


def cli(cfg: KbConfig, fmt: str, verbose: bool) -> int:
    rep = run(cfg)
    print({"json": format_json, "plain": format_plain}.get(fmt, lambda r: format_table(r, verbose))(rep))
    return 0
