"""`librari render` — the kb as a static site (phase 3).

One directory per page (`<slug>/index.html`, so `/group/slug` and
`/group/slug/` both resolve behind any static server), a sidebar from the nav
groups, a per-page table of contents, `agent:*` anchors as real heading ids
(`#agent:verify` deep-links work), directives rendered as callouts / steps /
cards / accordions, Pygments code highlighting, Mermaid via the client, and a
dependency-free client-side search over `search.json`. No JavaScript
framework, no build tool: the output is plain files for nginx.
"""
from __future__ import annotations

import html
import json
import re
import shutil
from pathlib import Path

from markdown_it import MarkdownIt
from markdown_it.token import Token
from mdit_py_plugins.container import container_plugin
from mdit_py_plugins.front_matter import front_matter_plugin
from pygments import highlight
from pygments.formatters import HtmlFormatter
from pygments.lexers import get_lexer_by_name
from pygments.util import ClassNotFound

from .config import KbConfig
from .model import Page
from .index import lead_of
from .parse import ANCHOR_RE, ID_ANCHOR_RE, ID_OPEN_RE, parse_file
from .rules.semantics import _heading_slugs

CALLOUTS = ("note", "info", "tip", "warning", "check", "danger")
CALLOUT_LABEL = {"note": "Note", "info": "Info", "tip": "Tip", "warning": "Warning", "check": "Check", "danger": "Danger"}
ASSETS = Path(__file__).parent / "assets"


from .model import slug_of_heading  # noqa: E402 — shared with search


