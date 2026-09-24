import asyncio
import json
import threading

from librari.search import LiveIndex, build_db, clean_body, format_hits, query, read_page, search


def test_search_ranks_the_section_that_holds_the_body_text(cfg):
    hits = search(cfg, "stale DNS 502")
    assert hits and hits[0]["ref"] == "calendar/radicale#agent:gotchas"
    assert hits[0]["match"] == "and" and "[stale]" in hits[0]["snippet"]


def test_search_finds_identifiers_in_tables_and_code(cfg):
    hits = search(cfg, "nginx.conf")
    assert "calendar/radicale#agent:key-files" in {h["ref"] for h in hits}
    assert all(h["anchor"] == "key-files" for h in hits)
    assert search(cfg, "podman ps")[0]["ref"] == "calendar/radicale#agent:verify"


def test_search_lead_row_and_title_weight(cfg):
    hits = search(cfg, "dav.example.com")
    assert hits[0]["ref"] == "calendar/radicale" and hits[0]["anchor"] == ""


def test_search_falls_back_to_any_word_and_reports_it(cfg):
    hits = search(cfg, "radicale zzzznotaword")
    assert hits and hits[0]["match"] == "or"
    assert "ranked by any word" in format_hits(hits)
    assert search(cfg, "zzzznotaword") == [] and format_hits([]) == "no match"


def test_search_operator_words_and_quotes_are_literal(cfg):
    db = build_db(cfg)
    assert query(db, 'AND OR NOT "') == [] or True          # must not raise
    assert query(db, "NEAR nginx")[0]["slug"] == "calendar/radicale"


def test_search_stems_and_reports_lines_and_description(cfg):
    hits = search(cfg, "resolving upstream")              # page says "resolves"/"resolve"
    assert hits and hits[0]["slug"] == "calendar/radicale"
    h = search(cfg, "stale DNS")[0]
    assert h["lines"][0] < h["lines"][1] and h["description"] == "How CalDAV is proxied to Radicale."
    txt = format_hits([h])
    assert f"L{h['lines'][0]}-{h['lines'][1]}" in txt and "page: How CalDAV" in txt


def test_search_indexes_unanchored_h2_regions(kb, cfg):
    p = kb / "calendar/radicale.md"
    p.write_text(p.read_text().replace("## Gotchas <!-- agent:gotchas -->",
                                       "## Finishing a stuck import\n\nSet `innodb_snapshot_isolation=OFF` live.\n\n"
                                       "## Gotchas <!-- agent:gotchas -->"))
    h = search(cfg, "innodb_snapshot_isolation")[0]
    assert h["ref"] == "calendar/radicale#finishing-a-stuck-import" and h["anchor"] == ""
    assert h["heading"] == "Finishing a stuck import" and h["lines"][1] - h["lines"][0] <= 4
    assert search(cfg, "stale DNS")[0]["ref"] == "calendar/radicale#agent:gotchas"   # anchored rows intact


def test_search_related_ranked_down(kb, cfg):
    p = kb / "calendar/radicale.md"
    p.write_text(p.read_text().rstrip("\n") + "\n- [Users](/identity/users) — zebra zebra zebra.\n")
    hits = search(cfg, "zebra")
    assert hits[0]["anchor"] == "related" and hits[0]["score"] < 20


def test_read_page_guard_on_long_pages(kb, cfg):
    p = kb / "calendar/radicale.md"
    p.write_text(p.read_text() + "\n" + "\n".join(f"filler {i}" for i in range(500)))
    out = read_page(cfg, "calendar/radicale")
    assert out.startswith("---\ntitle:") and "body withheld" in out and "<agent:gotchas>" in out and "filler 400" not in out
    assert "filler 400" in read_page(cfg, "calendar/radicale", force=True)
    assert "podman ps" in read_page(cfg, "calendar/radicale", "verify")


def test_penalty_applies_before_the_limit(kb, cfg):
    p = kb / "calendar/radicale.md"
    body = p.read_text().replace("| 2026-06-08 | lesson | Initial page. |",
                                 "| 2026-06-08 | lesson | Initial page. |\n" + "\n".join(
                                     f"| 2026-06-0{i} | fix | kumquat kumquat kumquat row {i}. |" for i in range(1, 6)))
    body = body.replace("- **502 → stale DNS → `resolve`.**", "- **502 → stale DNS → `resolve`.** kumquat once.")
    p.write_text(body)
    assert search(cfg, "kumquat", limit=1)[0]["anchor"] == "gotchas"      # changelog would win on raw bm25


def test_unanchored_related_is_penalised_and_nested_sections_indexed_once(kb, cfg):
    p = kb / "calendar/radicale.md"
    p.write_text(p.read_text().replace("## Gotchas <!-- agent:gotchas -->",
                                       "## Region\n\nwombat in region\n\n### Nested <!-- agent:nested -->\n\nwombat nested\n\n"
                                       "## Gotchas <!-- agent:gotchas -->")
                 .replace("## Related <!-- agent:related -->", "## Related"))
    hits = search(cfg, "wombat")
    assert {h["ref"] for h in hits} == {"calendar/radicale#region", "calendar/radicale#agent:nested"}
    assert all("nested" not in h["snippet"] for h in hits if h["ref"].endswith("#region"))
    from librari.search import rows_for
    from librari.parse import parse_file
    rows = rows_for(parse_file(p, cfg.root, cfg.settings["directives"]))
    assert [r[-1] for r in rows if r[2] == "Related"] == [0.5]


