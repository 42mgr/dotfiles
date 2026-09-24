"""Data model shared by the parser, the rules and the edit API."""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

SEVERITIES = ("error", "warning")


@dataclass
class Finding:
    rule: str
    severity: str          # error | warning
    path: str              # kb-relative page path
    line: int | None       # 1-based, None = whole page
    message: str
    hint: str = ""

    def as_dict(self) -> dict:
        return {"rule": self.rule, "severity": self.severity, "path": self.path,
                "line": self.line, "message": self.message, "hint": self.hint}


@dataclass
class Container:
    name: str
    title: str
    colons: int
    open_line: int                 # 0-based
    close_line: int | None = None  # 0-based line of the closing fence
    auto_closed_by: int | None = None  # 0-based line of the fence that force-closed it
    closed_in_fence: int | None = None  # 0-based start line of the code fence the closer sat in
    parent: "Container | None" = None
    children: list["Container"] = field(default_factory=list)

    @property
    def depth(self) -> int:
        d, c = 0, self.parent
        while c is not None:
            d, c = d + 1, c.parent
        return d


@dataclass
class CodeBlock:
    info: str        # language tag (first word of the fence info) or ""
    start: int       # 0-based fence line
    end: int         # 0-based line AFTER the closing fence (exclusive)
    content: str


@dataclass
class Link:
    href: str
    text: str
    line: int        # 0-based
    is_image: bool = False


@dataclass
class Heading:
    level: int
    text: str        # without the anchor comment
    line: int        # 0-based
    anchor: str | None = None


@dataclass
class Section:
    anchor: str
    heading: Heading
    start: int       # 0-based heading line
    end: int         # exclusive: next heading of level <= this one, or EOF

    @property
    def body_start(self) -> int:
        return self.start + 1


@dataclass
class Page:
    path: Path
    rel: str                       # kb-relative posix path
    text: str
    lines: list[str]
    frontmatter: dict | None       # None when missing or invalid
    frontmatter_end: int           # 0-based line AFTER the closing --- (0 when none)
    frontmatter_error: str | None = None
    headings: list[Heading] = field(default_factory=list)
    sections: list[Section] = field(default_factory=list)
    containers: list[Container] = field(default_factory=list)   # all, flattened
    code_blocks: list[CodeBlock] = field(default_factory=list)
    links: list[Link] = field(default_factory=list)
    raw_html: list[tuple[int, str]] = field(default_factory=list)  # (0-based line, snippet)
    stray_anchors: list[tuple[int, str]] = field(default_factory=list)
    ids: list[str] = field(default_factory=list)      # <a id="…"></a> link targets
    unknown_directives: list[tuple[int, str]] = field(default_factory=list)
    unclosed_fences: list[int] = field(default_factory=list)

    @property
    def slug(self) -> str:
        return self.rel[:-3] if self.rel.endswith(".md") else self.rel

    @property
    def kind(self) -> str | None:
        fm = self.frontmatter or {}
        k = fm.get("kind")
        return k if isinstance(k, str) else None

    def section(self, anchor: str) -> Section | None:
        for s in self.sections:
            if s.anchor == anchor:
                return s
        return None

    @property
    def anchors(self) -> list[str]:
        return [s.anchor for s in self.sections]

    def first_heading_line(self) -> int:
        return self.headings[0].line if self.headings else len(self.lines)

    def in_code(self, line: int) -> bool:
        return any(cb.start <= line < cb.end for cb in self.code_blocks)


def slug_of_heading(text: str) -> str:
    """Primary heading id, the Mintlify dialect (runs collapsed) — shared by the
    renderer (element ids) and search (refs of un-anchored H2 regions)."""
    import re
    s = re.sub(r"[^\w\s-]", "", text.lower(), flags=re.UNICODE).strip()
    return re.sub(r"[\s-]+", "-", s)
