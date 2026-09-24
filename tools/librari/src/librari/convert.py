"""Convert Mintlify `.mdx` pages (docs/) into kb pages.

Handles exactly the component set the corpus uses: the six callouts,
Steps/Step, CardGroup|Columns/Card, AccordionGroup/Accordion, `{/* */}`
comments (anchors included). Anything else is left in place and the validator
reports it (S005). Colon counts for nested directives are computed from the
tree, so converted pages never hit the outer-first closing footgun.
"""
from __future__ import annotations

import json
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path

import yaml

from .config import KbConfig

CALLOUTS = {"Note": "note", "Info": "info", "Tip": "tip", "Warning": "warning",
            "Check": "check", "Danger": "danger"}
OPEN_RE = re.compile(r"^(\s*)<(Steps|Step|CardGroup|Columns|Card|AccordionGroup|Accordion|Note|Info|Tip|Warning|Check|Danger)\b((?:\"[^\"]*\"|'[^']*'|\{[^}]*\}|[^>\"'{])*?)(/?)>\s*(.*?)\s*$")
CLOSE_RE = re.compile(r"^(\s*)</(Steps|Step|CardGroup|Columns|Card|AccordionGroup|Accordion|Note|Info|Tip|Warning|Check|Danger)>\s*$")
ATTR_RE = re.compile(r"""(\w+)=(?:"([^"]*)"|'([^']*)'|\{([^}]*)\})""")
JSX_COMMENT_RE = re.compile(r"\{/\*(.*?)\*/\}", re.S)
FENCE_RE = re.compile(r"^\s*(`{3,}|~{3,})")

# Changelog types seen in the legacy corpus → the kb enum. Unknown types are
# left as they are (C007 reports them).
TYPE_MAP = {"feature": "feat", "done": "feat", "maintenance": "chore", "note": "docs", "found": "lesson",
            "verify": "docs", "prep": "chore", "ops": "config", "docs+feat": "feat", "fix+lesson": "fix",
            "fix-owed": "fix", "blocked": "decision"}

KIND_BY_DIR = {"incidents": "incident", "runbooks": "runbook", "roadmap": "roadmap",
               "reference": "reference", "decisions": "reference", "guides": "topic"}


@dataclass
class Node:
    tag: str                      # jsx tag name, "" for root
    attrs: dict[str, str]
    children: list = field(default_factory=list)   # str lines or Node

    def height(self) -> int:
        return 1 + max((c.height() for c in self.children if isinstance(c, Node) and c.tag != "Card"), default=-1)


def _attrs(s: str) -> dict[str, str]:
    return {m.group(1): next(g for g in m.groups()[1:] if g is not None) for m in ATTR_RE.finditer(s)}


def build_tree(lines: list[str]) -> tuple[Node, list[str]]:
    root, stack, notes = Node("", {}), [], []
    in_fence: str | None = None
    for i, line in enumerate(lines):
        cur = stack[-1] if stack else root
        m = FENCE_RE.match(line)
        if in_fence:
            cur.children.append(line)
            if m and m.group(1)[0] == in_fence and len(m.group(1)) >= 3:
                in_fence = None
            continue
        if m:
            in_fence = m.group(1)[0]
            cur.children.append(line)
            continue
        mo = OPEN_RE.match(line)
        if mo:
            node = Node(mo.group(2), _attrs(mo.group(3)))
            cur.children.append(node)
            rest = mo.group(5)
            if mo.group(4) == "/":                           # self-closing <Card … />
                if rest:
                    cur.children.append(rest)
                continue
            if rest.endswith(f"</{mo.group(2)}>"):          # one-line <Note>x</Note>
                node.children.append(rest[: -len(f"</{mo.group(2)}>")].strip())
            elif rest:
                node.children.append(rest)
                stack.append(node)
            else:
                stack.append(node)
            continue
        mc = CLOSE_RE.match(line)
        if mc:
            if stack and stack[-1].tag == mc.group(2):
                stack.pop()
            else:
                notes.append(f"line {i + 1}: unexpected </{mc.group(2)}>")
            continue
        cur.children.append(line)
    for n in stack:
        notes.append(f"unclosed <{n.tag}> left at end of page")
    return root, notes


