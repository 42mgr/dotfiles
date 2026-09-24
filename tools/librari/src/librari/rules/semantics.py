"""M-tier: claims a page makes about the world outside itself — files on disk,
other pages, the nav, git, secrets."""
from __future__ import annotations

import glob
import re
from pathlib import Path

from ..model import Finding, Page
from ..tables import code_spans, key_files_table
from . import Ctx, finding, rule

PLACEHOLDER_CHARS = ("<", ">", "…", "{", "}", "$")
PATHISH_RE = re.compile(r"^[\w@./+~-]+$")
FILE_EXT_RE = re.compile(r"\.(php|js|mjs|ts|json|sh|py|yml|yaml|conf|ini|md|mdx|sql|txt|re|service|timer|lua|tpl|"
                         r"css|html|xml|toml|lock|env|example|neon|cfg|tsv|csv|log)$", re.I)


def _paths_in_cell(cell: str) -> list[str]:
    out = []
    for span in code_spans(cell):
        span = re.sub(r":\d+(-\d+)?$", "", span)
        if any(ch in span for ch in PLACEHOLDER_CHARS) or " " in span:
            continue
        if span.startswith(("...", "…")) or "/.../" in span or span.endswith(("/...", "/…")) \
                or (span.startswith(".") and "/" not in span):
            continue   # abbreviated path or a bare extension mention like `.tpl`
        # a path has a slash or a file extension; `chat.example.com` and
        # `users.settings.pushNotifications` are names, not paths
        if ("/" in span or FILE_EXT_RE.search(span)) and PATHISH_RE.match(span.replace("*", "")):
            out.append(span)
    return out


def _repo_files(ctx: Ctx) -> list[str]:
    if not hasattr(ctx, "_repo_files"):
        import subprocess
        r = subprocess.run(["git", "--no-optional-locks", "ls-files"], cwd=ctx.repo, capture_output=True, text=True)
        ctx._repo_files = r.stdout.split("\n") if r.returncode == 0 else []
    return ctx._repo_files


def _suffix_matches(ctx: Ctx, p: str) -> list[str]:
    """Files (or directories, for a trailing-slash entry) whose path ends with `p`."""
    if p.endswith("/"):
        seg = "/" + p.strip("/") + "/"
        dirs = {f[: f.index(seg) + len(seg)] for f in _repo_files(ctx) if seg in "/" + f}
        return sorted(d.lstrip("/") for d in dirs)
    tail = "/" + p.lstrip("/")
    return [f for f in _repo_files(ctx) if f.endswith(tail) or f == p]


def _ignored(ctx: Ctx, p: str) -> bool:
    """Runtime data (bind mounts, dumps, notes) is gitignored: it exists on the
    host, not in a checkout — never a dead path. One subprocess per run."""
    import subprocess
    cache = getattr(ctx, "_ignore_cache", None)
    if cache is None:
        cache = ctx._ignore_cache = {}
    if p not in cache:
        r = subprocess.run(["git", "--no-optional-locks", "check-ignore", "-q", "--", p], cwd=ctx.repo, capture_output=True)
        cache[p] = r.returncode == 0
    return cache[p]


@rule("M010", "semantics", "warning", "Key files path is abbreviated", """
The path does not exist as written but resolves to exactly one file in the
repository by suffix. Write the full repo-relative path so an agent can open
it without searching: `espocrm-custom/Espo/Custom/Hooks/Email/X.php`, not
`Hooks/Email/X.php`.
""")
def key_files_abbreviated(page: Page, ctx: Ctx) -> list[Finding]:
    return []   # produced inside key_files_exist to avoid a second table walk


