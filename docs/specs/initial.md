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

______________________________________________________________________

## 1. Purpose

Manage global (`~`) and repository-local configuration for AI coding agents
(Claude, Codex, …) from one layered source of truth: read, parse, diff, merge,
and render final configs from templates and packaged assets. Extensible per
agent through a plugin interface.

## 2. Tech stack

| Concern | Choice |
| -- | -- |
| Packaging/env | `uv` |
| CLI framework | `typer` |
| Schema/validation | `pydantic` v2 |
| Templating | `jinja2` |
| TOML I/O (comment-preserving) | `tomlkit` |
| YAML I/O (comment-preserving) | `ruamel.yaml` |
| Terminal UX | `rich` |
| Testing | `pytest`, `pytest-cov` |
| Lint/format | `ruff` |
| Type checking | `pyright` (strict) |

Note: the original spec named `mypy`; the build standardized on **pyright
strict** instead, matching the rn-forge umbrella convention.

## 3. Locked decisions

Settled with the owner during refinement 01. Do not re-litigate.

| Topic | Decision |
| -- | -- |
| Product name | **agentkit** — the `kiln` name is retired (matches the pykit/shkit `*kit` family) |
| Kiln port scope | Full asset pack: configs, hook scripts, CLAUDE.md/AGENTS.md, output style. MEMORY.md convention **dropped** — agents' native memory covers it |
| Global working data | Single root `~/.rn-forge/share/agentkit/` (sources + rendered + state + backups + shared hooks), honoring `$RNF_HOME` |
| Native sync mechanism | **One-way copy, never symlinks** — agents rewrite their own config files via atomic rename, which silently breaks symlinks; copy + hash + drift + backup stays auditable |
| Hook script location | Under the scope root, referenced by absolute path from configs — never copied into `~/.claude` or `~/.codex`. Per-agent scripts in `<agent>/hooks/`, the shared guard library in `_common/hooks/` (§4) |
| Hook script structure | Common logic library + thin per-agent dialect adapters (§6.2) |
| Install mechanism | macsetup-style `install.sh` → versioned venv under `~/.rn-forge/agentkit/v<version>/` + symlinks |
| In-repo working data | `<repo>/.rn-forge/agentkit/` |
| Claude local native tier | `.claude/settings.local.json` (personal tier) |
| Migration from `~/.agentkit` | None needed — no installed users |

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
with an adapter name. `state.json` and `backups/` sit alongside as agentkit's
own bookkeeping — deliberately not filed under `_common/`, which holds shared
_agent assets_, not tool internals.

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

Adapters are discovered from built-ins plus the `agentkit.adapters` entry-point
group (`agents/registry.py`), so third parties can ship plugin packages.

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
`_common/hooks/guard-core.sh` artifact; apply is hash-idempotent, so whichever
runs second is a no-op.

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
guidance to the pointer itself. The imperative form matters — a descriptive "see
CLAUDE.md" is something a model can read without acting on — and the anti-drift
line is what keeps a repo from ending up with two divergent sets of
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

| Agent | Native agent files | Shared executable hooks |
| -- | -- | -- |
| Claude | `~/.claude/settings.json`, `~/.claude/CLAUDE.md`, `~/.claude/output-styles/concise.md`, `~/.claude/skills/**` | `claude/hooks/`: `pre-bash-guard.sh`, `user-prompt-secret-guard.sh`, `pre-write-protect.sh`, `session-compact-context.sh` |
| Codex | `~/.codex/config.toml`, `~/.codex/AGENTS.md`, `~/.codex/hooks.json` | `codex/hooks/`: `pre-bash-guard.sh`, `user-prompt-secret-guard.sh`, `pre-write-protect.sh` |

Every file under the packaged `agents/claude/assets/skills/` tree is declared as
its own global artifact and copied verbatim to the matching path under
`~/.claude/skills/`; adding a skill is adding a directory there, with no adapter
code change. Packaged skills are repo-agnostic — they detect the target repo's
stack rather than assuming one.

`agentkit project init` / `project update` install:

| Agent | Native agent files | Shared executable hooks |
| -- | -- | -- |
| Claude | `<repo>/.claude/settings.local.json`, `<repo>/CLAUDE.md` (seed) | `<repo>/.rn-forge/agentkit/claude/hooks/post-edit-format.sh` |
| Codex | `<repo>/.codex/config.toml`, `<repo>/.codex/hooks.json`, `<repo>/AGENTS.md` (seed) | `<repo>/.rn-forge/agentkit/codex/hooks/post-edit-format.sh` |

Guard coverage: destructive-command blocking (filesystem, git, DB-client-scoped
SQL), branch protection (force pushes and pushes to protected branches;
`AGENTKIT_PROTECTED_BRANCHES` overrides the `main|master` default, with
`CLAUDE_PROTECTED_BRANCHES` honored as a fallback), sensitive-path write
protection, and prompt-secret scanning.

The repository-local `post-edit-format.sh` is not a guard. It invokes a
repository-installed formatter for the file an agent just changed and always
exits 0. A root `.mdformat.toml` opts Markdown into formatting; the hook then
prefers `<repo>/.venv/bin/mdformat`, followed by an `mdformat` on `PATH`, and
skips the branch when neither exists. It never installs a formatter, and the
global pack no longer imposes a Markdown style on repositories.

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
  it cannot mirror Claude's `permissions.deny` Read list. Its write guard
  still protects sensitive in-repo paths. Revisit if Codex ships a read
  matcher.
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
`gitleaks` is recommended (warning in `doctor`); formatter binaries are optional
and each dispatch branch is `command -v` guarded.

## 8. Cross-cutting behavior

- **Idempotency** — apply/sync hash content before writing and skip unchanged
  files. `state.json` records `{path, hash, last_applied, source_layer}` per
  native artifact.

- **Dry run** — every mutating command accepts `--dry-run`: renders to memory,
  diffs against the current native file, prints a unified diff, writes
  nothing.

- **Backups** — before overwriting a native file whose on-disk hash is untracked
  (i.e. manual drift), the previous content is snapshotted under
  `<scope-root>/backups/<timestamp>/`. `reset` always backs up first.

- **Diff** — layered key-change table (defaults → global → local → overrides)
  plus per-artifact rendered-vs-native drift, catching manual edits.

- **Doctor** — schema validity, native path existence/permissions, drift,
  orphaned rendered files, stale state entries, template syntax, agent
  binaries, and the `jq`/`gitleaks` dependency checks.

- **Output** — `rich` tables and diffs; `--quiet` and `--json` are root-level
  flags for scripting and CI.

