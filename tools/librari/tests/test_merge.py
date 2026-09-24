"""`librari merge-driver`: unions conflicting Changelog rows, leaves every other conflict."""
import subprocess
from pathlib import Path

from librari.cli import main
from librari.merge import resolve_changelog_conflicts, run_driver

PAGE = """---
title: "P"
description: "d"
keywords: ["p"]
kind: topic
---

Lead.

## Gotchas <!-- agent:gotchas -->

- one

## Changelog <!-- agent:changelog -->

| Date       | Type | Summary |
| ---------- | ---- | ------- |
| 2026-09-01 | feat | first   |
"""

OURS_ROW = "| 2026-09-23 | lesson | ours    |"
THEIRS_ROW = "| 2026-09-23 | docs | theirs |"


def _three(tmp_path: Path, ours_text: str, theirs_text: str, base_text: str = PAGE):
    b, o, t = tmp_path / "base.md", tmp_path / "ours.md", tmp_path / "theirs.md"
    b.write_text(base_text); o.write_text(ours_text); t.write_text(theirs_text)
    return b, o, t


def test_two_appended_rows_are_unioned_oldest_first(tmp_path):
    early = "| 2026-09-10 | fix | theirs-early |"
    b, o, t = _three(tmp_path, PAGE + OURS_ROW + "\n", PAGE + early + "\n" + THEIRS_ROW + "\n")
    assert run_driver(b, o, t, "kb/p.md") == 0
    lines = o.read_text().splitlines()
    tail = lines[-4:]
    assert tail == ["| 2026-09-01 | feat | first   |", early, OURS_ROW, THEIRS_ROW]   # ours before theirs on the same date
    assert "<<<<<<<" not in o.read_text()


def test_result_is_the_same_whichever_side_merges_first(tmp_path):
    b, o, t = _three(tmp_path, PAGE + OURS_ROW + "\n", PAGE + THEIRS_ROW + "\n")
    run_driver(b, o, t)
    first = o.read_text()
    b, o, t = _three(tmp_path, PAGE + THEIRS_ROW + "\n", PAGE + OURS_ROW + "\n")
    run_driver(b, o, t)
    assert sorted(first.splitlines()) == sorted(o.read_text().splitlines())


def test_identical_row_on_both_sides_is_kept_once(tmp_path):
    b, o, t = _three(tmp_path, PAGE + OURS_ROW + "\n", PAGE + OURS_ROW + "\n" + THEIRS_ROW + "\n")
    assert run_driver(b, o, t) == 0
    assert o.read_text().count(OURS_ROW) == 1 and THEIRS_ROW in o.read_text()


def test_prose_conflict_stays_a_conflict(tmp_path):
    b, o, t = _three(tmp_path, PAGE.replace("- one", "- ours"), PAGE.replace("- one", "- theirs"))
    assert run_driver(b, o, t) == 1
    text = o.read_text()
    assert "<<<<<<< ours" in text and ">>>>>>> theirs" in text and "- ours" in text and "- theirs" in text


def test_mixed_page_resolves_rows_but_reports_the_prose_conflict(tmp_path):
    b, o, t = _three(tmp_path, PAGE.replace("- one", "- ours") + OURS_ROW + "\n",
                     PAGE.replace("- one", "- theirs") + THEIRS_ROW + "\n")
    assert run_driver(b, o, t) == 1
    text = o.read_text()
    assert text.count("<<<<<<<") == 1 and OURS_ROW in text and THEIRS_ROW in text
    assert text.index(">>>>>>>") < text.index(OURS_ROW)          # only the Gotchas block is marked


def test_row_shaped_lines_outside_the_changelog_section_are_not_unioned():
    text = "## Key files <!-- agent:key-files -->\n\n<<<<<<< ours\n| 2026-01-01 | x | a |\n=======\n| 2026-01-02 | y | b |\n>>>>>>> theirs\n"
    out, left = resolve_changelog_conflicts(text)
    assert left == 1 and out == text


def test_clean_merge_and_cli_entry(tmp_path):
    b, o, t = _three(tmp_path, PAGE.replace("Lead.", "Lead, ours."), PAGE + THEIRS_ROW + "\n")
    assert main(["merge-driver", str(b), str(o), str(t), "kb/p.md"]) == 0
    assert "Lead, ours." in o.read_text() and THEIRS_ROW in o.read_text()


def test_git_merge_uses_the_driver_end_to_end(tmp_path):
    """A real `git merge` with the attribute + driver configured resolves the row collision."""
    def git(*a):
        return subprocess.run(["git", "-c", "user.email=t@t", "-c", "user.name=t", *a],
                              cwd=tmp_path, check=True, capture_output=True, text=True)
    git("init", "-q", "-b", "master")
    (tmp_path / "kb").mkdir()
    page = tmp_path / "kb" / "p.md"
    page.write_text(PAGE)
    (tmp_path / ".gitattributes").write_text("kb/**/*.md merge=librari\n")
    git("add", "."); git("commit", "-q", "-m", "base")
    git("config", "merge.librari.driver",
        f"{__import__('sys').executable} -m librari.cli merge-driver %O %A %B %P")
    git("checkout", "-q", "-b", "feature")
    page.write_text(PAGE + THEIRS_ROW + "\n"); git("commit", "-q", "-am", "theirs")
    git("checkout", "-q", "master")
    page.write_text(PAGE + OURS_ROW + "\n"); git("commit", "-q", "-am", "ours")
    # merge-tree (the plumbing merge AGENTS.md prescribes on play) honours the driver
    tree = git("merge-tree", "--write-tree", "master", "feature").stdout.split()[0]
    merged = git("show", f"{tree}:kb/p.md").stdout
    assert OURS_ROW in merged and THEIRS_ROW in merged and "<<<<<<<" not in merged
    # and so does a porcelain merge
    git("merge", "-q", "--no-edit", "feature")
    text = page.read_text()
    assert OURS_ROW in text and THEIRS_ROW in text and "<<<<<<<" not in text
