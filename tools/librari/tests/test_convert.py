from librari.convert import convert_text

MDX = """---
title: "T"
description: "D"
keywords: ["k"]
---

## How it works   {/* agent:how */}

<Steps>
  <Step title="One">
    Body one with `code`.

    ```bash
    echo hi
    ```
    <Warning>
      nested warning
    </Warning>
  </Step>
  <Step title="Two">Two body</Step>
</Steps>

<CardGroup cols={2}>
  <Card title="A" icon="x" href="/a/b">
    Desc A.
  </Card>
</CardGroup>

<Note>one-liner</Note>

## Changelog   {/* agent:changelog */}

| Date | Type | Summary |
|---|---|---|
| 2026-08-04 | docs | newer |
| 2026-07-02 | feat | older |
"""


def test_convert_components_and_colons(cfg):
    text, notes, fm = convert_text(MDX, "runbooks/x.mdx", cfg)
    assert fm["kind"] == "runbook"
    assert ":::::steps" in text and "::::step One" in text and ":::warning" in text
    assert ":::step Two\nTwo body\n:::" in text
    assert "- [A](/a/b) — Desc A." in text and ":::cards" in text
    assert ":::note\none-liner\n:::" in text
    assert "## How it works <!-- agent:how -->" in text or "## How it works   <!-- agent:how -->" in text
    assert "    echo hi" not in text and "echo hi" in text          # dedented
    assert text.index("| 2026-07-02 |") < text.index("| 2026-08-04 |")  # re-sorted oldest-first
    assert any("re-sorted" in n for n in notes)


def test_convert_roadmap_status(cfg):
    src = MDX.replace('title: "T"', 'title: "Plan — EXECUTED 2026-08-21"')
    _, notes, fm = convert_text(src, "roadmap/plan.mdx", cfg)
    assert fm["kind"] == "roadmap" and fm["status"] == "executed"


def test_convert_self_closing_and_quoted_attrs(cfg):
    src = MDX.replace('<Card title="A" icon="x" href="/a/b">\n    Desc A.\n  </Card>',
                      '<Card title=\'Q (</>) editor\' href="/q" />\n  <Card title="B" href="/b">B body</Card>')
    text, notes, _ = convert_text(src, "guides/x.mdx", cfg)
    assert "- [Q (</>) editor](/q)" in text and "- [B](/b) — B body" in text
    assert ":::note\none-liner\n:::" in text            # nothing after the self-closing card was swallowed


def test_convert_keeps_external_md_links(cfg):
    src = MDX + "\nSee [agents](https://example.com/x/AGENTS.md) and [local](/ops/backup.mdx).\n"
    text, _, _ = convert_text(src, "guides/x.mdx", cfg)
    assert "https://example.com/x/AGENTS.md" in text and "(/ops/backup)" in text


def test_convert_refuses_overwrite(cfg, kb, tmp_path, capsys):
    from librari.convert import cli as convert_cli
    (tmp_path / "docs" / "guides").mkdir(parents=True)
    src = tmp_path / "docs" / "guides" / "x.mdx"
    src.write_text(MDX)
    assert convert_cli(cfg, [str(src)], None, "Calendar", False) in (0, 1)
    (kb / "guides" / "x.md").write_text("enriched\n")
    assert convert_cli(cfg, [str(src)], None, "Calendar", False) == 1
    assert (kb / "guides" / "x.md").read_text() == "enriched\n"
    assert convert_cli(cfg, [str(src)], None, "Calendar", False, force=True) in (0, 1)
    assert (kb / "guides" / "x.md").read_text() != "enriched\n"
