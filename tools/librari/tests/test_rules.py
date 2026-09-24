import json
import subprocess

from librari.check import run
from librari.config import load

from conftest import GOOD_PAGE


def _rules(report, path=None):
    return sorted({f.rule for f in report.findings if path is None or f.path == path})


def _write(kb, rel, text):
    (kb / rel).write_text(text)


def test_fixture_kb_is_green(cfg):
    r = run(cfg)
    assert r.verdict == "GREEN", [f.as_dict() for f in r.findings]
    assert r.exit_code == 0


def test_syntax_rules(kb, cfg):
    _write(kb, "calendar/radicale.md", GOOD_PAGE.replace("```bash", "```").replace("`<x>`", "")
           + "\nbare <Entity> here\n\n:::bogus\nx\n:::\n\n<!-- agent:lost -->\n")
    r = run(cfg, [str(kb / "calendar/radicale.md")])
    rules = _rules(r)
    assert {"S002", "S004", "S005", "S006"} <= set(rules)


def test_nesting_rule_reports_force_close(kb, cfg):
    bad = GOOD_PAGE.replace("::::steps", ":::steps").replace("\n::::\n", "\n:::\n")
    _write(kb, "calendar/radicale.md", bad)
    r = run(cfg, [str(kb / "calendar/radicale.md")])
    assert "S007" in _rules(r)
    assert any("force-closed" in f.message for f in r.findings)


def test_contract_rules(kb, cfg):
    text = GOOD_PAGE.replace("kind: topic", "kind: topic\nstatus: open")  # extra key is fine
    text = text.replace("## Key files <!-- agent:key-files -->", "## Key files <!-- agent:key-files -->\n\nno table here\n")
    text = text.replace("| 2026-06-08 | lesson |", "| 2026-6-8 | bogus |")
    _write(kb, "calendar/radicale.md", text)
    r = run(cfg, [str(kb / "calendar/radicale.md")])
    rules = _rules(r)
    assert "C007" in rules
    assert "C006" not in rules  # a table still follows the prose


def test_required_sections_per_kind(kb, cfg):
    text = GOOD_PAGE.replace("## How to detect / verify <!-- agent:verify -->", "## Verify <!-- agent:check-it -->")
    _write(kb, "calendar/radicale.md", text)
    r = run(cfg, [str(kb / "calendar/radicale.md")])
    assert any(f.rule == "C002" and "agent:verify" in f.message for f in r.findings)


def test_order_and_duplicate(kb, cfg):
    text = GOOD_PAGE.replace("## Gotchas <!-- agent:gotchas -->", "## Gotchas <!-- agent:decision -->")
    _write(kb, "calendar/radicale.md", text)
    r = run(cfg, [str(kb / "calendar/radicale.md")])
    assert {"C003", "C004"} <= set(_rules(r))


def test_semantic_rules(kb, cfg):
    text = GOOD_PAGE.replace("`nginx/nginx.conf`", "`nginx/missing.conf`")
    text = text.replace("(/identity/users#agent:verify)", "(/identity/users#agent:nope)")
    text = text.replace("(/identity/users)", "(../identity/users.md)")
    text += "\npassword = hunter2butlonger123\n"
    _write(kb, "calendar/radicale.md", text)
    r = run(cfg, [str(kb / "calendar/radicale.md")])
    assert {"M001", "M002", "M003", "M006"} <= set(_rules(r))


def test_secret_scan_ignores_env_var_names(kb, cfg):
    _write(kb, "calendar/radicale.md", GOOD_PAGE + "\nClient Secret = `WIKI_OIDC_CLIENT_SECRET` from `.env`\n")
    r = run(cfg, [str(kb / "calendar/radicale.md")], rules={"M006"})
    assert r.findings == []


def test_nav_rules(kb, cfg):
    _write(kb, "identity/orphan.md", GOOD_PAGE)
    d = json.loads((kb / "librari.json").read_text())
    d["navigation"]["groups"][0]["pages"].append("calendar/ghost")
    (kb / "librari.json").write_text(json.dumps(d))
    r = run(load(kb))
    assert {"M004", "M005"} <= set(_rules(r))


def test_roadmap_status_vs_group(kb, cfg):
    page = GOOD_PAGE.replace("kind: topic", "kind: roadmap\nstatus: executed")
    _write(kb, "roadmap/plan.md", page)
    d = json.loads((kb / "librari.json").read_text())
    d["navigation"]["groups"][2]["pages"].append("roadmap/plan")
    (kb / "librari.json").write_text(json.dumps(d))
    r = run(load(kb), [str(kb / "roadmap/plan.md")])
    assert "M009" in _rules(r)
    page2 = page.replace("status: executed", "status: open")
    _write(kb, "roadmap/plan.md", page2)
    d["navigation"]["groups"][2]["pages"] = []
    d["navigation"]["groups"][3]["pages"] = ["roadmap/plan"]
    (kb / "librari.json").write_text(json.dumps(d))
    r = run(load(kb), [str(kb / "roadmap/plan.md")])
    assert "M009" in _rules(r)


