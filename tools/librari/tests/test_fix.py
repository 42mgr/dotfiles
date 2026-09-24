from librari.check import run
from librari.fix import cli as fix_cli
from conftest import GOOD_PAGE


def test_fix_paths_backlinks_lead(cfg, kb, capsys):
    # abbreviated path (unique suffix), a one-way Related link, no lead
    p = kb / "identity/users.md"
    p.write_text(p.read_text().replace("| `nginx/nginx.conf` | also here |", "| `nginx.conf` | also here |")
                 .replace("Lead sentence about users.\n", "")
                 .replace("- [Radicale](/calendar/radicale) — proxy.", "- nothing"))
    before = run(cfg, use_baseline=False)
    assert {f.rule for f in before.findings} >= {"M010", "M008", "C005"}
    rc = fix_cli(cfg, True, True, True, True, True)
    out = capsys.readouterr().out
    assert "M010 full paths: 1" in out and "C005 leads: 1" in out and "M008 back-links: 1" in out
    text = p.read_text()
    assert "| `nginx/nginx.conf` | also here |" in text
    assert "\nUser provisioning.\n" in text                       # description became the lead
    assert "- [Radicale via nginx](/calendar/radicale) — How CalDAV is proxied to Radicale." in text
    assert "| docs | librari fix:" in text                         # changelog row appended
    after = run(cfg, use_baseline=False)
    assert not {f.rule for f in after.findings} & {"M010", "M008", "C005", "C010"}
    assert rc == 0


def test_fix_dedents_indented_prose_inside_a_directive(cfg, kb):
    p = kb / "calendar/radicale.md"
    p.write_text(p.read_text().replace(":::step Resolve\nnginx resolves `radicale:5232` at runtime.\n:::",
        ":::step Resolve\nIntro.\n\n    indented prose\n\n    ```bash\n    echo hi\n    ```\n:::"))
    fix_cli(cfg, False, False, False, True, True)     # --changelog, or C010 makes the page RED
    text = p.read_text()
    assert "\nindented prose\n" in text and "\n```bash\necho hi\n```\n" in text
    assert run(cfg, [str(p)]).verdict == "GREEN"
