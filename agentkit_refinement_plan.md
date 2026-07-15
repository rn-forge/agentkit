# agentkit Refinement Plan — 01

rn-forge integration · kiln defaults port · multi-artifact adapters · docs · strict typing

Status: approved, ready for implementation.
Supersedes the path/layout decisions in `agentkit_spec.md` §3 (repo layout), §5 (folder structure), and §10 (packaging example). Everything else in the spec still applies.

---

## 0. Context and locked decisions

agentkit is one product under the **rn-forge** umbrella. The reference sibling is
`~/Devel/workspaces/rn-forge/macsetup` (shell toolkit), whose conventions we adopt:

- Products install into `~/.rn-forge/<product>/<version>/` with a `current` symlink.
- CLIs are symlinked into `~/.rn-forge/bin/`.
- `RNF_HOME` env var overrides `~/.rn-forge` (used heavily by tests).

Decisions locked with the owner (do not re-litigate):

| Topic | Decision |
| --- | --- |
| Product name | **agentkit** — the kiln name is retired entirely (matches the pykit/shkit *kit family) |
| Kiln port scope | **Full asset pack**: configs, hook scripts, CLAUDE.md/AGENTS.md, output style, codex skill. MEMORY.md convention **dropped** — agents' native memory covers it |
| Global working data | Single root `~/.rn-forge/share/agentkit/` (sources + rendered + state + backups + shared hooks), honoring `$RNF_HOME` |
| Native sync mechanism | **One-way copy** (never symlinks): agents rewrite their own config files via atomic rename, which silently breaks symlinks; copy + hash + drift + backup stays auditable |
| Hook script location | Shared dir `~/.rn-forge/share/agentkit/hooks/`, referenced by absolute path from configs — never copied into `~/.claude`/`~/.codex` |
| Hook script structure | **Common logic library + thin per-agent adapters**: guard logic (patterns, checks) lives once in `hooks/lib/`, and small `hooks/claude/`/`hooks/codex/` adapter scripts handle each agent's I/O dialect (claude: stderr + exit 2; codex: JSON decision + exit 0). See C.2 |
| Install mechanism | macsetup-style `install.sh` → versioned venv under `~/.rn-forge/agentkit/v<version>/` + symlinks |
| In-repo working data | `<repo>/.rn-forge/agentkit/` (was `.agentkit/`) |
| `.gitignore` scaffolding | **Deferred** — do not add |
| Claude local native tier | Keep `.claude/settings.local.json` (personal tier) — revisit shareability later |
| Write-back / capture (`diff --write`) | **Deferred to refinement 02** — see final section |
| Migration from `~/.agentkit` | None needed — no installed users |

Source material for the defaults port:
`~/Devel/workspaces/rn-forge/_backup/z.rn-forge-tool-config/src/kiln/templates/` (read-only backup; copy from it, never modify it).

---

## Milestone A — rn-forge path model

**Goal:** every hardcoded `.agentkit` / `~/.agentkit` path moves to the rn-forge layout.

New module `src/rn_forge/agentkit/core/paths.py`:

```python
def rnf_home() -> Path:
    """~/.rn-forge, overridable via $RNF_HOME (macsetup convention)."""
    return Path(os.environ.get("RNF_HOME", "~/.rn-forge")).expanduser()

def global_root() -> Path:          # was Path.home() / ".agentkit"
    return rnf_home() / "share" / "agentkit"

def project_scope_root(repo_root: Path) -> Path:   # was repo / ".agentkit"
    return Path(repo_root) / ".rn-forge" / "agentkit"
```

Changes:

1. `core/manager.py` — delete its local `global_root()`; import from `paths`. `scope_root()` and `resolve_config()` (currently `Path(repo_root) / ".agentkit"`) use `project_scope_root()`.
2. `commands/project_cmds.py` `status_command` — `root / ".agentkit"` → `project_scope_root(root)`.
3. Grep for any remaining `".agentkit"` string literal in `src/` and `tests/`; there must be none afterwards (docstrings/README updated too).
4. Tests isolate via `monkeypatch.setenv("RNF_HOME", str(tmp_path / "rnf"))` **in addition to** `HOME` (adapter native paths still use `Path.home()`). Add a shared fixture in `tests/conftest.py` that sets both and returns `(home, rnf, repo)`.

**Validation:** full test suite passes; `agentkit global list` in a scratch `RNF_HOME`/`HOME` shows paths under `$RNF_HOME/share/agentkit` and writes nothing outside the two fake roots.

