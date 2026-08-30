# agentkit

`agentkit` manages global and repository-local configuration for AI coding
agents from one layered source of truth. It ships adapters and a default asset
pack for Claude Code and Codex, and discovers third-party adapters through
Python entry points.

## Install

The installer creates a versioned environment under
`~/.rn-forge/agentkit/v<version>/`, updates `current`, and links the CLI at
`~/.rn-forge/bin/agentkit`:

```bash
./install.sh
export PATH="$HOME/.rn-forge/bin:$PATH"
agentkit version
```

`RNF_HOME` overrides `~/.rn-forge`. Installation currently runs from a checkout,
so this repository and the sibling `../pykit` path dependency must remain
available while `install.sh` runs. The installer does not edit shell rc files.

For development:

```bash
uv sync --group dev
uv run agentkit --help
```

### External dependencies

| Tool       | Status       | Used for                                                                                                                                                                                                                                                                |
| ---------- | ------------ | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `jq`       | **Required** | Every hook parses its JSON event payload with `jq`. `global apply` and `project init` warn when it is missing, and `doctor` reports it as an error. `PreToolUse` guards fail closed (exit 2) without it; `UserPromptSubmit` guards fail open so a session stays usable. |
| `gitleaks` | Recommended  | Prompt-secret scanning uses `gitleaks stdin` when present in addition to the built-in regex set. `doctor` reports it as a warning.                                                                                                                                      |

Formatter binaries (`ruff`, `npx`/`prettier`, `google-java-format`, `shfmt`) are
optional — the post-edit hook skips any branch whose tool is not installed.

## Configuration model

Values resolve in increasing precedence:

```text
packaged scope defaults
  → $RNF_HOME/share/agentkit/<agent>/config.toml
  → <repo>/.rn-forge/agentkit/<agent>/config.toml
  → --set dotted.key=value
```

The local managed source participates only for local operations. Packaged global
defaults do not leak into packaged local defaults, while a user's managed global
source still feeds both scopes.

Dictionaries merge recursively. Lists replace lower layers unless the adapter
schema marks a field with `merge_strategy: append`. Every final key retains its
source-layer provenance.

The default global scope root is `~/.rn-forge/share/agentkit`; a repository uses
`<repo>/.rn-forge/agentkit`. Every managed file lives under an agent directory,
except the guard library shared by all agents, which lives under `_common/`:

```text
<scope-root>/
├── _common/hooks/guard-core.sh   # shared guard logic (global scope only)
├── <agent>/config.toml           # managed source — the layer you edit
├── <agent>/hooks/*.sh            # this agent's hook scripts, run in place
├── <agent>/rendered/<native>     # staging mirror of the native tree
├── state.json                    # applied hashes
└── backups/<run-timestamp>/      # pre-overwrite snapshots, one dir per run
```

`rendered/` mirrors the destination path relative to its native root (`$HOME`
globally, the repo locally), so the staging tree is a path-for-path preview of
what gets laid down. Sync is always a one-way copy, never a symlink. Hashes in
`state.json` make repeated runs idempotent, and manual native drift is backed up
before overwrite.

Hook scripts are referenced from agent configs by absolute path and run from
`<scope-root>/<agent>/hooks/` — they are never copied into `~/.claude` or
`~/.codex`.

## Default pack

`agentkit global apply` installs these global artifacts:

| Agent  | Native agent files                                                                                            | Shared executable hooks                                                                                               |
| ------ | ------------------------------------------------------------------------------------------------------------- | --------------------------------------------------------------------------------------------------------------------- |
| Claude | `~/.claude/settings.json`, `~/.claude/CLAUDE.md`, `~/.claude/output-styles/concise.md`, `~/.claude/skills/**` | `claude/hooks/pre-bash-guard.sh`, `user-prompt-secret-guard.sh`, `pre-write-protect.sh`, `session-compact-context.sh` |
| Codex  | `~/.codex/config.toml`, `~/.codex/AGENTS.md`, `~/.codex/hooks.json`, `~/.codex/skills/**`                                           | `codex/hooks/pre-bash-guard.sh`, `user-prompt-secret-guard.sh`, `pre-write-protect.sh`                                |

