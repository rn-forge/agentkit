# agentkit

`agentkit` manages global and repository-local configuration for AI coding
agents from one layered source of truth. It ships adapters and a default asset
pack for Claude Code and Codex, and discovers third-party adapters through
Python entry points.

Every coding agent wants its own config tree (`~/.claude`, `~/.codex`,
`<repo>/.claude`, …). Keeping those consistent by hand means writing the same
policy decision several times and watching it drift. agentkit keeps the decision
in one managed source per agent, renders each agent's native files from it, and
reconciles them with a hash-tracked one-way copy that backs up manual drift
instead of silently clobbering it.

## Install

The installer creates a versioned environment under
`~/.rn-forge/agentkit/v<version>/`, updates `current`, and links the CLI at
`~/.rn-forge/bin/agentkit`:

```bash
curl -fsSL https://raw.githubusercontent.com/rn-forge/agentkit/main/scripts/bootstrap.sh | bash
export PATH="$HOME/.rn-forge/bin:$PATH"
agentkit version
```

`RNF_HOME` overrides `~/.rn-forge`. `bootstrap.sh` fetches the latest GitHub
release's source and runs `install.sh` from it; run `./install.sh` directly from
a checkout instead if you're developing agentkit itself. The installer does not
edit shell rc files.

To move to a newer release afterward, run `agentkit upgrade` instead of
re-running bootstrap by hand — it installs the latest release (or a local
tarball via `--archive`) without touching your configuration; follow up with
`agentkit global apply` / `agentkit project update` to apply anything new.
`agentkit cleanup` removes old installed versions once you no longer need them
for rollback.

### Setting up a new machine

1. Install prerequisites. The bootstrap itself needs `curl`, `tar`, and
   [`uv`](https://docs.astral.sh/uv/getting-started/installation/); the hooks
   need `jq`, and `gitleaks` is optional for prompt-secret scanning. See
   [the dependency table](docs/guides/development.md#external-dependencies)
   for what each one is used for and how to install it.

1. Install agentkit — no manual clone needed. `bootstrap.sh` downloads the
   source tarball for the latest GitHub release and runs the installer from
   it:

    ```bash
    curl -fsSL https://raw.githubusercontent.com/rn-forge/agentkit/main/scripts/bootstrap.sh | bash
    ```

    To install from a checkout instead (e.g. for development), run `./install.sh`
    directly from the repo root.

1. Add `~/.rn-forge/bin` to your shell's `PATH` (the installer does not edit rc
   files for you), then confirm the CLI resolves:

    ```bash
    export PATH="$HOME/.rn-forge/bin:$PATH"   # add this line to your shell rc
    agentkit version
    ```

1. Optionally enable shell completions once per shell:

    ```bash
    agentkit --install-completion
    exec zsh   # or restart your shell
    ```

1. Apply the global default pack to this machine's agent configs:

    ```bash
    agentkit global apply --dry-run   # preview first
    agentkit global apply
    ```

1. In any repository you want agentkit to manage:

    ```bash
    agentkit project init
    agentkit project update
    ```

`jq` is **required** — every hook parses its JSON event payload with it.
`gitleaks` is recommended for prompt-secret scanning. See
[the development guide](docs/guides/development.md#external-dependencies) for
the full dependency table.

Shell completions (zsh, bash, fish) come from Typer/Click and need no extra
setup beyond enabling them once per shell:

```bash
agentkit --install-completion   # writes a completion script and prints where
# restart your shell (or `exec zsh`) to pick it up
```

## Quickstart

```bash
# In a repository you want agentkit to manage
agentkit project init      # create local managed sources for both adapters
agentkit project update    # render and copy repository-local artifacts

# On this machine
agentkit global apply      # install the global default pack

# Preview before writing anything
agentkit global apply --agent codex --set model='"gpt-5"' --dry-run

# CI-friendly drift checks (exit status 2 means drift)
agentkit diff --scope local --check
agentkit doctor --scope local --check
```

Global commands are `apply`, `sync`, `reset`, and `list`. Project commands are
`init`, `update`, and `status`. Root commands are `diff`, `doctor`, and
`version`. `--quiet` and `--json` are global output flags.

> **After cloning a repo that uses agentkit, run `agentkit project update`.**
> Hook scripts are gitignored but referenced by absolute path from the committed
> `.codex/hooks.json`, so a fresh clone needs them regenerated.

## Documentation

The full documentation is published at
**[rn-forge.github.io/agentkit](https://rn-forge.github.io/agentkit/)**, built
from the MkDocs site under [`docs/`](docs/). Build it with `task docs:serve` for
a live-reloading local preview.

| Page | Covers |
| -- | -- |
| [Architecture overview](docs/architecture/index.md) | The configuration model, the path model, why copy and never symlink, hook and instruction single-sourcing |
| [Adapters and artifacts](docs/architecture/adapters.md) | The artifact model and how to write and register a new agent adapter |
| [Configuring a repository](docs/guides/configuration.md) | Full command surface, the default asset pack, repo instruction seeds, what to commit and what to ignore |
| [Development](docs/guides/development.md) | Local setup, conventions, source layout, and the safety rules for running this tool against your real machine config |
| [Task vocabulary](docs/guides/task-vocabulary.md) | The `task` verb map — the only supported entrypoint for build, lint, and test |
| [Documentation system](docs/architecture/docs-system.md) | How and why the docs site is built |
| [Python API](docs/reference/python-api.md) | Generated reference, grouped by architectural layer |
| [Initial build spec](docs/specs/initial.md) | The design record: decisions, build history, and §13 for what's pending |

## Development

`go-task` is the only entrypoint — install it with `brew install go-task`.

```bash
task setup       # sync the venv with the dev and docs dependency groups
task validate    # the gate: lint + typecheck + test + docs build
task docs:serve  # live-reloading docs on http://127.0.0.1:8083
task --list      # the full surface
```

This repo dogfoods itself — its own `.claude/`, `.codex/`, and
`.rn-forge/agentkit/` were produced by running agentkit against it. That means
commands without `--dry-run` write to your real `~/.claude` and `~/.codex`. Read
[the safety section](docs/guides/development.md#safety-this-repo-dogfoods-itself)
before running the CLI here.
