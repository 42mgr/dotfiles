---
title: "Clear, specific title — what this page is"
description: "One sentence: the exact question this page answers."
keywords: ["entity-names", "hook-names", "service-names", "error-strings", "env-vars"]
kind: topic
---

Lead sentence: what it is, plus the concrete identifiers an agent needs to act —
container name, repo path, service name, entry-point function. No preamble.

## Why it exists <!-- agent:decision -->

:::info
**Context.** What forced the decision, or what problem existed before.
**Decision.** What we actually chose.
**Consequences.** The tradeoffs and footguns that follow from it.
If a formal decision exists, link it: [ADR-00X](/decisions/records).
:::

## Key files <!-- agent:key-files -->

<!-- concept → file to edit. Only files someone would read or change for this
     topic; every path is checked against the repo (M001). -->

| File | Role |
|------|------|
| `path/to/File.php` | what it does for this topic |

## How it works <!-- agent:how -->

::::steps
:::step First stage
What happens, and the function / symbol that does it.
:::
:::step Next stage
…
:::
::::

## Config <!-- agent:config -->

<!-- Env vars / settings that change behaviour. Omit the heading if the topic
     has none, and say so in one line where it would have been. -->

| Env var / setting | Purpose | Default |
|-------------------|---------|---------|
| `EXAMPLE_VAR` | … | … |

## Gotchas <!-- agent:gotchas -->

- **Symptom → cause → fix.** Each bullet self-contained; lead with what the agent will observe.

## How to detect / verify <!-- agent:verify -->

<!-- Exact commands, queries or checks. NEVER abstract these away — this is
     what makes a claim actionable. -->

```bash
# concrete check an agent can run
```

## Changelog <!-- agent:changelog -->

| Date | Type | Summary |
|------|------|---------|
| YYYY-MM-DD | feat | Initial page. |

## Related <!-- agent:related -->

- [Related page](/group/slug) — why it is relevant.