- **Exit codes** — `0` success, `1` validation/render error, `2` drift detected
  in `--check` mode.

- **Upgrade and cleanup** — `agentkit upgrade [--archive PATH]`
  (`commands/self_cmds.py`) resolves the latest GitHub release (or stages a
  local tarball via `--archive`, which may intentionally move to an older
  version than what's installed — worded as "installing" that version, not
  "upgrading" to it), builds it directly into its own
  `~/.rn-forge/agentkit/v<version>/`, and atomically flips the `current`
  symlink onto it (a private symlink built under a throwaway name, then
  `Path.replace`d over `current`, rather than `ln -sfn`'s remove-then-recreate
  window). It is a no-op when the resolved version already matches the running
  one. Concurrent invocations serialize on a portable `mkdir`-based lock
  (`.install.lock` under the product home) rather than `flock`, which isn't
  available everywhere this runs. The version directory itself is built in
  place rather than staged elsewhere and renamed in: `uv sync` bakes the
  environment's own path into console-script shebangs and activation scripts,
  so a build-then-rename would silently produce a venv whose scripts point at
  a path that no longer exists — and since nothing points at `v<version>/`
  until `current` is flipped onto it, there was nothing to protect by staging
  it elsewhere in the first place. `install.sh` uses the same
  lock-and-atomic-flip shape for the same reason. Upgrading never applies
  configuration — `agentkit upgrade` only ever installs and flips `current`,
  the same as `install.sh` always has; its output reminds the user to run
  `agentkit global apply` / `project update` afterward. `agentkit cleanup`
  removes every `~/.rn-forge/agentkit/vX.Y.Z/` other than the one `current`
  resolves to, behind a confirmation prompt (same `--yes`/`-y` convention as
  `global reset`).

    Ported from sibling product `macsetup`'s `rnfmac upgrade` / `rnfmac cleanup`
    (`macsetup/src/commands/upgrade.sh`, `cleanup.sh`), adapted to agentkit's
    Python/Typer shape: because the installed artifact is a `uv`-managed venv
    rather than a shipped shell-script tree, the logic lives in the Python
    package itself rather than a `scripts/upgrade.sh` that would only exist in
    whichever checkout happened to install it. Deliberately narrower than
    `macsetup` in one respect: `rnfmac upgrade` verifies each downloaded tarball
    against a published `.sha256` sidecar because `macsetup` builds and
    publishes its own release asset. `agentkit`'s `bootstrap.sh` installs from
    GitHub's auto-generated source archive for a tag, which has no such sidecar
    — there is nothing to verify against without agentkit also standing up a
    custom release-asset build, so checksum verification stays out of scope
    until/unless that happens.

- **Uninstall and remove** — `agentkit uninstall` (global) and
  `agentkit project remove` (repository-local) undo what `apply`/`init` put in
  place, in the same two steps at each scope: edit the primary native config
  in place — parsed as a generic round-trip document and stripped of its
  top-level `hooks` key, if present, rather than re-rendered through the
  adapter's schema, so anything else in the file (Claude's `permissions.deny`,
  a permission grant added at runtime) survives untouched — then delete the
  packaged skill files and any artifact an adapter marks via
  `AgentAdapter.is_native_hook_artifact` (Codex's `hooks.json`, whose entire
  content is hook wiring rather than something worth editing in place),
  pruning directories left empty behind them. A file that no longer matches
  its last-recorded state hash is left alone and reported as drifted instead
  of deleted — the same rule `capture_assets` relies on. Seed-only repo
  instructions (`CLAUDE.md`, `AGENTS.md`) are never touched.

    The scope root itself — `$RNF_HOME/share/agentkit` globally,
    `<repo>/.rn-forge/agentkit/` locally — is asked about under a second,
    separately worded confirmation, because it holds every backup either command
    (or any past `apply`) has ever taken: once it is gone there is nothing left
    to restore from. `agentkit uninstall` then removes the installed versions
    under `$RNF_HOME/agentkit/` and the `agentkit` command symlink
    unconditionally, after that confirmation, and never before it — the
    command's own code must still be resolvable while it edits native config.
    `agentkit project remove` also collapses the `.gitignore` block
    `project init` added, once the working-data root it governs is actually
    gone. Neither command reaches into a repository it doesn't know about:
    `agentkit uninstall` is global-scope only, and every repo a global install's
    user ran `project init` in needs its own `project remove`.

## 9. CLI surface

| Group | Commands |
| -- | -- |
| `agentkit global` | `apply`, `sync`, `reset`, `list` |
| `agentkit project` | `init`, `update`, `status`, `remove` |
| root | `diff`, `doctor`, `version`, `upgrade`, `cleanup`, `uninstall` |

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
clone has none, and a stale one would capture drift the user never made. A scope
with no native config yet reports that there is nothing to capture instead of
failing. This turns runtime accumulations — permission grants, `/config` changes
— into durable source instead of drift waiting to be clobbered.

Scope and limits: only the **primary config artifact** is captured structurally.
Append-merged lists capture only a suffix added to the rendered value. Key
removals and destructive edits to append-merged lists cannot be represented by
the layered merge model and are rejected rather than silently dropped.

The same `--write` flag also captures every other artifact backed by a packaged
static source — hook scripts and skill files — via `capture_assets`: a
hand-edited native file is copied verbatim onto its packaged source path in this
checkout when the two differ, so the fix is versioned instead of lost on the
next `apply`. This is a plain file copy, not a structural merge, and only does
something useful when running from an editable checkout of this repo; an
unwritable packaged source (an installed, non-editable package) is reported
per-artifact instead of raising.

A separate `--promote-defaults` flag folds a scope's managed `config.toml`
overrides into the packaged scope defaults (`defaults/<scope>.json` / `.toml`)
via `capture_defaults`, the structural counterpart of `capture_assets` for the
primary config artifact: same "packaged source inside this checkout" merge
target, same unwritable-target handling, same append-suffix and
removal-rejection rules as `capture_adapter`. It is a separate opt-in flag
rather than folded into `--write` because it changes what ships as the default
for every install, not just this scope's managed source — deliberately
higher-stakes than capturing drift or hand edits, so it is never a silent side
effect of a plain `--write`. Combine both flags to promote drift captured in the
same run.

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
reaches every repo the next time `init` runs there, instead of leaving a stale
block from whichever agentkit version first initialized it (§12, Phase 6).

