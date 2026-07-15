---
name: repo-context
description: Gather brief on-demand repository orientation when the user asks for repo context, current branch state, dirty files, or a quick project snapshot. Use only when that context is explicitly requested or clearly needed.
---

# Repo Context

Use this skill only on demand. Do not load repo context automatically.

## Goal

Produce a brief repo snapshot with the minimum information needed to orient work:
- current branch
- working tree status summary
- top-level repo layout only when relevant
- optionally recent commits when the user asks

## Workflow

1. Start with the smallest useful read.
2. Prefer command output over prose summary.
3. Keep the response short. Do not restate the user's request.
4. Expand only if the user asks for more detail.

## Default commands

Run only what is needed:

```bash
git branch --show-current
git status --short
git log --oneline -5
```

Use the repo layout only when the user asks for structure or when the branch/status view is not enough:

```bash
find . -maxdepth 2 -type d | sort
```

## Response contract

- Lead with a one-line orientation if useful.
- Report only the relevant facts.
- If the repo is clean, say so in one line.
- If the repo is dirty, summarize changed areas briefly instead of listing every file when the list is long.
- Avoid generic reminders or workflow advice unless the user asked for it.
