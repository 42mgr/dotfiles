---
title: "Verb-first title — what this runbook does"
description: "One sentence: the situation this runbook resolves."
keywords: ["service-names", "error-strings", "commands"]
kind: runbook
---

Lead sentence: when to run this, who may run it, how long it takes, what it touches.

## Why it exists <!-- agent:decision -->

:::info
**Context.** The failure or task this procedure exists for.
**Decision.** Why it is done this way and not another.
**Consequences.** What the procedure cannot cover; when to stop and ask.
:::

## Key files <!-- agent:key-files -->

| File | Role |
|------|------|
| `myscripts/example.sh` | the script the procedure drives |

## Procedure <!-- agent:how -->

::::steps
:::step Preconditions
What must be true before starting (locks, backups, time window). Exact checks.
:::
:::step Do the thing
Exact commands, one concern per step.
:::
:::step Confirm
How you know it worked.
:::
::::

## Gotchas <!-- agent:gotchas -->

- **Symptom → cause → fix.**

## How to detect / verify <!-- agent:verify -->

```bash
# commands that prove the end state
```

## Changelog <!-- agent:changelog -->

| Date | Type | Summary |
|------|------|---------|
| YYYY-MM-DD | feat | Initial runbook. |

## Related <!-- agent:related -->

- [Related page](/group/slug) — why it is relevant.