@rule("M001", "semantics", "error", "Key files path does not exist", """
Every path in the Key files table is checked against the repository. A path
that moved or never existed sends an agent to the wrong place — fix the row,
or remove it if the file is gone. Globs (`myscripts/backup-*.sh`) are allowed;
placeholders like `<Entity>` are skipped, and so is a row that says the file
does not exist yet or any more (`(planned)`, `to build`, `not built`, `**NEW.**`,
`no longer on disk`). Only repo-relative paths are checked —
absolute and `~/` host paths differ per machine, gitignored paths are runtime
data (bind mounts, dumps), and settings.uncheckedPathPrefixes (EspoCRM core
`application/`, `client/`, `vendor/`, `data/` — files that live in the container
image) are documented but not on disk here.
""")
def key_files_exist(page: Page, ctx: Ctx) -> list[Finding]:
    t = key_files_table(page)
    if t is None:
        return []
    out = []
    absent = re.compile(r"\(planned\)|\bto build\b|\bnot (yet )?built\b|\*\*NEW\.?\*\*|no longer on disk", re.I)
    for ln, cells in t[1]:
        if absent.search(" | ".join(cells)):
            continue   # the row itself says the file is not there
        for p in _paths_in_cell(cells[0] if cells else ""):
            if p.startswith(("~", "/")) or ".." in p.split("/") or ctx.repo is None:
                continue   # host paths are machine-specific and `..` escapes the repo; never stat'ed
            if p.count("*") > 2 or "**" in p:
                continue   # a wide glob could stall the hook
            q = re.sub(r"^\./", "", p)
            if any(q.startswith(pre) for pre in ctx.cfg.settings.get("uncheckedPathPrefixes", [])):
                continue   # container-image paths (EspoCRM core), documented on purpose
            if _ignored(ctx, q):
                continue
            base = ctx.repo / p
            ok = glob.glob(str(base)) if "*" in p else base.exists()
            if ok:
                continue
            hits = _suffix_matches(ctx, p) if "*" not in p else []
            if len(hits) == 1:
                out.append(finding("M010", page, ln, f"`{p}` is abbreviated — write `{hits[0]}`"))
            else:
                out.append(finding("M001", page, ln, f"Key files path `{p}` not found"
                                   + (f" ({len(hits)} suffix matches — ambiguous)" if hits else "")))
    return out


def _heading_slugs(text: str) -> set[str]:
    """Both slug dialects the corpus links with: GitHub (every space → hyphen,
    "How to detect / verify" → "how-to-detect--verify") and Mintlify
    (runs collapsed → "how-to-detect-verify")."""
    s = re.sub(r"[^\w\s-]", "", text.lower(), flags=re.UNICODE).strip()
    return {s.replace(" ", "-"), re.sub(r"[\s-]+", "-", s)}


def _target_exists(ctx: Ctx, page: Page, href: str) -> str | None:
    """None when the internal link resolves, else a message."""
    path, _, frag = href.partition("#")
    if path in ("", "/"):
        target = page if path == "" else ctx.page_by_slug("index")
    else:
        target = ctx.page_by_slug(path)
    if target is None:
        legacy = ctx.cfg.settings.get("legacyDocsDir")
        if legacy and ctx.repo is not None and path:
            for ext in (".mdx", ".md"):
                if (ctx.repo / legacy / (path.strip("/") + ext)).is_file():
                    return None   # still lives in the legacy docs tree — accepted until cutover
        return f"link target `{path}` is not a page in the kb"
    if frag:
        if frag.startswith("agent:"):
            if target.section(frag[6:]) is None:
                return f"`#{frag}` is not a section anchor of `{path or page.slug}`"
        elif frag not in {sl for h in target.headings for sl in _heading_slugs(h.text)} \
                and frag not in target.ids and target.section(frag) is None:
            return f"`#{frag}` matches no heading, <a id> or anchor on `{path or page.slug}` (use #agent:<name> or a heading slug)"
    return None


@rule("M002", "semantics", "error", "internal link does not resolve", """
Internal links are root-relative without extension (`/espocrm/gotchas`) and may
carry `#agent:<anchor>` or a heading slug. The target page must exist in the
kb and the fragment must match one of its sections.
""")
def links_resolve(page: Page, ctx: Ctx) -> list[Finding]:
    out = []
    for l in page.links:
        if l.is_image or re.match(r"^[a-z][a-z0-9+.-]*:", l.href, re.I) or l.href.startswith("//"):
            continue
        if l.href.startswith("/") or l.href.startswith("#"):
            msg = _target_exists(ctx, page, l.href)
            if msg:
                out.append(finding("M002", page, l.line, msg))
    return out


