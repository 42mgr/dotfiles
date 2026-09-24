---
title: "Incident: short name (YYYY-MM-DD)"
description: "One sentence: what broke, for whom, and the root cause."
keywords: ["service-names", "error-strings", "symptoms"]
kind: incident
---

Lead sentence: date, blast radius, duration, one-line root cause.

## What happened <!-- agent:decision -->

:::warning
**Timeline.** First symptom → detection → diagnosis → fix, with timestamps.
**Root cause.** The mechanism, not the trigger.
**Decision.** What was changed so it cannot recur (link the ADR / page).
:::

## Key files <!-- agent:key-files -->

| File | Role |
|------|------|
| `path/to/File.php` | where the cause lived / where the fix landed |

## Gotchas <!-- agent:gotchas -->

- **Symptom → cause → fix.** The reusable lessons, each self-contained.

## How to detect / verify <!-- agent:verify -->

```bash
# the query or command that shows whether this is happening again
```

## Changelog <!-- agent:changelog -->

| Date | Type | Summary |
|------|------|---------|
| YYYY-MM-DD | incident | Initial write-up. |

## Related <!-- agent:related -->

- [Related page](/group/slug) — why it is relevant.
