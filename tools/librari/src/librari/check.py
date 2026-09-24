"""Run the rules over pages, apply the shrink-only baseline, format the report.

Verdict vocabulary is the repo's (myscripts/preflight.sh):
  GREEN (0) every selected check ran and passed
  RED (1) a check ran and failed
  NO-VERDICT (2) something could not be checked at all — not a pass
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

from .config import KbConfig
from .gitutil import changed_files, merge_base, repo_root
from .model import Finding, Page
from .parse import parse_file
from .rules import Ctx, all_rules

BASELINE_NAME = "librari-baseline.json"


@dataclass
class Report:
    findings: list[Finding] = field(default_factory=list)
    baselined: list[Finding] = field(default_factory=list)
    pages: list[str] = field(default_factory=list)
    unreadable: list[str] = field(default_factory=list)

    @property
    def errors(self) -> list[Finding]:
        return [f for f in self.findings if f.severity == "error"]

    @property
    def warnings(self) -> list[Finding]:
        return [f for f in self.findings if f.severity == "warning"]

    @property
    def verdict(self) -> str:
        if self.unreadable:
            return "NO-VERDICT"
        return "RED" if self.errors else "GREEN"

    @property
    def exit_code(self) -> int:
        return {"GREEN": 0, "RED": 1, "NO-VERDICT": 2}[self.verdict]

    def as_dict(self) -> dict:
        return {"verdict": self.verdict, "pages": self.pages, "unreadable": self.unreadable,
                "errors": len(self.errors), "warnings": len(self.warnings),
                "baselined": len(self.baselined),
                "findings": [f.as_dict() for f in self.findings]}


def load_baseline(cfg: KbConfig) -> dict[str, list[str]]:
    p = cfg.root / BASELINE_NAME
    return json.loads(p.read_text()) if p.is_file() else {}


def select_pages(cfg: KbConfig, paths: list[str] | None, changed: bool,
                 base: str | None = None) -> list[Path]:
    if paths:
        return [Path(p).resolve() for p in paths]
    if changed:
        repo = repo_root(cfg.root)
        if repo is None:
            return cfg.all_pages()
        touched = changed_files(repo, base)
        out = []
        for p in cfg.all_pages():
            if p.resolve().relative_to(repo.resolve()).as_posix() in touched:
                out.append(p)
        return out
    return cfg.all_pages()


def kb_findings(cfg: KbConfig, ctx: Ctx, baseline: dict, report: Report, whole_kb: bool) -> list[Finding]:
    """Findings that belong to the kb, not to one page (nav orphans, stale baseline)."""
    out = []
    existing = {cfg.slug_of(p) for p in cfg.all_pages()}
    for g in cfg.groups:
        for slug in g.get("pages", []):
            if isinstance(slug, str) and slug not in existing:
                out.append(Finding("M005", "error", "librari.json", None,
                                   f"nav group `{g['group']}` lists `{slug}` but `{slug}.md` does not exist"))
    if whole_kb:
        seen = {(f.rule, f.path) for f in report.baselined}
        for rule_id, pages in baseline.items():
            for rel in pages:
                if (rule_id, rel) not in seen:
                    out.append(Finding("B001", "error", BASELINE_NAME, None,
                                       f"stale baseline entry {rule_id} → {rel}: the finding is gone, remove the entry",
                                       "the baseline only shrinks"))
    return out


def run(cfg: KbConfig, paths: list[str] | None = None, changed: bool = False,
        use_baseline: bool = True, rules: set[str] | None = None) -> Report:
    report = Report()
    repo = repo_root(cfg.root)
    base = "HEAD"
    if changed and repo is not None:
        # under --changed the changelog rules diff against the merge-base, so a
        # committed body change still needs its row (CI semantics, not hook semantics)
        base = merge_base(repo)
        if base is None:
            report.unreadable.append("--changed: no merge-base with origin/master or master — nothing selected")
            return report
    ctx = Ctx(cfg, repo, base)
    baseline = load_baseline(cfg) if use_baseline else {}
    active = [r for r in all_rules() if not rules or r.id in rules]
    pages = select_pages(cfg, paths, changed, base)
    for path in pages:
        try:
            page = parse_file(path, cfg.root, cfg.settings["directives"])
        except (OSError, UnicodeDecodeError, ValueError) as e:
            report.unreadable.append(f"{path}: {e}")
            continue
        report.pages.append(page.rel)
        for r in active:
            for f in r.func(page, ctx):
                if f.path in baseline.get(f.rule, []):
                    report.baselined.append(f)
                else:
                    report.findings.append(f)
    # the baseline ratchet (B001) needs EVERY rule over EVERY page — under
    # --rule / paths / --changed a missing finding proves nothing
    whole_kb = not paths and not changed and not rules
    report.findings.extend(kb_findings(cfg, ctx, baseline, report, whole_kb))
    report.findings.sort(key=lambda f: (f.path, f.line or 0, f.rule))
    return report


def format_text(report: Report, verbose: bool = False) -> str:
    lines = []
    for f in report.findings:
        loc = f"{f.path}:{f.line}" if f.line else f.path
        lines.append(f"{loc}: {f.severity} {f.rule} {f.message}")
        if f.hint:
            lines.append(f"    ↳ {f.hint}")
    for u in report.unreadable:
        lines.append(f"unreadable: {u}")
    n_pages = len(report.pages)
    lines.append(f"librari check: {report.verdict} — {n_pages} page(s), {len(report.errors)} error(s), "
                 f"{len(report.warnings)} warning(s), {len(report.baselined)} baselined")
    if report.errors:
        rules = sorted({f.rule for f in report.errors})
        lines.append("explain a rule: librari explain " + " | ".join(rules))
    return "\n".join(lines)


def format_json(report: Report) -> str:
    return json.dumps(report.as_dict(), indent=2, ensure_ascii=False)
