# agentkit — Initial Build (implemented)

Status: **complete and validated 2026-08-03.** This document is the consolidated
record of everything that has been designed and built, merging the original
scaffolding spec, refinement plan 01, and the packaged-asset review. It replaces
`agentkit_spec.md`, `agentkit_refinement_plan.md`, and
`agentkit_asset_review_plan.md`.

User-facing usage lives in the repository's `README.md`; the current-state
architecture and guides live in the docs site alongside this page. This document
is the *historical* record and stays append-only. Remaining open items are in
§13 — none are blocking.

**2026-08-29 — phase 4, documentation system.** Added a go-task command
vocabulary (root `Taskfile.yml` wrappers over `tasks/*.yml` namespaces, with
`scripts/check_task_layout.py` and `scripts/check_ci_entrypoint.py` enforcing
the split) and an MkDocs site (`mkdocs.yml`, `docs/architecture/`,
`docs/guides/`, `docs/runbooks/`, mkdocstrings reference, `strict: true`, plus
`scripts/check-docs.py` in `task lint`). README slimmed from 253 to ~93 lines,
with the configuration model, asset pack, what-to-commit, source layout, and
adapter contract migrated into the site. Rationale in
[architecture/docs-system.md](../architecture/docs-system.md) and
[guides/task-vocabulary.md](../guides/task-vocabulary.md).

---

## 1. Purpose

Manage global (`~`) and repository-local configuration for AI coding agents
(Claude, Codex, …) from one layered source of truth: read, parse, diff, merge,
and render final configs from templates and packaged assets. Extensible per
agent through a plugin interface.

## 2. Tech stack

| Concern                       | Choice                 |
| ----------------------------- | ---------------------- |
| Packaging/env                 | `uv`                   |
| CLI framework                 | `typer`                |
| Schema/validation             | `pydantic` v2          |
| Templating                    | `jinja2`               |
| TOML I/O (comment-preserving) | `tomlkit`              |
| YAML I/O (comment-preserving) | `ruamel.yaml`          |
| Terminal UX                   | `rich`                 |
| Testing                       | `pytest`, `pytest-cov` |
| Lint/format                   | `ruff`                 |
| Type checking                 | `pyright` (strict)     |

Note: the original spec named `mypy`; the build standardized on **pyright
strict** instead, matching the rn-forge umbrella convention.

## 3. Locked decisions

Settled with the owner during refinement 01. Do not re-litigate.

| Topic                        | Decision                                                                                                                                                                                               |
| ---------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| Product name                 | **agentkit** — the `kiln` name is retired (matches the pykit/shkit `*kit` family)                                                                                                                      |
| Kiln port scope              | Full asset pack: configs, hook scripts, CLAUDE.md/AGENTS.md, output style. MEMORY.md convention **dropped** — agents' native memory covers it                                                          |
| Global working data          | Single root `~/.rn-forge/share/agentkit/` (sources + rendered + state + backups + shared hooks), honoring `$RNF_HOME`                                                                                  |
| Native sync mechanism        | **One-way copy, never symlinks** — agents rewrite their own config files via atomic rename, which silently breaks symlinks; copy + hash + drift + backup stays auditable                               |
| Hook script location         | Under the scope root, referenced by absolute path from configs — never copied into `~/.claude` or `~/.codex`. Per-agent scripts in `<agent>/hooks/`, the shared guard library in `_common/hooks/` (§4) |
| Hook script structure        | Common logic library + thin per-agent dialect adapters (§6.2)                                                                                                                                          |
| Install mechanism            | macsetup-style `install.sh` → versioned venv under `~/.rn-forge/agentkit/v<version>/` + symlinks                                                                                                       |
| In-repo working data         | `<repo>/.rn-forge/agentkit/`                                                                                                                                                                           |
| Claude local native tier     | `.claude/settings.local.json` (personal tier)                                                                                                                                                          |
| Migration from `~/.agentkit` | None needed — no installed users                                                                                                                                                                       |

## 4. Path model

```python
rnf_home()                  # ~/.rn-forge, overridable via $RNF_HOME
global_root()               # $RNF_HOME/share/agentkit
project_scope_root(repo)    # <repo>/.rn-forge/agentkit
```