def test_read_page_resolves_unanchored_region(kb, cfg):
    p = kb / "calendar/radicale.md"
    p.write_text(p.read_text().replace("## Gotchas <!-- agent:gotchas -->",
                                       "## Finishing a stuck import\n\nSet it OFF.\n\n## Gotchas <!-- agent:gotchas -->"))
    out = read_page(cfg, "calendar/radicale", "finishing-a-stuck-import")
    assert out.startswith("## Finishing a stuck import") and "Set it OFF." in out and "Gotchas" not in out
    import pytest
    from librari.sections import SectionError
    with pytest.raises(SectionError, match="un-anchored regions: finishing-a-stuck-import"):
        read_page(cfg, "calendar/radicale", "nope")


def test_unicode_terms_and_limit_clamp(cfg):
    from librari.search import _terms
    assert _terms("Postfächer Überstunden") == ['"Postfächer"', '"Überstunden"']
    assert len(search(cfg, "nginx", limit=-1)) == 1 and len(search(cfg, "nginx", limit=0)) == 1


def test_live_index_survives_thread_changes(cfg):
    live = LiveIndex(cfg)
    results, errors = [], []

    def worker():
        try:
            results.append(live.search("stale DNS")[0]["ref"])
        except Exception as e:                     # sqlite same-thread check would land here
            errors.append(repr(e))
    for _ in range(3):
        th = threading.Thread(target=worker); th.start(); th.join()
    assert errors == [] and results == ["calendar/radicale#agent:gotchas"] * 3


def test_search_kind_filter_and_json(cfg):
    assert search(cfg, "nginx", kind="runbook") == []
    out = json.loads(format_hits(search(cfg, "nginx", kind="topic"), "json"))
    assert out[0]["slug"] == "calendar/radicale" and out[0]["kind"] == "topic"


def test_search_drops_stopwords_and_ranks_changelog_last(cfg):
    hits = search(cfg, "why is the DNS stale")
    assert hits[0]["ref"] == "calendar/radicale#agent:gotchas" and hits[0]["match"] == "and"
    hits = search(cfg, "initial page")            # only the changelog row says this
    assert hits and hits[0]["anchor"] == "changelog"
    hits = search(cfg, "nginx")                   # changelog never outranks a body section for a shared word
    assert hits[0]["anchor"] != "changelog"
    assert search(cfg, "the of") == search(cfg, "the of")  # stopword-only query: words kept, no crash


def test_clean_body_strips_comments_and_directive_markers():
    text = clean_body(["<!-- agent:x -->", ":::warning", "Footgun `a.b`", ":::", ":::step Clear the cache", "", "x",
                       "| File | Role |", "|------|------|", "| `a` | b |"])
    assert text == "Footgun `a.b`\nClear the cache\nx\n| File | Role |\n| `a` | b |"


def test_read_page_whole_and_section(cfg):
    whole = read_page(cfg, "calendar/radicale")
    assert whole.startswith("---\ntitle:") and "podman ps" in whole
    sec = read_page(cfg, "calendar/radicale.md", "agent:verify")
    assert sec.startswith("## How to detect / verify") and "podman ps" in sec and "Changelog" not in sec


def test_live_index_rebuilds_after_a_page_changes(kb, cfg):
    live = LiveIndex(cfg)
    assert live.search("qqqunique") == []
    p = kb / "calendar/radicale.md"
    p.write_text(p.read_text().replace("inner warning inside a step", "inner warning qqqunique inside a step"))
    assert live.search("qqqunique")[0]["ref"] == "calendar/radicale#agent:how"


def test_search_cli_exit_codes(cfg, capsys):
    from librari.search import cli
    assert cli(cfg, ["stale", "dns"], 5, "", "text") == 0
    assert "calendar/radicale#agent:gotchas" in capsys.readouterr().out
    assert cli(cfg, ["zzzznotaword"], 5, "", "text") == 1


def test_mcp_search_and_read_page(cfg):
    from librari.mcp_server import build
    srv = build(cfg)
    names = {t.name for t in asyncio.run(srv.list_tools())}
    assert {"search", "read_page"} <= names
    res = str(asyncio.run(srv.call_tool("search", {"query": "stale DNS"})))
    assert "calendar/radicale#agent:gotchas" in res
    res = str(asyncio.run(srv.call_tool("read_page", {"page": "calendar/radicale", "anchor": "key-files"})))
    assert "nginx/nginx.conf" in res
    res = str(asyncio.run(srv.call_tool("read_page", {"page": "calendar/radicale", "anchor": "nope"})))
    assert "no section" in res and "[exit 1]" in res