---

## Milestone B — multi-artifact adapter model

**Goal:** an adapter manages a *set* of files per scope, not one. This is the
architectural core of the refinement — do it before the kiln port.

### B.1 Artifact type (new `src/rn_forge/agentkit/core/artifacts.py`)

```python
@dataclass(frozen=True, slots=True)
class Artifact:
    """One managed file an adapter renders/copies and syncs to a native path."""
    key: str                    # stable id, e.g. "settings", "hooks/pre-bash-guard.sh"
    native_relative: Path       # relative to the chosen root, e.g. ".claude/settings.json"
    root: Literal["agent", "share"] = "agent"
                                # "agent": home dir (global) / repo root (local) —
                                #   for files the agent discovers by location
                                # "share": the scope root itself (global:
                                #   $RNF_HOME/share/agentkit, local: <repo>/.rn-forge/agentkit)
                                #   — for files referenced by path from configs (hooks)
    template: str | None = None # Jinja template name (adapter templates dir);
                                # rendered with {"config": validated_merged_config}
    source: Path | None = None  # packaged static file, copied verbatim
    executable: bool = False    # chmod 0o755 after write (hook scripts)
    # exactly one of template/source must be set — enforce in __post_init__
```

Sync is always a **one-way copy** — never a symlink. Rationale (decided):
agents rewrite their own config files with write-temp-then-rename, which
silently replaces a symlink with a regular file and diverges the copies;
and a symlink would not survive re-render anyway. Retaining native-side
updates is the job of the deferred write-back flow (see final section).

The artifact with `key == "config"` (exactly one per scope) is the **primary
config artifact**: the only one whose content derives from the merged config
layers. All others are companion assets.

### B.2 AgentAdapter changes (`agents/base.py`)

- Add abstract `artifacts(self, scope: Scope) -> list[Artifact]`.
- Replace `rendered_relative_path(scope)` with a concrete helper:
  `rendered_path(scope_root, scope, artifact)` = `scope_root / self.name / "rendered" / artifact.native_relative`.
- `render(merged_config, *, scope)` stays but is now "render the primary config artifact".
- Add `render_artifact(self, artifact, merged_config, scope) -> str | bytes` default impl:
  primary/templated → Jinja render; `source` → read packaged bytes verbatim.
- `native_path(scope, repo_root)` generalizes to
  `native_path(scope, repo_root, artifact)`:
  `root == "agent"` → `(Path.home() if scope == "global" else repo_root) / native_relative`;
  `root == "share"` → `scope_root(scope, repo_root) / native_relative`.
  Note this *replaces* `global_native_path()` / `local_native_path()` as the
  source of truth; keep those two as thin wrappers over the primary config
  artifact (doctor/list/CLI already call them).
  Share-rooted artifacts need no separate `rendered/` staging copy — the
  synced file under the scope root *is* the managed copy (state.json still
  records it for drift checks).
- Add `defaults(self, scope: Scope) -> dict` — see Milestone C.4 (scope-aware).

### B.3 Manager changes (`core/manager.py`)

- `OperationResult` gains `artifact: str` field.
- `apply_adapter` iterates `adapter.artifacts(scope)` and returns
  `list[OperationResult]` (one per artifact). Per artifact: render/copy → hash →
  skip-if-unchanged → backup-if-manual-drift → atomic write staging + native →
  `chmod` if `executable` → record in state. Config resolution/validation runs
  **once** per adapter, before the loop.
- `sync_adapter` iterates all staged artifacts the same way.
- `reset_adapter` resets the managed source then applies (loop comes for free).
- `atomic_write` in `core/io.py` gains optional `mode: int | None` (applied to
  the temp file before `os.replace`; existing-file mode preservation stays).
- `init_adapter` unchanged in shape. (An earlier draft seeded a shared
  `MEMORY.md` convention file here — **dropped**: agents' native memory
  management covers it.)

### B.4 Doctor / diff / status

- `core/doctor.py` `check_agent`: drift + orphan checks loop over
  `adapter.artifacts(scope)`. The "unexpected rendered file" check compares the
  `rendered/` tree against the full expected artifact set (not the single path).
- `diff` command: layered key-change table stays config-only; the unified-diff
  section reports per-artifact drift (skip byte-identical companions; for
  binary/verbatim assets a one-line "differs" is enough).
- `global list` / `project status`: `in_sync`/`drift` = **all** artifacts in sync.