Implemented in `core/paths.py`; no `".agentkit"` string literal survives in
`src/` or `tests/`. Tests isolate by setting **both** `HOME` and `RNF_HOME`
(adapter native paths still resolve through `Path.home()`), via the shared
`isolated_env` fixture in `tests/conftest.py`.

Scope root layout:

```text
<scope-root>/
├── _common/hooks/guard-core.sh   # guard library shared by every agent
├── <agent>/config.toml           # managed source of truth
├── <agent>/hooks/*.sh            # this agent's scripts, executed in place
├── <agent>/rendered/<native>     # staging, mirrors native tree
├── state.json                    # applied hashes
└── backups/<run-timestamp>/      # pre-overwrite snapshots, one dir per run
```

Every managed _content_ directory is either an `<agent>/` directory or
`_common/`. The underscore prefix keeps the shared directory from ever colliding
with an adapter name. `state.json` and `backups/` sit alongside as agentkit's own
bookkeeping — deliberately not filed under `_common/`, which holds shared _agent
assets_, not tool internals.

## 5. Configuration model

Precedence, lowest to highest:

```text
packaged scope defaults
  → $RNF_HOME/share/agentkit/<agent>/config.toml
  → <repo>/.rn-forge/agentkit/<agent>/config.toml     (local operations only)
  → --set dotted.key=value
```

- Dicts deep-merge; lists replace lower layers unless the adapter schema marks a
  field `merge_strategy: append`.
- `ConfigMerger` returns the merged result **and** a provenance map recording
  which layer produced each key — this is what `diff` and `doctor` display.
- Defaults are **scope-aware** (`defaults(scope)`): packaged _global_ defaults
  (hook wiring, deny permissions) deliberately do **not** leak into local
  rendering, while a user's managed _global source_ still feeds both scopes.

## 6. Artifact and adapter model

### 6.1 Artifact

An adapter manages a _set_ of files per scope, not one. Each `Artifact`
(`core/artifacts.py`) declares: a stable key, a native-relative path, either a
Jinja template or a packaged static source, a root (`agent` or `share`), an
optional executable bit, and an optional `seed_only` flag.

- **Agent-rooted** artifacts land in the agent's own tree (`~/.claude/…`,
  `~/.codex/…`). Discovery-by-location assets — output styles, `CLAUDE.md`,
  `AGENTS.md` — must be agent-rooted, since the agents only find them at fixed
  native paths.
- **Share-rooted** artifacts land in `<scope-root>/hooks/` and are referenced by
  absolute path from configs.
- **Seed-only** artifacts are written when the native path is absent and then
  left to the repository. They are the one exception to "everything agentkit
  writes is regenerable", and exist for hand-authored files agentkit should
  scaffold but never own (§6.4).

The shipped `AgentAdapter` ABC (`agents/base.py`): `schema()`,
`artifacts(scope)`, `render(config, *, scope)`, `parse_native(path)`, plus
overridable `render_artifact()`, `defaults(scope)`, `validate()`. Native and
rendered paths are derived from each `Artifact` rather than declared per scope.

Adapters are discovered from built-ins plus the `agentkit.adapters`
entry-point group (`agents/registry.py`), so third parties can ship plugin
packages.

### 6.2 Hook architecture

Guard logic lives once in `assets/scripts/guard-core.sh`; thin per-agent
adapters handle each agent's I/O dialect:

- Claude: reason on stderr, `exit 2`.
- Codex: `{"decision": "block", "reason": …}` on stdout, `exit 0`.

The library is pure logic with no stdin/stdout side effects, exposing
`guard_check_bash_command`, `guard_check_prompt_secrets`, and
`guard_check_write_path`. Adapters read the payload from stdin, extract fields
with `jq`, source the lib relative to themselves
(`${0%/*}/../../_common/hooks/guard-core.sh`, so no install path is baked into
any script), and emit the verdict. Both adapters declare the identical
`_common/hooks/guard-core.sh` artifact; apply is hash-idempotent, so whichever runs
second is a no-op.

### 6.3 Instruction single-sourcing

`~/.claude/CLAUDE.md`, `~/.codex/AGENTS.md`, and
`~/.claude/output-styles/concise.md` all render from shared partials in
`assets/instructions/{behavior,style,clarifications}.md`:

