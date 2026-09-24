"""Thin git helper. Every call uses --no-optional-locks: on play the live
checkout's index must never be rewritten by a read (AGENTS.md §12)."""
from __future__ import annotations

import subprocess
from pathlib import Path


def _git(cwd: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(["git", "--no-optional-locks", *args], cwd=cwd,
                          capture_output=True, text=True)


def repo_root(start: Path) -> Path | None:
    r = _git(start, "rev-parse", "--show-toplevel")
    return Path(r.stdout.strip()) if r.returncode == 0 and r.stdout.strip() else None


def head_text(repo: Path, rel: str, ref: str = "HEAD") -> str | None:
    """Content of `rel` (repo-relative) at `ref`, or None when untracked there."""
    r = _git(repo, "show", f"{ref}:{rel}")
    return r.stdout if r.returncode == 0 else None


def merge_base(repo: Path, upstream: str = "origin/master") -> str | None:
    r = _git(repo, "merge-base", "HEAD", upstream)
    if r.returncode != 0:
        r = _git(repo, "merge-base", "HEAD", "master")
    return r.stdout.strip() or None


def changed_files(repo: Path, base: str | None) -> set[str]:
    """Repo-relative paths changed vs `base` (committed + uncommitted + untracked)."""
    out: set[str] = set()
    if base:
        r = _git(repo, "diff", "--name-only", base)
        out.update(p for p in r.stdout.split("\n") if p)
    r = _git(repo, "status", "--porcelain", "--untracked-files=all")
    for line in r.stdout.split("\n"):
        if len(line) > 3:
            out.add(line[3:].split(" -> ")[-1])
    return out


def renamed_from(repo: Path, rel: str, base: str = "HEAD") -> str | None:
    """Old repo-relative path when `rel` is a rename (staged, in the working
    tree, or committed since `base`), else None."""
    for args in (("diff", "--cached", "-M", "--name-status"), ("diff", "-M", "--name-status"),
                 ("diff", "-M", "--name-status", base)):
        r = _git(repo, *args)
        if r.returncode != 0:
            continue
        for line in r.stdout.split("\n"):
            parts = line.split("\t")
            if len(parts) == 3 and parts[0].startswith("R") and parts[2] == rel:
                return parts[1]
    return None