Both adapters declare the shared `_common/hooks/guard-core.sh`. The shared library
contains the common destructive-command, sensitive-path, and prompt-secret checks; thin adapters
emit Claude's stderr/exit-2 or Codex's JSON/exit-0 blocking dialect.

The branch-protection guard blocks force pushes and pushes to protected
branches. `AGENTKIT_PROTECTED_BRANCHES` overrides the default `main|master`
pattern (the legacy `CLAUDE_PROTECTED_BRANCHES` is still honored as a fallback).

Skills are single-sourced the same way, in `src/rn_forge/agentkit/assets/skills/`.
Both agents read the identical skill container (`<name>/SKILL.md` with `name` +
`description` frontmatter, plus `references/`, `scripts/` and `assets/`), so one
tree serves both: `AgentAdapter.skill_artifacts` enumerates it and each adapter
maps it onto its own root (`~/.claude/skills/`, `~/.codex/skills/`). Adding a
skill is just adding its directory — no code change.

Within a skill, `SKILL.md.j2` renders per agent with an `agent` variable, so the
handful of genuinely harness-specific lines can branch (Claude's `allowed-tools`
frontmatter, its `ToolSearch` hint for deferred MCP tools). Everything else stays
agent-neutral prose. Bundled resources are copied **verbatim, never rendered** —
they carry placeholder syntax that is not Jinja and must survive untouched
(go-task's `{{.VAR}}`, GitHub Actions' `${{ }}`).

The packaged skills are repo-agnostic on purpose: they detect the target repo's
stack rather than assuming one, so they apply cleanly on a new machine.

Instruction files are single-sourced: `~/.claude/CLAUDE.md`, `~/.codex/AGENTS.md`,
and `~/.claude/output-styles/concise.md` all render from the shared partials in
`src/rn_forge/agentkit/assets/instructions/`, so the two agents cannot drift
apart. Adapter tests assert each rendered file byte-matches its packaged
snapshot.

Intentional hook parity exclusions:

- Codex has no built-in read-tool matcher, so it cannot mirror Claude's
  secret-read denials. Its write guard still protects sensitive in-repo paths.
- Compaction context injection remains Claude-only because Codex has no
  equivalent context-injection behavior for this asset pack.

Project initialization and update install:

| Agent  | Native agent files                                                             | Shared executable hooks                                      |
| ------ | ------------------------------------------------------------------------------ | ------------------------------------------------------------ |
| Claude | `<repo>/.claude/settings.local.json`, `<repo>/CLAUDE.md` (seed)                | `<repo>/.rn-forge/agentkit/claude/hooks/post-edit-format.sh` |
| Codex  | `<repo>/.codex/config.toml`, `<repo>/.codex/hooks.json`, `<repo>/AGENTS.md` (seed) | `<repo>/.rn-forge/agentkit/codex/hooks/post-edit-format.sh`  |

### Repo instruction seeds

The repo-root `CLAUDE.md` and `AGENTS.md` are **seeds, not managed artifacts**.
Every other file agentkit writes is generated and reconciled on each
`project update`; these two are written only when absent and then belong to the
repository — later applies report them as `exists; owned by the repository`,
never overwrite them, and `agentkit diff` does not treat divergence as drift.

The seeded `AGENTS.md` is a pointer that tells any non-Claude agent to read
`CLAUDE.md` and follow it as if its contents appeared inline, plus a standing
instruction not to add guidance to the pointer itself. That keeps one set of
repo instructions instead of two files drifting apart. The seeded `CLAUDE.md` is
a short scaffold with placeholder sections for the repo to fill in.


## Use

