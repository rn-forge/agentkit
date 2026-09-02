# Adapters and artifacts

An **adapter** teaches agentkit about one agent. An **artifact** is one file
that adapter wants written. Everything agentkit lays down — configs, hook
scripts, instruction files, skills — is an artifact.

## The artifact model

An artifact declares:

- **A source** — either a Jinja template rendered from resolved config values,
  or a packaged static file copied verbatim.
- **A root** — the agent root (`~/.claude`, `<repo>/.codex`, …) or the shared
  root (`_common/`, for assets more than one agent depends on).
- **A stable key** — the identity used in command output, diffs, and doctor
  rows. Note that `state.json` is keyed by *resolved native path*, not by this
  key: renaming a destination therefore does orphan its applied-hash record,
  which `doctor` reports as a stale entry.
- **A native-relative path** — where it lands under that root.
- **An optional executable mode** — hook scripts need `+x`; configs don't.
- **An optional `template_root`** — the packaged directory a template is
  resolved against, when that differs from the adapter's own `template_dir`
  (for example, a shared instruction or skill template). `None` means the
  adapter's own `template_dir`; setting `template_root` without `template` is
  rejected.

Artifacts are **ordered**. A hook script must exist before the config that
references it by absolute path is applied, or the agent reads a config pointing
at a missing file.

## Writing an adapter

Implement `rn_forge.agentkit.agents.base.AgentAdapter`:

- **Schema** — a Pydantic model describing the agent's settable config surface,
  including `merge_strategy: append` on any list field that should accumulate
  across layers rather than being replaced by the highest one.
- **Scope-aware defaults** — packaged `global.json` / `local.json`, found
  automatically from a `_defaults_suffix` class attribute (for example
  `".json"`); an adapter with schema-only defaults leaves it unset. Global
  defaults must not leak into local defaults; see the
  [configuration model](index.md#configuration-model).
- **Primary renderer and parser** — the renderer turns resolved values into the
  agent's native config format; the parser reads that format back, which is
  what makes `agentkit diff --write` write-back possible. The parser must
  preserve comments, which is why the codebase uses `tomlkit` and
  `ruamel.yaml` rather than `tomllib` and `PyYAML`. Capture parses its
  expected baseline from an in-memory render through the base class's
  `parse_native_text`, so a path-based `parse_native` is all an adapter has to
  supply.
- **Ordered artifact declarations** — implement `_global_artifacts()` and
  `_local_artifacts()` (the concrete `artifacts(scope)` on the base class
  dispatches between them) per the model above. Rendering itself is not an
  extension point: the base class's `render_artifact()` reads a static
  artifact's `source`, calls `render()` for the `config` key, and otherwise
  renders `template` against `template_root` (or `template_dir`) with a
  context chosen by the artifact's `kind` (`skill` gets
  `{"agent": self.name}`, `doc` gets `{}`, everything else gets
  `{"config": merged_config}`) — set `template_root` and `kind` on the
  artifact declaration instead of overriding `render_artifact()`.
- **Optional `cli_extension`** — an adapter-specific Typer app, if the agent
  needs commands the generic surface doesn't cover.

## Registration

Publish the adapter under the `agentkit.adapters` entry-point group:

```toml
[project.entry-points."agentkit.adapters"]
my-agent = "my_package:MyAgentAdapter"
```

Built-in adapters (`claude`, `codex`) are constructed directly by the registry
rather than loaded through this group, so agentkit works with no metadata to
read. Third-party adapters share everything after loading: the same
`AgentAdapter` contract, the same artifact and scope handling, the same
commands.

Their names are reserved. A discovered adapter is rejected — with the reason
reported by `doctor` — when it claims a built-in name, uses a name that is not a
safe directory segment, or declares duplicate artifact keys or destinations. A
plugin that fails to import is skipped and reported rather than fatal, so one
broken package cannot take down `--help` or the other agents.

## Reference

See the [Python API reference](../reference/python-api.md#agents-and-adapters)
for `AgentAdapter`, the registry, and the built-in Claude and Codex adapters.