@rule("M003", "semantics", "error", "link style", """
No relative links (`../page`, `./page`) and no file extensions (`/page.md`).
Write `/group/slug`.
""")
def link_style(page: Page, ctx: Ctx) -> list[Finding]:
    out = []
    for l in page.links:
        if l.is_image or re.match(r"^[a-z][a-z0-9+.-]*:", l.href, re.I):
            continue
        if l.href.startswith(("./", "../")) or (not l.href.startswith(("/", "#")) and l.href):
            out.append(finding("M003", page, l.line, f"relative link `{l.href}` — use a root-relative `/group/slug`"))
        elif re.search(r"\.(md|mdx)(#.*)?$", l.href):
            out.append(finding("M003", page, l.line, f"link `{l.href}` carries a file extension"))
    return out


@rule("M004", "semantics", "error", "page not registered in the nav", """
Every page except templates is listed in `librari.json` → navigation.groups.
`librari new` registers automatically; `librari nav add <group> <slug>` does it
for an existing page.
""")
def nav_registered(page: Page, ctx: Ctx) -> list[Finding]:
    if page.rel.startswith("_templates/"):
        return []
    if page.slug not in ctx.cfg.nav_pages():
        return [finding("M004", page, None, f"`{page.slug}` is not in any nav group of librari.json")]
    return []


@rule("M005", "semantics", "error", "nav entry without a page", """
A slug listed in librari.json navigation must exist as `<slug>.md`.
""")
def _nav_orphan_placeholder(page: Page, ctx: Ctx) -> list[Finding]:
    return []  # kb-level; evaluated in check.kb_findings


ASSIGNMENT_RE = re.compile(
    r"(?:password|passwd|pwd|secret|api[_-]?key|apikey|auth[_-]?token|oauth|jwt|token|"
    r"access[_-]?key|secret[_-]?key|private[_-]?key)\s*[=:]\s*[\"']?([^\s\"'\n|]+)", re.IGNORECASE)
HIGH_SIGNAL = [re.compile(p) for p in (
    r"-----BEGIN (?:RSA |EC |OPENSSH |PGP )?PRIVATE KEY",
    r"\bAKIA[0-9A-Z]{16}\b", r"\bghp_[A-Za-z0-9]{30,}\b", r"\bglpat-[A-Za-z0-9_-]{20,}\b",
    r"\bxox[baprs]-[A-Za-z0-9-]{10,}\b", r"\beyJ[A-Za-z0-9_-]{20,}\.eyJ[A-Za-z0-9_-]{20,}\b",
    r"\bBearer\s+[A-Za-z0-9_\-.=]{20,}\b",
)]
PLACEHOLDER_WORDS = {
    "password", "passwort", "passwd", "secret", "token", "key", "value", "changeme", "change_me",
    "change-me", "example", "sample", "placeholder", "redacted", "masked", "hidden", "omitted",
    "dummy", "test", "testing", "none", "null", "nil", "undefined", "true", "false", "yes", "no",
    "todo", "tbd", "fixme", "hunter2", "unknown", "empty", "unset", "set", "required", "optional",
    "string", "str",
}


def looks_like_secret(value: str) -> bool:
    """Mirror of githooks/pre-push looks_like_secret — keep the two in sync."""
    v = value.strip(".,;:)(\"'`")
    if len(v) < 8 or v[0] in "$<%{*" or v.endswith(("}}", ">")):
        return False
    if re.fullmatch(r"(.)\1{4,}", v) or re.fullmatch(r"[x*.\-_]{5,}", v, re.IGNORECASE):
        return False
    if v.lower().replace("-", "_") in PLACEHOLDER_WORDS:
        return False
    if v.lower().startswith(("your_", "your-", "my_", "my-", "insert", "replace", "enter")):
        return False
    if v.startswith(("/", "./", "~/", "http://", "https://")):
        return False
    if v.isalpha() and len(v) < 16:
        return False
    if re.fullmatch(r"[A-Z][A-Z0-9_]*", v):   # an env-var NAME, e.g. WIKI_OIDC_CLIENT_SECRET
        return False
    if re.fullmatch(r"[A-Z][A-Za-z0-9]*(-[A-Z][A-Za-z0-9]*)+", v):   # a header NAME, e.g. X-CSRF-Token
        return False
    if any(ch in v for ch in "$(){}"):        # shell expansion / a formula, e.g. ${VAR:-x}, base64(sha256(t))
        return False
    if re.fullmatch(r"[a-z]+(-[a-z]+)+", v) and len(v) <= 24:   # a slug-like NAME, e.g. forgejo-admin
        return False
    return True


