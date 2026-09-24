"""Rule registry. A rule is a function `(page, ctx) -> list[Finding]` decorated
with its id, tier, severity and an `explain` text that `librari explain <id>`
prints — the hook points the agent at that instead of loading a whole skill.

Ids: S = syntax, C = contract (the page template), M = semantics (cross-page,
filesystem, git, secrets). Errors make a page RED; warnings never do.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

from ..model import Finding, Page

RULES: dict[str, "Rule"] = {}


@dataclass
class Rule:
    id: str
    tier: str
    severity: str
    title: str
    explain: str
    func: Callable[[Page, "Ctx"], list[Finding]]


def rule(id: str, tier: str, severity: str, title: str, explain: str):
    def deco(func):
        RULES[id] = Rule(id, tier, severity, title, explain.strip(), func)
        return func
    return deco


def finding(rule_id: str, page: Page, line: int | None, message: str, hint: str = "") -> Finding:
    r = RULES[rule_id]
    return Finding(rule_id, r.severity, page.rel, None if line is None else line + 1, message, hint)


class Ctx:
    """Per-run context: config, repo, lazily loaded sibling pages."""

    def __init__(self, cfg, repo: "Path | None", base: str = "HEAD"):
        self.cfg = cfg
        self.repo = repo
        self.base = base          # git ref the C009/C010 diff is taken against
        self._pages: dict[str, Page] | None = None
        self.head_cache: dict[str, str | None] = {}

    def pages(self) -> dict[str, Page]:
        if self._pages is None:
            from ..parse import parse_file
            self._pages = {}
            for p in self.cfg.all_pages():
                try:
                    pg = parse_file(p, self.cfg.root, self.cfg.settings["directives"])
                except (OSError, UnicodeDecodeError, ValueError):
                    continue   # check.run reports it as unreadable; a link to it then fails M002
                self._pages[pg.slug] = pg
        return self._pages

    def page_by_slug(self, slug: str) -> Page | None:
        return self.pages().get(slug.strip("/"))

    def head(self, page: Page) -> str | None:
        """HEAD content of the page, None when untracked or no repo."""
        if self.repo is None:
            return None
        rel = page.path.resolve().relative_to(self.repo.resolve()).as_posix()
        if rel not in self.head_cache:
            from ..gitutil import head_text, renamed_from
            text = head_text(self.repo, rel, self.base)
            if text is None:   # a renamed page keeps its history: diff against the old path
                old = renamed_from(self.repo, rel, self.base)
                text = head_text(self.repo, old, self.base) if old else None
            self.head_cache[rel] = text
        return self.head_cache[rel]


def all_rules() -> list[Rule]:
    from . import contract, semantics, syntax  # noqa: F401  (registration side effect)
    return [RULES[k] for k in sorted(RULES)]