The block only governs `.rn-forge/agentkit/`; it does not touch `.codex/` or
`.claude/` at all. Whether to commit or ignore agent-native files — including
`.claude/settings.local.json`, which stays personal by Claude convention as the
accumulation point for per-developer permission grants — is left to each repo's
own `.gitignore`, not prescribed by agentkit.

**Accepted tradeoff:** the committed `.codex/hooks.json` references hook scripts
that are ignored, so a fresh clone needs `agentkit project update` before the
Codex `PostToolUse` hook resolves. The alternative — committing generated,
version-dependent hook scripts — vendors build output into the repo and invites
conflicts between developers on different agentkit versions.

## 10. Installer

`install.sh` builds a versioned environment under
`$RNF_HOME/agentkit/v<version>/`, updates the `current` symlink, and links the
CLI at `$RNF_HOME/bin/agentkit`. It runs from a checkout, but a checkout is no
longer required to install: `scripts/bootstrap.sh` downloads the source tarball
for the latest GitHub release, extracts it to a temp dir, and runs `install.sh`
from there —
`curl -fsSL https://raw.githubusercontent.com/rn-forge/agentkit/main/scripts/bootstrap.sh | bash`.
Neither script edits shell rc files.

After the first install, `agentkit upgrade` (§8) is the way to move to a newer
version without re-running `bootstrap.sh` by hand, and `agentkit cleanup`
reclaims the disk space old versions leave behind — `install.sh` itself never
prunes them, which is what makes rollback-by-symlink (manually repointing
`current`) possible in the first place.

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

| Milestone | Outcome |
| -- | -- |
| A — rn-forge path model | `core/paths.py`; zero `".agentkit"` literals; dual `HOME`/`RNF_HOME` test isolation |
| B — multi-artifact adapters | `core/artifacts.py`; ordered per-scope artifact sets; artifact-aware doctor/diff/status |
| C — kiln defaults port | packaged defaults, shared guard lib + dialect adapters, absolute-path hook references |
| D — installer | `install.sh` (versioned venv, `current` symlink, `bin` link) |
| E — documentation | Google-style docstrings throughout `src/`, README source-layout and default-pack sections |
| F — test reorganization | `tests/` mirrors `src/` |
| G — pyright strict | 84 errors → 0, no new ignores |

**Phase 3 — packaged-asset review** (18 items, all implemented):

| # | Item | Landed in |
| -- | -- | -- |
| 1 | Stack-scoped Bash allowlist replaces blanket `Bash` allow | `claude/defaults/local.json` — `Bash`/`MultiEdit` removed, ~60 allow prefixes, publish/deploy commands moved to `ask` |
| 2 | `git push` guard rewritten to parse args | `guard-core.sh` — force detection anywhere in argv, `--force-with-lease` allowed off protected branches, `HEAD` resolved via `git branch --show-current`, `-u` false positive fixed |
| 3 | Auto-stage hook removed | `post-edit-git-stage.sh` deleted and unregistered — silent `git add` broke partial staging |
| 4 | jq enforced at install time, split runtime fail modes | `commands/common.py`, `core/doctor.py`, all guard adapters; guard-lib presence check before sourcing |
| 5 | `PostCompact` registration removed | that event surfaces only stderr while the script writes stdout; `SessionStart(compact)` already covers it |
| 6 | Read-deny list aligned with write-protect list | `claude/defaults/global.json` — 21 deny entries |
| 7 | `post-edit-format.sh` rewritten as extension dispatch | promoted to `assets/scripts/`; per-file, `command -v` guarded, logs failures, always exits 0 |
| 8 | SQL guard patterns narrowed to DB clients | `truncate -s 0` no longer false-positives |
| 9 | gitleaks with regex fallback | `guard-core.sh` + optional-dependency warning in `doctor` |
| 10 | Instruction content single-sourced | `assets/instructions/` partials + three `.j2` renderers + byte-equality snapshot tests |
| 11 | Clarifications section trimmed 14 → 5 bullets | `assets/instructions/clarifications.md` |
| 12 | Risk/tradeoff carve-out added to concise style | `assets/instructions/style.md` |
| 13 | Sub-agent rule conditioned on large tasks | `assets/instructions/behavior.md` |
| 14 | Codex `global.toml` hygiene | model pin removed, `[features] hooks`, `[profiles.trusted]` safety comment |
| 15 | Protected-branch env var renamed | `AGENTKIT_PROTECTED_BRANCHES`, legacy name as fallback |
| 16 | Executable bits normalized | all six hook adapters + shared formatter at 755 |
| 17 | repo-context skill dropped | restated default behavior with no added capability; `Artifact` skill-tree plumbing retained for future real skills |
| 18 | Cross-agent hook/guard parity | Codex `pre-write-protect.sh`, Codex `post-edit-format` via `hooks.local.json`, shared `guard_check_write_path`, both dialects tested |

**Phase 4 — post-review fixes and write-back.** Three defects found by running
the tool for real, plus the two remaining design items:

| Item | Outcome |
| -- | -- |
| gitleaks weakened the prompt-secret guard | An early `return 0` made the regex set unreachable whenever gitleaks was installed, so the _recommended_ dependency silently cut detection coverage. Now unioned — block if either fires — with detection distinguished from gitleaks execution failure. Surfaced only because installing gitleaks un-skipped four tests. |
| `apply` created one backup directory per file | `backup_file` called `datetime.now()` per invocation. The timestamp is now scoped to the CLI run via `start_backup_run()`, called from the root callback, giving one directory per run |
| `project init` left a non-working repo | `init` scaffolded only the managed `config.toml`; rendering happened solely in `update`. `init_command` now composes scaffold + render + sync, keeping `init_adapter` scaffold-only as the honest primitive |
| `.gitignore` scaffolding | `project init` writes the derived-data block between markers, idempotently (§9b) |
| Write-back phase 1 | `diff --write` captures native drift into the managed source (§9a) |

**Phase 5 — scope-root layout consolidation.** The scope root previously mixed
`hooks/{lib,claude,codex}/` alongside the `<agent>/` directories, splitting each
agent's files across two places. Consolidated so every content directory is an
`<agent>/` directory or `_common/`:

| Before | After |
| -- | -- |
| `hooks/lib/guard-core.sh` | `_common/hooks/guard-core.sh` |
| `hooks/<agent>/*.sh` | `<agent>/hooks/*.sh` |

The shared library was the sole reason hooks lived at the scope root — it is
declared by both adapters and must not be duplicated. `_common/` names that
sharing explicitly, and the underscore prefix cannot collide with an adapter
name. Mechanical: artifact registrations, 9 absolute references in packaged
configs, the `LIB=` line in 6 hook scripts (now `../../_common/hooks/`), the
`.gitignore` block, and tests. No logic changed.

