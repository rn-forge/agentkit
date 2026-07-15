# agentkit — Spec & Scaffolding Plan

## 1. Purpose

Manage global (`~`) and local (repo-level) configuration for AI coding agents
(Claude, Codex, etc.) through a unified CLI: read, parse, diff, merge, and
render final configs from templates. Extensible per-agent via a plugin
interface.

---

## 2. Tech Stack

| Concern            | Choice                          |
|---------------------|----------------------------------|
| Packaging/env       | `uv`                             |
| CLI framework       | `typer`                          |
| Schema/validation   | `pydantic` (v2)                  |
| Templating          | `jinja2`                         |
| TOML I/O (preserve comments) | `tomlkit`               |
| YAML I/O (preserve comments) | `ruamel.yaml`           |
| Terminal UX         | `rich`                           |
| Testing             | `pytest`, `pytest-cov`           |
| Lint/format         | `ruff`                           |
| Type checking       | `mypy`                           |

---

## 3. Repo Layout

> **Superseded by refinement plan 01:** use the repository and packaged-data
> layout defined in `agentkit_refinement_plan.md`; this section is retained as
> historical context only.

```
agentkit/
├── pyproject.toml
├── README.md
├── src/
│   └── agentkit/
│       ├── __init__.py
│       ├── cli.py                  # root Typer app, mounts subcommands
│       ├── core/
│       │   ├── __init__.py
│       │   ├── config.py           # ConfigMerger, precedence resolution
│       │   ├── diff.py             # config diffing (global vs local vs rendered)
│       │   ├── render.py           # Jinja2 template rendering engine
│       │   ├── io.py               # format-aware read/write (toml/yaml/json)
│       │   ├── state.py            # tracks applied state for idempotency
│       │   └── doctor.py           # environment/config health checks
│       ├── agents/
│       │   ├── __init__.py
│       │   ├── base.py             # AgentAdapter ABC — plugin interface
│       │   ├── registry.py         # discovers/loads agent adapters
│       │   ├── claude/
│       │   │   ├── __init__.py
│       │   │   ├── adapter.py      # ClaudeAdapter(AgentAdapter)
│       │   │   ├── schema.py       # pydantic models for Claude config
│       │   │   └── templates/
│       │   │       ├── global.j2
│       │   │       └── local.j2
│       │   └── codex/
│       │       ├── __init__.py
│       │       ├── adapter.py
│       │       ├── schema.py
│       │       └── templates/
│       │           ├── global.j2
│       │           └── local.j2
│       └── commands/
│           ├── __init__.py
│           ├── global_cmds.py      # apply, sync, reset, list (global scope)
│           ├── project_cmds.py     # init, update, status (repo scope)
│           └── shared_cmds.py      # diff, doctor, version
├── tests/
│   ├── test_config_merge.py
│   ├── test_diff.py
│   ├── test_render.py
│   ├── agents/
│   │   ├── test_claude_adapter.py
│   │   └── test_codex_adapter.py
│   └── fixtures/
│       ├── global/
│       └── local/
└── .agentkit/                      # generated at runtime (state, cache)
    ├── state.json
    └── cache/
```

---

## 4. Config Resolution Model

Precedence (lowest → highest):

```
built-in defaults → global (~/.agentkit/<agent>/config.*)
                   → local  (<repo>/.agentkit/<agent>/config.*)
                   → CLI overrides (--set key=value)
```

- Deep merge for dicts, override (not append) for lists unless a field is
  explicitly marked `merge_strategy: append` in the agent schema.
- `ConfigMerger` returns both the merged result **and** a provenance map
  (which layer each key came from) — needed for `diff` and `doctor`.

---

## 5. Standard Agent Folder Structure

> **Superseded by refinement plan 01:** use the rn-forge global/project roots
> and multi-artifact layout defined in `agentkit_refinement_plan.md`; this
> section is retained as historical context only.

Each agent adapter declares where its native config lives, on both scopes:

```
# Global
~/.agentkit/
└── <agent>/
    ├── config.toml          # agentkit-managed source of truth
    └── rendered/
        └── <native-path>    # what actually gets written to the agent's real location

# Local (per repo)
<repo>/.agentkit/
└── <agent>/
    ├── config.toml
    └── rendered/
        └── <native-path>
```

The adapter maps `rendered/<native-path>` to the agent's actual expected
location (e.g. `~/.claude/settings.json`, `<repo>/.codex/config.yaml`).
agentkit never edits native files directly — it renders into `rendered/`
then **syncs** (copies/symlinks) to the native path, so the source of truth
always stays in `.agentkit/`.

---

## 6. Agent Adapter Interface (`agents/base.py`)

