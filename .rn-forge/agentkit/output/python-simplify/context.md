# python-simplify context — rn-forge/agentkit

Written 2026-09-02 from commit `8a46215`. **This is a cache, not truth.** Check
every path still exists and every command is still defined before relying on it;
re-derive and rewrite anything stale. If HEAD is far past `8a46215`, redo the
orientation pass outright — it is cheap.

## Design record

`docs/specs/initial.md` — a single numbered design record, `## N.` sections,
currently through §15. Discovered, not asked: `CLAUDE.md` names it directly as
"the historical design record: decisions, full build history, and §13 for what's
pending". §13 is the pending-work section; new phases append as a new top-level
`## N.` and get one pointer line in §13.

Also present and load-bearing for orientation, none of them a promotion target:
`docs/architecture/` (index, adapters, safety-model, docs-system),
`docs/guides/` (configuration, development, task-vocabulary), `docs/runbooks/`,
`docs/reference/python-api.md`. `mkdocs.yml`'s `nav` is the source of page
structure — a new *page* not in `nav` fails `task lint` as an orphan. A new
section inside an existing page does not touch `nav`.

`docs/architecture/safety-model.md` matters for this skill specifically: several
apparent gaps in the guard/apply/install paths are deliberate and recorded
there. Read it before proposing a "hardening" finding.

## Commands

`task` is the only entrypoint — never `uv`, `pytest`, `ruff`, `pyright`, or
`mkdocs` directly. `scripts/check_ci_entrypoint.py` enforces this for CI
definitions.

| Purpose | Command |
|---|---|
| format | `task format` (ruff + mdformat, in place) |
| lint | `task lint` (python, task layout, CI entrypoint, docs, markdown) |
| typecheck | `task typecheck` (`pyright src`, strict, zero errors) |
| test | `task test` |
| full gate | `task validate` (lint + typecheck + test + docs build) |

Tasks live in `tasks/*.yml` namespace files; the root `Taskfile.yml` holds
wrappers only. `scripts/check_task_layout.py` enforces that.

## Framework

None — this is a library plus a Typer CLI. Do **not** load
`references/web-framework-signatures.md`; there is no ORM and no HTTP boundary.

Dependencies that shape the code: `typer` (hence the `B008`
`typer.Option`-as-default idiom, which is not a finding), `rich` for output,
`ruamel.yaml`/`tomlkit` for round-trip config documents, `jinja2` for asset
rendering.

## Test suite

`tests/` mirrors `src/`. Meaningful and fast enough to be the contract for a
preserving refactor — the `--sweep` stop rule is sound here.

Two conventions a refactor must not break:

- `tests/conftest.py`'s `isolated_env` fixture sets both `HOME` and `RNF_HOME`.
  Tests must never touch the real `~/.rn-forge`, `~/.claude`, or `~/.codex`.
  Never write a test that bypasses it.
- Artifact and operation-result **ordering is not a tested contract**. Do not
  write or accept a test that indexes into `AgentAdapter.artifacts()` or an
  `apply_adapter()`/`sync_adapter()`/`reset_adapter()` result list positionally.
  Select by `.key` / `.artifact` — see the `_result_for` helpers in
  `tests/core/test_manager.py` and `tests/core/test_doctor.py`.

Coverage is not thin anywhere that has been swept so far, and there is no
coverage floor (a deliberate trade-off, recorded in
`docs/guides/development.md`).

## Read these first

- `CLAUDE.md` — conventions, plus a "Deliberate trade-offs" pointer. A finding a
  documented trade-off already covers is noise.
- `docs/guides/development.md` § "Deliberate trade-offs" — test lint exclusions,
  no coverage floor, `.editorconfig` defaults, the Python floor, release
  triggering. Extend it rather than re-litigating any of them.
- `src/rn_forge/agentkit/agents/base.py` — the `AgentAdapter` contract every
  operation goes through. Its ~30 small methods are the *target* shape from
  phases §14.1/§15.1, not debt.
- `src/rn_forge/agentkit/core/operations/result.py` — `OperationResult` and the
  shared write-diffing helpers. Check here before proposing any new shared
  helper in `core/operations/`; several already exist.

## Scope note

`docs/specs/initial.md` §15 (phase 6) is designed and **not yet implemented**.
It covers `core/doctor.py`, `core/state.py`, `core/config.py`, `core/io.py`,
`core/render.py`, `core/paths.py`, `core/artifacts.py`, and `cli.py`. Leave
those alone until §15 lands — findings there will contradict an agreed plan.