class Site:
    def __init__(self, cfg: KbConfig, base_path: str = "/", cdn: bool = True):
        self.cfg = cfg
        self.base = "/" + base_path.strip("/") + "/" if base_path.strip("/") else "/"
        self.cdn = cdn
        self.pages: dict[str, Page] = {}
        self.dangling: list[tuple[str, str]] = []   # (page, href) links no rendered page answers
        for p in cfg.all_pages():
            pg = parse_file(p, cfg.root, cfg.settings["directives"])
            self.pages[pg.slug] = pg
        self.md = self._parser()

    # -- markdown-it -------------------------------------------------------
    def _parser(self) -> MarkdownIt:
        md = MarkdownIt("commonmark", {"html": True, "linkify": False}).enable("table")
        md.use(front_matter_plugin)
        for name in self.cfg.settings["directives"]:
            md.use(container_plugin, name=name)
        site = self

        def container_open(name):
            def render(renderer, tokens, idx, options, env):
                t = tokens[idx]
                title = t.info.strip()[len(name):].strip()
                if name in CALLOUTS:
                    return f'<div class="callout {name}"><div class="callout-label">{CALLOUT_LABEL[name]}</div><div class="callout-body">\n'
                if name == "steps":
                    return '<ol class="steps">\n'
                if name == "step":
                    return f'<li class="step"><div class="step-title">{html.escape(title)}</div><div class="step-body">\n'
                if name == "cards":
                    return '<div class="cards">\n'
                if name == "accordion":
                    return f'<details class="accordion"><summary>{html.escape(title)}</summary><div class="accordion-body">\n'
                return "<div>\n"
            return render

        def container_close(name):
            closers = {"steps": "</ol>\n", "step": "</div></li>\n", "cards": "</div>\n",
                       "accordion": "</div></details>\n"}
            def render(renderer, tokens, idx, options, env):
                return closers.get(name, "</div></div>\n" if name in CALLOUTS else "</div>\n")
            return render

        for name in self.cfg.settings["directives"]:
            md.add_render_rule(f"container_{name}_open", container_open(name))
            md.add_render_rule(f"container_{name}_close", container_close(name))

        def fence(renderer, tokens, idx, options, env):
            t = tokens[idx]
            info = t.info.strip().split()
            lang = info[0] if info else "text"
            tag = " ".join(info[1:])
            code = t.content
            if lang == "mermaid":
                return f'<pre class="mermaid">{html.escape(code)}</pre>\n'
            try:
                lexer = get_lexer_by_name(lang)
            except ClassNotFound:
                lexer = get_lexer_by_name("text")
            body = highlight(code, lexer, HtmlFormatter(nowrap=True))
            label = f'<span class="code-lang">{html.escape(lang)}{(" · " + html.escape(tag)) if tag else ""}</span>'
            return f'<div class="code">{label}<pre><code class="language-{html.escape(lang)}">{body}</code></pre></div>\n'
        md.add_render_rule("fence", fence)

        def heading_open(renderer, tokens, idx, options, env):
            t = tokens[idx]
            inline = tokens[idx + 1] if idx + 1 < len(tokens) and tokens[idx + 1].type == "inline" else None
            content = inline.content if inline else ""
            text = ANCHOR_RE.sub("", content).strip()
            m = ANCHOR_RE.search(content)
            # every id the validator accepts must resolve in the browser: the
            # agent anchor, then BOTH slug dialects; duplicates get -1, -2 …
            seen: dict = env.setdefault("ids", {})
            ids = ([f"agent:{m.group(1)}"] if m else []) + sorted(_heading_slugs(text), key=len)
            uniq = []
            for i in dict.fromkeys(ids):
                if not i:
                    continue
                n = seen.get(i, 0)
                seen[i] = n + 1
                uniq.append(i if n == 0 else f"{i}-{n}")
            main = uniq[0] if uniq else ""
            env.setdefault("headings", []).append((int(t.tag[1]), text, main))
            extra = "".join(f'<span id="{html.escape(i)}"></span>' for i in uniq[1:])
            return f'{extra}<{t.tag} id="{html.escape(main)}">'
        md.add_render_rule("heading_open", heading_open)

        def html_inline(renderer, tokens, idx, options, env):
            c = tokens[idx].content
            if ANCHOR_RE.fullmatch(c.strip()) or c.strip().startswith("<!--"):
                return ""
            m = ID_ANCHOR_RE.fullmatch(c.strip()) or ID_OPEN_RE.fullmatch(c.strip())
            if m:
                return f'<span id="{html.escape(m.group(1))}"></span>'
            if c.strip() == "</a>" and idx > 0 and tokens[idx - 1].type == "html_inline" \
                    and ID_OPEN_RE.fullmatch(tokens[idx - 1].content.strip()):
                return ""
            return html.escape(c)
        md.add_render_rule("html_inline", html_inline)

        def html_block(renderer, tokens, idx, options, env):
            c = tokens[idx].content
            out = ""
            for m in ID_ANCHOR_RE.finditer(c):
                out += f'<span id="{html.escape(m.group(1))}"></span>'
            rest = re.sub(r"<!--.*?-->", "", ID_ANCHOR_RE.sub("", c), flags=re.S).strip()
            return out + (f"<p>{html.escape(rest)}</p>\n" if rest else "")
        md.add_render_rule("html_block", html_block)

        def link_open(renderer, tokens, idx, options, env):
            t = tokens[idx]
            href = t.attrGet("href") or ""
            t.attrSet("href", site.rewrite_href(href, env))
            if re.match(r"^https?:", href, re.I) or href.startswith("//"):
                t.attrSet("target", "_blank")        # web links only — never mailto:/tel:
                t.attrSet("rel", "noopener")
            return renderer.renderToken(tokens, idx, options, env)
        md.add_render_rule("link_open", link_open)

        def image(renderer, tokens, idx, options, env):
            t = tokens[idx]
            src = t.attrGet("src") or ""
            if src.startswith("/") and not src.startswith("//"):
                t.attrSet("src", site.base + src.lstrip("/"))
            return f'<img src="{html.escape(t.attrGet("src") or "")}" alt="{html.escape(t.content)}">'
        md.add_render_rule("image", image)
        return md

    def rewrite_href(self, href: str, env: dict | None = None) -> str:
        if not href or re.match(r"^[a-z][a-z0-9+.-]*:", href, re.I) or href.startswith("//"):
            return href
        if href.startswith("#"):
            return href
        path, _, frag = href.partition("#")
        slug = path.strip("/")
        if slug == "index":
            slug = ""                      # the landing page lives at the site root
        elif slug and slug not in self.pages and env is not None:
            # accepted by the validator only via legacyDocsDir — dead on this site
            env.setdefault("dangling", []).append(href)
        target = self.base + (slug + "/" if slug else "")
        return target + (f"#{frag}" if frag else "")

    # -- page --------------------------------------------------------------
    def render_page(self, page: Page) -> str:
        fm = page.frontmatter or {}
        body_md = "\n".join(page.lines[page.frontmatter_end:])
        # a self-closing <a id="x" /> ALONE on a line is an html_block that runs to
        # the next blank line (CommonMark type 7) and would turn the paragraph
        # after it into literal text; the <a id="x"></a> form stays inline
        body_md = re.sub(r"""(?m)^(\s*)<a\s+id=(["'])([A-Za-z0-9_.:-]+)\2\s*/>\s*$""", r"\1<a id=\2\3\2></a>", body_md)
        env = {"slug": page.slug, "headings": []}
        body = self.md.render(body_md, env)
        for href in env.get("dangling", []):
            self.dangling.append((page.rel, href))
        toc = "".join(f'<li class="toc-h{level}"><a href="#{html.escape(hid)}">{html.escape(text)}</a></li>'
                      for level, text, hid in env["headings"] if level in (2, 3) and hid)
        kind = page.kind or ""
        status = fm.get("status")
        badges = f'<span class="badge kind-{html.escape(kind)}">{html.escape(kind)}</span>' if kind else ""
        if status:
            badges += f'<span class="badge status-{html.escape(str(status))}">{html.escape(str(status))}</span>'
        keywords = ", ".join(fm.get("keywords", []) if isinstance(fm.get("keywords"), list) else [])
        return self.layout(
            title=fm.get("title", page.slug), description=fm.get("description", ""), keywords=keywords,
            content=f'<article class="page"><header><h1>{html.escape(fm.get("title", page.slug))}</h1>'
                    f'<p class="description">{html.escape(fm.get("description", ""))}</p><div class="badges">{badges}'
                    f'<span class="src">kb/{html.escape(page.rel)}</span></div></header>{body}</article>',
            toc=f'<nav class="toc"><div class="toc-title">On this page</div><ul>{toc}</ul></nav>' if toc else "",
            current=page.slug)

    def sidebar(self, current: str) -> str:
        out = []
        for g in self.cfg.groups:
            items = []
            for slug in g.get("pages", []):
                pg = self.pages.get(slug)
                if pg is None:
                    continue
                title = (pg.frontmatter or {}).get("title", slug)
                cls = ' class="active"' if slug == current else ""
                href = self.base if slug == "index" else f"{self.base}{slug}/"
                items.append(f'<li{cls}><a href="{href}">{html.escape(title)}</a></li>')
            if items:
                out.append(f'<details class="nav-group" open><summary>{html.escape(g["group"])}</summary><ul>{"".join(items)}</ul></details>')
        return "".join(out)

    def layout(self, title: str, description: str, keywords: str, content: str, toc: str, current: str) -> str:
        mermaid = ((f'<script src="https://cdn.jsdelivr.net/npm/mermaid@11.17.2/dist/mermaid.min.js" integrity="sha384-EOXBFmc3gx5mb+vn0vPvvGqACToJD24hhacX5Yx+8NUUQrHIle/Qi5Bg9o3zKwW2" crossorigin="anonymous" defer></script>'
                    '<script>addEventListener("DOMContentLoaded",()=>{window.mermaid&&mermaid.initialize({startOnLoad:true,'
                    'theme:matchMedia("(prefers-color-scheme: dark)").matches?"dark":"default"})});</script>')
                   if self.cdn else "")
        return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>{html.escape(title)} — {html.escape(self.cfg.name)}</title>
