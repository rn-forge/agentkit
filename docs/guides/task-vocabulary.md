# The task vocabulary

`go-task` is the only thing a developer or a CI job invokes — never `uv`,
`pytest`, `ruff`, `pyright` or `mkdocs` directly.
`scripts/check_ci_entrypoint.py` enforces this for every CI definition; nothing
enforces it for a developer's shell, because the vocabulary being smaller and
more memorable than the tools underneath it is the actual incentive.

## Top-level tasks

| Task | Does |
| -- | -- |
| `task setup` | Sync the virtualenv with the dev and docs dependency groups |
| `task validate` | The aggregate gate — `lint`, `typecheck`, `test`, `docs:build` |
| `task lint` | Every lint: ruff, task layout, CI entrypoints, docs links, Markdown formatting |
| `task format` | Format Python and tracked Markdown files in place |
| `task typecheck` | `pyright` in strict mode over `src/` |
| `task test` | The pytest suite |
| `task build` | Wheel and sdist into `dist/` |
| `task clean` | Remove build outputs, caches, and the rendered docs site |

## Namespaced tasks

| Namespace | Example | Does |
| -- | -- | -- |
| `docs:*` | `task docs:serve`, `task docs:build` | The documentation site — public, because writing prose means running `docs:serve` directly |
| `quality:*` | `task quality:lint:python` | Internal — the lint/format/typecheck/test primitives the top-level wrappers compose |
| `workspace:*` | `task workspace:clean` | Install, build, and clean |

Run `task --list` for the full, current surface — this page is a map, not the
source of truth for what exists.

## Why a task runner in a single-package repo

The usual argument for go-task is polyglot: one verb that means "test" across
Gradle *and* Vitest. That argument does not apply here — this is one Python
package with one toolchain.

Two narrower arguments do apply, and they are the reason this exists:

1. **The invocations carry non-obvious required context.** Every command needs
   `UV_CACHE_DIR` set, and `task build` needs a *different* value than the
   rest (packaging must not reuse the in-repo cache). Encoding that once in
   `Taskfile.yml`'s `env:` beats repeating it in the README, in `CLAUDE.md`,
   and in every CI step — three places that had already started to drift.
1. **The lint surface is now multiple tools, not one.** `task lint` runs ruff,
   mdformat, and three project-specific checkers. Without an aggregate verb,
   "did you run the linters" stops having a single answer.

## The wrapper/inner split

The root `Taskfile.yml` holds **wrappers only** — every task in it is a list of
`task: <namespace>:<name>` calls, never a `cmds:` entry that shells out.
Anything that actually invokes a tool lives in the `tasks/*.yml` namespace file
that owns it.

`scripts/check_task_layout.py` enforces this, and also that every task carries a
non-empty `desc:` — `task --list` being self-documenting is what makes the
vocabulary memorable enough that people stop reaching for the raw tools.

When adding a task: put it in the namespace file that owns the tool it calls.
Add a root-level wrapper only if it composes across namespaces, or if a bare
verb is genuinely the memorable name for it.

## Changelog

- 2026-08-29: initial setup (scaffolded by the `go-task-setup` skill, adapted to
  a single-package Python repo — no backend/frontend namespace split).
- 2026-09-01: `task format` gained tracked-Markdown formatting and `task lint`
  gained the matching mdformat compliance check.
