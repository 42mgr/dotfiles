# librari page format

CommonMark + YAML front matter + a **closed** directive set. No MDX, no JSX,
no raw HTML. Everything below is enforced by `librari check`
(`librari explain <rule>` prints the rule with a fix example).

## Front matter

```yaml
---
title: "Radicale CalDAV via nginx"
description: "One sentence: the exact question this page answers."
keywords: ["radicale", "caldav", "nginx", "502"]
kind: topic            # topic | runbook | incident | roadmap | reference
status: open           # roadmap only: open | executed | dropped
---
```

## Sections and anchors

A section is a heading carrying an anchor comment **on the heading line**:

```markdown
## Key files <!-- agent:key-files -->
```

The heading text is free; the anchor is the contract. Canonical anchors, in
this order when present: `decision → key-files → how → config → gotchas →
verify → changelog → related`. Page-specific anchors (`agent:runbook-add`)
may sit anywhere. Each kind requires a subset (`librari explain kinds`):

| kind | required |
|---|---|
| topic | key-files, verify, changelog |
| runbook | key-files, how, verify, changelog |
| incident | decision, gotchas, verify, changelog |
| roadmap | decision, changelog (+ front matter `status`) |
| reference | changelog |

`Key files` holds a `| File | Role |` table whose File cells are backticked
repo paths — every path is checked on disk. `Changelog` holds
`| Date | Type | Summary |`, ISO dates, append-only (rows at HEAD may never
change), one new row per body change.

## Directives

```markdown
:::warning
Footgun text. Also: note, info, tip, check, danger.
:::

::::steps
:::step Clear the cache
`podman exec espocrm php command.php clear-cache`
:::
:::step Rebuild
…
:::
::::

:::cards
- [Networking](/architecture/networking) — why the DBs are unreachable.
- **No link** — description only.
:::

:::accordion Caveat: team changes only apply on next login
Body.
:::
```

**Nesting rule:** an enclosing container uses one colon MORE than its deepest
child (like code fences). A bare `:::` closes the *outermost* open container
with ≤ that many colons and force-closes everything inside — the validator
reports exactly which container swallowed which (S007). `librari fmt`
rewrites colon counts to the canonical `3 + nesting height`.

**A bare `:::` inside a code fence still closes an open container** — the
renderer scans raw lines for closers and does not know about fences. Inside a
container, never put a line that is only colons into a code block; the validator
reports it (S007 "inside the code fence").

## Everything else

- A verification recipe is a fence tagged ```` ```bash verify ````: `librari verify <page>`
  lists these blocks, `--run` executes them from the repo root (destructive patterns
  are listed, never run).
- Code fences always carry a language: ```` ```bash ````, ```` ```text ````, ```` ```mermaid ````.
- Placeholders in backticks: `` `<Entity>` ``. A bare `<Entity>` is raw HTML (S005).
- Internal links are root-relative without extension: `/identity/users`,
  `/identity/users#agent:verify`, `/identity/users#heading-slug` (GitHub or
  Mintlify slug dialect), or `#<anchor>` for a section anchor.
- An explicit link target inside a paragraph: `<a id="statement-0b"></a>` (or
  `<a id="…" />`) — the one raw-HTML element the format allows besides comments.
- Images: `![alt text](/images/name.png)`, stored under `<kb>/images/`.
- HTML comments (`<!-- … -->`) are allowed anywhere and render as nothing.
- No H1 in the body (the title is the front matter); canonical sections are H2.