Two questions settled at the same time:

- **`rendered/<agent-dot-dir>/` is kept.** It mirrors the destination path
  relative to its native root, not the agent name; the apparent duplication
  only shows because both built-in adapters happen to put every artifact under
  one dot-directory. Flattening would need a special case that breaks for any
  adapter writing to two native roots, and would risk basename collisions.
- **Managed sources are now self-documenting and symmetric.** `config.toml` is
  scaffolded with a header explaining that it is the hand-edited layer and the
  `diff --write` capture target. `global apply` scaffolds it too — previously
  only the local scope got a file, leaving no obvious home for global
  overrides.

**Validation (2026-08-03):** `pytest` 93 passed, `ruff check src tests` clean,
`pyright src` 0 errors, and a full end-to-end gate in scratch `HOME`/`RNF_HOME`
— `global apply` → re-apply reporting all-unchanged → `project init` →
`project update` → `doctor` on both scopes.

**Phase 6 — dogfooding and documentation pass.** Running the tool on its own
repository surfaced three loose ends, plus this repo's own `CLAUDE.md`/
`AGENTS.md`/README were brought up to date:

| Item | Outcome |
| -- | -- |
| `.gitignore` block could go stale | `project init` previously left an existing `# BEGIN/END rn-forge agentkit` block untouched, so a layout change like Phase 5 never reached repos initialized on an older version. It now replaces the block in place on every `init` run, matched by its markers |
| Claude skills undocumented in this spec | `~/.claude/skills/**` is a real global artifact set (one artifact per packaged skill file) but was missing from the §7 table; added |
| Repo's own `.gitignore` had drifted | This repo's `.gitignore` still had the pre-Phase-5 blanket `.rn-forge/` entry (predating the fine-grained `_GITIGNORE_ENTRIES` list). Fixed by running `agentkit project init` against this repo, which rewrote it via the fix above |
| `CLAUDE.md` / `AGENTS.md` / `README.md` | Root-level `CLAUDE.md` (model context, references this spec + README) and `AGENTS.md` (thin pointer to `CLAUDE.md`) added; `README.md` reviewed for accuracy against current code |

**Phase 7 — repo instruction seeds (2026-08-29).** The pointer-`AGENTS.md`
construct developed by hand in `macsetup` and `shkit` was adopted for this
repo's own `AGENTS.md` and then packaged, so `project init` seeds it in every
target repo (§6.4).

| Item | Outcome |
| -- | -- |
| `Artifact.seed_only` | New flag: write when the native path is absent, then leave the file to the repo. Honored in `_apply_resolved`, `sync_adapter`, and the `diff` command |
| Repo-root `AGENTS.md` | Codex local artifact from `assets/instructions/AGENTS.local.md.j2` — the imperative pointer to `CLAUDE.md` plus the "do not add guidance here" rule |
| Repo-root `CLAUDE.md` | Claude local artifact from `CLAUDE.local.md.j2`; a placeholder scaffold, so the pointer never dangles |
| This repo's `AGENTS.md` | Rewritten from the old descriptive "see CLAUDE.md" form into the shared construct |

**Validation (2026-08-29):** `pytest` 100 passed (2 updated adapter-artifact
tests, 2 new seed-behavior tests), `ruff check src tests` clean, `pyright src` 0
errors, plus an end-to-end run in a scratch `HOME`/`RNF_HOME` — `project init`
seeds both files, a hand edit survives `project update`, and `diff` reports no
drift.

**Phase 8 — release install path and Pages verification (2026-08-31).** The repo
gained its GitHub remote (`rn-forge/agentkit`), closing out the two
install/deploy items that had been blocked on that.

| Item | Outcome |
| -- | -- |
| Clone-free install | `scripts/bootstrap.sh` added: resolves the latest GitHub release, downloads its source tarball to a temp dir, and runs `install.sh` from there — no `git clone` needed (§10) |
| Editable-install bug | `install.sh`'s `uv sync` was editable by default, so a CLI installed from a temp dir (as bootstrap does) pointed back at a path deleted right after; fixed with `--no-editable`, which is also correct for a deployed CLI vs. a dev checkout |
| Pages deploy | Verified end-to-end: remote added, Pages enabled (Source: GitHub Actions), `.github/workflows/docs.yml` ran successfully on `main`, site live at <https://rn-forge.github.io/agentkit/> (HTTP 200) |
| GitHub Release publish step | Verified already working (not missing, as first suspected): CI's `publish` job tags the version, creates a GitHub Release, and uploads the wheel/sdist — confirmed via `v0.1.1` release existing |

**Validation (2026-08-31):** `task lint` clean. Bootstrap flow tested twice —
once against the already-tagged `v0.1.1` release (reproduced the editable-
install bug), once via `git archive HEAD` piped through the patched `install.sh`
(confirmed `agentkit version` works after the source dir is removed). Pages URL
confirmed live with `curl -o /dev/null -w '%{http_code}'`.

**Phase 9 — default-value curation (2026-08-31).** Kiln-ported config values
(models, policies) had never been reviewed on their merits — Phase 3 curated the
asset pack's structure and safety, not every value. Reviewed all four packaged
default files (`claude/defaults/{global,local}.json`,
`codex/defaults/{global,local}.toml`) against current Claude Code and Codex CLI
documentation.

| Item | Outcome |
| -- | -- |
| Claude `effortLevel: "medium"`, `outputStyle: "concise"` | Confirmed current and correct; `outputStyle` is load-bearing for the §6.3 instruction single-sourcing, not an arbitrary port |
| Claude `permissions.deny`/`allow`/`ask` lists | Confirmed still aligned with the Phase 3 item 1/6 curation — no stale entries found |
| Codex `personality`, `model_reasoning_effort`, `approval_policy`, `sandbox_mode`, `profiles.*` | Confirmed current and correct against upstream docs; no changes needed |
| Codex `model_reasoning_summary = "concise"` | Kept — CLI default is `auto`, but `"concise"` is a deliberate parity choice with Claude's output style; added a comment in `global.toml` so it doesn't read as an unreviewed leftover |
| `codex/schema.py` `model_reasoning_effort` literal | Was missing the `"none"` value present in current upstream docs; added |

No default values changed as a result of the review — the kiln port held up.
This closes the item as "reviewed and confirmed" rather than "found and fixed."

