# Development

## Installing the CLI

The installer creates a versioned environment under
`~/.rn-forge/agentkit/v<version>/`, updates `current`, and links the CLI at
`~/.rn-forge/bin/agentkit`:

```bash
./install.sh
export PATH="$HOME/.rn-forge/bin:$PATH"
agentkit version
```

`RNF_HOME` overrides `~/.rn-forge`. Installation currently runs from a checkout
of this repository. The installer does not edit shell rc files.

## External dependencies

| Tool | Status | Used for |
| --- | --- | --- |
| `jq` | **Required** | Every hook parses its JSON event payload with `jq`. `global apply` and `project init` warn when it is missing, and `doctor` reports it as an error. `PreToolUse` guards fail closed (exit 2) without it; `UserPromptSubmit` guards fail open so a session stays usable. |
| `gitleaks` | Recommended | Prompt-secret scanning uses `gitleaks stdin` when present, in addition to the built-in regex set. `doctor` reports it as a warning. |
| `go-task` | **Required for development** | The task vocabulary is the only supported entrypoint for build, lint, and test. Install with `brew install go-task`. |

Formatter binaries (`ruff`, `npx`/`prettier`, `google-java-format`, `shfmt`) are
optional — the post-edit hook skips any branch whose tool is not installed.

## Working on agentkit

```bash
task setup       # uv sync --group dev --group docs
task validate    # lint + typecheck + test — the gate
task test
task lint
task format
task docs:serve  # live-reloading docs on http://127.0.0.1:8000
```

`task --list` is the authoritative surface; see the
[task vocabulary](task-vocabulary.md) for the map and the reasoning.

## Safety: this repo dogfoods itself

agentkit's own `.claude/`, `.codex/`, and `.rn-forge/agentkit/` were produced by
running `agentkit project init` / `global apply` against this repo. That makes it
one of the few repos where running the tool's own CLI against the real machine is
an expected workflow rather than a mistake — but it also means commands like
`agentkit global apply`, `agentkit global reset`, or anything without
`--dry-run` will write to the real `~/.claude`, `~/.codex`, and
`~/.rn-forge/share/agentkit`.

Prefer `--dry-run` first, and prefer running against a scratch `HOME`/`RNF_HOME`
over the real one unless the task specifically calls for touching this machine's
configuration.

Tests must never touch the real `~/.rn-forge`, `~/.claude`, or `~/.codex`. The
`isolated_env` fixture in `tests/conftest.py` sets both `HOME` and `RNF_HOME` for
exactly this reason — do not write a test that bypasses it.

## Conventions

- `pyright src` runs in **strict mode at zero errors**. Fix typing at the
  untyped-library boundary rather than adding `# type: ignore` or downgrading
  rules — see [the spec, §11](../specs/initial.md).
- `tests/` mirrors `src/`. Add new tests under the matching subtree.
- Skill assets under `src/rn_forge/agentkit/assets/skills/` are excluded from
  both ruff and pyright. They are templates copied verbatim into *other* repos,
  not code this package imports, so they are not held to this project's
  strictness.

## Source layout

| Folder | Purpose |
| --- | --- |
| `src/rn_forge/agentkit/agents/` | Adapter interface, registry, built-in schemas, defaults, templates, and discovery-by-location assets |
| `src/rn_forge/agentkit/assets/` | Shared guard library, instruction partials, and packaged skills |
| `src/rn_forge/agentkit/core/` | Artifacts, paths, merge, render, I/O, state, diff, doctor, and manager services |
| `src/rn_forge/agentkit/commands/` | Typer global, project, and root command groups |
| `tests/` | Isolated tests mirroring the source tree; fake `HOME` and `RNF_HOME` from `conftest.py` |
| `tasks/`, `scripts/` | The task vocabulary and its enforcement linters |
| `docs/` | This site |
| `install.sh` | Checkout-based, versioned rn-forge installer |
