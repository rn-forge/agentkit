# Documentation system

How this repo's documentation is built, and why. The build itself is
`task docs:build`; see [the task vocabulary](../guides/task-vocabulary.md).

## Design

- **One MkDocs site is the umbrella** for handwritten prose and generated
  reference — no separate "API docs" site to keep in sync. Everything lands in
  the same nav; only the source of truth differs per page.
- **Handwritten and checked in**: `docs/index.md`, `docs/architecture/`,
  `docs/guides/`, `docs/runbooks/`, `docs/specs/`, and
  `docs/reference/python-api.md` (which is the mkdocstrings *entry point* — the
  directives are handwritten, the rendered content is not).
- **Generated and gitignored**: nothing, currently. `.docs-site/` is the built
  HTML and is gitignored, but it lives outside `docs/` because MkDocs refuses a
  `site_dir` nested under `docs_dir`.
- **Python reference: mkdocstrings**, grouped by architectural layer in
  `python-api.md` rather than dumped flat. The grouping is the value-add over
  raw docstring output — a reader should be able to see the CLI/core/adapter
  layering from the reference page alone.
- **No frontend reference generator.** This repo has no frontend, so neither
  TypeDoc nor compodoc applies. If a frontend is ever added, the decision to
  revisit is which of those two — compodoc for Angular, TypeDoc otherwise.
- **No `scripts/gen-docs.sh`.** The orchestration script the setup normally
  ships exists to sequence frontend generation before `mkdocs build`. With no
  frontend, the whole build is one mkdocs invocation, and a shell script wrapping
  it would be a second runner competing with go-task. The build lives in
  `tasks/docs.yml` instead.
- **`strict: true`** in `mkdocs.yml` turns broken internal links and missing nav
  targets into build failures. This is deliberate: a docs site that builds green
  while silently dropping links is worse than one that fails.
- **`scripts/check-docs.py`** runs as part of `task lint`. It reads `mkdocs.yml`'s
  `nav` as the single source of page structure and checks broken relative links,
  broken heading anchors, and orphan pages unreachable from nav — the class of
  rot that `--strict` alone does not catch.

## Relationship to the README

The README is the front door for someone browsing the repository: what agentkit
is, how to install it, and a quickstart. Everything longer-form — the
configuration model, the path model, the default pack, what to commit, the
adapter contract — lives here and is linked from the README rather than
duplicated in it. There is one copy of each explanation.

The design record in [`docs/specs/initial.md`](../specs/initial.md) is different
again: it is the *historical* record of what was decided and built, and it is
append-only. These architecture pages describe the system as it is now.

## Changelog

- 2026-08-29: initial setup (scaffolded by the `mkdocs-site-setup` skill).
  Python-only variant: mkdocstrings, no frontend generator, no `gen-docs.sh`.
  README slimmed to overview/install/quickstart with detail migrated here.
  `docs/openclaw-tailscale-setup.md` adopted as `docs/runbooks/openclaw-tailscale.md`.
