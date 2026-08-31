# Architecture overview

agentkit resolves configuration through a layered merge, renders each agent's
native files from the resolved values, and syncs them with a hash-tracked
one-way copy. This page covers the configuration model and the path model; the
[adapters page](adapters.md) covers what an agent plugin actually implements.

## Configuration model

Values resolve in increasing precedence:

```text
packaged scope defaults
  → $RNF_HOME/share/agentkit/<agent>/config.toml
  → <repo>/.rn-forge/agentkit/<agent>/config.toml
  → --set dotted.key=value
```

The local managed source participates only for local operations. Packaged global
defaults do not leak into packaged local defaults, while a user's managed global
source still feeds both scopes.

Dictionaries merge recursively. Lists replace lower layers unless the adapter
schema marks a field with `merge_strategy: append`. Every final key retains its
source-layer provenance, which is what makes `agentkit --json global list`
useful for debugging "where did this value come from".

## Path model

The default global scope root is `~/.rn-forge/share/agentkit`; a repository uses
`<repo>/.rn-forge/agentkit`. `RNF_HOME` overrides `~/.rn-forge` throughout —
this is the umbrella-wide convention, not an agentkit-specific one.

Every managed file lives under an agent directory, except the guard library
shared by all agents, which lives under `_common/`:

```text
<scope-root>/
├── _common/hooks/guard-core.sh   # shared guard logic (global scope only)
├── <agent>/config.toml           # managed source — the layer you edit
├── <agent>/hooks/*.sh            # this agent's hook scripts, run in place
├── <agent>/rendered/<native>     # staging mirror of the native tree
├── state.json                    # applied hashes
└── backups/<run-timestamp>/      # pre-overwrite snapshots, one dir per run
```

`rendered/` mirrors the destination path relative to its native root (`$HOME`
globally, the repo locally), so the staging tree is a path-for-path preview of
what gets laid down.

## Why copy, never symlink

Sync is always a one-way copy. Agents rewrite their own config files via atomic
rename, which replaces the inode and silently breaks a symlink — the config
would appear managed while quietly diverging. Copy plus hash plus drift
detection plus backup stays auditable instead.

Hashes in `state.json` make repeated runs idempotent, and manual native drift is
backed up under `backups/<run-timestamp>/` before overwrite. `agentkit diff
--write` runs the loop in reverse, capturing native primary-config edits back
into the managed source. For artifacts with a packaged static source instead
of a template — hook scripts and skill files — the same flag copies a
hand-edited native file back onto its packaged source path in this checkout,
so a quick fix made directly in `~/.claude/hooks/` or `~/.claude/skills/`
becomes part of the versioned asset pack instead of being silently overwritten
by the next `apply`. That only lands somewhere useful when agentkit is running
from an editable checkout of this repo (its own dogfooding loop); against an
installed, non-editable package the write is reported as unwritable rather
than raising.

Hook scripts are referenced from agent configs by absolute path and run from
`<scope-root>/<agent>/hooks/` — they are never copied into `~/.claude` or
`~/.codex`. That keeps one copy of each script, executable in place, with the
agent config pointing at it.

## Hooks: shared logic, per-agent dialect

Both adapters declare the shared `_common/hooks/guard-core.sh`. The shared
library contains the common destructive-command, sensitive-path, and
prompt-secret checks; thin per-agent adapters emit Claude's stderr/exit-2 or
Codex's JSON/exit-0 blocking dialect. The guard logic is written once; only the
way a refusal is signalled differs.

Two parity exclusions are intentional:

- Codex has no built-in read-tool matcher, so it cannot mirror Claude's
  secret-read denials. Its write guard still protects sensitive in-repo paths.
- Compaction context injection remains Claude-only, because Codex has no
  equivalent context-injection behavior for this asset pack.

Not every hook is a guard. `post-write-unwrap-md.sh` fires on
`PostToolUse`/`Write|Edit|MultiEdit` (Codex: `Edit|Write`) against `.md` files
and unwraps prose back to one line per paragraph or list item via the
co-installed `unwrap_md.py`, so hand-authored docs stay diff-friendly no
matter which agent wrote them. It always exits 0 — a formatting convenience,
not something that can block an edit that already happened — and a repo opts
out globally with a `.nounwrap` marker at its git root.

## Instruction and skill single-sourcing

Instruction files are single-sourced: `~/.claude/CLAUDE.md`, `~/.codex/AGENTS.md`,
and `~/.claude/output-styles/concise.md` all render from shared partials in
`src/rn_forge/agentkit/assets/instructions/`, so the two agents cannot drift
apart. Adapter tests assert each rendered file byte-matches its packaged
snapshot.

Skills work the same way, from `src/rn_forge/agentkit/assets/skills/`. Both
agents read the identical skill container (`<name>/SKILL.md` with `name` +
`description` frontmatter, plus `references/`, `scripts/` and `assets/`), and
`AgentAdapter.skill_artifacts` maps that one tree onto each agent's own root.
Adding a skill is adding its directory — no code change.

Within a skill, `SKILL.md.j2` renders per agent with an `agent` variable, so the
handful of genuinely harness-specific lines can branch (Claude's `allowed-tools`
frontmatter, its `ToolSearch` hint for deferred MCP tools). Bundled resources
under a skill are copied **verbatim, never rendered** — they carry placeholder
syntax that is not Jinja and must survive untouched — go-task's and GitHub
Actions' own brace placeholders would otherwise be eaten by the renderer.
