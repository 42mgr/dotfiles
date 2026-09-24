import json

from librari.render import Site


def test_render_site(cfg, kb, tmp_path):
    (kb / "index.md").write_text("---\ntitle: Home\ndescription: landing\nkeywords: [home]\nkind: reference\n---\n\nWelcome.\n\n## Changelog <!-- agent:changelog -->\n\n| Date | Type | Summary |\n|---|---|---|\n| 2026-09-22 | docs | init |\n")
    out = tmp_path / "site"
    info = Site(cfg, "/", cdn=False).build(out)
    assert info["pages"] == 3
    page = (out / "calendar/radicale/index.html").read_text()
    assert 'id="agent:key-files"' in page and 'id="agent:verify"' in page
    assert 'href="/identity/users/#agent:verify"' in page                  # internal link rewritten, fragment kept
    assert '<ol class="steps">' in page and 'class="step-title">Resolve' in page
    assert 'class="callout info"' in page and 'class="callout warning"' in page   # nested inside a step
    assert '<code class="language-bash">' in page and "mermaid" not in page
    assert "<table>" in page and "nginx/nginx.conf" in page
    assert 'class="active"' in page and 'href="/"' in page                 # sidebar + landing link
    search = json.loads((out / "search.json").read_text())
    assert {e["slug"] for e in search} == {"calendar/radicale", "identity/users", "index"}
    assert (out / "index.html").read_text() == (out / "index" / "index.html").read_text()
    assert (out / "assets" / "style.css").exists() and (out / "assets" / "site.js").exists()


def test_render_base_path_and_raw_html_escaped(cfg, kb, tmp_path):
    p = kb / "calendar/radicale.md"
    p.write_text(p.read_text().replace("Lead:", "Lead: <script>alert(1)</script> <a id=\"marker\"></a>"))
    out = tmp_path / "site"
    Site(cfg, "/docs", cdn=True).build(out)
    page = (out / "calendar/radicale/index.html").read_text()
    assert "<script>alert(1)</script>" not in page and "&lt;script&gt;" in page
    assert 'id="marker"' in page
    assert 'href="/docs/identity/users/"' in page and 'href="/docs/assets/style.css"' in page
    assert "mermaid.min.js" in page and 'integrity="sha384-' in page


def test_render_ids_both_dialects_dedupe_and_dangling(cfg, kb, tmp_path):
    p = kb / "calendar/radicale.md"
    p.write_text(p.read_text().replace("## Gotchas <!-- agent:gotchas -->",
                                       "## Gotchas <!-- agent:gotchas -->\n\n### How to detect / verify\n\ntext\n\n### How to detect / verify\n\nagain\n\nSee [legacy](/ops/legacy-only).\n"))
    out = tmp_path / "site"
    site = Site(cfg, "/", cdn=False)
    info = site.build(out)
    page = (out / "calendar/radicale/index.html").read_text()
    assert 'id="how-to-detect--verify"' in page and 'id="how-to-detect-verify"' in page   # both dialects
    assert 'id="how-to-detect-verify-1"' in page and 'id="how-to-detect--verify-1"' in page   # duplicates suffixed
    assert info["dangling"] == [("calendar/radicale.md", "/ops/legacy-only")]
    assert 'target="_blank" rel="noopener"' not in page or "http" in page
    # rebuild replaces the previous output; a foreign non-empty dir is refused
    (out / "calendar" / "stale" ).mkdir(); (out / "calendar/stale/index.html").write_text("old")
    site.build(out)
    assert not (out / "calendar/stale").exists()
    foreign = tmp_path / "foreign"; foreign.mkdir(); (foreign / "keep.txt").write_text("x")
    import pytest
    with pytest.raises(SystemExit):
        site.build(foreign)
    assert (foreign / "keep.txt").exists()


def test_render_block_id_anchor_keeps_paragraph_and_toc_matches_ids(cfg, kb, tmp_path):
    p = kb / "calendar/radicale.md"
    p.write_text(p.read_text().replace("- **502 → stale DNS → `resolve`.**",
                                       '<a id="s1" />\nSome **bold** and [link](/identity/users) here.\n\n- **502 → stale DNS → `resolve`.**')
                 .replace("## Gotchas <!-- agent:gotchas -->", "## Gotchas <!-- agent:gotchas -->\n\n### Dup\n\na\n\n### Dup\n\nb\n"))
    out = tmp_path / "site"
    Site(cfg, "/", cdn=True).build(out)
    page = (out / "calendar/radicale/index.html").read_text()
    assert '<span id="s1"></span>' in page and "<strong>bold</strong>" in page and 'href="/identity/users/"' in page
    assert 'href="#dup"' in page and 'href="#dup-1"' in page                  # TOC follows the de-duplicated ids
    assert 'integrity="sha384-' in page and "mermaid@11." in page
    assert 'href="mailto:' not in page or 'target="_blank"' not in page.split('href="mailto:')[1][:80]