**Validation:** existing tests updated for list-returning manager functions;
new unit test: adapter with 1 templated + 1 static-executable artifact — apply
writes both, exec bit set, second apply reports all unchanged, manual edit to
either native file triggers backup on next apply.

---

## Milestone C — kiln defaults port

**Goal:** fresh `agentkit global apply` / `project update` reproduces the kiln
setup. Copy assets from the backup tree; the only allowed content edits are the
path rewrites in C.5 and the hook-guard restructure in C.2. Port config values
verbatim (even stale-looking ones like `model = "gpt-5.4"`) — value curation is
a later pass.

### C.1 Packaged layout (new files under `src/rn_forge/agentkit/`)

Per-agent data stays under `agents/<agent>/`; hook scripts are agent-spanning,
so they live at package level:

```text
agents/claude/
├── defaults/global.json        # kiln claude/global/settings.json values (path-rewritten)
├── defaults/local.json         # kiln claude/project/settings.json values (path-rewritten)
├── assets/CLAUDE.md            # kiln claude/global/CLAUDE.md
├── assets/output-styles/concise.md
└── templates/…                 # unchanged
agents/codex/
├── defaults/global.toml        # kiln codex/global/config.toml values
├── defaults/local.toml         # kiln codex/project/config.toml (empty mapping + comment)
├── assets/AGENTS.md
├── assets/hooks.json           # path-rewritten
└── assets/skills/repo-context/SKILL.md
    assets/skills/repo-context/agents/openai.yaml
assets/hooks/                   # package-level (see C.2)
├── lib/guard-core.sh           # authored: shared guard logic
├── claude/pre-bash-guard.sh    # authored: thin claude adapter
├── claude/user-prompt-secret-guard.sh   # authored: thin claude adapter
├── claude/pre-write-protect.sh         # claude-only, ported verbatim
├── claude/session-compact-context.sh   # claude-only, ported verbatim
├── claude/post-edit-git-stage.sh       # claude-only, ported verbatim
├── claude/post-edit-format.sh          # claude-only (project scope), ported verbatim
├── codex/pre-bash-guard.sh     # authored: thin codex adapter
└── codex/user-prompt-secret-guard.sh    # authored: thin codex adapter
```

Kiln's `shared/MEMORY.md` is **not ported** (dropped — see locked decisions).

Do **not** copy `.DS_Store` files. Confirm packaged data files ship in the wheel
(uv_build includes package data by default; verify with `uv build && unzip -l`).

### C.2 Hook script architecture — common logic, per-agent adapters

Kiln shipped near-duplicate guard scripts per agent; they differ only in the
block protocol (claude: reason on stderr + exit 2; codex: JSON
`{"decision": "block", "reason": ...}` on stdout + exit 0) and had drifted
pattern lists. Restructure (decided):

