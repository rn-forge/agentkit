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
- **A stable key** — the identity used in `state.json` for hash tracking, so
  renaming a destination path doesn't orphan its applied-hash record.
- **A native-relative path** — where it lands under that root.
- **An optional executable mode** — hook scripts need `+x`; configs don't.

Artifacts are **ordered**. A hook script must exist before the config that
references it by absolute path is applied, or the agent reads a config pointing
at a missing file.

## Writing an adapter

Implement `rn_forge.agentkit.agents.base.AgentAdapter`:

- **Schema** — a Pydantic model describing the agent's settable config surface,
  including `merge_strategy: append` on any list field that should accumulate
  across layers rather than being replaced by the highest one.
- **Scope-aware defaults** — packaged `global.json` / `local.json`. Global
  defaults must not leak into local defaults; see the
  [configuration model](index.md#configuration-model).
- **Primary renderer and parser** — the renderer turns resolved values into the
  agent's native config format; the parser reads that format back, which is what
  makes `agentkit diff --write` write-back possible. The parser must preserve
  comments, which is why the codebase uses `tomlkit` and `ruamel.yaml` rather
  than `tomllib` and `PyYAML`. Capture parses its expected baseline from an
  in-memory render through the base class's `parse_native_text`, so a
  path-based `parse_native` is all an adapter has to supply.
- **Ordered artifact declarations** — per the model above.
- **Optional `cli_extension`** — an adapter-specific Typer app, if the agent
  needs commands the generic surface doesn't cover.

## Registration

Publish the adapter under the `agentkit.adapters` entry-point group:

```toml
[project.entry-points."agentkit.adapters"]
my-agent = "my_package:MyAgentAdapter"
```

Built-in adapters are registered the same way, so a third-party adapter is not a
second-class citizen — there is no separate plugin path to keep working.

## Reference

See the [Python API reference](../reference/python-api.md#agents-and-adapters)
for `AgentAdapter`, the registry, and the built-in Claude and Codex adapters.