def test_changelog_git_rules(kb, cfg):
    # body change without a new row → C010; editing an existing row → C009
    _write(kb, "calendar/radicale.md", GOOD_PAGE.replace("nginx resolves", "nginx re-resolves"))
    r = run(cfg, [str(kb / "calendar/radicale.md")])
    assert "C010" in _rules(r)
    _write(kb, "calendar/radicale.md", GOOD_PAGE.replace("| lesson | Initial page.", "| lesson | Edited row."))
    r = run(cfg, [str(kb / "calendar/radicale.md")])
    assert "C009" in _rules(r)
    # appending a row satisfies both
    _write(kb, "calendar/radicale.md", GOOD_PAGE.replace("nginx resolves", "nginx re-resolves")
           .replace("| 2026-06-08 | lesson | Initial page. |", "| 2026-06-08 | lesson | Initial page. |\n| 2026-09-21 | fix | wording |"))
    r = run(cfg, [str(kb / "calendar/radicale.md")])
    assert not {"C009", "C010"} & set(_rules(r))


def test_baseline_suppresses_and_ratchets(kb, cfg):
    _write(kb, "calendar/radicale.md", GOOD_PAGE.replace("`nginx/nginx.conf`", "`nginx/gone.conf`"))
    (kb / "librari-baseline.json").write_text(json.dumps({"M001": ["calendar/radicale.md"], "S002": ["identity/users.md"]}))
    r = run(load(kb))
    assert "M001" not in _rules(r) and len(r.baselined) == 1
    assert any(f.rule == "B001" and "S002" in f.message for f in r.findings)   # stale entry must go


def test_changed_selection(kb, cfg):
    _write(kb, "identity/users.md", GOOD_PAGE.replace("Radicale via nginx", "Users changed"))
    r = run(cfg, changed=True)
    assert r.pages == ["identity/users.md"]


def test_legacy_docs_link_accepted(kb, cfg, tmp_path):
    (tmp_path / "docs" / "ops").mkdir(parents=True)
    (tmp_path / "docs" / "ops" / "backup.mdx").write_text("---\ntitle: b\n---\n")
    _write(kb, "calendar/radicale.md", GOOD_PAGE + "\nSee [backup](/ops/backup) and [nope](/ops/nope).\n")
    d = json.loads((kb / "librari.json").read_text()); d["settings"]["legacyDocsDir"] = "docs"
    (kb / "librari.json").write_text(json.dumps(d))
    r = run(load(kb), [str(kb / "calendar/radicale.md")], rules={"M002"})
    assert [f.message for f in r.findings] == ["link target `/ops/nope` is not a page in the kb"]


def test_secret_scan_ignores_header_names_and_m003_is_case_insensitive(kb, cfg):
    _write(kb, "calendar/radicale.md", GOOD_PAGE + "\nThe CSRF token: X-CSRF-Token header. See [x](HTTPS://example.com/a.md).\n")
    r = run(cfg, [str(kb / "calendar/radicale.md")], rules={"M006", "M003"})
    assert r.findings == []


def test_closer_inside_fence_is_s007(kb, cfg):
    _write(kb, "calendar/radicale.md", GOOD_PAGE + "\n:::note\n```text\n:::\n```\n:::\n")
    r = run(cfg, [str(kb / "calendar/radicale.md")])
    assert any(f.rule == "S007" and "inside the code fence" in f.message for f in r.findings)


def test_c009_follows_a_rename(kb, cfg):
    subprocess.run(["git", "mv", "calendar/radicale.md", "calendar/renamed.md"], cwd=kb, check=True)
    d = json.loads((kb / "librari.json").read_text())
    d["navigation"]["groups"][0]["pages"] = ["calendar/renamed"]
    (kb / "librari.json").write_text(json.dumps(d))
    _write(kb, "calendar/renamed.md", GOOD_PAGE.replace("| lesson | Initial page.", "| lesson | Edited row."))
    r = run(load(kb), [str(kb / "calendar/renamed.md")], rules={"C009"})
    assert [f.rule for f in r.findings] == ["C009"]


def test_baseline_ratchet_only_on_full_runs(kb, cfg):
    (kb / "librari-baseline.json").write_text(json.dumps({"S002": ["identity/users.md"]}))
    assert not any(f.rule == "B001" for f in run(load(kb), rules={"C001"}).findings)
    assert any(f.rule == "B001" for f in run(load(kb)).findings)
