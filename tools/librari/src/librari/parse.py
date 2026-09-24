"""Parse a kb page into the `Page` model.

Two passes:

1. A line scanner that models code fences and `:::` directive containers with
   markdown-it's exact semantics — a bare closing fence closes the OUTERMOST
   open container whose colon count is <= the fence's, force-closing anything
   nested above it. That is the footgun the format's "each enclosing level adds
   one colon" rule exists for, and modelling it here (instead of a naive stack)
   is what lets the validator reject what the renderer would silently misparse.
2. markdown-it (CommonMark + tables + front matter + the closed directive set)
   for headings, code fences, links, images and raw HTML.
"""
from __future__ import annotations

import re
from pathlib import Path

import yaml
from markdown_it import MarkdownIt
from markdown_it.token import Token
from mdit_py_plugins.container import container_plugin
from mdit_py_plugins.front_matter import front_matter_plugin

from .config import DEFAULT_SETTINGS
from .model import CodeBlock, Container, Heading, Link, Page, Section

ANCHOR_RE = re.compile(r"<!--\s*agent:([A-Za-z0-9_-]+)\s*-->")
ANY_COMMENT_RE = re.compile(r"<!--.*?-->", re.S)
ID_ANCHOR_RE = re.compile(r"""<a\s+id=["']([A-Za-z0-9_.:-]+)["']\s*(?:/>|>\s*</a>)""")
ID_OPEN_RE = re.compile(r"""<a\s+id=["']([A-Za-z0-9_.:-]+)["']\s*>""")   # markdown-it splits <a id=x></a> into two inline tokens
FENCE_RE = re.compile(r"^ {0,3}(`{3,}|~{3,})(.*)$")
CONTAINER_RE = re.compile(r"^ {0,3}(:{3,})(.*)$")

_PARSERS: dict[tuple[str, ...], MarkdownIt] = {}


def _parser(directives: tuple[str, ...]) -> MarkdownIt:
    md = _PARSERS.get(directives)
    if md is None:
        md = MarkdownIt("commonmark", {"html": True}).enable("table")
        md.use(front_matter_plugin)
        for name in directives:
            md.use(container_plugin, name=name)
        _PARSERS[directives] = md
    return md


def scan_blocks(lines: list[str]) -> tuple[list[CodeBlock], list[Container], list[int], list[int]]:
    """Return (code_blocks, containers, unclosed_fence_lines, stray_close_lines).

    markdown-it-container finds a container's closing fence by scanning raw
    lines — it does NOT know about code fences. So a bare `:::` inside a code
    block still closes an open container (the fence is then cut short and a
    later ``` swallows the rest of the page). The scanner mirrors that and marks
    the container `closed_in_fence` so S007 can name the real cause.
    """
    code: list[CodeBlock] = []
    containers: list[Container] = []
    stack: list[Container] = []
    unclosed_fences: list[int] = []
    stray_close: list[int] = []
    fence: tuple[str, int, int] | None = None  # (char, count, start line)

    def close_container(colons: int, i: int) -> bool:
        idx = next((j for j, c in enumerate(stack) if c.colons <= colons), None)
        if idx is None:
            return False
        for c in stack[idx + 1:]:
            c.auto_closed_by = i
        stack[idx].close_line = i
        del stack[idx:]
        return True

    def end_fence(i: int) -> None:
        ch, cnt, start = fence  # type: ignore[misc]
        info = lines[start].strip().lstrip(ch).strip()
        code.append(CodeBlock(info.split()[0] if info else "", start, i + 1,
                              "\n".join(lines[start + 1:i]) + ("\n" if i > start + 1 else "")))

    for i, line in enumerate(lines):
        if fence is not None:
            ch, cnt, start = fence
            m = re.match(r"^ {0,3}(" + re.escape(ch) + "{" + str(cnt) + r",})\s*$", line)
            if m:
                end_fence(i)
                fence = None
                continue
            mc = CONTAINER_RE.match(line)
            if mc and mc.group(2).strip() == "" and stack:
                # a bare closer inside a fence: markdown-it closes the container here
                colons = len(mc.group(1))
                if any(c.colons <= colons for c in stack):
                    idx = next(j for j, c in enumerate(stack) if c.colons <= colons)
                    stack[idx].closed_in_fence = fence[2]
                    end_fence(i - 1) if i - 1 > start else code.append(CodeBlock("", start, i, ""))
                    close_container(colons, i)
                    fence = None
            continue
        m = FENCE_RE.match(line)
        if m and not (m.group(1)[0] == "`" and "`" in m.group(2)):
            fence = (m.group(1)[0], len(m.group(1)), i)
            continue
        m = CONTAINER_RE.match(line)
        if not m:
            continue
        colons, rest = len(m.group(1)), m.group(2).strip()
        if rest == "":
            if not close_container(colons, i):
                stray_close.append(i)
            continue
        name, _, title = rest.partition(" ")
        c = Container(name=name, title=title.strip(), colons=colons, open_line=i,
                      parent=stack[-1] if stack else None)
        if stack:
            stack[-1].children.append(c)
        containers.append(c)
        stack.append(c)
    if fence is not None:
        unclosed_fences.append(fence[2])
        code.append(CodeBlock("", fence[2], len(lines), "\n".join(lines[fence[2] + 1:]) + "\n"))
    return code, containers, unclosed_fences, stray_close


