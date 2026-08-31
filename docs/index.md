# agentkit

`agentkit` manages global and repository-local configuration for AI coding
agents from one layered source of truth. It ships adapters and a default asset
pack for Claude Code and Codex, and discovers third-party adapters through
Python entry points.

The problem it solves: every coding agent wants its own config tree
(`~/.claude`, `~/.codex`, `<repo>/.claude`, …), and keeping those trees
consistent by hand means the same policy decision gets written several times and
drifts. agentkit keeps the decision in one managed source per agent, renders each
agent's native files from it, and reconciles them with a hash-tracked one-way
copy that backs up manual drift instead of silently clobbering it.

## Where to start

| You want to | Read |
| --- | --- |
| Install the CLI and run it | [Development](guides/development.md#installing-the-cli) |
| Understand how values resolve and where files land | [Architecture overview](architecture/index.md) |
| Add support for a new agent | [Adapters and artifacts](architecture/adapters.md) |
| Set agentkit up in one of your repositories | [Configuring a repository](guides/configuration.md) |
| Work on agentkit itself | [Development](guides/development.md) |
| Look up a module, class, or function | [Python API](reference/python-api.md) |
| Know why the design is what it is | [Initial build spec](specs/initial.md) |

## The shape of it in one page

Values resolve in increasing precedence — packaged defaults, then your global
managed source, then the repository's managed source, then a one-run `--set`
override. Each resolved value keeps its source-layer provenance, so
`agentkit --json global list` can tell you not just what a setting is but which
layer decided it.

Each agent adapter declares an ordered list of **artifacts**: a template or a
packaged static file, a destination root, and a native-relative path. Rendering
those artifacts produces a staging tree that mirrors the destination path for
path, so what gets laid down is previewable before anything is copied.

Sync is always a one-way copy, never a symlink — agents rewrite their own config
files via atomic rename, which silently breaks symlinks.