- **`lib/guard-core.sh`** — pure logic, no stdin/stdout side effects, no
  agent-specific behavior. Exposes check functions that print the first
  matched block reason to stdout and return 1, or return 0 silently:
  `guard_check_bash_command "$cmd"`, `guard_check_prompt_secrets "$prompt"`.
  Pattern set = the **union** of both kiln variants (they drifted — e.g. the
  claude variant checks `$HOME`/current-dir deletion; reconcile to the
  superset, claude's messages win where wording differs).
- **Adapter scripts** (`claude/…`, `codex/…` for the two shared guards) — thin
  wrappers that: read the payload from stdin, extract the field with `jq`
  (payload field paths are the same across both agents: `.tool_input.command`,
  `.prompt`), source the lib, and emit the verdict in their agent's dialect.
  The jq-missing fail-safe also follows the dialect (claude: block via
  stderr + exit 2; codex: block via JSON + exit 0).
- Adapters locate the lib **relative to themselves** —
  `. "$(dirname "$0")/../lib/guard-core.sh"` — configs invoke hooks by
  absolute path, so no install path is hardcoded inside any script.
- Claude-only hooks (`pre-write-protect`, `session-compact-context`,
  `post-edit-git-stage`, `post-edit-format`) are ported verbatim (header
  comment `# kiln:` → `# agentkit:` only); they may source the lib later if
  they grow shared patterns, but don't restructure them now.

Both adapters declare the `lib/guard-core.sh` artifact (identical packaged
source); apply is hash-idempotent, so whichever runs second is a no-op.
Doctor's orphan check for the share-rooted `hooks/` tree must use the union
of artifact sets across adapters, or `lib/` would be flagged as orphaned when
checking a single agent.

### C.3 Artifact registrations

Hook scripts are **share-rooted** (referenced by path from configs, so they
never enter `~/.claude`/`~/.codex`). Discovery-by-location assets (output
styles, skills, CLAUDE.md, AGENTS.md) must be agent-rooted — the agents only
find them at fixed native paths.

`ClaudeAdapter.artifacts("global")`:

| key | root | native_relative | kind |
| --- | --- | --- | --- |
| `config` | agent | `.claude/settings.json` | template `global.j2` |
| `CLAUDE.md` | agent | `.claude/CLAUDE.md` | static |
| `output-styles/concise.md` | agent | `.claude/output-styles/concise.md` | static |
| `hooks/lib/guard-core.sh` | share | `hooks/lib/guard-core.sh` | static |
| `hooks/<name>.sh` ×5 (global hooks) | share | `hooks/claude/<name>.sh` | static, executable |

`ClaudeAdapter.artifacts("local")`:

| key | root | native_relative | kind |
| --- | --- | --- | --- |
| `config` | agent | `.claude/settings.local.json` | template `local.j2` |
| `hooks/post-edit-format.sh` | share | `hooks/claude/post-edit-format.sh` | static, executable |

`CodexAdapter.artifacts("global")`:

| key | root | native_relative | kind |
| --- | --- | --- | --- |
| `config` | agent | `.codex/config.toml` | template `global.j2` |
| `AGENTS.md` | agent | `.codex/AGENTS.md` | static |
| `hooks.json` | agent | `.codex/hooks.json` | static |
| `hooks/lib/guard-core.sh` | share | `hooks/lib/guard-core.sh` | static |
| `hooks/<name>.sh` ×2 | share | `hooks/codex/<name>.sh` | static, executable |
| `skills/repo-context/…` ×2 | agent | `.codex/skills/repo-context/…` | static |

`CodexAdapter.artifacts("local")`: `config` → `.codex/config.toml` only.

### C.4 Scope-aware defaults

Replace `defaults_for(schema)`-only defaults with:

```python
def defaults(self, scope: Scope) -> dict[str, Any]:
    """Schema defaults deep-merged with the packaged per-scope defaults file."""
    packaged = read_config(Path(__file__).parent / "defaults" / f"{scope}{ext}")
    return ConfigMerger(self.schema()).merge(defaults_for(self.schema()), packaged).config
```

`resolve_config` passes `scope` through. Resulting layer chain:
`defaults(scope) → global source → [local source] → overrides`. Note the
consequence (intended): global-scope packaged defaults (hooks wiring, deny
permissions) do **not** leak into the local rendering; the user's *managed
global source* still does, per the spec's precedence chain.

Schema additions (typed fields for values the defaults use; `extra="allow"`
already tolerates the rest — add these for validation value):

- `ClaudeConfig`: `effortLevel: str | None`, `outputStyle: str | None`,
  `extraKnownMarketplaces: dict[str, Any]`.
- `CodexConfig`: `personality: str | None`,
  `model_reasoning_summary: str | None`,
  `sandbox_workspace_write: dict[str, Any]`, `profiles: dict[str, Any]`.

### C.5 Path rewrites

| In file | Old reference | New reference |
| --- | --- | --- |
| claude `defaults/global.json` hooks | `$HOME/.rn-forge/kiln/claude/hooks/<x>.sh` | `$HOME/.rn-forge/share/agentkit/hooks/claude/<x>.sh` |
| claude `defaults/local.json` hooks | `$CLAUDE_PROJECT_DIR/.rn-forge/kiln/claude/hooks/post-edit-format.sh` | `$CLAUDE_PROJECT_DIR/.rn-forge/agentkit/hooks/claude/post-edit-format.sh` |
| codex `assets/hooks.json` | `$HOME/.rn-forge/kiln/codex/hooks/<x>.sh` | `$HOME/.rn-forge/share/agentkit/hooks/codex/<x>.sh` |

`$HOME`/`$CLAUDE_PROJECT_DIR` expand at hook execution time — keep them
literal (no Jinja substitution). Note the references use literal
`$HOME/.rn-forge/`, not `$RNF_HOME`: the agents' hook runners can't be assumed
to have `RNF_HOME` exported, and the override is a test convenience. Tests
asserting on hook paths should set `RNF_HOME="$HOME/.rn-forge"` inside the fake
home so references resolve.
No hook *script* contains an install path — the authored adapters source the
lib via `$(dirname "$0")` (C.2), and the ported claude-only scripts get only a
header-comment update (`# kiln:` → `# agentkit:`).

**Validation:** integration test — fresh fake `HOME` with
`RNF_HOME="$HOME/.rn-forge"`, run `global apply` + `project init` +
`project update`; assert `~/.claude/settings.json` parses as JSON, every
`"command"` inside it (after `$HOME`/`$CLAUDE_PROJECT_DIR` substitution)
points at an existing executable file under the share/scope hooks dir, and
`~/.codex/config.toml` round-trips through tomlkit with `model = "gpt-5.4"`.

Additionally, because the guard adapters are authored (not copied), add
script-behavior tests (`tests/hooks/test_guard_scripts.py`, skipped when `jq`
is unavailable) that run each synced adapter via `subprocess` with sample
stdin payloads and assert the dialect: `rm -rf /` payload → claude adapter
exits 2 with reason on stderr, codex adapter exits 0 with
`{"decision": "block", ...}` on stdout; a benign command passes both; a
prompt containing `sk-…`/`ghp_…` tokens is blocked by both secret guards.

---

## Milestone D — installer (`install.sh` at repo root)

Model it on `macsetup/src/install.sh` (read it first), simplified to
**in-path install from a checkout only** — no release-tarball streaming yet.

Behavior when sourced or executed from the repo:

1. `RNF_HOME="${RNF_HOME:-$HOME/.rn-forge}"`; version = `grep '^version' pyproject.toml`.
2. Target `“$RNF_HOME/agentkit/v<version>”`. No-op with a success message if
   `current` already resolves to that version and `bin/agentkit` exists.
3. Build the env there:
   `UV_PROJECT_ENVIRONMENT="$RNF_HOME/agentkit/v<version>" uv sync --frozen --no-dev`
   (run from the repo root; this resolves the `rn-forge-commons` path source
   from `tool.uv.sources`, which plain `uv pip install .` cannot).
4. `ln -sfn "v<version>" "$RNF_HOME/agentkit/current"`;
   `mkdir -p "$RNF_HOME/bin"`;
   `ln -sfn "../agentkit/current/bin/agentkit" "$RNF_HOME/bin/agentkit"`.
5. Print next steps (add `~/.rn-forge/bin` to PATH — same message style as macsetup).

Constraints: `set -euo pipefail` compatible when executed, safe when sourced
(macsetup's `${__SOURCED__:+return}` guard pattern); no rc-file edits; document
in README that the checkout (and the sibling `pykit` path dep) must exist at
install time.

**Validation:** run with scratch `RNF_HOME`; `"$RNF_HOME/bin/agentkit" version`
prints the version; re-run is a no-op.

---

## Milestone E — documentation

1. **Docstrings** (target: extractable later via mkdocs + mkdocstrings — do not
   add mkdocs config now):
   - Google-style throughout `src/`; every public module gets a module docstring
     explaining its role and collaborators; every public class/function gets
     Args/Returns/Raises where non-obvious.
   - Package `__init__.py` files (`agentkit`, `core`, `agents`, `commands`,
     `agents/claude`, `agents/codex`) get short package-overview docstrings:
     what lives here, key entry points.
2. **README.md** — add a "Source layout" section (table: folder → purpose),
   update every path (`~/.rn-forge/share/agentkit`, `.rn-forge/agentkit`,
   install instructions via `install.sh`), and document the default pack
   (what `global apply` installs, artifact tables from C.3 in condensed form).
3. **agentkit_spec.md** — add a short "Superseded by refinement plan 01" note at
   the top of §3/§5/§10 rather than rewriting the spec.

---

## Milestone F — test reorganization (mirror `src/`)

```text
tests/
├── conftest.py                  # shared home/rnf/repo isolation fixture (Milestone A)
├── core/
│   ├── test_config.py           # ← test_config_merge.py
│   ├── test_io.py
│   ├── test_diff.py
│   ├── test_render.py
│   ├── test_manager.py
│   ├── test_doctor.py
│   ├── test_paths.py            # new: RNF_HOME override, project_scope_root
│   └── test_artifacts.py        # new: Milestone B validation cases
├── agents/
│   ├── test_claude_adapter.py
│   └── test_codex_adapter.py    # both extended with artifact/defaults assertions
├── hooks/
│   └── test_guard_scripts.py    # new: adapter dialect tests (Milestone C validation)
└── commands/
    └── test_cli.py
```

`git mv` the existing files (preserve history), then extend. Every test must
pass under the conftest isolation fixture — no test may touch the real
`~/.rn-forge`, `~/.claude`, or `~/.codex`.

---

## Milestone G — pyright strict: zero errors

`pyproject.toml` already sets `typeCheckingMode = "strict"` with
`ignore = ["tests"]`. Current count: **84 errors** in `src/`, distribution:
~79 `reportUnknown{Variable,Argument,Member}Type` (tomlkit/ruamel untyped
boundaries), 2 `reportUnnecessaryIsInstance`, 2 `reportArgumentType`
(render.py filters), 1 `reportAttributeAccessIssue`.

Rules: no `# type: ignore` sprinkling, no rule downgrades in config. Fix at the
boundary:

- `core/io.py`: introduce one typed choke point — after any tomlkit/ruamel
  load, validate `isinstance(value, Mapping)` (already done) then
  `cast(dict[str, Any], ...)` via `_to_plain` (annotate `_to_plain(value: Any) -> Any`
  with typed public wrappers returning `dict[str, Any]`). Type the YAML
  helpers: `yaml.load` returns `Any` — assign to an `Any`-typed local, then
  narrow. Same for `dump` (wrap in small `def _yaml_dumps(data: object) -> str`).
- `core/render.py:28-29`: replace the filter lambdas with module-level typed
  functions `def _to_toml(value: Mapping[str, Any]) -> str` and register those
  (fixes both `reportArgumentType`s).
- `core/state.py:40`: validate then `cast(dict[str, dict[str, Any]], data)`.
- `core/config.py:109`: tomlkit item `.unwrap()` — go through a typed helper
  (`cast(Any, ...)` at the single call site inside `_parse_scalar`).
- `reportUnnecessaryIsInstance` (2): delete the redundant checks pyright points
  at (they are provably-true branches — verify each before removing).
- Commands/adapters: annotate the row-dict literals
  (`rows: list[dict[str, Any]]`) and similar inferred-unknown spots.

**Acceptance:** `uv run pyright src` → `0 errors, 0 warnings` in strict mode,
with zero new ignores.

---

## Build order and validation gates

Implement milestones in order **A → B → C → G → F → E → D** (G before the test
move so moved tests land against typed code; D last since it only wraps the
package). After every milestone:

```bash
uv run pytest -q
uv run ruff check src tests
uv run pyright src        # must be zero from Milestone G onward
```

Final end-to-end gate (scratch dirs only):

```bash
export RNF_HOME=/tmp/rnf-test HOME=/tmp/home-test   # in a subshell
uv run agentkit global apply
uv run agentkit project init  && uv run agentkit project update
uv run agentkit doctor --scope global && uv run agentkit doctor --scope local
uv run agentkit global apply | grep -c unchanged    # second run: all unchanged
./install.sh && "$RNF_HOME/bin/agentkit" version
```

## Out of scope (explicitly deferred)

- `.gitignore` scaffolding for `.rn-forge/` — pending shareability decision.
- Release-tarball / curl-streaming install path.
- mkdocs site build (docstrings only, written mkdocstrings-compatible).
- Curating kiln config *values* (models, policies) — ported verbatim.
- Claude local tier revisit (`settings.local.json` vs `settings.json`).
- Migration from the old `~/.agentkit` layout.
- Restructuring the claude-only hooks onto the guard lib (only the two
  agent-spanning guards are unified in this pass — see C.2).
- **Write-back / capture** — see below.

## Refinement 02 preview — write-back (do not implement now)

Modeled on `rnfmac brew diff --write` (drift report that can update the
source-of-truth in a git checkout). Plan 01 deliberately preserves the
enablers: one-way copies with hash-based drift detection, `parse_native()`
on every adapter, and comment-preserving `update_config()` in `core/io.py`.

- **Phase 1 — capture to managed source:** `agentkit diff --write` parses the
  native config, computes the structural delta vs the rendered config, and
  merges it into the managed source (`config.toml` at the relevant scope).
  Turns runtime accumulations (permission grants, `#` memory appends via a
  CLAUDE.md text merge, `/config` changes) into durable source instead of
  drift to be clobbered. Only the primary config artifact can be captured
  structurally; edited static assets are captured as whole-file copies.
- **Phase 2 — capture to kit checkout:** point the write-back at a checked-out
  agentkit repo (packaged `defaults/` + `assets/`), so captures can be
  committed and released as a new default-pack version — the Brewfile loop.
  Blocked on the project-config shareability decision.