def _dedent(lines: list[str]) -> list[str]:
    indents = [len(l) - len(l.lstrip(" ")) for l in lines if l.strip()]
    d = min(indents) if indents else 0
    return [l[d:] if l.strip() else "" for l in lines]


def render(node: Node, notes: list[str]) -> list[str]:
    # text lines of THIS node are dedented as a group; children render at column 0
    out: list[str] = []
    buf: list[str] = []

    def flush():
        nonlocal buf
        out.extend(_dedent(buf))
        buf = []

    for c in node.children:
        if isinstance(c, str):
            buf.append(c)
        else:
            flush()
            out.extend(render_node(c, notes))
    flush()
    return out


def _strip_blank_edges(lines: list[str]) -> list[str]:
    while lines and not lines[0].strip():
        lines.pop(0)
    while lines and not lines[-1].strip():
        lines.pop()
    return lines


def render_node(n: Node, notes: list[str]) -> list[str]:
    body = _strip_blank_edges(render(n, notes))
    colons = ":" * (3 + n.height())
    tag = n.tag
    if tag in CALLOUTS:
        return [f"{colons}{CALLOUTS[tag]}", *body, colons, ""]
    if tag == "Steps":
        return ["", f"{colons}steps", *body, colons, ""]
    if tag == "Step":
        title = n.attrs.get("title", "").strip()
        if not title:
            notes.append("<Step> without title")
        return [f"{colons}step {title}", *body, colons]
    if tag in ("CardGroup", "Columns"):
        return ["", f"{colons}cards", *body, colons, ""]
    if tag == "Card":
        title, href = n.attrs.get("title", "").strip(), n.attrs.get("href", "").strip()
        desc = " ".join(l.strip() for l in body if l.strip())
        if not title:
            title = href or "(untitled card)"
            notes.append("<Card> without title")
        head = f"[{title}]({href})" if href else f"**{title}**"
        return [f"- {head}" + (f" — {desc}" if desc else "")]
    if tag == "AccordionGroup":
        return ["", *body, ""]
    if tag == "Accordion":
        return [f"{colons}accordion {n.attrs.get('title', '').strip()}", *body, colons, ""]
    notes.append(f"unknown tag <{tag}> left as-is")
    return [f"<{tag}>", *body, f"</{tag}>"]


def _collapse_blank(lines: list[str]) -> list[str]:
    out, blank = [], False
    for l in lines:
        if l.strip():
            out.append(l)
            blank = False
        elif not blank:
            out.append("")
            blank = True
    return _strip_blank_edges(out)


def normalize_types(lines: list[str], notes: list[str]) -> list[str]:
    """Map legacy changelog Type values onto the kb enum (TYPE_MAP)."""
    from .parse import split_row
    from .tables import DATE_RE
    out, n = [], 0
    for l in lines:
        cells = split_row(l) if l.lstrip().startswith("|") else []
        if len(cells) >= 3 and DATE_RE.match(cells[0]) and cells[1] in TYPE_MAP:
            l = l.replace(f"| {cells[1]} |", f"| {TYPE_MAP[cells[1]]} |", 1); n += 1
        out.append(l)
    if n:
        notes.append(f"{n} changelog type(s) normalised (TYPE_MAP)")
    return out


def tag_bare_fences(lines: list[str], notes: list[str]) -> list[str]:
    """A ``` with no language becomes ```text (S002); closing fences untouched."""
    out, open_fence, n = [], False, 0
    for l in lines:
        m = re.match(r"^(\s*)(`{3,}|~{3,})\s*$", l)
        if m and not open_fence:
            l = f"{m.group(1)}{m.group(2)}text"; n += 1; open_fence = True
        elif re.match(r"^\s*(`{3,}|~{3,})", l):
            open_fence = not open_fence
        out.append(l)
    if n:
        notes.append(f"{n} bare code fence(s) tagged ```text — check the language")
    return out


BULLET_ROW_RE = re.compile(r"^- \*\*(\d{4}-\d{2}-\d{2})\*\*\s*[—–-]\s*(.*)$")