<meta name="description" content="{html.escape(description)}"><meta name="keywords" content="{html.escape(keywords)}">
<link rel="stylesheet" href="{self.base}assets/style.css"><link rel="stylesheet" href="{self.base}assets/pygments.css">
<script defer src="{self.base}assets/site.js"></script>{mermaid}</head>
<body data-base="{html.escape(self.base)}">
<header class="top"><a class="brand" href="{self.base}">{html.escape(self.cfg.name)}</a>
<div class="search"><input id="q" type="search" placeholder="Search pages… (press /)" autocomplete="off"><ul id="results" hidden></ul></div>
<button class="nav-toggle" aria-label="menu">☰</button></header>
<div class="shell"><aside class="sidebar">{self.sidebar(current)}</aside>
<main>{content}</main>{toc}</div>
<footer class="foot">{html.escape(self.cfg.description)}</footer>
</body></html>
"""

    # -- site --------------------------------------------------------------
    MARKER = ".librari-site"

    def build(self, out: Path) -> dict:
        """Write the site into `out`, replacing a previous build (so renamed or
        deleted pages leave no stale copy). Refuses a non-empty directory that
        was not produced by librari — never `rm -rf` somebody else's files."""
        out = Path(out).resolve()          # a symlinked web root is fine; rmtree needs the real dir
        if out.exists() and not out.is_dir():
            raise SystemExit(f"librari render: {out} is not a directory")
        if out.exists():
            if any(out.iterdir()) and not (out / self.MARKER).exists():
                raise SystemExit(f"librari render: {out} is not empty and not a librari site (no {self.MARKER}); "
                                 "choose another --out or empty it yourself")
            shutil.rmtree(out)
        out.mkdir(parents=True)
        (out / self.MARKER).write_text("built by librari render\n", encoding="utf-8")
        (out / "assets").mkdir(exist_ok=True)
        for f in ASSETS.glob("*"):
            shutil.copy(f, out / "assets" / f.name)
        (out / "assets" / "pygments.css").write_text(
            HtmlFormatter(style="default").get_style_defs(".code pre") + "\n@media (prefers-color-scheme: dark){"
            + HtmlFormatter(style="monokai").get_style_defs(".code pre") + "}\n", encoding="utf-8")
        if (self.cfg.root / "images").is_dir():
            shutil.copytree(self.cfg.root / "images", out / "images", dirs_exist_ok=True)
        search = []
        n = 0
        for slug, page in self.pages.items():
            target = out / slug / "index.html"
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(self.render_page(page), encoding="utf-8")
            fm = page.frontmatter or {}
            search.append({"slug": slug, "title": fm.get("title", slug), "description": fm.get("description", ""),
                           "keywords": fm.get("keywords", []) if isinstance(fm.get("keywords"), list) else [],
                           "headings": [h.text for h in page.headings if h.level <= 3], "lead": lead_of(page, 300),
                           "group": self.cfg.group_of(slug) or ""})
            n += 1
        (out / "search.json").write_text(json.dumps(search, ensure_ascii=False), encoding="utf-8")
        if "index" not in self.pages:
            (out / "index.html").write_text(self.layout(self.cfg.name, self.cfg.description, "",
                                            f"<article class='page'><h1>{html.escape(self.cfg.name)}</h1><p>{html.escape(self.cfg.description)}</p></article>",
                                            "", ""), encoding="utf-8")
        else:
            shutil.copy(out / "index" / "index.html", out / "index.html")
        return {"pages": n, "out": str(out), "dangling": self.dangling}