def _walk_inline(tok: Token, line: int, page: Page) -> None:
    children = tok.children or []
    i = 0
    while i < len(children):
        c = children[i]
        if c.type == "link_open":
            href = c.attrGet("href") or ""
            text, j = [], i + 1
            while j < len(children) and children[j].type != "link_close":
                if children[j].type in ("text", "code_inline"):
                    text.append(children[j].content)
                j += 1
            page.links.append(Link(href, "".join(text), line))
            i = j
        elif c.type == "image":
            page.links.append(Link(c.attrGet("src") or "", c.content, line, is_image=True))
        elif c.type == "html_inline":
            snippet = c.content
            if ANCHOR_RE.fullmatch(snippet.strip()):
                page.stray_anchors.append((line, snippet.strip()))
            elif ID_ANCHOR_RE.fullmatch(snippet.strip()):
                page.ids.append(ID_ANCHOR_RE.fullmatch(snippet.strip()).group(1))
            elif ID_OPEN_RE.fullmatch(snippet.strip()) and i + 1 < len(children) \
                    and children[i + 1].type == "html_inline" and children[i + 1].content.strip() == "</a>":
                page.ids.append(ID_OPEN_RE.fullmatch(snippet.strip()).group(1))
                i += 1                                   # swallow the closing </a>
            elif not snippet.startswith("<!--"):
                page.raw_html.append((line, snippet.strip()))
        i += 1


