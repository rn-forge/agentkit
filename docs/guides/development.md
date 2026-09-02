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

Installation commands assume Homebrew on macOS and a Debian/Ubuntu `apt` on
Linux; substitute your own package manager as needed.

| Tool | Status | Install | Used for |
| -- | -- | -- | -- |
| `curl` | **Required to bootstrap** | preinstalled on macOS; `apt install curl` | `bootstrap.sh` resolves the release and downloads its source archive. |
| `tar` | **Required to bootstrap** | preinstalled on macOS; `apt install tar` | `bootstrap.sh` extracts the downloaded archive. |
| `uv` | **Required** | `brew install uv`, or see the [uv install guide](https://docs.astral.sh/uv/getting-started/installation/) | `install.sh` builds and installs the CLI with `uv`; it also provides the Python interpreter. |
| `jq` | **Required** | `brew install jq` / `apt install jq` | Every hook parses its JSON event payload with `jq`. `global apply` and `project init` warn when it is missing, and `doctor` reports it as an error. `PreToolUse` guards fail closed (exit 2) without it; `UserPromptSubmit` guards fail open so a session stays usable. |
| `gitleaks` | Recommended | `brew install gitleaks` | Prompt-secret scanning uses `gitleaks stdin` when present, in addition to the built-in regex set. `doctor` reports it as a warning. |
| `go-task` | **Required for development** | `brew install go-task` | The task vocabulary is the only supported entrypoint for build, lint, and test. |

The docs dependency group installs `mdformat` with the GFM, MkDocs, and
front-matter extensions used by `task format` and `task lint`. Other formatter
binaries (`npx`/`prettier`, `google-java-format`, `shfmt`) are optional — the
post-edit hook skips any branch whose tool is not installed.

## Working on agentkit

```bash
task setup       # uv sync --group dev --group docs
task validate    # lint + typecheck + test + docs build — the gate
task test
task lint
task format
task docs:serve  # live-reloading docs on http://127.0.0.1:8083
```

`task --list` is the authoritative surface; see the
[task vocabulary](task-vocabulary.md) for the map and the reasoning.

## Safety: this repo dogfoods itself

agentkit's own `.claude/`, `.codex/`, and `.rn-forge/agentkit/` were produced by
running `agentkit project init` / `global apply` against this repo. That makes
it one of the few repos where running the tool's own CLI against the real
machine is an expected workflow rather than a mistake — but it also means
commands like `agentkit global apply`, `agentkit global reset`, or anything
without `--dry-run` will write to the real `~/.claude`, `~/.codex`, and
`~/.rn-forge/share/agentkit`.

Prefer `--dry-run` first, and prefer running against a scratch `HOME`/`RNF_HOME`
over the real one unless the task specifically calls for touching this machine's
configuration.

Tests must never touch the real `~/.rn-forge`, `~/.claude`, or `~/.codex`. The
`isolated_env` fixture in `tests/conftest.py` sets both `HOME` and `RNF_HOME`
for exactly this reason — do not write a test that bypasses it.

## Conventions

- `pyright src` runs in **strict mode at zero errors**. Fix typing at the
  untyped-library boundary rather than adding `# type: ignore` or downgrading
  rules — see [the spec, §11](../specs/initial.md).
- `tests/` mirrors `src/`. Add new tests under the matching subtree.
- Skill assets under `src/rn_forge/agentkit/assets/skills/` are excluded from
  both ruff and pyright. They are templates copied verbatim into *other*
  repos, not code this package imports, so they are not held to this project's
  strictness.

## Source layout

| Folder | Purpose |
| -- | -- |
| `src/rn_forge/agentkit/agents/` | Adapter interface, registry, built-in schemas, defaults, templates, and discovery-by-location assets |
| `src/rn_forge/agentkit/assets/` | Shared guard library, instruction partials, and packaged skills |
| `src/rn_forge/agentkit/core/` | Artifacts, paths, merge, render, I/O, state, diff, doctor, and the `operations/` apply, remove, capture, and init pipelines |
| `src/rn_forge/agentkit/commands/` | `BaseCommand` plus the `Global`/`Project`/`Self`/`Root` command classes the Typer surface in `cli.py` constructs and calls |
| `tests/` | Isolated tests mirroring the source tree; fake `HOME` and `RNF_HOME` from `conftest.py` |
| `tasks/`, `scripts/` | The task vocabulary and its enforcement linters |
| `docs/` | This site |
| `install.sh` | Checkout-based, versioned rn-forge installer |

## Deliberate trade-offs in the tooling

These are choices, not oversights. Each has been raised in review at least once;
the reasoning is recorded here so it does not have to be re-argued.

**Tests are excluded from Ruff and Pyright** (`pyproject.toml`). Test code is
read far more often than it is refactored, and the patterns that lint rules
object to in tests — long literal fixtures, shadowed names, broad `subprocess`
use — are usually the clearest way to write the test. The cost is that fixture
typing errors go uncaught. Revisit if the suite grows a substantial helper layer
of its own, where the tradeoff flips.

**Coverage is measured but not enforced.** `task test:coverage` emits a report;
there is no `--cov-fail-under` and no branch coverage, and the normal gate runs
`task test` without coverage. A ratcheted floor mostly buys tests written to
move a number. Behavioural risk is covered directly instead — the registry,
guard, state, and reset regressions all exist because a specific failure mode
was worth pinning, not because a percentage demanded it.

**`core/manager.py` was split into `core/operations/`.** The module started at
~600 lines as one cohesive apply pipeline, which is why an earlier version of
this entry recorded a decision *not* to split it. It grew to 919 lines and came
to carry four pipelines that share only `OperationResult` — apply/sync,
uninstall-style removal, capture/write-back, and project init — which is what
triggered the split (`docs/specs/initial.md` §14.2). Each pipeline is now its
own module (`apply.py`, `remove.py`, `capture.py`, `init.py`) plus a shared
`result.py`; `core/operations/__init__.py` re-exports the public verbs so call
sites still import from one place.

**`.editorconfig` disables `insert_final_newline` and `trim_trailing_whitespace`
globally.** Both are unusual defaults. They are set this way because the
repository ships packaged assets — templates, skill files, static hook scripts —
that are copied verbatim into other repositories, and an editor silently
normalizing them changes the bytes agentkit hashes and would show up as spurious
drift. The linters, not the editor, own formatting here.

**Python 3.14 only.** See the comment in `pyproject.toml`: nothing in the source
requires it, and lowering the bound is a matter of adding CI versions rather
than back-porting code.

**Releases are triggered by a version change on `main`.** Pushing a
`pyproject.toml` version that has no matching tag tags and releases it. This is
a single-maintainer convenience and it does mean a premature version bump
publishes. Tag-driven releases or a protected environment would be safer if this
ever gains other committers.
