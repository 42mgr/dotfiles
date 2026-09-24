import json
import subprocess
from pathlib import Path

import pytest

from librari.config import DEFAULT_KINDS, DEFAULT_SETTINGS, load

GOOD_PAGE = """---
title: "Radicale via nginx"
description: "How CalDAV is proxied to Radicale."
keywords: ["radicale", "caldav", "nginx"]
kind: topic
---

Lead: `espo-nginx` proxies `dav.example.com` to the `radicale` container.

## Why it exists <!-- agent:decision -->

:::info
**Context.** DNS goes stale. **Decision.** resolve upstream. **Consequences.** none.
:::

## Key files <!-- agent:key-files -->

| File | Role |
|------|------|
| `nginx/nginx.conf` | reverse proxy |

## How it works <!-- agent:how -->

:::::steps
:::step Resolve
nginx resolves `radicale:5232` at runtime.
:::
::::step Proxy
:::warning
inner warning inside a step
:::
::::
:::::

## Gotchas <!-- agent:gotchas -->

- **502 → stale DNS → `resolve`.** See [users](/identity/users#agent:verify).

## How to detect / verify <!-- agent:verify -->

```bash
podman ps --filter name=radicale
```

## Changelog <!-- agent:changelog -->

| Date | Type | Summary |
|------|------|---------|
| 2026-06-08 | lesson | Initial page. |

## Related <!-- agent:related -->

- [Users](/identity/users) — who logs in.
"""

USERS_PAGE = """---
title: "Users"
description: "User provisioning."
keywords: ["users", "authentik"]
kind: topic
---

Lead sentence about users.

## Key files <!-- agent:key-files -->

| File | Role |
|------|------|
| `nginx/nginx.conf` | also here |

## How to detect / verify <!-- agent:verify -->

```sql
SELECT 1;
```

## Changelog <!-- agent:changelog -->

| Date | Type | Summary |
|------|------|---------|
| 2026-06-01 | feat | Initial page. |

## Related <!-- agent:related -->

- [Radicale](/calendar/radicale) — proxy.
"""


def make_kb(root: Path, with_git: bool = True) -> Path:
    """A minimal repo: <root>/kb with two pages, nginx/nginx.conf on disk."""
    kb = root / "kb"
    (kb / "calendar").mkdir(parents=True)
    (kb / "identity").mkdir()
    (kb / "roadmap").mkdir()
    (root / "nginx").mkdir()
    (root / "nginx" / "nginx.conf").write_text("server {}\n")
    (kb / "calendar" / "radicale.md").write_text(GOOD_PAGE)
    (kb / "identity" / "users.md").write_text(USERS_PAGE)
    cfg = {
        "name": "test kb",
        "settings": dict(DEFAULT_SETTINGS),
        "kinds": DEFAULT_KINDS,
        "navigation": {"groups": [
            {"group": "Calendar", "pages": ["calendar/radicale"]},
            {"group": "Identity", "pages": ["identity/users"]},
            {"group": "Roadmap — open plans", "pages": []},
            {"group": "History", "pages": []},
        ]},
    }
    (kb / "librari.json").write_text(json.dumps(cfg, indent=2))
    if with_git:
        subprocess.run(["git", "init", "-q", "-b", "master"], cwd=root, check=True)
        subprocess.run(["git", "-c", "user.email=t@t", "-c", "user.name=t", "add", "."], cwd=root, check=True)
        subprocess.run(["git", "-c", "user.email=t@t", "-c", "user.name=t", "commit", "-q", "-m", "init"],
                       cwd=root, check=True)
    return kb


@pytest.fixture
def kb(tmp_path):
    return make_kb(tmp_path)


@pytest.fixture
def cfg(kb):
    return load(kb)