**Phase 10 — `doctor` report model (2026-09-01).** The report conflated three
things in one `status` field (`ok`/`warning`/`error`/`drift` mixes severity
words with outcome words), which is why a drifted artifact rendered as
`drift | drift | key: differs: <path>` — the same fact three times — while the
one path it showed was ellipsis-truncated and named only the target, never what
the target was compared against.

| Item | Outcome |
| -- | -- |
| Status/severity split | `CheckResult.status` is now the outcome (`ok`, `seeded`, `drift`, `stale`, `missing`, `unsynced`, `orphan`, `invalid`, `unwritable`) and `severity` (`info`/`warning`/`error`) is how much it matters. Exit codes read `severity == "error"` → 1 and, with `--check`, `status in {drift, stale}` → 2 — the same behavior as before the split |
| `Artifact.kind` | New declared field (`config`/`hook`/`skill`/`doc`) replacing `CheckResult.check` for artifact rows. Declared by the adapter rather than sniffed from key prefixes, so a third-party adapter's artifacts type correctly without agentkit parsing its naming scheme |
| `source`/`target` columns | `AgentAdapter.source_path()` names the packaged file an artifact is produced from — the static asset, or the resolved Jinja template. Artifact rows drop their prose message entirely: two paths plus a status say which files were compared and how they differ |
| `template_root()` | Extracted so "which packaged directory does this template resolve against" has one dispatch point. `render_artifact` and `source_path` both consume it; previously only `render_artifact` knew, and a second copy in doctor would have silently drifted from it |
| Two tables | Artifact rows (`agent`/`type`/`status`/`severity`/`source`/`target`) and diagnostic rows (`…/detail`) — schema errors, binaries, dependencies, plugins, state have no two files to compare, and are the only rows a message is load-bearing for |
| No truncation | Roots are factored into a `$PKG`/`$SHARE`/`$HOME`\|`$REPO` legend and cells use rich's `overflow="fold"`. A narrow terminal wraps; it never elides. A doctor row exists to be acted on, and a path ending in `…` cannot be opened or copied |
| `stale` target corrected | A stale finding now points `target` at the staged copy that is actually out of date, not at the native file, which was healthy |

**Breaking output change.** `--json` objects lose `check` and gain `kind`,
`severity`, `source`, `target`; `status` values changed as above. `--quiet`
lines went from `agent:status:check` to `agent:severity:status:kind`. Pre-1.0
and unreleased, but it is the reason this is recorded rather than folded into a
patch note.

**Note on `$PKG`.** It follows the running interpreter's import path, so it
distinguishes a site-packages install from a repo checkout — but only for a
non-editable install. This repo's own `~/.rn-forge/agentkit/current` is an
editable venv whose `.pth` points at the checkout's `src/`, so both resolve to
the same files there and `source` cannot explain drift on this machine.

**Validation (2026-09-01):** `task validate` clean — lint, pyright strict (0
errors), 188 tests passed, docs build. Three new CLI tests cover the
source/target contract on artifact rows, the legend-plus-no-ellipsis rendering,
and exit code following severity rather than status.

**Phase 10a — interactive diff prompt on `doctor` (2026-09-01).** Following the
report-model rework above, `doctor`'s human-readable output numbers each
artifact row (`#` column) and, when both stdin and stdout are attached to a
terminal, prompts after the tables for a row number and prints that artifact's
unified diff — recomputed on demand from the same adapter and rendered content
`check_agent` used, matched back to the `Artifact` by target path since
`CheckResult` carries no direct reference to it. Blank input, `q`, Ctrl+D, or
Ctrl+C exit the prompt. A piped or scripted invocation (either stream not a tty)
skips the prompt entirely — confirmed with `< /dev/null`, which returns
immediately rather than blocking.

Considered and rejected: a full cursor-navigable TUI (arrow-key highlight, Enter
to drill in, Esc to pop back). That needs raw terminal control a plain `rich`
table can't provide — `textual` or `prompt_toolkit` as a new dependency, plus a
second non-interactive code path — for the same outcome the numbered-prompt loop
gets with no new dependency and no divergent path between piped and interactive
use.

The diff computation itself is `_artifact_diff`, extracted from `diff_command`'s
existing per-artifact text/bytes comparison rather than duplicated — the
interactive prompt and `agentkit diff` now share the one implementation.

**Validation (2026-09-01):** `task validate` clean (same figures as above, 188
tests — no new automated coverage for the interactive branch itself, since it
only runs on a real tty; verified manually via a `pty`-backed harness that sent
`"1\nq\n"` to `doctor --scope global --agent codex` and confirmed a real unified
diff printed for row 1 and a clean exit (code 0) on `q`).

**Phase 11 — repository-owned Markdown formatting (2026-09-01).** Replaced the
global, dependency-free `unwrap_md.py` convention with mdformat as a
repository-owned docs tool. The original helper collapsed each paragraph to one
source line and had to approximate Markdown structure with regular expressions;
the proposed Prettier replacement reflowed prose correctly but needed a second
custom parser to undo its padded GFM tables. `mdformat` provides the required
80-column reflow itself, and `mdformat-gfm` provides compact tables without a
post-processing script.

The formatter stack is `mdformat`, `mdformat-gfm`, `mdformat-mkdocs`, and
`mdformat-front-matters` in the uv-managed `docs` dependency group. It is not a
runtime dependency of the published CLI. `.mdformat.toml` fixes `wrap = 80`,
enables compact table output, preserves MkDocs missing-reference syntax, and
disables math parsing because this site's Markdown configuration does not enable
Arithmatex. `task format` formats tracked `*.md` files and `task lint` runs the
matching `mdformat --check`, so the convention is both mechanical and
CI-enforced. The Jinja-bearing `assets/instructions/style.md` source fragment is
excluded because template whitespace affects its rendered output; the rendered
instruction artifacts remain formatted and snapshot-tested.

Formatting policy stays with each repository. A root `.mdformat.toml` opts into
the local `post-edit-format.sh`, which uses `<repo>/.venv/bin/mdformat` when
present, falls back to an `mdformat` already on `PATH`, and otherwise does
nothing; it never fetches or installs tooling from a hook. The global
`PostToolUse` registration, `post-write-unwrap-md.sh`, `unwrap_md.py`, and the
bespoke `.nounwrap` marker were removed. Agentkit owns the post-edit
integration, not a general-purpose Markdown formatter or table parser.

**Validation (2026-09-01):** `task lint`, pyright strict, and the strict docs
build clean; 187 tests passed. A second mdformat check was clean after the
one-time repository-wide normalization.