def parse_text(text: str, rel: str, path: Path | None = None,
               directives: list[str] | None = None) -> Page:
    lines = text.split("\n")
    if lines and lines[-1] == "":
        lines = lines[:-1]
    page = Page(path=path or Path(rel), rel=rel, text=text, lines=lines,
                frontmatter=None, frontmatter_end=0)

    # -- front matter ------------------------------------------------------
    if lines and lines[0].strip() == "---":
        for i in range(1, len(lines)):
            if lines[i].strip() == "---":
                page.frontmatter_end = i + 1
                try:
                    fm = yaml.safe_load("\n".join(lines[1:i])) or {}
                    if not isinstance(fm, dict):
                        raise ValueError("front matter must be a mapping")
                    page.frontmatter = fm
                except Exception as e:  # yaml.YAMLError or ValueError
                    page.frontmatter_error = str(e).splitlines()[0]
                break
        else:
            page.frontmatter_error = "front matter opened with --- but never closed"

    # -- pass 1: fences + containers --------------------------------------
    page.code_blocks, page.containers, page.unclosed_fences, stray_close = scan_blocks(lines)
    known = set(directives or DEFAULT_SETTINGS["directives"])
    for c in page.containers:
        if c.name not in known:
            page.unknown_directives.append((c.open_line, c.name))
    for i in stray_close:
        page.unknown_directives.append((i, ""))

    # -- pass 2: markdown-it ----------------------------------------------
    md = _parser(tuple(sorted(known)))
    tokens = md.parse(text)
    skip_inline = False
    for idx, tok in enumerate(tokens):
        if tok.map is None:
            continue
        line = tok.map[0]
        if skip_inline and tok.type == "inline":
            skip_inline = False
            continue
        if tok.type == "heading_open":
            skip_inline = True
            inline = tokens[idx + 1]
            content = inline.content if inline.type == "inline" else ""
            m = ANCHOR_RE.search(content)
            h = Heading(level=int(tok.tag[1]), text=ANCHOR_RE.sub("", content).strip(), line=line,
                        anchor=m.group(1) if m else None)
            page.headings.append(h)
            # links inside the heading still count; anchors there are not stray
            if inline.type == "inline":
                inline_children = [c for c in (inline.children or []) if c.type != "html_inline"]
                tmp = Token("inline", "", 0)
                tmp.children = inline_children
                _walk_inline(tmp, line, page)
        elif tok.type == "inline":
            _walk_inline(tok, line, page)
        elif tok.type == "html_block":
            body = ANY_COMMENT_RE.sub("", tok.content).strip()
            for m in ANCHOR_RE.finditer(tok.content):
                page.stray_anchors.append((line, m.group(0)))
            for m in ID_ANCHOR_RE.finditer(body):
                page.ids.append(m.group(1))
            body = ID_ANCHOR_RE.sub("", body).strip()
            # an html_block runs to the next blank line; after removing the
            # allowed anchors only a real tag counts as raw HTML
            if re.search(r"<[A-Za-z/!]", body):
                page.raw_html.append((line, body.splitlines()[0][:60]))
        elif tok.type == "code_block":
            # indented code block — flagged by the rules, kept out of the fence list
            page.code_blocks.append(CodeBlock("<indented>", tok.map[0], tok.map[1], tok.content))

    # -- sections ------------------------------------------------------------
    for n, h in enumerate(page.headings):
        if h.anchor is None:
            continue
        end = len(lines)
        for nxt in page.headings[n + 1:]:
            if nxt.level <= h.level:
                end = nxt.line
                break
        page.sections.append(Section(anchor=h.anchor, heading=h, start=h.line, end=end))
    return page


def parse_file(path: Path, root: Path, directives: list[str] | None = None) -> Page:
    rel = Path(path).resolve().relative_to(root.resolve()).as_posix()
    return parse_text(Path(path).read_text(encoding="utf-8"), rel, Path(path), directives)


# -- tables -------------------------------------------------------------------

def split_row(line: str) -> list[str]:
    cells, cur, esc = [], [], False
    s = line.strip()
    if s.startswith("|"):
        s = s[1:]
    if s.endswith("|") and not s.endswith("\\|"):
        s = s[:-1]
    for ch in s:
        if esc:
            cur.append(ch)
            esc = False
        elif ch == "\\":
            cur.append(ch)
            esc = True
        elif ch == "|":
            cells.append("".join(cur).strip())
            cur = []
        else:
            cur.append(ch)
    cells.append("".join(cur).strip())
    return cells


SEP_RE = re.compile(r"^\s*\|?\s*:?-{1,}:?\s*(\|\s*:?-{1,}:?\s*)*\|?\s*$")


def find_tables(lines: list[str], start: int, end: int) -> list[tuple[int, list[str], list[tuple[int, list[str]]]]]:
    """Pipe tables in lines[start:end] -> [(header_line, header_cells, [(line, cells), ...])]."""
    out = []
    i = start
    while i < end - 1:
        if "|" in lines[i] and SEP_RE.match(lines[i + 1]) and "|" in lines[i + 1]:
            header = split_row(lines[i])
            rows = []
            j = i + 2
            while j < end and "|" in lines[j] and lines[j].strip():
                rows.append((j, split_row(lines[j])))
                j += 1
            out.append((i, header, rows))
            i = j
        else:
            i += 1
    return out