```python
class AgentAdapter(ABC):
    name: str

    @abstractmethod
    def schema(self) -> type[BaseModel]: ...

    @abstractmethod
    def global_native_path(self) -> Path: ...

    @abstractmethod
    def local_native_path(self, repo_root: Path) -> Path: ...

    @abstractmethod
    def render(self, merged_config: dict) -> str: ...

    @abstractmethod
    def parse_native(self, path: Path) -> dict: ...
        # for `import`/`diff` against hand-edited native files

    def validate(self, config: dict) -> list[str]:
        # returns list of validation errors, default: pydantic schema check
```

New agents = new subpackage under `agents/`, registered in `registry.py`
via entry-point discovery (`importlib.metadata.entry_points`) so third
parties could ship `agentkit-<agent>` plugin packages later.

---

## 7. CLI Dispatcher Design

Root app mounts scoped sub-apps; each agent can also mount its own
sub-commands dynamically via the registry.

```python
# cli.py
app = typer.Typer(name="agentkit")
app.add_typer(global_cmds.app, name="global")
app.add_typer(project_cmds.app, name="project")
app.add_typer(shared_cmds.app)  # diff, doctor, version at root level

for agent in registry.discover():
    if agent.cli_extension:
        app.add_typer(agent.cli_extension, name=agent.name)
```

### Global-scope commands (`agentkit global ...`)
| Command | Description |
|---|---|
| `apply` | Render + sync global config for one/all agents |
| `sync` | Re-sync rendered configs to native paths (no re-render) |
| `reset` | Restore agent to built-in defaults (with confirmation) |
| `list` | List managed agents and their global config status |

### Project-scope commands (`agentkit project ...`)
| Command | Description |
|---|---|
| `init` | Scaffold `.agentkit/` in current repo, per selected agents |
| `update` | Re-render + sync local config after template/global changes |
| `status` | Show local config drift vs global/defaults |

### Shared/root commands
| Command | Description |
|---|---|
| `diff` | Show diff between merged config and currently-native file (`--scope global\|local`) |
| `doctor` | Validate schema, check native paths exist/writable, detect drift, check for orphaned rendered files |
| `--dry-run` | Global flag on `apply`/`sync`/`update` — show what would change, write nothing |
| `version` | agentkit + adapter versions |

---

## 8. Standard Requirements (Cross-Cutting)

**Idempotency**
- `apply`/`sync` compute a content hash before writing; skip write if
  unchanged. State tracked in `.agentkit/state.json` (per scope) with
  `{path, hash, last_applied, source_layer}`.

**Dry-run**
- Every mutating command accepts `--dry-run`; renders to memory, diffs
  against current native file, prints unified diff via `rich`, writes nothing.

**Reset**
- `reset` reverts to schema defaults; requires `--yes` or interactive
  confirmation; takes a backup to `.agentkit/backups/<timestamp>/` first.

**Diff**
- Three-way aware: shows `defaults → global → local → rendered` per key,
  plus rendered-vs-native drift (catches manual edits to native files).

**Doctor**
- Checks: schema validity, native path existence/permissions, orphaned
  rendered files (in `.agentkit/` but not synced), stale state entries,
  template syntax errors, missing required agent binaries (optional).

**Backups**
- Any destructive operation (`reset`, overwriting a manually-edited native
  file) snapshots the previous native file to `.agentkit/backups/` first.

**Logging/output**
- `rich` for tables/diffs; `--quiet` and `--json` flags on all commands for
  scripting/CI use.

**Exit codes**
- `0` success, `1` validation/render error, `2` drift detected (`doctor`/`diff`
  in `--check` mode, CI-friendly).

---

## 9. Suggested Build Order

1. `core/io.py` + `core/config.py` (merge + provenance)
2. `agents/base.py` + one reference adapter (`claude`)
3. `core/render.py` (Jinja2, using the schema + merged config)
4. `commands/shared_cmds.py` → `diff` and `doctor` (cheapest to validate design)
5. `commands/global_cmds.py` → `apply`, `sync`
6. `commands/project_cmds.py` → `init`, `update`, `status`
7. Add `codex` adapter to prove the plugin interface generalizes
8. `core/state.py` idempotency + backups
9. Entry-point plugin discovery for third-party agent adapters

---

## 10. pyproject.toml — key sections

> **Superseded by refinement plan 01:** use the package and installation layout
> defined in `agentkit_refinement_plan.md`; this example is retained as
> historical context only.

```toml
[project]
name = "agentkit"
requires-python = ">=3.11"
dependencies = [
    "typer>=0.12",
    "pydantic>=2.7",
    "jinja2>=3.1",
    "tomlkit>=0.13",
    "ruamel.yaml>=0.18",
    "rich>=13.7",
]

[project.scripts]
agentkit = "agentkit.cli:app"

[project.entry-points."agentkit.agents"]
claude = "agentkit.agents.claude.adapter:ClaudeAdapter"
codex = "agentkit.agents.codex.adapter:CodexAdapter"

[project.optional-dependencies]
dev = ["pytest", "pytest-cov", "ruff", "mypy"]
```