**Phase 12 — write-back phase 2: promote config values to packaged defaults
(2026-09-01).** Closed the one remaining §13 item. `capture_assets` already
wrote hand-edited hooks/skills back to their packaged source in an editable
checkout; `config.toml` changes captured by `capture_adapter` still only ever
landed in the scope's managed `config.toml`, never in the packaged
`defaults/global.json` / `global.toml` those scopes render from.

Added `AgentAdapter.defaults_path(scope)` (both adapters implement it; the base
default is `None`, meaning "nothing packaged to promote into") so `defaults()`
and the new capture share one packaged-file location instead of each adapter
deriving it twice. Added `capture_defaults` in `manager.py`: the structural
counterpart of `capture_assets` for the primary config artifact — same
`_capture_updates` merge helper `capture_adapter` uses, run between the packaged
defaults (`expected`) and packaged-defaults-plus-managed-override (`actual`),
targeting only this scope's own managed source so a local scope's promotion
never pulls in the global layer that also feeds its resolved config. Same
append-suffix and removal-rejection rules, same
unwritable-target-reported-not-raised handling as `capture_assets`.

Exposed as a separate `--promote-defaults` flag on `agentkit diff`, not folded
into `--write`: unlike native-drift capture (stays scope-local) or hand-edited
asset capture (only fires when a native file actually diverged from its packaged
source), a managed `config.toml` routinely holds prior overrides unrelated to
the current invocation, and folding those into the packaged defaults changes
what ships to every install. Running it unconditionally under `--write` surfaced
exactly that risk during development: a test using the real (editable-checkout)
adapters wrote a captured value straight into this repo's own
`codex/defaults/local.toml`, which then leaked into later tests in the same
process. `--promote-defaults` makes that a deliberate, separately-invoked
action; combine it with `--write` to promote drift captured in the same run.