- `AGENTS.md` = all sections
- `CLAUDE.md` = behavior sections
- `output-styles/concise.md` = style sections + output-style frontmatter

Adapter tests assert each rendered file byte-matches its packaged snapshot, so
the two agents cannot drift apart.

### 6.4 Repo instruction seeds

`project init` seeds a repo-root `CLAUDE.md` (Claude adapter) and `AGENTS.md`
(Codex adapter) from `assets/instructions/{CLAUDE,AGENTS}.local.md.j2`. These
are `seed_only` artifacts, and they are a different thing from the global
instruction files above: the global `~/.codex/AGENTS.md` is *content* rendered
from the shared partials, while the repo-root one is a *pointer*.

The pointer construct is deliberate. `AGENTS.md` tells any non-Claude agent to
read `CLAUDE.md` and follow it as if its contents appeared inline, states in one
line what it will find there, and carries a standing instruction not to add
guidance to the pointer itself. The imperative form matters — a descriptive
"see CLAUDE.md" is something a model can read without acting on — and the
anti-drift line is what keeps a repo from ending up with two divergent sets of
instructions. The construct was proven by hand in the sibling `macsetup` and
`shkit` repos before being packaged here. The seeded `CLAUDE.md` is a short
placeholder scaffold, so the pointer never dangles.

Seed-only was chosen over full management because repo-root instruction files
are hand-authored and human-owned. Managing them would mean `project update`
replacing a repo's real `AGENTS.md` with a pointer — recoverable via the backup
path, but the wrong default. The posture matches `init_adapter`'s existing
"scaffold without overwriting existing source" rule for managed config. Three
call sites honor the flag: `_apply_resolved` and `sync_adapter` skip an existing
native and report `exists; owned by the repository`, and the `diff` command
skips it so an edited seed is never reported as drift.

## 7. Default asset pack

`agentkit global apply` installs:

| Agent  | Native agent files                                                                                            | Shared executable hooks                                                                                                   |
| ------ | ------------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------- |
| Claude | `~/.claude/settings.json`, `~/.claude/CLAUDE.md`, `~/.claude/output-styles/concise.md`, `~/.claude/skills/**` | `claude/hooks/`: `pre-bash-guard.sh`, `user-prompt-secret-guard.sh`, `pre-write-protect.sh`, `session-compact-context.sh`, `post-write-unwrap-md.sh` |
| Codex  | `~/.codex/config.toml`, `~/.codex/AGENTS.md`, `~/.codex/hooks.json`                                           | `codex/hooks/`: `pre-bash-guard.sh`, `user-prompt-secret-guard.sh`, `pre-write-protect.sh`, `post-write-unwrap-md.sh`                                |

Every file under the packaged `agents/claude/assets/skills/` tree is declared
as its own global artifact and copied verbatim to the matching path under
`~/.claude/skills/`; adding a skill is adding a directory there, with no
adapter code change. Packaged skills are repo-agnostic — they detect the
target repo's stack rather than assuming one.

`agentkit project init` / `project update` install:

| Agent  | Native agent files                                                                 | Shared executable hooks                                      |
| ------ | ---------------------------------------------------------------------------------- | ------------------------------------------------------------ |
| Claude | `<repo>/.claude/settings.local.json`, `<repo>/CLAUDE.md` (seed)                    | `<repo>/.rn-forge/agentkit/claude/hooks/post-edit-format.sh` |
| Codex  | `<repo>/.codex/config.toml`, `<repo>/.codex/hooks.json`, `<repo>/AGENTS.md` (seed) | `<repo>/.rn-forge/agentkit/codex/hooks/post-edit-format.sh`  |

Guard coverage: destructive-command blocking (filesystem, git, DB-client-scoped
SQL), branch protection (force pushes and pushes to protected branches;
`AGENTKIT_PROTECTED_BRANCHES` overrides the `main|master` default, with
`CLAUDE_PROTECTED_BRANCHES` honored as a fallback), sensitive-path write
protection, and prompt-secret scanning.

