"""S-tier: the page must parse the way the renderer will parse it."""
from __future__ import annotations

from ..model import Finding, Page
from . import Ctx, finding, rule


@rule("S001", "syntax", "error", "front matter missing or invalid", """
Every page starts with a YAML front matter block:

    ---
    title: "…"
    description: "…"
    keywords: ["…"]
    kind: topic
    ---

The block must be the first thing in the file and must parse as a YAML mapping.
""")
def front_matter(page: Page, ctx: Ctx) -> list[Finding]:
    if page.frontmatter_error:
        return [finding("S001", page, 0, f"front matter: {page.frontmatter_error}")]
    if page.frontmatter is None:
        return [finding("S001", page, 0, "no front matter block (--- … ---) at the top of the file")]
    return []


@rule("S002", "syntax", "error", "code fence without a language tag", """
Every fenced code block names its language: ```bash, ```sql, ```php, ```json,
```text for plain output, ```mermaid for diagrams. A bare ``` renders without
highlighting and hides what the block is.
""")
def fence_language(page: Page, ctx: Ctx) -> list[Finding]:
    return [finding("S002", page, cb.start, "code fence has no language tag",
                    "use ```bash / ```sql / ```text …")
            for cb in page.code_blocks if cb.info == "" and cb.start not in page.unclosed_fences]


@rule("S003", "syntax", "error", "code fence never closed", """
A ``` (or ~~~) fence must be closed by a line holding only the same marker,
at least as long as the opening one. Everything after an unclosed fence is
swallowed into the code block.
""")
def fence_unclosed(page: Page, ctx: Ctx) -> list[Finding]:
    return [finding("S003", page, ln, "code fence opened here is never closed") for ln in page.unclosed_fences]


@rule("S004", "syntax", "error", "unknown directive or stray closing fence", """
The directive set is closed. Allowed: :::note :::info :::tip :::warning :::check
:::danger, ::::steps containing :::step <title>, :::cards, :::accordion <title>.
A bare ::: that closes nothing renders as literal text.
""")
def directive_unknown(page: Page, ctx: Ctx) -> list[Finding]:
    out = []
    for ln, name in page.unknown_directives:
        if name:
            out.append(finding("S004", page, ln, f"unknown directive ':::{name}'",
                               "allowed: " + ", ".join(ctx.cfg.settings["directives"])))
        else:
            out.append(finding("S004", page, ln, "closing ':::' with no open container at this depth",
                               "an enclosing container needs MORE colons than the ones inside it"))
    return out


@rule("S005", "syntax", "error", "raw HTML / bare angle-bracket placeholder", """
Raw HTML is not part of the format (the renderer escapes it). A bare <Entity>,
<N> or <path> placeholder is parsed as an HTML tag: wrap it in backticks —
`<Entity>`. HTML comments (<!-- … -->) are allowed.
""")
def raw_html(page: Page, ctx: Ctx) -> list[Finding]:
    return [finding("S005", page, ln, f"raw HTML `{snippet}` — wrap placeholders in backticks")
            for ln, snippet in page.raw_html]


@rule("S006", "syntax", "error", "agent anchor not on a heading line", """
An anchor comment marks a section and belongs at the end of its heading line:

    ## Key files <!-- agent:key-files -->

Anywhere else it marks nothing and `librari section` cannot find the section.
""")
def anchor_placement(page: Page, ctx: Ctx) -> list[Finding]:
    return [finding("S006", page, ln, f"{snippet} is not on a heading line")
            for ln, snippet in page.stray_anchors]


@rule("S007", "syntax", "error", "directive nesting", """
Containers nest by colon count: a container that encloses others uses one colon
MORE than its deepest child, exactly like code fences.

    ::::steps
    :::step Rebuild
    text
    :::
    ::::

A bare ::: closes the OUTERMOST open container with <= colons, force-closing
everything nested inside it. `:::step` is only valid directly inside `steps`, and
`steps` may contain only `step` children.
""")
def nesting(page: Page, ctx: Ctx) -> list[Finding]:
    out = []
    for c in page.containers:
        if c.auto_closed_by is not None:
            closer = next((x for x in page.containers if x.close_line == c.auto_closed_by), None)
            what = f"':::{closer.name}' (line {closer.open_line + 1})" if closer else "an outer container"
            out.append(finding("S007", page, c.open_line,
                               f"':::{c.name}' was force-closed at line {c.auto_closed_by + 1}, which closes {what}",
                               "give the enclosing container more colons than this one"))
        elif c.close_line is None:
            out.append(finding("S007", page, c.open_line, f"':::{c.name}' is never closed"))
        if c.closed_in_fence is not None:
            out.append(finding("S007", page, c.close_line,
                               f"this ':::' sits inside the code fence opened at line {c.closed_in_fence + 1} "
                               f"but still closes ':::{c.name}' (line {c.open_line + 1}) — the renderer ignores fences here",
                               "close the container after the fence, or use more colons on the container"))
        if c.name == "step" and (c.parent is None or c.parent.name != "steps"):
            out.append(finding("S007", page, c.open_line, "':::step' must sit directly inside '::::steps'"))
        if c.name == "steps":
            for ch in c.children:
                if ch.name != "step":
                    out.append(finding("S007", page, ch.open_line,
                                       f"'::::steps' may only contain ':::step' children, found ':::{ch.name}'"))
        if c.name == "step" and not c.title:
            out.append(finding("S007", page, c.open_line, "':::step' needs a title: ':::step Clear the cache'"))
        if c.name == "accordion" and not c.title:
            out.append(finding("S007", page, c.open_line, "':::accordion' needs a title"))
    return out


@rule("S008", "syntax", "warning", "indented code block", """
A block indented by four spaces renders as code without a language. Use a
fenced block with a language tag instead.
""")
def indented_code(page: Page, ctx: Ctx) -> list[Finding]:
    return [finding("S008", page, cb.start, "indented code block — use a fenced block with a language tag")
            for cb in page.code_blocks if cb.info == "<indented>"]
