# agentkit

`agentkit` manages global and repository-local configuration for AI coding
agents from one layered source of truth. It currently includes adapters for
Claude Code and Codex, and discovers third-party adapters through Python entry
points.

## Configuration model

Values are resolved in increasing precedence:

```text
built-in defaults → ~/.agentkit/<agent>/config.toml
                  → <repo>/.agentkit/<agent>/config.toml
                  → --set dotted.key=value
```

Dictionaries merge recursively. Lists replace lower layers unless the adapter
schema marks that field with `merge_strategy: append`. Every final key retains
its source-layer provenance.

Managed sources are never edited into an agent's file directly. A command first
renders to `.agentkit/<agent>/rendered/<native-path>`, then atomically syncs that
content to the native path. Hashes in `.agentkit/state.json` make repeated runs
idempotent, and agentkit backs up unmanaged/manual native changes before an
overwrite.

## Install and use

```bash
uv sync --group dev
uv run agentkit --help

# Create local sources for both built-in adapters
uv run agentkit project init

# Update one local agent, with a one-run override
uv run agentkit project update --agent codex --set model='"gpt-5"'

# Preview a global apply without writing
uv run agentkit global apply --agent claude --dry-run

# CI-friendly drift checks (exit status 2 means drift)
uv run agentkit diff --scope local --check
uv run agentkit doctor --scope local --check

# Scriptable output
uv run agentkit --json global list
```

Global commands are `apply`, `sync`, `reset`, and `list`. Project commands are
`init`, `update`, and `status`. Root commands are `diff`, `doctor`, and
`version`. `--quiet` and `--json` are global output flags.

## Adding an adapter

Implement `rn_forge.agentkit.agents.base.AgentAdapter`, then publish it under
the `agentkit.adapters` entry-point group:

```toml
[project.entry-points."agentkit.adapters"]
my-agent = "my_package:MyAgentAdapter"
```

An adapter declares its schema, native paths, rendered relative path, renderer,
and native parser. Optional adapter-specific Typer commands can be exposed with
`cli_extension`.

## Development

```bash
UV_CACHE_DIR=.uv-cache uv run pytest
UV_CACHE_DIR=.uv-cache uv run ruff check src tests
UV_CACHE_DIR=.uv-cache uv run pyright src tests
```