```bash
# Create local managed sources for both built-in adapters
agentkit project init

# Render and copy repository-local artifacts
agentkit project update

# Apply the global default pack
agentkit global apply

# Preview one adapter with a one-run override
agentkit global apply --agent codex --set model='"gpt-5"' --dry-run

# CI-friendly drift checks (exit status 2 means drift)
agentkit diff --scope local --check
agentkit doctor --scope local --check

# Capture native primary-config changes into the managed source
agentkit diff --scope local --write

# Scriptable output
agentkit --json global list
```

Global commands are `apply`, `sync`, `reset`, and `list`. Project commands are
`init`, `update`, and `status`. Root commands are `diff`, `doctor`, and
`version`. `--quiet` and `--json` are global output flags.

`project init` scaffolds the managed sources, renders and syncs native files,
and adds the machine-local derived-data block to the repository `.gitignore`.

## What to commit

Repository-local agentkit files split into shared source and machine-local
derived data.

Commit these — they carry team-shared intent:

- `<repo>/.rn-forge/agentkit/<agent>/config.toml` — the managed source
- `<repo>/.codex/config.toml`, `<repo>/.codex/hooks.json` — Codex has no
  personal tier at repo level, so its rendered config is the shared team config
- `<repo>/CLAUDE.md`, `<repo>/AGENTS.md` — seeded once, then hand-maintained
  repo instructions

Ignore these — all regenerable with `agentkit project update`:

```gitignore
/.rn-forge/agentkit/*/rendered/
/.rn-forge/agentkit/*/hooks/
/.rn-forge/agentkit/_common/
/.rn-forge/agentkit/state.json
/.rn-forge/agentkit/backups/
```

`project init` only manages the `.rn-forge/` block; whether to commit or ignore
agent-native files (e.g. `.claude/settings.local.json`) is left to each repo's
own `.gitignore`. Because the ignored hook scripts are referenced by the
committed `.codex/hooks.json`, **run `agentkit project update` after cloning**
so the local hooks exist.

## Source layout

| Folder                            | Purpose                                                                                              |
| --------------------------------- | ---------------------------------------------------------------------------------------------------- |
| `src/rn_forge/agentkit/agents/`   | Adapter interface, registry, built-in schemas, defaults, templates, and discovery-by-location assets |
| `src/rn_forge/agentkit/assets/`   | Shared guard library and instruction partials                                                        |
| `src/rn_forge/agentkit/core/`     | Artifacts, paths, merge, render, I/O, state, diff, doctor, and manager services                      |
| `src/rn_forge/agentkit/commands/` | Typer global, project, and root command groups                                                       |
| `tests/`                          | Isolated tests mirroring the source tree; fake `HOME` and `RNF_HOME` are provided by `conftest.py`   |
| `docs/specs/`                     | Design record — [initial.md](docs/specs/initial.md): what is built, why, and what's pending (§13)    |
| `install.sh`                      | Checkout-based, versioned rn-forge installer                                                         |

## Adding an adapter

Implement `rn_forge.agentkit.agents.base.AgentAdapter`, including its schema,
scope-aware defaults, primary renderer/parser, and ordered artifact declarations.
Publish it under the `agentkit.adapters` entry-point group:

```toml
[project.entry-points."agentkit.adapters"]
my-agent = "my_package:MyAgentAdapter"
```

An artifact chooses either a Jinja template or packaged static source, an agent
or share root, a stable key, a native-relative path, and optional executable
mode. Optional adapter-specific Typer commands can be exposed with
`cli_extension`.

## Development

```bash
UV_CACHE_DIR=.uv-cache uv run pytest -q
UV_CACHE_DIR=.uv-cache uv run ruff check src tests
UV_CACHE_DIR=.uv-cache uv run pyright src
UV_CACHE_DIR=/tmp/agentkit-uv-cache uv build
```

Design decisions, the artifact/adapter model, the full build history, and the
remaining deferred items are in [docs/specs/initial.md](docs/specs/initial.md).
