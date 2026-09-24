"""Locate the knowledge base and load its configuration (`<kb>/librari.json`).

The kb root is the nearest ancestor directory (of the cwd or of a given page
path) that holds `librari.json`. `LIBRARI_KB` or `--kb` override the search.
Everything tunable — page kinds, nav, changelog types, limits — lives in that
file; the defaults below are what a fresh kb gets and what the tests run on.
"""
from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from pathlib import Path

CONFIG_NAME = "librari.json"
PAGE_SUFFIX = ".md"

# Canonical section order of a topic page. Every kind's contract is a subset
# of this list (plus page-specific anchors, which may appear anywhere).
CANONICAL_ANCHORS = [
    "decision", "key-files", "how", "config", "gotchas", "verify", "changelog", "related",
]

# kind -> {"anchors": [[anchor, required], ...], "frontmatter": [required keys]}
DEFAULT_KINDS: dict[str, dict] = {
    "topic": {
        "anchors": [["decision", False], ["key-files", True], ["how", False], ["config", False],
                    ["gotchas", False], ["verify", True], ["changelog", True], ["related", False]],
        "frontmatter": [],
    },
    "runbook": {
        "anchors": [["decision", False], ["key-files", True], ["how", True], ["config", False],
                    ["gotchas", False], ["verify", True], ["changelog", True], ["related", False]],
        "frontmatter": [],
    },
    "incident": {
        "anchors": [["decision", True], ["key-files", False], ["how", False], ["config", False],
                    ["gotchas", True], ["verify", True], ["changelog", True], ["related", False]],
        "frontmatter": [],
    },
    "roadmap": {
        "anchors": [["decision", True], ["key-files", False], ["how", False], ["config", False],
                    ["gotchas", False], ["verify", False], ["changelog", True], ["related", False]],
        "frontmatter": ["status"],
    },
    "reference": {
        "anchors": [["key-files", False], ["verify", False], ["changelog", True]],
        "frontmatter": [],
    },
}

DEFAULT_SETTINGS = {
    "changelogTypes": ["feat", "fix", "lesson", "config", "refactor", "docs", "incident",
                       "decision", "chore", "plan", "infra", "test", "security", "review"],
    "roadmapStatuses": ["open", "executed", "dropped"],
    # Nav group that may hold ONLY roadmap pages with status "open" (and must
    # hold every open one). Null disables the rule.
    "openRoadmapGroup": "Roadmap — open plans",
    "maxLines": 800,
    # Repo-relative directory of the legacy (Mintlify) docs tree. While it is
    # set, a link whose target still lives there resolves. Remove at cutover.
    "legacyDocsDir": None,
    # Key files prefixes that are documented but not in this checkout (they live
    # in a container image): never reported by M001.
    "uncheckedPathPrefixes": ["application/", "client/", "vendor/", "data/"],
    "directives": ["note", "info", "tip", "warning", "check", "danger",
                   "steps", "step", "cards", "accordion"],
    # `librari score` thresholds; keys and defaults in score.SCORE_DEFAULTS.
    # A partial dict here overrides only the keys it names.
    "score": {},
}


@dataclass
class KbConfig:
    root: Path
    name: str = "Knowledge base"
    description: str = ""
    kinds: dict[str, dict] = field(default_factory=lambda: json.loads(json.dumps(DEFAULT_KINDS)))
    settings: dict = field(default_factory=lambda: dict(DEFAULT_SETTINGS))
    groups: list[dict] = field(default_factory=list)  # [{"group": str, "pages": [str]}]
    raw: dict = field(default_factory=dict)

    @property
    def config_path(self) -> Path:
        return self.root / CONFIG_NAME

    def kind_anchors(self, kind: str) -> list[tuple[str, bool]]:
        return [(a, bool(r)) for a, r in self.kinds[kind]["anchors"]]

    def required_frontmatter(self, kind: str) -> list[str]:
        return list(self.kinds[kind].get("frontmatter", []))

    def nav_pages(self) -> list[str]:
        out: list[str] = []
        for g in self.groups:
            out.extend(p for p in g.get("pages", []) if isinstance(p, str))
        return out

    def group_of(self, slug: str) -> str | None:
        for g in self.groups:
            if slug in g.get("pages", []):
                return g["group"]
        return None

    def page_path(self, slug: str) -> Path:
        return self.root / (slug.strip("/") + PAGE_SUFFIX)

    def slug_of(self, path: Path) -> str:
        rel = Path(path).resolve().relative_to(self.root.resolve())
        return rel.as_posix()[: -len(PAGE_SUFFIX)] if rel.suffix == PAGE_SUFFIX else rel.as_posix()

    def all_pages(self) -> list[Path]:
        # `_templates/` (and any `_dir`) holds scaffolds, not pages
        return sorted(p for p in self.root.rglob("*" + PAGE_SUFFIX)
                      if not any(part.startswith((".", "_")) for part in p.relative_to(self.root).parts))

    def save(self) -> None:
        data = dict(self.raw)
        data["navigation"] = {**(self.raw.get("navigation") or {}), "groups": self.groups}
        self.config_path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def find_root(start: Path | None = None, explicit: str | None = None) -> Path:
    if explicit or os.environ.get("LIBRARI_KB"):
        root = Path(explicit or os.environ["LIBRARI_KB"]).resolve()
        if not (root / CONFIG_NAME).is_file():
            raise FileNotFoundError(f"{root / CONFIG_NAME} not found")
        return root
    cur = (start or Path.cwd()).resolve()
    if cur.is_file():
        cur = cur.parent
    for cand in [cur, *cur.parents]:
        if (cand / CONFIG_NAME).is_file():
            return cand
    # Fall back to <repo>/kb when invoked from anywhere inside the repo.
    for cand in [cur, *cur.parents]:
        if (cand / "kb" / CONFIG_NAME).is_file():
            return cand / "kb"
    raise FileNotFoundError(f"no {CONFIG_NAME} found above {cur}; pass --kb or set LIBRARI_KB")


def load(root: Path) -> KbConfig:
    raw = json.loads((root / CONFIG_NAME).read_text(encoding="utf-8"))
    cfg = KbConfig(root=root, raw=raw)
    cfg.name = raw.get("name", cfg.name)
    cfg.description = raw.get("description", "")
    for k, v in (raw.get("kinds") or {}).items():
        cfg.kinds[k] = v
    cfg.settings.update(raw.get("settings") or {})
    cfg.groups = list((raw.get("navigation") or {}).get("groups") or [])
    return cfg