def cli(cfg: KbConfig, out: str | None, base_path: str, cdn: bool, strict: bool = False) -> int:
    import sys
    target = Path(out) if out else (cfg.root.parent / "site")
    info = Site(cfg, base_path, cdn).build(target)
    for rel, href in info["dangling"]:
        print(f"{rel}: link `{href}` has no page on this site (legacy docs/ only)", file=sys.stderr)
    print(f"librari render: {info['pages']} page(s) → {info['out']}"
          + (f", {len(info['dangling'])} dangling link(s)" if info["dangling"] else ""))
    return 1 if (strict and info["dangling"]) else 0


def _kb_stamp(cfg: KbConfig) -> tuple:
    files = [*cfg.root.rglob("*.md"), cfg.config_path]
    return tuple(sorted((str(p), p.stat().st_mtime_ns) for p in files if p.exists()))


def serve(cfg: KbConfig, out: str | None, port: int, base_path: str, cdn: bool, watch: bool = True) -> int:
    """Like `mint dev`: render, serve on loopback, rebuild when kb/ changes
    (1 s mtime poll — no watcher dependency). Reach it from a laptop with
    `ssh -L 8090:127.0.0.1:8090 <host>` and open http://127.0.0.1:8090/."""
    import functools
    import http.server
    import threading
    import time
    root = Path(out) if out else (cfg.root.parent / "site")
    prefix = base_path.strip("/")
    # a base path is a URL prefix: build under <root>/<prefix>/ and serve <root>
    target = root / prefix if prefix else root
    Site(cfg, base_path, cdn).build(target)
    stamp = _kb_stamp(cfg)

    def watcher():
        nonlocal stamp
        while True:
            time.sleep(1)
            try:
                cur = _kb_stamp(cfg)
            except OSError:
                continue
            if cur != stamp:
                stamp = cur
                try:
                    from .config import load
                    info = Site(load(cfg.root), base_path, cdn).build(target)
                    print(f"rebuilt {info['pages']} page(s)" + (f", {len(info['dangling'])} dangling link(s)" if info["dangling"] else ""))
                except Exception as e:      # a half-written page must not kill the server
                    print(f"rebuild failed: {e}")

    if watch:
        threading.Thread(target=watcher, daemon=True).start()
    handler = functools.partial(http.server.SimpleHTTPRequestHandler, directory=str(root))
    print(f"serving {target} at http://127.0.0.1:{port}/{prefix + '/' if prefix else ''}"
          f"{'  (rebuilds on change; ' if watch else '  ('}Ctrl-C to stop)")
    with http.server.ThreadingHTTPServer(("127.0.0.1", port), handler) as srv:
        try:
            srv.serve_forever()
        except KeyboardInterrupt:
            pass
    return 0
