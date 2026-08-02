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

| Tool | Status | Used for |
| --- | --- | --- |
| `jq` | **Required** | Every hook parses its JSON event payload with `jq`. `global apply` and `project init` warn when it is missing, and `doctor` reports it as an error. `PreToolUse` guards fail closed (exit 2) without it; `UserPromptSubmit` guards fail open so a session stays usable. |
| `gitleaks` | Recommended | Prompt-secret scanning uses `gitleaks stdin` when present and falls back to the built-in regex set otherwise. `doctor` reports it as a warning. |

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

Agent-rooted artifacts render beneath
`<scope-root>/<agent>/rendered/<native-path>` before being copied atomically to
their native locations. Shared hooks live directly beneath
`<scope-root>/hooks/`. Sync is always a one-way copy, never a symlink. Hashes in
`state.json` make repeated runs idempotent, and manual native drift is backed up
under `<scope-root>/backups/` before overwrite.

The default global scope root is `~/.rn-forge/share/agentkit`; a repository uses
`<repo>/.rn-forge/agentkit`.

## Default pack

`agentkit global apply` installs these global artifacts:

| Agent | Native agent files | Shared executable hooks |
| --- | --- | --- |
| Claude | `~/.claude/settings.json`, `~/.claude/CLAUDE.md`, `~/.claude/output-styles/concise.md` | `hooks/claude/pre-bash-guard.sh`, `user-prompt-secret-guard.sh`, `pre-write-protect.sh`, `session-compact-context.sh` |
| Codex | `~/.codex/config.toml`, `~/.codex/AGENTS.md`, `~/.codex/hooks.json` | `hooks/codex/pre-bash-guard.sh`, `user-prompt-secret-guard.sh`, `pre-write-protect.sh` |

Both adapters declare the shared `hooks/lib/guard-core.sh`. The shared library
contains the common destructive-command, sensitive-path, and prompt-secret checks; thin adapters
emit Claude's stderr/exit-2 or Codex's JSON/exit-0 blocking dialect.

The branch-protection guard blocks force pushes and pushes to protected
branches. `AGENTKIT_PROTECTED_BRANCHES` overrides the default `main|master`
pattern (the legacy `CLAUDE_PROTECTED_BRANCHES` is still honored as a fallback).

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

| Agent | Native agent files | Shared executable hooks |
| --- | --- | --- |
| Claude | `<repo>/.claude/settings.local.json` | `<repo>/.rn-forge/agentkit/hooks/claude/post-edit-format.sh` |
| Codex | `<repo>/.codex/config.toml`, `<repo>/.codex/hooks.json` | `<repo>/.rn-forge/agentkit/hooks/codex/post-edit-format.sh` |

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

# Scriptable output
agentkit --json global list
```

Global commands are `apply`, `sync`, `reset`, and `list`. Project commands are
`init`, `update`, and `status`. Root commands are `diff`, `doctor`, and
`version`. `--quiet` and `--json` are global output flags.

## Source layout

| Folder | Purpose |
| --- | --- |
| `src/rn_forge/agentkit/agents/` | Adapter interface, registry, built-in schemas, defaults, templates, and discovery-by-location assets |
| `src/rn_forge/agentkit/assets/` | Shared guard library and instruction partials |
| `src/rn_forge/agentkit/core/` | Artifacts, paths, merge, render, I/O, state, diff, doctor, and manager services |
| `src/rn_forge/agentkit/commands/` | Typer global, project, and root command groups |
| `tests/` | Isolated tests mirroring the source tree; fake `HOME` and `RNF_HOME` are provided by `conftest.py` |
| `install.sh` | Checkout-based, versioned rn-forge installer |

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
