import io
import sys
from types import SimpleNamespace as NS

import pytest

from librari import sections
from librari.changelog import add_row
from librari.check import run
from librari.fmt import format_text
from librari.index import owner, pages_for
from librari.scaffold import new_page
from librari.config import load


def _args(**kw):
    base = dict(page=None, anchor=None, src=None, create=False, heading=None, allow_drop=False,
                no_check=False, with_heading=False, before=None, after=None)
    base.update(kw)
    return NS(**base)


def test_section_get_and_list(cfg, capsys):
    assert sections.cli(cfg, _args(action="get", page="calendar/radicale", anchor="key-files")) == 0
    out = capsys.readouterr().out
    assert "| `nginx/nginx.conf` | reverse proxy |" in out and "## Key files" not in out
    sections.cli(cfg, _args(action="list", page="calendar/radicale"))
    assert "agent:verify" in capsys.readouterr().out


def test_section_set_refuses_detail_loss(cfg, kb, tmp_path, capsys):
    new = tmp_path / "new.md"
    new.write_text("A readable rewrite with no command.\n")
    rc = sections.cli(cfg, _args(action="set", page="calendar/radicale", anchor="verify", src=str(new)))
    assert rc == 1
    err = capsys.readouterr().err
    assert "drops actionable detail" in err and "podman ps --filter name=radicale" in err
    assert "podman ps" in (kb / "calendar/radicale.md").read_text()      # unchanged
    rc = sections.cli(cfg, _args(action="set", page="calendar/radicale", anchor="verify", src=str(new), allow_drop=True))
    assert rc == 0 and "podman ps" not in (kb / "calendar/radicale.md").read_text()


def test_section_set_keeps_detail_when_moved(cfg, kb, tmp_path):
    new = tmp_path / "new.md"
    new.write_text("Reworded.\n\n```bash\npodman ps --filter name=radicale\n```\n")
    rc = sections.cli(cfg, _args(action="set", page="calendar/radicale", anchor="verify", src=str(new)))
    assert rc == 0


def test_section_set_refuses_new_errors(cfg, kb, tmp_path, capsys):
    new = tmp_path / "new.md"
    new.write_text("```\nno language\n```\n")
    rc = sections.cli(cfg, _args(action="set", page="calendar/radicale", anchor="gotchas", src=str(new)))
    assert rc == 1 and "S002" in capsys.readouterr().err


def test_section_create_at_canonical_position(cfg, kb, tmp_path):
    new = tmp_path / "new.md"
    new.write_text("| Env var / setting | Purpose | Default |\n|---|---|---|\n| `X` | y | z |\n")
    rc = sections.cli(cfg, _args(action="set", page="identity/users", anchor="config", src=str(new), create=True))
    assert rc == 0
    text = (kb / "identity/users.md").read_text()
    assert text.index("agent:key-files") < text.index("agent:config") < text.index("agent:verify")
    assert run(cfg, [str(kb / "identity/users.md")]).verdict == "GREEN" or \
        {f.rule for f in run(cfg, [str(kb / "identity/users.md")]).errors} == {"C010"}


def test_section_append_and_move(cfg, kb, tmp_path):
    extra = tmp_path / "x.md"
    extra.write_text("- **New symptom → cause → fix.**\n")
    assert sections.cli(cfg, _args(action="append", page="calendar/radicale", anchor="gotchas", src=str(extra))) == 0
    assert "New symptom" in (kb / "calendar/radicale.md").read_text()
    # moving gotchas above how would violate the canonical order → refused, page unchanged
    assert sections.cli(cfg, _args(action="move", page="calendar/radicale", anchor="gotchas", before="how")) == 1
    text = (kb / "calendar/radicale.md").read_text()
    assert text.index("agent:how") < text.index("agent:gotchas")
    # a legal move (page-specific anchor) succeeds
    text = text.replace("## Gotchas <!-- agent:gotchas -->", "## Gotchas <!-- agent:gotchas -->\n\n## Extra <!-- agent:extra -->\n\nfree text\n")
    (kb / "calendar/radicale.md").write_text(text)
    assert sections.cli(cfg, _args(action="move", page="calendar/radicale", anchor="extra", before="decision")) == 0
    text = (kb / "calendar/radicale.md").read_text()
    assert text.index("agent:extra") < text.index("agent:decision")


def test_changelog_add(cfg, kb, capsys):
    assert add_row(cfg, "calendar/radicale", "fix", "wording | with pipe", "2026-09-21") == 0
    text = (kb / "calendar/radicale.md").read_text()
    assert "| 2026-09-21 | fix | wording \\| with pipe |" in text
    assert add_row(cfg, "calendar/radicale", "bogus", "x") == 2
    assert add_row(cfg, "calendar/radicale", "fix", "x", "21.09.2026") == 2


