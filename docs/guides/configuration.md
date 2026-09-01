# Configuring a repository

This guide covers using agentkit on one of your own repositories: what the
default pack installs, what to commit, and what to ignore.

## Commands

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

# Capture native primary-config changes back into the managed source
agentkit diff --scope local --write

# Scriptable output
agentkit --json global list
```

Global commands are `apply`, `sync`, `reset`, and `list`. Project commands are
`init`, `update`, and `status`. Root commands are `diff`, `doctor`, and
`version`. `--quiet` and `--json` are global output flags.

`doctor` groups its report into `config` (schema and template validity),
`artifacts` (one row per managed file — its worst finding of missing, drifted,
unsynced, or unwritable), `environment` (agent binaries and the `jq`/`gitleaks`
hook dependencies), and `state`. Within each section the most severe status
comes first, and checks that passed are summarized rather than listed — pass
`--all` to see them. `--json` always emits every check, ungrouped and
unfiltered.

Each artifact row is numbered. When run at a terminal (not piped or scripted),
`doctor` prompts after the tables for a row number and prints that artifact's
unified diff; blank input, `q`, Ctrl+D, or Ctrl+C exit the prompt.

`project init` scaffolds the managed sources, renders and syncs native files,
and adds the machine-local derived-data block to the repository `.gitignore`.

## What the global pack installs

`agentkit global apply` installs these global artifacts:

| Agent | Native agent files | Shared executable hooks |
| -- | -- | -- |
| Claude | `~/.claude/settings.json`, `~/.claude/CLAUDE.md`, `~/.claude/output-styles/concise.md`, `~/.claude/skills/**` | `claude/hooks/pre-bash-guard.sh`, `user-prompt-secret-guard.sh`, `pre-write-protect.sh`, `session-compact-context.sh` |
| Codex | `~/.codex/config.toml`, `~/.codex/AGENTS.md`, `~/.codex/hooks.json`, `~/.codex/skills/**` | `codex/hooks/pre-bash-guard.sh`, `user-prompt-secret-guard.sh`, `pre-write-protect.sh` |

The branch-protection guard blocks force pushes and pushes to protected
branches. `AGENTKIT_PROTECTED_BRANCHES` overrides the default `main|master`
pattern (the legacy `CLAUDE_PROTECTED_BRANCHES` is still honored as a fallback).

## What project init and update install

| Agent | Native agent files | Shared executable hooks |
| -- | -- | -- |
| Claude | `<repo>/.claude/settings.local.json`, `<repo>/CLAUDE.md` (seed) | `<repo>/.rn-forge/agentkit/claude/hooks/post-edit-format.sh` |
| Codex | `<repo>/.codex/config.toml`, `<repo>/.codex/hooks.json`, `<repo>/AGENTS.md` (seed) | `<repo>/.rn-forge/agentkit/codex/hooks/post-edit-format.sh` |

`post-edit-format.sh` uses formatter binaries already installed by the
repository and skips missing tools. Markdown repositories opt in with a root
`.mdformat.toml`; the hook then prefers `<repo>/.venv/bin/mdformat`, followed by
an `mdformat` on `PATH`. It never downloads a formatter while handling an agent
event, and the repository's formatter configuration remains the source of truth.

## Repo instruction seeds

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

## What to commit

Repository-local agentkit files split into shared source and machine-local
derived data.

Commit these — they carry team-shared intent:

- `<repo>/.rn-forge/agentkit/<agent>/config.toml` — the managed source
- `<repo>/.codex/config.toml`, `<repo>/.codex/hooks.json` — Codex has no
  personal tier at repo level, so its rendered config *is* the shared team
  config
- `<repo>/CLAUDE.md`, `<repo>/AGENTS.md` — seeded once, then hand-maintained

Ignore these — all regenerable with `agentkit project update`:

```gitignore
.rn-forge/agentkit/*/rendered/
.rn-forge/agentkit/*/hooks/
.rn-forge/agentkit/_common/
.rn-forge/agentkit/state.json
.rn-forge/agentkit/backups/
```

The authoritative list is `_GITIGNORE_ENTRIES` in
`src/rn_forge/agentkit/commands/project_cmds.py`; `project init` writes it
between `# BEGIN rn-forge agentkit` / `# END rn-forge agentkit` markers and
refreshes the block in place on later runs.

`project init` only manages the `.rn-forge/` block; whether to commit or ignore
agent-native files (for example `.claude/settings.local.json`) is left to each
repo's own `.gitignore`.

!!! warning "Run `agentkit project update` after cloning"

    The ignored hook scripts are referenced by absolute path from the *committed*
    `.codex/hooks.json`. A fresh clone has the config but not the scripts, so hooks
    point at missing files until `project update` regenerates them.
