# Python API

Generated from docstrings with [mkdocstrings](https://mkdocstrings.github.io/).
Modules are grouped by architectural layer rather than listed flat — the
grouping mirrors how a change actually flows through the codebase: a CLI command
resolves configuration through `core`, then asks an adapter what artifacts to
write.

## Package entry points

::: rn_forge.agentkit

## Command layer

The Typer application and its command groups. These own argument parsing, output
mode (`--quiet` / `--json`), and user-facing failure messages — no business
logic.

::: rn_forge.agentkit.cli

::: rn_forge.agentkit.commands.base

::: rn_forge.agentkit.commands.global_command

::: rn_forge.agentkit.commands.project_command

::: rn_forge.agentkit.commands.self_command

::: rn_forge.agentkit.commands.root_command

## Core services

Configuration resolution, rendering, file I/O, state tracking, and diagnostics.
Everything here is agent-agnostic — `core` never imports an adapter.

### Paths and configuration

::: rn_forge.agentkit.core.paths

::: rn_forge.agentkit.core.config

### Artifacts and rendering

::: rn_forge.agentkit.core.artifacts

::: rn_forge.agentkit.core.render

::: rn_forge.agentkit.core.io

### Orchestration and diagnostics

::: rn_forge.agentkit.core.operations.result

::: rn_forge.agentkit.core.operations.apply

::: rn_forge.agentkit.core.operations.remove

::: rn_forge.agentkit.core.operations.capture

::: rn_forge.agentkit.core.operations.init

::: rn_forge.agentkit.core.state

::: rn_forge.agentkit.core.diff

::: rn_forge.agentkit.core.doctor

## Agents and adapters

The plugin surface. `base` defines the contract; `registry` combines built-ins
with entry-point discoveries; the rest are the two shipped implementations.

::: rn_forge.agentkit.agents.base

::: rn_forge.agentkit.agents.registry

### Claude Code

::: rn_forge.agentkit.agents.claude.adapter

::: rn_forge.agentkit.agents.claude.schema

### Codex

::: rn_forge.agentkit.agents.codex.adapter

::: rn_forge.agentkit.agents.codex.schema
