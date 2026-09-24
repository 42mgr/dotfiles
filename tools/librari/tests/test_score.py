import json

from librari.config import load
from librari.score import format_json, format_plain, format_table, run

from conftest import GOOD_PAGE

INDEX_PAGE = """---
title: "Test kb"
description: "Internal reference for the test stack, a discovery map for humans and coding agents."
keywords: ["index", "map", "start here"]
kind: reference
---

Start here. The table routes every task to the one page that answers it.

## Task index

| Task | Start here |
|------|------------|
| Proxy CalDAV | [Radicale](/calendar/radicale) |
| Provision a user | [Users](/identity/users) |
| Fix a 502 | [Gotchas](/calendar/radicale#agent:gotchas) |
| Check the proxy | [Verify](/calendar/radicale#agent:verify) |
| Log in | [Users](/identity/users) |

## Changelog <!-- agent:changelog -->

| Date | Type | Summary |
|------|------|---------|
| 2099-01-01 | docs | Initial page. |
"""


def _by_id(rep):
    return {c.id: c for c in rep.checks}


def test_score_without_entry_page_skips_children(cfg):
    rep = run(cfg)
    c = _by_id(rep)
    assert c["entryExists"].status == "FAIL"
    for child in ("entryTaskTable", "entryLinksResolve", "entrySize", "entryReach"):
        assert c[child].status == "SKIP", child
        assert c[child].ratio is None
    assert 0 <= rep.score <= 100
    assert c["contractGreen"].status == "PASS"


def test_entry_page_checks_pass(kb):
    (kb / "index.md").write_text(INDEX_PAGE)
    cfgj = json.loads((kb / "librari.json").read_text())
    cfgj["navigation"]["groups"][0]["pages"].insert(0, "index")
    (kb / "librari.json").write_text(json.dumps(cfgj))
    rep = run(load(kb))
    c = _by_id(rep)
    for cid in ("entryExists", "entryTaskTable", "entryLinksResolve", "entrySize", "entryReach"):
        assert c[cid].status == "PASS", (cid, c[cid].detail)
    assert rep.pages == 3


def test_per_page_checks_report_offenders(kb, cfg):
    long_section = GOOD_PAGE.replace("## Gotchas <!-- agent:gotchas -->\n",
                                     "## Gotchas <!-- agent:gotchas -->\n" + "- filler line\n" * 450)
    (kb / "calendar" / "radicale.md").write_text(long_section)
    rep = run(cfg)
    c = _by_id(rep)
    assert c["pageFitsRead"].status == "PART"
    assert len(c["sectionFitsRead"].offenders) == 1
    assert c["sectionFitsRead"].offenders[0].startswith("calendar/radicale#agent:gotchas (45")
    # description of the fixture pages is short: both fail the word threshold
    assert c["descriptionWords"].status == "FAIL"
    assert set(c["descriptionWords"].offenders) == {"calendar/radicale (6 words)", "identity/users (2 words)"}
    # verify sections have code but no ```bash verify recipe
    assert c["verifyHasCode"].status == "PASS"
    assert c["verifyRunnable"].status == "FAIL"


def test_thresholds_come_from_settings(kb):
    cfgj = json.loads((kb / "librari.json").read_text())
    cfgj["settings"]["score"] = {"descriptionMinWords": 2, "keywordsMin": 1}
    (kb / "librari.json").write_text(json.dumps(cfgj))
    c = _by_id(run(load(kb)))
    assert c["descriptionWords"].status == "PASS"
    assert "≥ 2 words" in c["descriptionWords"].title


def test_formats(cfg):
    rep = run(cfg)
    assert format_table(rep).startswith("librari score: ")
    assert format_plain(rep).splitlines()[0].startswith("score\t")
    data = json.loads(format_json(rep))
    assert set(data) == {"score", "pages", "unreadable", "checks"}
    assert data["score"] == rep.score


def test_unreadable_page_does_not_crash(kb, cfg):
    (kb / "broken.md").write_bytes(b"\xff\xfe not utf-8")
    rep = run(cfg)
    assert len(rep.unreadable) == 1 and "broken.md" in rep.unreadable[0]
    assert rep.pages == 2
    assert 0 <= rep.score <= 100
