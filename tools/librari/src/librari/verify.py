"""`librari verify` — the runnable checks a page declares.

A fenced block whose info string is `bash verify` (or `sh verify`) is a
verification recipe: `librari verify <page>` lists them, `--run` executes each
with bash from the repo root and reports exit codes. Blocks matching the
destructive denylist are never run, only listed.
"""
from __future__ import annotations

import re
import subprocess
import sys

from .config import KbConfig
from .sections import _load

# A TRIPWIRE, not a boundary: destructive verbs and the secret files of
# AGENTS.md §4.9. A verify block is page-authored text; `--run` is opt-in from
# the CLI only (never MCP, never a hook) and the human who passes --run owns
# what the page says. Blocks run in their own session so a timeout kills the
# whole process group.
DENY = re.compile(
    r"\b(rm\s+(-[a-z]*[rRf][a-z]*|--recursive|--force)|shred|find\b[^\n]*\s-(delete|exec)\b|sudo|doas|"
    r"DELETE\s+FROM|DROP\s+|TRUNCATE|podman\s+(rm|rmi|volume\s+(rm|prune)|system\s+(prune|reset))|"
    r"(podman|docker)(\s+-\S+)*\s+compose\b[^\n]*\b(up|down)\b|"
    r"git(\s+-C\s+\S+)?\s+(push|reset\s+--hard|clean|branch\s+-D)|systemctl\s+(stop|disable)|mkfs|dd\s+if=|"
    r"crontab\s+-r|chmod\s+-R|chown\s+-R|shutil\.rmtree|curl\b[^\n]*\|\s*(ba)?sh|wget\b[^\n]*\|\s*(ba)?sh)"
    r"|(?<![\w.-])\.env\b(?!\.example)|\.autorestic\.ya?ml\b|radicale/config/users"
    r"|\.autore\*|\.en\?|:\(\)\s*\{", re.I)


def blocks(cfg: KbConfig, page_arg: str) -> list[dict]:
    page = _load(cfg, page_arg)
    out = []
    for cb in page.code_blocks:
        info = page.lines[cb.start].strip().lstrip("`~").split()
        if len(info) >= 2 and info[0] in ("bash", "sh") and info[1] == "verify":
            sec = next((s.anchor for s in page.sections if s.start <= cb.start < s.end), None)
            out.append({"line": cb.start + 1, "section": sec, "code": cb.content,
                        "denied": bool(DENY.search(cb.content))})
    return out


def cli(cfg: KbConfig, page_arg: str, run: bool, timeout: int) -> int:
    from .gitutil import repo_root
    from .sections import SectionError
    try:
        found = blocks(cfg, page_arg)
    except SectionError as e:
        print(f"librari verify: {e}", file=sys.stderr)
        return 2
    if not found:
        print("no ```bash verify blocks on this page")
        return 0
    rc = 0
    for b in found:
        head = f"L{b['line']} [{b['section'] or '-'}]" + ("  (denied: destructive pattern, not run)" if b["denied"] else "")
        if not run:
            print(head)
            print("    " + b["code"].rstrip().replace("\n", "\n    "))
            continue
        if b["denied"]:
            print(f"SKIP  {head}")
            continue
        import os
        import signal
        proc = subprocess.Popen(["bash", "-eo", "pipefail", "-c", b["code"]], cwd=repo_root(cfg.root) or cfg.root,
                                stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, start_new_session=True)
        try:
            out, _ = proc.communicate(timeout=timeout)
            status = "PASS" if proc.returncode == 0 else f"FAIL(rc={proc.returncode})"
            tail = out.strip().splitlines()[-3:]
        except subprocess.TimeoutExpired:
            os.killpg(proc.pid, signal.SIGKILL)   # the block's whole process group, grandchildren included
            proc.communicate()
            status, tail = f"TIMEOUT({timeout}s)", []
        print(f"{status:<14}{head}")
        for t in tail:
            print("    " + t[:160])
        if not status.startswith("PASS"):
            rc = 1
    return rc