def tableize_changelog(lines: list[str], notes: list[str]) -> list[str]:
    """A Changelog written as `- **YYYY-MM-DD** — text` bullets becomes the
    contract's table. Type is taken from a leading `fix:`/`feat:`… prefix,
    else `docs`. Text is kept verbatim (pipes escaped)."""
    for i, l in enumerate(lines):
        if "agent:changelog" in l:
            break
    else:
        return lines
    j = i + 1
    while j < len(lines) and not lines[j].startswith("#"):
        if lines[j].lstrip().startswith("|"):
            return lines            # already a table
        if BULLET_ROW_RE.match(lines[j]):
            break
        j += 1
    else:
        return lines
    rows, k = [], j
    while k < len(lines) and not lines[k].startswith("#"):
        m = BULLET_ROW_RE.match(lines[k])
        if m:
            rows.append([m.group(1), m.group(2).strip()])
        elif lines[k].startswith("  ") and rows:
            rows[-1][1] += " " + lines[k].strip()
        elif lines[k].strip():
            break
        k += 1
    if not rows:
        return lines
    table = ["| Date | Type | Summary |", "|------|------|---------|"]
    for date, text in rows:
        t = "docs"
        mt = re.match(r"^(feat|fix|lesson|config|refactor|docs|incident|decision|chore|plan|infra|test|security|review)\b[:—–-]?\s*", text, re.I)
        if mt:
            t = mt.group(1).lower()
            text = text[mt.end():]
        table.append(f"| {date} | {t} | {text.replace('|', '\\|')} |")
    notes.append(f"changelog bullets → table ({len(rows)} rows)")
    return lines[:j] + table + lines[k:]


def _sort_changelog(lines: list[str], notes: list[str]) -> list[str]:
    """Changelog rows are append-only (oldest first). Pages written newest-first
    are re-sorted by date, stable, so no row is lost or edited."""
    from .parse import SEP_RE, split_row
    from .tables import DATE_RE
    for i, l in enumerate(lines):
        if "agent:changelog" in l:
            break
    else:
        return lines
    j = i + 1
    while j < len(lines) - 1 and not (lines[j].lstrip().startswith("|") and SEP_RE.match(lines[j + 1])):
        if lines[j].startswith("#"):
            return lines
        j += 1
    if j >= len(lines) - 1:
        return lines
    start = j + 2
    end = start
    while end < len(lines) and lines[end].lstrip().startswith("|"):
        end += 1
    rows = lines[start:end]
    keyed = [(split_row(r)[0] if split_row(r) else "", r) for r in rows]
    if all(DATE_RE.match(k) for k, _ in keyed) and keyed != sorted(keyed, key=lambda t: t[0]):
        rows = [r for _, r in sorted(keyed, key=lambda t: t[0])]
        notes.append("changelog rows re-sorted oldest-first (append-only convention)")
    return lines[:start] + rows + lines[end:]


def derive_kind(rel: str) -> str:
    top = rel.split("/")[0]
    if rel in ("index.mdx",):
        return "reference"
    return KIND_BY_DIR.get(top, "topic")


def derive_status(fm: dict, body: str, docs_group: str | None = None, open_group: str | None = None) -> str:
    """The human-curated nav group is the primary source: a page listed in the
    open-plans group is `open`. Otherwise only the title and explicit "Status:"
    lines decide between dropped and executed — prose like "Not done:" or
    "merged PR #12" must not flip a plan."""
    if docs_group is not None and open_group is not None:
        if docs_group == open_group:
            return "open"
    lines = [fm.get("title", "")] + [l for l in body[:4000].split("\n") if re.search(r"\bstatus\b", l, re.I)]
    head = "\n".join(lines).upper()
    negated = re.search(r"\bNOT(?: YET)? (?:EXECUTED|SHIPPED|DONE|LIVE)\b|\bSTATUS:?\s*OPEN\b", head)
    if re.search(r"\b(DROPPED|RETIRED|ABANDONED|SUPERSEDED)\b", head):
        return "dropped"
    if re.search(r"\b(EXECUTED|SHIPPED|LIVE IN PROD|DONE)\b", head) and not negated:
        return "executed"
    if negated or docs_group is None:
        return "open"
    return "executed"   # listed in a history group with no Status line