`post-write-unwrap-md.sh` is not a guard — it's a formatting convenience that
always exits 0. It fires on `PostToolUse` for `Write`/`Edit`/`MultiEdit`
(Codex: `Edit|Write`) against `.md` files and unwraps prose to one line per
paragraph/list item via the co-installed `unwrap_md.py`, so hand-authored docs
stay diff-friendly regardless of which agent wrote them. A repo opts out with
a `.nounwrap` marker at its git root, checked once per invocation rather than
walked per-directory. `unwrap_md.py` refuses to write — and reports to
stderr instead — when the source has a hard line break, or when the
whitespace-normalized document would change; PostToolUse can't undo an edit
anyway, so there is nothing blocking to do beyond that.

Prompt-secret scanning runs gitleaks **in addition to** the built-in regex set,
never instead of it, and blocks if either fires. This matters: gitleaks' default
ruleset is narrower than the hand-written set in places — measured on 8.30.1 it
misses bare `AKIA…` keys, `KEY=value` assignments, and short-form `sk-`/`xoxb-`
tokens that the regex set catches. Because gitleaks exits 1 both on detection
and on a malformed invocation, the guard inspects its output to distinguish
"leaks found" from an execution failure and reports the two differently. It
fails closed either way.

### Accepted parity exclusions

Parity is the default — one behavior spec rendered per agent — and every
divergence is intentional and recorded:

- **Secret-read denial is Claude-only.** Codex exposes no read-tool matcher, so
  it cannot mirror Claude's `permissions.deny` Read list. Its write guard still
  protects sensitive in-repo paths. Revisit if Codex ships a read matcher.
- **Compaction context injection is Claude-only.** Codex has no equivalent
  context-injection event, so `session-compact-context.sh` stands alone rather
  than living on the shared guard lib with the agent-spanning guards. Revisit
  the unification if a second agent grows an equivalent event.

### External dependencies

`jq` is **required** — every hook parses its JSON event payload with it.
`global apply` and `project init` warn when it is missing and `doctor` reports
it as an error. Runtime fail modes are deliberately split: `PreToolUse` guards
fail **closed** (exit 2, so the destructive-command guard can never fail open),
while `UserPromptSubmit` guards fail **open** so a session stays usable.
`gitleaks` is recommended (warning in `doctor`); formatter binaries are
optional and each dispatch branch is `command -v` guarded.

## 8. Cross-cutting behavior

- **Idempotency** — apply/sync hash content before writing and skip unchanged
  files. `state.json` records `{path, hash, last_applied, source_layer}` per
  native artifact.
- **Dry run** — every mutating command accepts `--dry-run`: renders to memory,
  diffs against the current native file, prints a unified diff, writes nothing.
- **Backups** — before overwriting a native file whose on-disk hash is untracked
  (i.e. manual drift), the previous content is snapshotted under
  `<scope-root>/backups/<timestamp>/`. `reset` always backs up first.
- **Diff** — layered key-change table (defaults → global → local → overrides)
  plus per-artifact rendered-vs-native drift, catching manual edits.
- **Doctor** — schema validity, native path existence/permissions, drift,
  orphaned rendered files, stale state entries, template syntax, agent binaries,
  and the `jq`/`gitleaks` dependency checks.
- **Output** — `rich` tables and diffs; `--quiet` and `--json` are root-level
  flags for scripting and CI.
- **Exit codes** — `0` success, `1` validation/render error, `2` drift detected
  in `--check` mode.

## 9. CLI surface

| Group              | Commands                         |
| ------------------ | -------------------------------- |
| `agentkit global`  | `apply`, `sync`, `reset`, `list` |
| `agentkit project` | `init`, `update`, `status`       |
| root               | `diff`, `doctor`, `version`      |

`project init` scaffolds the managed sources, renders and syncs the native
files, and adds the derived-data block to the repository `.gitignore` — a bare
`init` leaves a working repository, with no follow-up `update` required.

`diff --write` captures native drift back into the managed source (§10).

Adapters may mount their own sub-commands via `cli_extension`.

## 9a. Write-back / capture

`agentkit diff --write` parses the native config, computes the structural delta
against the rendered config, and merges it into the managed `config.toml` at
that scope. The baseline is re-rendered from the resolved layers in memory
rather than read from `rendered/`: that staging copy is gitignored, so a fresh
clone has none, and a stale one would capture drift the user never made. A
scope with no native config yet reports that there is nothing to capture
instead of failing. This turns runtime accumulations — permission grants, `/config`
changes — into durable source instead of drift waiting to be clobbered.