**Validation (2026-09-01):** `task lint`, `task typecheck` (pyright strict, 0
errors), and `task test` clean (189 tests, plus the 2 pre-existing failures in
`test_claude_instruction_snapshots_match_shared_templates` and
`test_codex_instruction_snapshot_matches_shared_template` carried over unrelated
from this session's starting WIP). New coverage: unit tests for
`capture_defaults` (promote, no-managed-overrides, unwritable-target) against a
monkeypatched `defaults_path`, and a CLI test for `--promote-defaults` against a
monkeypatched `CodexAdapter.defaults_path` — never against this repo's real
`defaults/*.json` / `*.toml` files, for the reason above.

**2026-09-01 — `agentkit uninstall` and `agentkit project remove`.** The build
had no way to undo an install: `global reset` restores agentkit's own defaults,
not a pre-agentkit state, and neither it nor `cleanup` touched the hook
registrations `apply` wires into `~/.claude/settings.json` or
`~/.codex/hooks.json`. Two new commands close that gap — `agentkit uninstall` at
global scope, `agentkit project remove` per repository — sharing two new
`core/manager.py` primitives: `strip_native_hooks` parses the primary native
config as a generic round-trip document (`read_config_document` /
`write_config_document`, format-agnostic across JSON/TOML/YAML) and drops its
top-level `hooks` key in place, so Claude's `permissions.deny` and other
runtime-added content survive; `remove_owned_artifacts` deletes packaged skill
files and any artifact an adapter flags via the new
`AgentAdapter.is_native_hook_artifact` (Codex's `hooks.json`, whose entire
content is hook wiring, unlike the mixed-content primary config), pruning
directories left empty behind them, and leaves a file alone — reporting it as
drifted rather than deleted — if its hash no longer matches `state.json`,
mirroring `capture_assets`'s drift safety.

Both commands ask about the scope root (`$RNF_HOME/share/agentkit` /
`<repo>/.rn-forge/agentkit/`) under a second, separately worded confirmation
before deleting it, since it holds every backup ever taken at that scope —
irreversible once gone, and the reason a blind `rm -rf ~/.rn-forge` (or a naive
single-prompt uninstall) would have made rollback impossible. Removing
agentkit's own installed versions and command symlink happens last, after that
confirmation, so the running code stays resolvable while it edits native config
first — the mirror image of `upgrade`'s atomic-flip ordering (§8).
`project remove` also collapses the `.gitignore` block `project init` added,
once the working-data root it governs is confirmed gone. Neither command reaches
into a scope it wasn't invoked against: `uninstall` never touches a repository's
`project init` state, by design (§9).

**Validation (2026-09-01):** `task test` (13 new tests: `strip_native_hooks` and
`remove_owned_artifacts` unit coverage in `test_manager.py`, CLI coverage for
both commands' confirm/decline/dry-run paths in `test_self_cmds.py` and
`test_cli.py`) and `task typecheck` (pyright strict, 0 errors) both clean,
alongside the same 2 pre-existing snapshot-test failures carried over from this
session's starting WIP.

**2026-09-01 — Phase 5, structural refactor (§14), executed as specified.**
Three commits, one per phase, each behaviour-preserving and independently green:

- **A** collapsed `agents/claude/adapter.py` and `agents/codex/adapter.py` into
  `AgentAdapter`: `Artifact.template_root`, a linear
  `render_artifact()`/`source_path()` in the base class keyed off
  `Artifact.kind`, `package_dir`-derived `template_dir`/`_assets_dir`/
  `defaults_path()`, and `_global_artifacts()`/`_local_artifacts()` replacing
  the per-adapter `artifacts()` override. `AgentRegistry._validate_artifacts`
  moved from a module function to a private static method.
- **B** split `core/manager.py` (919 lines, four pipelines sharing only
  `OperationResult`) into
  `core/operations/{result,apply,remove,capture, init}.py`, re-exported from
  `core/operations/__init__.py`. `project_root`, `scope_root`, and
  `managed_config_path` moved to `core/paths.py`; `Artifact.mode` replaced
  `_artifact_mode()`; `AgentAdapter.managed_source_scaffold()` replaced the
  module-level `_managed_source_scaffold()`.
- **C** made `cli.py` the complete Typer surface (root callback, `global`/
  `project`/`self` sub-apps, root-level `diff`/`doctor`/`version`, every
  command function 1–3 lines) backed by command classes in `commands/`:
  `BaseCommand` (replacing `commands/common.py`) carries per-invocation
  `--quiet`/`--json` state and exposes `emit`/`emit_operations`/`fail`/
  `selected`/`boundary`/`warn_if_jq_missing`; `GlobalCommand`,
  `ProjectCommand`, `SelfCommand`, and `RootCommand` replace
  `{global,project,self,shared}_cmds.py`. `RootCommand`'s doctor/diff
  presentation split by row kind into private methods
  (`_print_agent_summary`/`_print_artifact_rows`/`_print_diagnostic_rows`/
  `_print_doctor_footer` and `_print_capture_summary`/`_print_layer_changes`/
  `_print_artifact_drift`).

**Validation:** `task format`, `task typecheck` (pyright strict, 0 errors), and
`task test` (204 tests) clean after every phase; `task docs:build --strict`
clean after phase C. `task lint`'s `mdformat --check` step continues to fail on
the same 2 pre-existing packaged-snapshot files noted above (unrelated to phase
5 — reproduces identically on the pre-phase-5 commit); not fixed here.

## 13. Pending

None. All items from phases 1–5 are resolved; see §12 for the closing entries.

______________________________________________________________________

## 14. Phase 5 — structural refactor (implemented 2026-09-01; see §12)

Origin: a maintainability review of `src/` on 2026-09-01. Nothing here fixes a
bug or adds a capability — the whole phase exists so that a future reader can
see what a module does without reconstructing a dispatch chain first. It is
written as a hand-off: a session that has read §§1–13 and this section should be
able to execute a phase end to end without further design decisions.

### 14.0 Ground rules

**Behaviour-preserving.** No change to the CLI surface, option names, help text,
human or `--json` output bytes, artifact keys, native paths, `state.json`
format, or backup layout. `tests/` is the contract: the suite should pass
unchanged except where a phase below explicitly authorizes an edit. A test that
needs a *new assertion changed* is a signal that the refactor has changed
behaviour — stop and report it rather than updating the assertion.

**One phase, one commit, one green gate.** Phases A → B → C in order; each ends
at `task format && task validate` clean (lint, pyright strict at zero errors,
tests, docs build) and is independently revertable. B is much easier after A; C
is much easier after B.

**Docs move with the code.** Each phase names the pages it invalidates. In
particular `docs/reference/python-api.md` lists modules explicitly and
`mkdocs.yml`'s `nav` is the page structure — a module added or renamed without
updating them fails `task lint`.

**The existing conventions still apply.** No positional indexing into
`artifacts()` or operation-result lists (select by `.key` / `.artifact`); no new
`# type: ignore`; `task` remains the only entrypoint.

### 14.1 Phase A — collapse the two adapters into `AgentAdapter`

`agents/claude/adapter.py` and `agents/codex/adapter.py` are ~180 lines each and
differ in about 40 of them. `render_artifact()` and `template_root()` are
if/else chains over artifact *keys*, duplicated per adapter, and `doctor` has to
re-enter the same dispatch through `source_path()` to name a template's source
file. Target: each concrete adapter declares only `schema()`, `render()`,
`parse_native()`, and its two artifact lists.

**A1 — put the template root on the declaration.** Add
`template_root: Path | None = None` to `Artifact` (`core/artifacts.py`): the
packaged directory `template` resolves against, `None` meaning the adapter's own
`template_dir`. Reject `template_root` set without `template` in
`__post_init__`, alongside the existing exclusivity check.

**A2 — `render_artifact()` becomes linear, in the base class only.** Source
first, then the primary config through `render()` (which validates through the
schema), then a single templated path:

```python
root = artifact.template_root or self.template_dir
return RenderEngine(root).render_template(
    artifact.template, self._render_context(artifact, merged_config)
)
```

`_render_context()` keys off `artifact.kind`, not `artifact.key`: `skill` →
`{"agent": self.name}`, `doc` → `{}`, otherwise `{"config": merged_config}`.
Both adapter overrides of `render_artifact()` and `template_root()` are then
deleted, as is `AgentAdapter.template_root()` itself. `source_path()` collapses
to
`artifact.source or (artifact.template_root or self.template_dir) / artifact.template`;
`core/doctor.py:167` is its only external caller.

Do **not** implement this as an adapter-registered `{key or kind: directory}`
map. That keeps the indirection and adds a second place to look; the point is
that the artifact declaration already knows where it comes from.

**A3 — derive the packaged directories from `self.name` in the base class.**
`template_dir`, `_assets_dir`, `_shared_scripts_dir`, `_shared_instructions_dir`
and the native skills root (`.claude/skills` / `.codex/skills`, i.e.
`Path(f".{self.name}") / "skills"`) are identical modulo the agent name. The
subtlety: the base class cannot use `__file__` to find a *subclass's* package
directory. Use one `package_dir` property —
`Path(inspect.getfile(type(self))).parent` — and derive `template_dir`,
`_assets_dir` and `defaults_path()` from it. This works for third-party adapters
too, which is why it is preferable to a per-adapter constant.

**A4 — move `defaults()` / `defaults_path()` up.** Both adapters merge schema
defaults with a packaged scope file and differ only in extension. Base
`defaults_path()` returns `package_dir / "defaults" / f"{scope}{suffix}"` from a
class attribute (`".json"` for Claude, `".toml"` for Codex) and keeps returning
`None` when the attribute is unset, so a schema-only third-party adapter still
works; `defaults()` merges the packaged layer only when that path exists.
`template_errors()` is byte-identical in both adapters — move it as-is.

**A5 — factor the repeated artifact blocks.** The global "guard-core.sh plus N
executable hook scripts under `<share>/<agent>/hooks/`" block and the local
`post-edit-format.sh` block are structurally identical; give the base a helper
taking the script names. Preserve declaration **order** exactly — the comments
in both adapters explain that hook scripts are declared before the config that
points at them by absolute path, and `tests/agents/test_*_adapter.py` asserts
the key order.

**A6 — `artifacts(scope)` becomes concrete in the base**, dispatching to
abstract `_global_artifacts()` / `_local_artifacts()` that each adapter
implements as a flat list. Do **not** turn these into class-level list
attributes: `skill_artifacts()` `rglob`s the packaged skills tree, and a
class-body list would run that glob at import time for every adapter on every
invocation, including `--help`. The method form reads the same and stays lazy.
Record that reason next to the abstract methods so it is not "simplified" later.

**A7 — `registry._validate_artifacts` becomes a private static method of
`AgentRegistry`**, called from `_load()`. No test imports it by name today
(checked), so this is pure motion.

Expected shape afterwards: `agents/base.py` grows to roughly 400 lines; each
concrete adapter drops to ~80 and reads as "schema, render, parse, two lists".
Docs to update: `docs/architecture/adapters.md` (the adapter contract — the
`template_root` field and the fact that `render_artifact`/`template_root` are no
longer extension points), and the `Artifact` attribute table in §6.1 of this
document is historical and stays as written.

### 14.2 Phase B — split `core/manager.py`

919 lines spanning four pipelines that no longer share much beyond
`OperationResult`: apply/sync, uninstall-style removal, capture/write-back, and
project init. Target layout — a `core/operations/` package:

| Module | Contents |
| -- | -- |
| `operations/result.py` | `OperationResult` and the shared private helpers (`_content_diff`, `_seeded_result`, `_managed_copy_path`, `_mode_differs`, `_highest_source`) |
| `operations/apply.py` | `resolve_config`, `apply_adapter`, `sync_adapter`, `_apply_resolved`, `artifact_drifted` |
| `operations/remove.py` | `reset_adapter`, `strip_native_hooks`, `remove_owned_artifacts`, `_prune_empty_dirs` |
| `operations/capture.py` | `capture_adapter`, `capture_assets`, `capture_defaults`, `_capture_updates` |
| `operations/init.py` | `init_adapter`, `scaffold_managed_source` |

`operations/__init__.py` re-exports the public verbs and `OperationResult`, so
call sites import one module:
`from ..core.operations import apply_adapter, OperationResult`. Delete
`core/manager.py` rather than leaving it as a forwarding facade — a facade that
still answers to the old name is exactly the kind of "where does this actually
live" question this phase exists to remove. Import sites to update:
`commands/*`, `core/doctor.py`, and five test modules
(`tests/core/test_artifacts.py`, `test_doctor.py`, `test_state.py`,
`test_manager.py`, `tests/hooks/test_guard_scripts.py`). **Import-line edits are
the only authorized test change in this phase**; rename
`tests/core/ test_manager.py` to mirror the new modules if the split is clean
enough to divide it, otherwise leave it whole.

Also in B:

- `project_root`, `scope_root`, `managed_config_path` move to `core/paths.py`,
  which is where every other path derivation already lives.
- `_artifact_mode()` becomes an `Artifact.mode` property (`0o755` when
  `executable`, else `None`). This is the *right* version of "bring
  capabilities into the artifact": a derived property on a frozen declaration.
- `_managed_source_scaffold()` becomes an `AgentAdapter` method — it is
  adapter-shaped data (the commented header of a managed source file), not
  manager logic.

**Explicitly rejected, do not implement:** moving atomic writes, backups, or
state recording onto `Artifact`. `Artifact` is a frozen, self-validating
declaration constructed inside every adapter's artifact list; giving it I/O
would pull `core.io`, `core.state` and the backup-run singleton into that list
and make the declaration untestable without a filesystem. If write consolidation
becomes worthwhile, the home is an `ArtifactWriter` in `core/operations/` that
*takes* an `Artifact` — and that is a separate, later decision, not part of this
phase.

**Also rejected:** moving `write_config()` from `core/io.py` into
`core/render.py`. `render.py` is the Jinja engine (template resolution,
`StrictUndefined`, compile-time validation); `write_config` is JSON/TOML/YAML
serialization plus a write, which is `io`'s entire subject. The move would make
the render layer depend on format dispatch to serve one caller.

Docs to update in B: the source-layout table in `docs/guides/development.md`;
`docs/reference/python-api.md` (replace the `core.manager` entry with the
`core.operations` modules); and — importantly — the **"`core/manager.py` is
large" trade-off entry** in `docs/guides/development.md`. That entry currently
records a decision *not* to split, on the grounds that the module is one
cohesive apply pipeline. Per `CLAUDE.md`, extend rather than re-litigate:
rewrite it to record that the condition it named has since failed — the module
grew from ~600 to 919 lines and now carries four pipelines (apply, remove,
capture, init) that share only a result type — and that this is what triggered
the split.

### 14.3 Phase C — one command surface, command objects behind it

Two problems: there is no single place to see the whole CLI, and the command
modules mix argument parsing, orchestration, and presentation, which is where
Sonar's cyclomatic-complexity findings sit.

**C1 — `cli.py` becomes the complete command-line surface.** Every Typer
registration lives there: the root callback, the `global` / `project` / `self`
sub-apps, and the root-level commands, with all option names, defaults, and help
strings inline. Each function body is one to three lines — construct the command
object from the Typer context, call the method, nothing else. The file will land
around 400 lines; that is the point, since it is then a readable index of the
tool. Adapter `cli_extension` mounting and its per-plugin isolation stay exactly
as they are today.

**C2 — `commands/<name>_cmds.py` becomes `commands/<name>_command.py` with a
class**, methods named for the operation: `GlobalCommand.apply/sync/reset/list`,
`ProjectCommand.init/update/status/remove`,
`SelfCommand.upgrade/cleanup/ uninstall`, `RootCommand.diff/doctor/version`.

**C3 — the shared logic is a base class, not a static-method bag.** A class of
`@staticmethod`s is a module with extra syntax. Make `commands/base.py` hold a
`BaseCommand` constructed from the Typer context that *carries the invocation
state* every function currently re-derives — the context, the resolved
`quiet`/`json` flags, the repo root — and exposes `emit`, `emit_operations`,
`fail`, `selected`, `boundary`, `warn_if_jq_missing` as methods. That absorbs
most of today's `commands/common.py`. Keep the module-level `_json_mode` mirror
and `set_json_mode()` as free functions: the root callback resolves `--json`
before any command object exists, and the JSON error contract has to hold for a
root-level parameter conflict. Leave a comment saying so.

**C4 — the presentation helpers are the complexity, and the only place a
non-trivial rewrite is invited.** `_render_doctor` and `_render_diff` in
`shared_cmds.py` are the flagged functions; while moving them onto
`RootCommand`, split each by row kind into private methods. Their output is
asserted on in `tests/commands/test_cli.py` — it must stay byte-identical, and
that suite is the check that the split is safe.

Docs to update in C: `docs/reference/python-api.md` (module renames — note it is
currently missing `commands.self_cmds` entirely, so add the `self` command
module while renaming) and the source-layout table in
`docs/guides/development.md`.

### 14.4 Out of scope for phase 5

`core/config.py`, `core/diff.py`, `core/doctor.py` and `core/state.py` were
reviewed and deliberately parked; touch them only for the import updates phases
A–C force. `agents/*/assets/`, `defaults/`, `templates/`, and the `schema.py`
modules were reviewed and judged fine as they are. No new features, flags,
output modes, or dependencies belong in this phase — the value of the whole
exercise depends on being able to say afterwards that nothing about the tool's
behaviour changed.
