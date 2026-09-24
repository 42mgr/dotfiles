from librari.parse import parse_text, scan_blocks


def test_nesting_models_markdown_it_outer_first_close():
    lines = ["::::steps", ":::step One", ":::warning", "w", ":::", ":::", "::::"]
    _, containers, _, stray = scan_blocks(lines)
    by = {c.name: c for c in containers}
    assert by["steps"].close_line == 6
    assert by["step"].close_line == 4            # the first bare ::: closes step, not warning
    assert by["warning"].auto_closed_by == 4     # warning was force-closed
    assert stray == [5]                          # the second ::: closes nothing


def test_container_markers_inside_code_fences_are_ignored():
    lines = ["```bash", ":::note", "```", ":::note", "x", ":::"]
    code, containers, unclosed, stray = scan_blocks(lines)
    assert len(code) == 1 and code[0].info == "bash"
    assert [c.name for c in containers] == ["note"] and containers[0].open_line == 3


def test_sections_and_anchors():
    p = parse_text("---\ntitle: t\n---\n## A <!-- agent:decision -->\nx\n### sub\ny\n## B <!-- agent:verify -->\nz\n", "p.md")
    assert p.anchors == ["decision", "verify"]
    dec = p.section("decision")
    assert (dec.start, dec.end) == (3, 7)        # H3 does not end an H2 section
    assert p.stray_anchors == []


def test_raw_html_and_backticked_placeholder():
    p = parse_text("---\ntitle: t\n---\nuse `<Entity>` but not <Entity> here\n", "p.md")
    assert [s for _, s in p.raw_html] == ["<Entity>"]


def test_front_matter_errors():
    assert parse_text("no front matter\n", "p.md").frontmatter is None
    bad = parse_text("---\ntitle: [unclosed\n---\n", "p.md")
    assert bad.frontmatter is None and bad.frontmatter_error


def test_closer_inside_fence_still_closes_container_like_markdown_it():
    lines = [":::note", "```text", ":::", "```", ":::", "## H <!-- agent:verify -->"]
    code, containers, unclosed, stray = scan_blocks(lines)
    note = containers[0]
    assert note.close_line == 2 and note.closed_in_fence == 1
    assert unclosed == [3]                       # the second ``` swallows the rest
    assert stray == []                           # line 4 is inside that fence: plain code, not a closer


def test_closing_fence_needs_at_most_three_spaces_indent():
    lines = ["```bash", "    ```", "more", "```"]
    code, _, unclosed, _ = scan_blocks(lines)
    assert unclosed == [] and code[0].end == 4 and "more" in code[0].content