Scope and limits: only the **primary config artifact** is captured
structurally. Append-merged lists capture only a suffix added to the rendered
value. Key removals and destructive edits to append-merged lists cannot be
represented by the layered merge model and are rejected rather than silently
dropped.

The same `--write` flag also captures every other artifact backed by a
packaged static source — hook scripts and skill files — via `capture_assets`:
a hand-edited native file is copied verbatim onto its packaged source path in
this checkout when the two differ, so the fix is versioned instead of lost on
the next `apply`. This is a plain file copy, not a structural merge, and only
does something useful when running from an editable checkout of this repo; an
unwritable packaged source (an installed, non-editable package) is reported
per-artifact instead of raising.

## 9b. Repository shareability

Repository-local files split into shared source and machine-local derived data.

**Committed** — team-shared intent, and the artifacts teammates consume:
`<repo>/.rn-forge/agentkit/<agent>/config.toml`, `<repo>/.codex/config.toml`,
`<repo>/.codex/hooks.json`. Codex has no personal tier at repo level, so its
rendered config _is_ the shared team config.

**Ignored** — regenerable with `project update`: `*/rendered/`, `*/hooks/`,
`_common/`, `state.json`, `backups/` — all beneath `.rn-forge/agentkit/`.

`project init` writes this block into the repo `.gitignore` between
`# BEGIN rn-forge agentkit` / `# END rn-forge agentkit` markers. Re-running
replaces the block in place rather than skipping it when the markers already
exist, so a layout change (e.g. Phase 5's `_common/`/`<agent>/hooks/` move)
reaches every repo the next time `init` runs there, instead of leaving a
stale block from whichever agentkit version first initialized it (§12, Phase
6).

The block only governs `.rn-forge/agentkit/`; it does not touch `.codex/` or
`.claude/` at all. Whether to commit or ignore agent-native files — including
`.claude/settings.local.json`, which stays personal by Claude convention as
the accumulation point for per-developer permission grants — is left to each
repo's own `.gitignore`, not prescribed by agentkit.

**Accepted tradeoff:** the committed `.codex/hooks.json` references hook scripts
that are ignored, so a fresh clone needs `agentkit project update` before the
Codex `PostToolUse` hook resolves. The alternative — committing generated,
version-dependent hook scripts — vendors build output into the repo and invites
conflicts between developers on different agentkit versions.

## 10. Installer

`install.sh` builds a versioned environment under
`$RNF_HOME/agentkit/v<version>/`, updates the `current` symlink, and links the
CLI at `$RNF_HOME/bin/agentkit`. It runs from a checkout, but a checkout is no
longer required to install: `scripts/bootstrap.sh` downloads the source
tarball for the latest GitHub release, extracts it to a temp dir, and runs
`install.sh` from there — `curl -fsSL
https://raw.githubusercontent.com/rn-forge/agentkit/main/scripts/bootstrap.sh
| bash`. Neither script edits shell rc files.

## 11. Testing and typing

Tests mirror `src/`: `tests/{core,agents,hooks,commands}/` plus a shared
`conftest.py` isolation fixture. No test may touch the real `~/.rn-forge`,
`~/.claude`, or `~/.codex`. Hook tests run each synced adapter through
`subprocess` with sample payloads and assert **both** agent dialects.

`pyright src` runs in strict mode at zero errors, achieved by typing at the
untyped-library boundary (tomlkit/ruamel choke points in `core/io.py`, typed
Jinja filter functions in `core/render.py`, validated casts in `core/state.py`)
rather than by sprinkling `# type: ignore` or downgrading rules.

## 12. Build history

Three phases, all complete.

**Phase 1 — original scaffolding spec.** Core merge/provenance, adapter ABC,
render engine, the command groups, and the cross-cutting requirements in §8.

**Phase 2 — refinement 01** (rn-forge integration, kiln defaults port,
multi-artifact adapters, docs, strict typing):

| Milestone                   | Outcome                                                                                   |
| --------------------------- | ----------------------------------------------------------------------------------------- |
| A — rn-forge path model     | `core/paths.py`; zero `".agentkit"` literals; dual `HOME`/`RNF_HOME` test isolation       |
| B — multi-artifact adapters | `core/artifacts.py`; ordered per-scope artifact sets; artifact-aware doctor/diff/status   |
| C — kiln defaults port      | packaged defaults, shared guard lib + dialect adapters, absolute-path hook references     |
| D — installer               | `install.sh` (versioned venv, `current` symlink, `bin` link)                              |
| E — documentation           | Google-style docstrings throughout `src/`, README source-layout and default-pack sections |
| F — test reorganization     | `tests/` mirrors `src/`                                                                   |
| G — pyright strict          | 84 errors → 0, no new ignores                                                             |

**Phase 3 — packaged-asset review** (18 items, all implemented):

| #   | Item                                                      | Landed in                                                                                                                                                                           |
| --- | --------------------------------------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| 1   | Stack-scoped Bash allowlist replaces blanket `Bash` allow | `claude/defaults/local.json` — `Bash`/`MultiEdit` removed, ~60 allow prefixes, publish/deploy commands moved to `ask`                                                               |
| 2   | `git push` guard rewritten to parse args                  | `guard-core.sh` — force detection anywhere in argv, `--force-with-lease` allowed off protected branches, `HEAD` resolved via `git branch --show-current`, `-u` false positive fixed |
| 3   | Auto-stage hook removed                                   | `post-edit-git-stage.sh` deleted and unregistered — silent `git add` broke partial staging                                                                                          |
| 4   | jq enforced at install time, split runtime fail modes     | `commands/common.py`, `core/doctor.py`, all guard adapters; guard-lib presence check before sourcing                                                                                |
| 5   | `PostCompact` registration removed                        | that event surfaces only stderr while the script writes stdout; `SessionStart(compact)` already covers it                                                                           |
| 6   | Read-deny list aligned with write-protect list            | `claude/defaults/global.json` — 21 deny entries                                                                                                                                     |
| 7   | `post-edit-format.sh` rewritten as extension dispatch     | promoted to `assets/scripts/`; per-file, `command -v` guarded, logs failures, always exits 0                                                                                        |
| 8   | SQL guard patterns narrowed to DB clients                 | `truncate -s 0` no longer false-positives                                                                                                                                           |
| 9   | gitleaks with regex fallback                              | `guard-core.sh` + optional-dependency warning in `doctor`                                                                                                                           |
| 10  | Instruction content single-sourced                        | `assets/instructions/` partials + three `.j2` renderers + byte-equality snapshot tests                                                                                              |
| 11  | Clarifications section trimmed 14 → 5 bullets             | `assets/instructions/clarifications.md`                                                                                                                                             |
| 12  | Risk/tradeoff carve-out added to concise style            | `assets/instructions/style.md`                                                                                                                                                      |
| 13  | Sub-agent rule conditioned on large tasks                 | `assets/instructions/behavior.md`                                                                                                                                                   |
| 14  | Codex `global.toml` hygiene                               | model pin removed, `[features] hooks`, `[profiles.trusted]` safety comment                                                                                                          |
| 15  | Protected-branch env var renamed                          | `AGENTKIT_PROTECTED_BRANCHES`, legacy name as fallback                                                                                                                              |
| 16  | Executable bits normalized                                | all six hook adapters + shared formatter at 755                                                                                                                                     |
| 17  | repo-context skill dropped                                | restated default behavior with no added capability; `Artifact` skill-tree plumbing retained for future real skills                                                                  |
| 18  | Cross-agent hook/guard parity                             | Codex `pre-write-protect.sh`, Codex `post-edit-format` via `hooks.local.json`, shared `guard_check_write_path`, both dialects tested                                                |

**Phase 4 — post-review fixes and write-back.** Three defects found by running
the tool for real, plus the two remaining design items:

| Item                                          | Outcome                                                                                                                                                                                                                                                                                                                   |
| --------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| gitleaks weakened the prompt-secret guard     | An early `return 0` made the regex set unreachable whenever gitleaks was installed, so the _recommended_ dependency silently cut detection coverage. Now unioned — block if either fires — with detection distinguished from gitleaks execution failure. Surfaced only because installing gitleaks un-skipped four tests. |
| `apply` created one backup directory per file | `backup_file` called `datetime.now()` per invocation. The timestamp is now scoped to the CLI run via `start_backup_run()`, called from the root callback, giving one directory per run                                                                                                                                    |
| `project init` left a non-working repo        | `init` scaffolded only the managed `config.toml`; rendering happened solely in `update`. `init_command` now composes scaffold + render + sync, keeping `init_adapter` scaffold-only as the honest primitive                                                                                                               |
| `.gitignore` scaffolding                      | `project init` writes the derived-data block between markers, idempotently (§9b)                                                                                                                                                                                                                                          |
| Write-back phase 1                            | `diff --write` captures native drift into the managed source (§9a)                                                                                                                                                                                                                                                        |

**Phase 5 — scope-root layout consolidation.** The scope root previously mixed
`hooks/{lib,claude,codex}/` alongside the `<agent>/` directories, splitting each
agent's files across two places. Consolidated so every content directory is an
`<agent>/` directory or `_common/`:

| Before                    | After                         |
| ------------------------- | ----------------------------- |
| `hooks/lib/guard-core.sh` | `_common/hooks/guard-core.sh` |
| `hooks/<agent>/*.sh`      | `<agent>/hooks/*.sh`          |

The shared library was the sole reason hooks lived at the scope root — it is
declared by both adapters and must not be duplicated. `_common/` names that
sharing explicitly, and the underscore prefix cannot collide with an adapter
name. Mechanical: artifact registrations, 9 absolute references in packaged
configs, the `LIB=` line in 6 hook scripts (now `../../_common/hooks/`), the
`.gitignore` block, and tests. No logic changed.

Two questions settled at the same time:

- **`rendered/<agent-dot-dir>/` is kept.** It mirrors the destination path
  relative to its native root, not the agent name; the apparent duplication only
  shows because both built-in adapters happen to put every artifact under one
  dot-directory. Flattening would need a special case that breaks for any
  adapter writing to two native roots, and would risk basename collisions.
- **Managed sources are now self-documenting and symmetric.** `config.toml` is
  scaffolded with a header explaining that it is the hand-edited layer and the
  `diff --write` capture target. `global apply` scaffolds it too — previously
  only the local scope got a file, leaving no obvious home for global overrides.

**Validation (2026-08-03):** `pytest` 93 passed, `ruff check src tests` clean,
`pyright src` 0 errors, and a full end-to-end gate in scratch `HOME`/`RNF_HOME`
— `global apply` → re-apply reporting all-unchanged → `project init` →
`project update` → `doctor` on both scopes.

**Phase 6 — dogfooding and documentation pass.** Running the tool on its own
repository surfaced three loose ends, plus this repo's own `CLAUDE.md`/
`AGENTS.md`/README were brought up to date:

| Item                                    | Outcome                                                                                                                                                                                                                                                         |
| --------------------------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `.gitignore` block could go stale       | `project init` previously left an existing `# BEGIN/END rn-forge agentkit` block untouched, so a layout change like Phase 5 never reached repos initialized on an older version. It now replaces the block in place on every `init` run, matched by its markers |
| Claude skills undocumented in this spec | `~/.claude/skills/**` is a real global artifact set (one artifact per packaged skill file) but was missing from the §7 table; added                                                                                                                             |
| Repo's own `.gitignore` had drifted     | This repo's `.gitignore` still had the pre-Phase-5 blanket `.rn-forge/` entry (predating the fine-grained `_GITIGNORE_ENTRIES` list). Fixed by running `agentkit project init` against this repo, which rewrote it via the fix above                            |
| `CLAUDE.md` / `AGENTS.md` / `README.md` | Root-level `CLAUDE.md` (model context, references this spec + README) and `AGENTS.md` (thin pointer to `CLAUDE.md`) added; `README.md` reviewed for accuracy against current code                                                                               |

**Phase 7 — repo instruction seeds (2026-08-29).** The pointer-`AGENTS.md`
construct developed by hand in `macsetup` and `shkit` was adopted for this
repo's own `AGENTS.md` and then packaged, so `project init` seeds it in every
target repo (§6.4).

| Item                    | Outcome                                                                                                                                                 |
| ----------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `Artifact.seed_only`    | New flag: write when the native path is absent, then leave the file to the repo. Honored in `_apply_resolved`, `sync_adapter`, and the `diff` command  |
| Repo-root `AGENTS.md`   | Codex local artifact from `assets/instructions/AGENTS.local.md.j2` — the imperative pointer to `CLAUDE.md` plus the "do not add guidance here" rule    |
| Repo-root `CLAUDE.md`   | Claude local artifact from `CLAUDE.local.md.j2`; a placeholder scaffold, so the pointer never dangles                                                   |
| This repo's `AGENTS.md` | Rewritten from the old descriptive "see CLAUDE.md" form into the shared construct                                                                       |

**Validation (2026-08-29):** `pytest` 100 passed (2 updated adapter-artifact
tests, 2 new seed-behavior tests), `ruff check src tests` clean, `pyright src`
0 errors, plus an end-to-end run in a scratch `HOME`/`RNF_HOME` — `project
init` seeds both files, a hand edit survives `project update`, and `diff`
reports no drift.

**Phase 8 — release install path and Pages verification (2026-08-31).** The
repo gained its GitHub remote (`rn-forge/agentkit`), closing out the two
install/deploy items that had been blocked on that.

| Item | Outcome |
| - | - |
| Clone-free install | `scripts/bootstrap.sh` added: resolves the latest GitHub release, downloads its source tarball to a temp dir, and runs `install.sh` from there — no `git clone` needed (§10) |
| Editable-install bug | `install.sh`'s `uv sync` was editable by default, so a CLI installed from a temp dir (as bootstrap does) pointed back at a path deleted right after; fixed with `--no-editable`, which is also correct for a deployed CLI vs. a dev checkout |
| Pages deploy | Verified end-to-end: remote added, Pages enabled (Source: GitHub Actions), `.github/workflows/docs.yml` ran successfully on `main`, site live at <https://rn-forge.github.io/agentkit/> (HTTP 200) |
| GitHub Release publish step | Verified already working (not missing, as first suspected): CI's `publish` job tags the version, creates a GitHub Release, and uploads the wheel/sdist — confirmed via `v0.1.1` release existing |

**Validation (2026-08-31):** `task lint` clean. Bootstrap flow tested twice —
once against the already-tagged `v0.1.1` release (reproduced the editable-
install bug), once via `git archive HEAD` piped through the patched
`install.sh` (confirmed `agentkit version` works after the source dir is
removed). Pages URL confirmed live with `curl -o /dev/null -w '%{http_code}'`.

**Phase 9 — default-value curation (2026-08-31).** Kiln-ported config values
(models, policies) had never been reviewed on their merits — Phase 3 curated
the asset pack's structure and safety, not every value. Reviewed all four
packaged default files (`claude/defaults/{global,local}.json`,
`codex/defaults/{global,local}.toml`) against current Claude Code and Codex
CLI documentation.

| Item | Outcome |
| - | - |
| Claude `effortLevel: "medium"`, `outputStyle: "concise"` | Confirmed current and correct; `outputStyle` is load-bearing for the §6.3 instruction single-sourcing, not an arbitrary port |
| Claude `permissions.deny`/`allow`/`ask` lists | Confirmed still aligned with the Phase 3 item 1/6 curation — no stale entries found |
| Codex `personality`, `model_reasoning_effort`, `approval_policy`, `sandbox_mode`, `profiles.*` | Confirmed current and correct against upstream docs; no changes needed |
| Codex `model_reasoning_summary = "concise"` | Kept — CLI default is `auto`, but `"concise"` is a deliberate parity choice with Claude's output style; added a comment in `global.toml` so it doesn't read as an unreviewed leftover |
| `codex/schema.py` `model_reasoning_effort` literal | Was missing the `"none"` value present in current upstream docs; added |

No default values changed as a result of the review — the kiln port held up.
This closes the item as "reviewed and confirmed" rather than "found and fixed."

## 13. Pending

Open items, none blocking. All were considered and consciously postponed.
Collected here so nothing pending is left scattered in earlier sections.

- **Write-back phase 2 — capture config values to packaged defaults.** Narrower
  than originally scoped: `capture_assets` (§9a) already writes hand-edited
  hooks/skills back to their packaged source in an editable checkout, so the
  `assets/` half of the Brewfile loop is done. What remains is `config.toml`
  changes captured by `capture_adapter` — they only ever land in the scope's
  managed `config.toml`, never in the packaged `defaults/global.json` /
  `global.toml` those scopes render from, so a runtime config change can't be
  promoted into a new default-pack version the way a hook edit now can.