def test_fmt_idempotent_and_structure_preserving(cfg, kb):
    src = (kb / "calendar/radicale.md").read_text().replace("## Key files <!-- agent:key-files -->", "##   Key files    <!-- agent:key-files -->")
    once = format_text(src, cfg.settings["directives"])
    assert format_text(once, cfg.settings["directives"]) == once
    assert "## Key files <!-- agent:key-files -->" in once
    assert "| `nginx/nginx.conf` | reverse proxy |" in once
    assert ":::::steps" in once and "::::step Proxy" in once


def test_new_page_and_nav(cfg, kb, tmp_path, monkeypatch):
    monkeypatch.setattr("librari.scaffold.TEMPLATES", tmp_path / "no-templates")  # force the kb override path
    (kb / "_templates").mkdir()
    (kb / "_templates" / "topic.md").write_text("---\ntitle: t\n---\n\nLead.\n\n## Key files <!-- agent:key-files -->\n\n| File | Role |\n|---|---|\n| `nginx/nginx.conf` | x |\n\n## How to detect / verify <!-- agent:verify -->\n\n```bash\ntrue\n```\n\n## Changelog <!-- agent:changelog -->\n\n| Date | Type | Summary |\n|---|---|---|\n| YYYY-MM-DD | feat | Initial page. |\n")
    assert new_page(cfg, "identity/groups", "topic", "Groups", "Identity", keywords="groups") == 0
    cfg2 = load(kb)
    assert "identity/groups" in cfg2.nav_pages()
    r = run(cfg2, [str(kb / "identity/groups.md")])
    assert r.verdict == "GREEN", [f.as_dict() for f in r.findings]
    assert new_page(cfg2, "identity/groups", "topic", "Groups", "Identity") == 2   # exists
    assert new_page(cfg2, "identity/x", "nope", "X", "Identity") == 2             # bad kind


def test_owner_and_pages_for(cfg):
    ranked = owner(cfg, "radicale caldav")
    assert ranked[0][1] == "calendar/radicale"
    hits = pages_for(cfg, "nginx/nginx.conf")
    assert [h[0] for h in hits] == ["calendar/radicale", "identity/users"]
    assert pages_for(cfg, "nginx/other.conf") == []


def test_move_refuses_nested_sections_and_uses_reduced_positions(cfg, kb, capsys):
    text = (kb / "calendar/radicale.md").read_text().replace(
        "## How it works <!-- agent:how -->",
        "## How it works <!-- agent:how -->\n\n### A <!-- agent:sub -->\n\nsub body\n\n### B <!-- agent:sub2 -->\n\nsub2 body\n")
    (kb / "calendar/radicale.md").write_text(text)
    assert sections.cli(cfg, _args(action="move", page="calendar/radicale", anchor="sub", after="how")) == 2
    assert "nested" in capsys.readouterr().err
    # a legal move of a page-specific H2 far down the page lands exactly after the reference
    text = (kb / "calendar/radicale.md").read_text() + "\n## Tail <!-- agent:tail -->\n\ntail body\n"
    (kb / "calendar/radicale.md").write_text(text)
    assert sections.cli(cfg, _args(action="move", page="calendar/radicale", anchor="tail", before="decision")) == 0
    out = (kb / "calendar/radicale.md").read_text()
    assert out.index("agent:tail") < out.index("agent:decision") and "tail body" in out
    assert "```bash\npodman ps --filter name=radicale\n```" in out   # verify fence intact


def test_fmt_only_change_does_not_trigger_c010(cfg, kb):
    p = kb / "calendar/radicale.md"
    p.write_text(p.read_text().replace("## Key files <!-- agent:key-files -->", "##   Key files   <!-- agent:key-files -->"))
    r = run(cfg, [str(p)], rules={"C010"})
    assert r.findings == []


def test_section_load_outside_kb(cfg, tmp_path, capsys):
    other = tmp_path / "outside.md"
    other.write_text("---\ntitle: x\n---\n")
    assert sections.cli(cfg, _args(action="list", page=str(other))) == 2


def test_section_set_protects_indented_code_blocks(cfg, kb, tmp_path, capsys):
    p = kb / "calendar/radicale.md"
    p.write_text(p.read_text().replace("- **502 → stale DNS → `resolve`.**", "    indented-block-content\n\n- **502 → stale DNS → `resolve`.**"))
    new = tmp_path / "new.md"
    new.write_text("- rewritten bullet only\n")
    rc = sections.cli(cfg, _args(action="set", page="calendar/radicale", anchor="gotchas", src=str(new)))
    assert rc == 1 and "indented-block-content" in capsys.readouterr().err