@rule("M006", "semantics", "error", "possible secret value", """
Docs carry env-var NAMES, never values. The scan mirrors githooks/pre-push:
`password=…`, `token: …` assignments with a non-placeholder value, private key
blocks, AWS/GitHub/GitLab/Slack tokens, JWTs, Bearer tokens. False positive?
Rewrite the value as `<redacted>` or `$VAR` — the page is a public artifact.
""")
def secrets(page: Page, ctx: Ctx) -> list[Finding]:
    out = []
    for i, line in enumerate(page.lines):
        for m in ASSIGNMENT_RE.finditer(line):
            if looks_like_secret(m.group(1)):
                out.append(finding("M006", page, i, f"looks like a secret assignment: `{m.group(0)[:40]}…`"))
                break
        for pat in HIGH_SIGNAL:
            if pat.search(line):
                out.append(finding("M006", page, i, "high-signal secret pattern (key block / token / JWT)"))
                break
    return out


@rule("M007", "semantics", "error", "image", """
Images live under `<kb>/images/` and are referenced root-relative with
descriptive alt text: `![Dashboard overview](/images/dashboard.png)`.
""")
def images(page: Page, ctx: Ctx) -> list[Finding]:
    out = []
    for l in page.links:
        if not l.is_image:
            continue
        if not l.text.strip():
            out.append(finding("M007", page, l.line, f"image `{l.href}` has no alt text"))
        if l.href.startswith("/") and not (ctx.cfg.root / l.href.lstrip("/")).exists():
            out.append(finding("M007", page, l.line, f"image `{l.href}` not found under the kb root"))
    return out


@rule("M008", "semantics", "warning", "Related link is one-way", """
Related sections cross-link both ways: if this page relates to `/x/y`, page
`/x/y` should list this page in its own Related section.
""")
def related_bidirectional(page: Page, ctx: Ctx) -> list[Finding]:
    sec = page.section("related")
    if sec is None:
        return []
    out = []
    for l in page.links:
        if not (sec.body_start <= l.line < sec.end) or not l.href.startswith("/"):
            continue
        slug = l.href.partition("#")[0].strip("/")
        other = ctx.page_by_slug(slug)
        if other is None or other.section("related") is None:
            continue
        osec = other.section("related")
        back = any(ol.href.partition("#")[0].strip("/") == page.slug
                   for ol in other.links if osec.body_start <= ol.line < osec.end)
        if not back:
            out.append(finding("M008", page, l.line, f"`/{slug}` does not link back here from its Related section"))
    return out


@rule("M009", "semantics", "error", "roadmap status vs nav group", """
The nav group named by settings.openRoadmapGroup holds exactly the roadmap
pages with `status: open`. An executed or dropped plan leaves that group (it
stays in the kb as a design record); an open plan must be listed there.
""")
def roadmap_status_nav(page: Page, ctx: Ctx) -> list[Finding]:
    group = ctx.cfg.settings.get("openRoadmapGroup")
    if not group:
        return []
    fm = page.frontmatter or {}
    in_group = ctx.cfg.group_of(page.slug) == group
    is_open = page.kind == "roadmap" and fm.get("status") == "open"
    if in_group and not is_open:
        return [finding("M009", page, 0, f"listed in nav group `{group}` but not an open roadmap page")]
    if is_open and not in_group:
        return [finding("M009", page, 0, f"status: open but not listed in nav group `{group}`")]
    return []