def convert_text(src: str, rel_mdx: str, cfg: KbConfig, docs_group: str | None = None) -> tuple[str, list[str], dict]:
    notes: list[str] = []
    m = re.match(r"^---\n(.*?)\n---\n?", src, re.S)
    if not m:
        raise ValueError(f"{rel_mdx}: no front matter")
    fm = yaml.safe_load(m.group(1)) or {}
    body = src[m.end():]
    body = JSX_COMMENT_RE.sub(lambda mm: f"<!--{mm.group(1)}-->", body)
    body = re.sub(r"\]\((/[^)]+?)\.mdx?(#[^)]*)?\)", r"](\1\2)", body)   # internal links only
    root, tree_notes = build_tree(body.split("\n"))
    notes += tree_notes
    lines = _sort_changelog(_collapse_blank(render(root, notes)), notes)
    lines = tag_bare_fences(normalize_types(tableize_changelog(lines, notes), notes), notes)
    kind = derive_kind(rel_mdx)
    out_fm = {"title": fm.get("title", ""), "description": fm.get("description", ""),
              "keywords": fm.get("keywords", []), "kind": kind}
    if kind == "roadmap":
        out_fm["status"] = derive_status(fm, "\n".join(lines), docs_group, cfg.settings.get("openRoadmapGroup"))
        notes.append(f"status derived as `{out_fm['status']}` — verify")
    fm_text = yaml.safe_dump(out_fm, sort_keys=False, allow_unicode=True, width=1000).rstrip()
    return f"---\n{fm_text}\n---\n\n" + "\n".join(lines) + "\n", notes, out_fm


def docs_group(repo: Path, slug: str) -> str | None:
    p = repo / "docs" / "docs.json"
    if not p.is_file():
        return None
    for g in json.loads(p.read_text())["navigation"]["groups"]:
        if slug in g.get("pages", []):
            return g["group"]
    return None


def cli(cfg: KbConfig, sources: list[str], out_dir: str | None, group: str | None, dry_run: bool,
        force: bool = False) -> int:
    from .gitutil import repo_root
    from .scaffold import nav_add
    repo = repo_root(cfg.root) or cfg.root.parent
    rc = 0
    for s in sources:
        src_path = Path(s).resolve()
        try:
            rel_mdx = src_path.relative_to((repo / "docs").resolve()).as_posix()
        except ValueError:
            rel_mdx = src_path.name
        slug = rel_mdx[:-4] if rel_mdx.endswith(".mdx") else rel_mdx.rsplit(".", 1)[0]
        text, notes, fm = convert_text(src_path.read_text(encoding="utf-8"), rel_mdx, cfg, group or docs_group(repo, slug))
        if out_dir:
            slug = f"{out_dir.strip('/')}/{Path(slug).name}"
        target = cfg.page_path(slug)
        grp = group or docs_group(repo, slug)
        open_grp = cfg.settings.get("openRoadmapGroup")
        if grp == open_grp and fm.get("status") not in (None, "open"):
            grp = "Project history & reviews"
            notes.append(f"moved out of `{open_grp}` (status {fm['status']}) into `{grp}`")
        print(f"{rel_mdx} → {target.relative_to(cfg.root)}" + (f"  [nav: {grp}]" if grp else "  [nav: NONE — pass --group]"))
        for n in notes:
            print(f"  note: {n}")
        if grp is None:
            rc = 1
        if dry_run:
            continue
        if target.exists() and not force:
            print(f"  refused: {target.relative_to(cfg.root)} exists — enrichments made after conversion "
                  f"would be lost; pass --force to overwrite", file=sys.stderr)
            rc = 1
            continue
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text, encoding="utf-8")
        if grp and slug not in cfg.nav_pages() and not slug.startswith("_templates/"):
            nav_add(cfg, grp, slug)
        from .check import run
        rep = run(cfg, [str(target)])
        print(f"  check: {rep.verdict} — {len(rep.errors)} error(s), {len(rep.warnings)} warning(s)"
              + ("" if not rep.errors else "  (librari check " + str(target.relative_to(cfg.root)) + ")"))
    return rc
