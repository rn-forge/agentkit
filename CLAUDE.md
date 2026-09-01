# CLAUDE.md

Model context for working in this repository. User-facing usage and the full
design record live elsewhere — this file only adds what an agent needs that
isn't already there, plus pointers instead of duplication:

- [README.md](README.md) — what agentkit is, install, quickstart, and the index
  into the docs site.
- [docs/](docs/) — the MkDocs site. Start at
  [architecture/index.md](docs/architecture/index.md) for the configuration
  and path models, [architecture/adapters.md](docs/architecture/adapters.md)
  for the adapter contract,
  [guides/configuration.md](docs/guides/configuration.md) for the asset pack
  and what to commit, and [guides/development.md](docs/guides/development.md)
  for conventions and source layout.
- [docs/specs/initial.md](docs/specs/initial.md) — the historical design record:
  decisions, full build history, and §13 for what's pending.
- [docs/architecture/safety-model.md](docs/architecture/safety-model.md) — what
  the guards, apply, and install paths do and do not promise, and why. Read it
  before "hardening" a hook or an apply path; several apparent gaps are
  deliberate and recorded there.
- [docs/architecture/docs-system.md](docs/architecture/docs-system.md) — how and
  why the docs site is built; update it when the docs tooling changes.
- [docs/guides/task-vocabulary.md](docs/guides/task-vocabulary.md) — the task
  vocabulary and its rules; update it when the verb set changes.

## What this repo is

`agentkit` (package `rn_forge.agentkit`) manages global and repository-local
configuration for AI coding agents (Claude Code, Codex, …) from one layered
source of truth, and this repo dogfoods itself: its own `.claude/`, `.codex/`,
and `.rn-forge/agentkit/` were produced by running `agentkit project init` /
`global apply` against this repo. See
[guides/configuration.md](docs/guides/configuration.md) before hand-editing
anything under those paths — most of it is generated and regenerable with
`agentkit project update`.

## Safety when working here

This is one of the few repos where running the tool's own CLI against the real
machine is an expected workflow, not a mistake — but it means commands like
`agentkit global apply`, `agentkit global reset`, or anything without
`--dry-run` can write to the real `~/.claude`, `~/.codex`, and
`~/.rn-forge/share/agentkit`. Prefer `--dry-run` first, and prefer running
against a scratch `HOME`/`RNF_HOME` (as the test suite does) over the real one
unless the task specifically calls for touching this machine's config.

Tests must never touch the real `~/.rn-forge`, `~/.claude`, or `~/.codex` — the
`isolated_env` fixture in `tests/conftest.py` sets both `HOME` and `RNF_HOME`
for this reason. Do not write a test that bypasses it.

## Conventions

- `pyright src` runs in strict mode at zero errors — fix typing at the
  untyped-library boundary rather than adding `# type: ignore` or downgrading
  rules (see `docs/specs/initial.md` §11).
- `tests/` mirrors `src/`; add new tests under the matching subtree.
- **`task` is the only entrypoint** — never invoke `uv`, `pytest`, `ruff`,
  `pyright` or `mkdocs` directly, in a CI step or in a command you hand the
  user. `scripts/check_ci_entrypoint.py` enforces this for CI definitions. New
  tasks go in the `tasks/*.yml` namespace file that owns the tool they call;
  the root `Taskfile.yml` holds wrappers only (a list of `task:` calls, never
  raw shell); every task carries a non-empty `desc:`.
  `scripts/check_task_layout.py` enforces those two rules. See
  [docs/guides/task-vocabulary.md](docs/guides/task-vocabulary.md).
- Deliberate trade-offs in the tooling (test lint exclusions, no coverage floor,
  `.editorconfig` defaults, the Python floor, release triggering) are recorded
  under "Deliberate trade-offs" in
  [docs/guides/development.md](docs/guides/development.md). Extend that
  section rather than re-litigating them.
- Docs prose lives in `docs/` and is linked, never duplicated, from README.
  `mkdocs.yml`'s `nav` is the source of page structure — a new page that isn't
  in `nav` fails `task lint` as an orphan.
- Artifact and operation-result ordering (`AgentAdapter.artifacts()`,
  `apply_adapter()`/`sync_adapter()`/`reset_adapter()` return lists) is not a
  tested contract — don't write or accept a test that indexes into these lists
  (`results[0]`, `artifacts("global")[0]`) to mean "the config one." Select by
  `.key` / `.artifact` instead (see `_result_for` helpers in
  `tests/core/test_manager.py` and `tests/core/test_doctor.py`). An
  index-based test breaks on any unrelated reordering and either has to be
  fixed blind or becomes a reason to avoid a reordering that's otherwise fine.
- `uv_build` packages whatever is on disk under `src/`, not what's tracked by
  git — a gitignored file (`.DS_Store`, a stray `__pycache__`) can still ship
  in a wheel. `task build` runs `scripts/check_dist_contents.py` after every
  build for this reason; extend its disallow list rather than adding a one-off
  cleanup step if a new junk-file class shows up.

## Before reporting work done

Run the narrowest relevant slice of the task vocabulary — `task test`,
`task lint`, `task typecheck`, or `task validate` for the full gate (lint +
typecheck + test + docs build). The `UV_CACHE_DIR` handling that used to have to
be remembered by hand is now in `Taskfile.yml`; don't reintroduce raw `uv run`
invocations to work around it.
