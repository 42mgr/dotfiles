import asyncio
import subprocess

from librari.config import load
from librari.diff import format_diff, page_diff
from librari.verify import blocks
from conftest import GOOD_PAGE


def test_diff_reports_dropped_detail_and_new_rows(cfg):
    new = GOOD_PAGE.replace("```bash\npodman ps --filter name=radicale\n```", "prose only now") \
                   .replace("| 2026-06-08 | lesson | Initial page. |", "| 2026-06-08 | lesson | Initial page. |\n| 2026-09-21 | fix | x |")
    d = page_diff(GOOD_PAGE, new, "calendar/radicale.md", cfg.settings["directives"])
    verify = next(s for s in d["sections"] if s["anchor"] == "verify")
    assert verify["status"] == "changed" and verify["code_dropped"]
    assert d["detail_lost"] and d["changelog_rows_added"] == ["2026-09-21 | fix | x"]
    md = format_diff(d, "md")
    assert "| `agent:verify` | changed |" in md and "detail dropped" in md
    assert all(s["status"] == "unchanged" for s in d["sections"] if s["anchor"] not in ("verify", "changelog"))


def test_diff_new_page(cfg):
    d = page_diff(None, GOOD_PAGE, "x.md", cfg.settings["directives"])
    assert d["new_page"] and all(s["status"] == "added" for s in d["sections"])


def test_diff_cli_changed(kb, cfg, capsys):
    from librari.diff import cli
    p = kb / "calendar/radicale.md"
    p.write_text(p.read_text().replace("nginx resolves", "nginx re-resolves"))
    rc = cli(cfg, [], True, None, "text")
    out = capsys.readouterr().out
    assert rc == 0 and "agent:how" in out and "changelog: NO new row" in out


def test_verify_blocks_and_denylist(kb, cfg):
    p = kb / "calendar/radicale.md"
    p.write_text(p.read_text().replace("```bash\npodman ps --filter name=radicale\n```",
                                       "```bash verify\ntrue\n```\n\n```bash verify\nrm -rf /tmp/x\n```"))
    found = blocks(cfg, "calendar/radicale")
    assert [b["denied"] for b in found] == [False, True] and found[0]["section"] == "verify"
    from librari.verify import cli
    assert cli(cfg, "calendar/radicale", True, 10) == 0      # denied block skipped, the other passes


def test_mcp_tools_roundtrip(kb, cfg):
    from librari.mcp_server import build
    srv = build(cfg)
    names = {t.name for t in asyncio.run(srv.list_tools())}
    assert {"check", "section_get", "section_set", "changelog_add", "owner", "pages_for", "diff"} <= names
    res = asyncio.run(srv.call_tool("section_get", {"page": "calendar/radicale", "anchor": "key-files"}))
    text = str(res)
    assert "nginx/nginx.conf" in text
    res = asyncio.run(srv.call_tool("section_set", {"page": "calendar/radicale", "anchor": "verify", "body": "gone"}))
    assert "drops actionable detail" in str(res)
    assert "podman ps" in (kb / "calendar/radicale.md").read_text()


def test_diff_moved_block_is_not_a_loss(cfg):
    moved = GOOD_PAGE.replace("```bash\npodman ps --filter name=radicale\n```", "prose") \
                     .replace("- **502 → stale DNS → `resolve`.**", "- **502 → stale DNS → `resolve`.**\n\n```bash\npodman ps --filter name=radicale\n```")
    d = page_diff(GOOD_PAGE, moved, "x.md", cfg.settings["directives"])
    assert not d["detail_lost"]


def test_derive_status_negations():
    from librari.convert import derive_status
    assert derive_status({"title": "Plan"}, "Status: not yet executed", None, "Open") == "open"
    assert derive_status({"title": "Plan"}, "Status: EXECUTED 2026-08-01", "History", "Open") == "executed"
    assert derive_status({"title": "Plan"}, "Not done: the renderer", "Open", "Open") == "open"
    assert derive_status({"title": "Plan — DROPPED"}, "", "History", "Open") == "dropped"
