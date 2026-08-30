# CLAUDE.md

Model context for working in this repository. User-facing usage and the full
design record live elsewhere — this file only adds what an agent needs that
isn't already there, plus pointers instead of duplication:

- [README.md](README.md) — install, CLI usage, configuration model, default
  asset pack, source layout, what to commit.
- [docs/specs/initial.md](docs/specs/initial.md) — design decisions, the
  artifact/adapter model, full build history, and §13 for what's pending.

## What this repo is

`agentkit` (package `rn_forge.agentkit`) manages global and repository-local
configuration for AI coding agents (Claude Code, Codex, …) from one layered
source of truth, and this repo dogfoods itself: its own `.claude/`, `.codex/`,
and `.rn-forge/agentkit/` were produced by running `agentkit project init` /
`global apply` against this repo. See README's "What to commit" section
before hand-editing anything under those paths — most of it is generated and
regenerable with `agentkit project update`.

## Safety when working here

This is one of the few repos where running the tool's own CLI against the
real machine is an expected workflow, not a mistake — but it means commands
like `agentkit global apply`, `agentkit global reset`, or anything without
`--dry-run` can write to the real `~/.claude`, `~/.codex`, and
`~/.rn-forge/share/agentkit`. Prefer `--dry-run` first, and prefer running
against a scratch `HOME`/`RNF_HOME` (as the test suite does) over the real
one unless the task specifically calls for touching this machine's config.

Tests must never touch the real `~/.rn-forge`, `~/.claude`, or `~/.codex` —
the `isolated_env` fixture in `tests/conftest.py` sets both `HOME` and
`RNF_HOME` for this reason. Do not write a test that bypasses it.

## Conventions

- `pyright src` runs in strict mode at zero errors — fix typing at the
  untyped-library boundary rather than adding `# type: ignore` or downgrading
  rules (see `docs/specs/initial.md` §11).
- `rn-forge-commons` is a local path dependency on the sibling `../pykit`
  checkout (`tool.uv.sources` in `pyproject.toml`) — it must remain available
  alongside this repo, and installs go through `uv sync`, not `uv pip install`.
- `tests/` mirrors `src/`; add new tests under the matching subtree.
- No Taskfile/go-task in this repo — use the `uv run` commands in README's
  Development section directly.

## Before reporting work done

Run the narrowest relevant slice of the commands in README's Development
section (`pytest`, `ruff check`, `pyright`) — use the exact invocations
there, including the `UV_CACHE_DIR` overrides.
