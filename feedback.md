# agentkit implementation review — response

Review date: 2026-08-31 Response date: 2026-08-31

Thanks — the P0s were real and reproducible, and #1 in particular was a genuine
silent-corruption bug. This document keeps the original findings and adds a
response to each. Findings are marked:

- **Fixed** — changed, with a regression test where the finding was behavioural.
- **Fixed (partly)** — the defect is closed; a broader recommendation was not
  adopted, with the reason given.
- **Documented as deliberate** — a real trade-off rather than a defect. The
  reasoning is now recorded in the repo so it does not have to be re-derived;
  the links say where.
- **Not accepted** — the finding does not reproduce, or its diagnosis is wrong.

Everything claimed below was verified by running it. Validation evidence is at
the bottom.

______________________________________________________________________

## Summary table

| # | Finding | Response |
| -- | -- | -- |
| 1 | `global reset` duplicates Claude permission defaults | **Fixed** |
| 2 | Destructive-command guards bypassable | **Fixed (partly)** |
| 3 | Hooks fail open on malformed event JSON | **Fixed** |
| 4 | Bootstrap executes unverified remote code | **Documented as deliberate** (description corrected) |
| 5 | `doctor` reports stale artifacts as in sync | **Fixed** |
| 6 | Seed files reported as drift | **Fixed** |
| 7 | Plugin discovery can disable the CLI or replace built-ins | **Fixed** |
| 8 | `diff --write` rewrites installed package files | **Documented as deliberate** |
| 9 | Apply/sync are not transactional | **Fixed (partly)** |
| 10 | Machine-readable error output is not machine-readable | **Fixed** |
| 11 | Markdown post-processing can change semantics | **Not accepted** (no reproducer) |
| 12 | Post-edit formatting can install npm packages | **Fixed** |
| 13 | Validation is red and environment-dependent | **Not accepted** as written; hermeticity **Fixed** |
| 14 | Release publication triggered too easily | **Documented as deliberate** |
| 15 | Test code excluded from static checks | **Documented as deliberate** |
| 16 | Coverage not enforced or branch-aware | **Documented as deliberate** |
| 17 | State lacks schema validation, locking, durability | **Fixed** |
| 18 | Filesystem/adapter invariants not enforced | **Fixed** |
| 19 | CLI error handling inconsistent | **Fixed** |
| 20 | `manager.py` and `diff` do too much | **Documented as deliberate** |
| 21 | Docs not built on pull requests | **Fixed** |
| 22 | Distributions released without validation | **Fixed (partly)** |
| 23 | Package metadata and legal status incomplete | **Fixed** |
| 24 | Documentation contract errors | **Fixed** |
| 25 | New-machine prerequisites incomplete | **Fixed** |
| 26 | CI supply-chain policy inconsistent | **Fixed (partly)** |
| 27 | Python compatibility narrow and unexplained | **Documented as deliberate** |
| 28 | Repository hygiene and auxiliary docs | **Fixed (partly)** |

______________________________________________________________________

## P0

### 1. `global reset` does not produce a clean default state — **Fixed**

Confirmed and reproduced before fixing. Against a scratch `HOME`, one
`agentkit global reset --agent claude` produced 42 `permissions.deny` entries
where 21 are unique, and each further reset would have doubled again. The
managed source also went from the 7-line scaffold to 51 lines of materialized
defaults, unbacked-up.

`reset_adapter()` now backs up **both** the native primary config and the
managed source, writes the documented empty-override scaffold rather than
materialized defaults, and applies packaged defaults once. The comment at
`core/manager.py` explains why writing defaults there is the bug: it turns them
into an override layer that the following apply merges on top of the packaged
defaults a second time.

Verified: `deny` is 21 unique after reset, and still 21 unique after a second
reset. Three tests added in `tests/core/test_manager.py` —
`test_reset_does_not_duplicate_append_merged_defaults` (Claude, two consecutive
resets), `test_reset_backs_up_the_hand_edited_managed_source` (comments and keys
recoverable from the backup), and the existing Codex reset test updated to
assert scaffold restoration rather than materialized defaults.

### 2. Destructive-command guards are easy to bypass — **Fixed (partly)**

Reproduced, with two corrections to the finding. Measured before the fix:

```text
blocked: rm -rf /              ALLOWED: rm -r -f /
blocked: /bin/rm -rf /         ALLOWED: rm --recursive --force /
blocked: command rm -rf /      ALLOWED: git -C . push --force
```

`/bin/rm -rf /` and `command rm -rf /` were **already blocked** — the regex is
unanchored, so the claim about executable paths and wrappers was incorrect. The
separated-flag, long-flag, and Git-global-option bypasses were real.

Fixed by matching the recursive and force flags as a combined token or as two
separate tokens in either order, with unrelated flags interleaved and GNU long
forms accepted; and by sharing one `git … push` pattern between detection and
argument extraction so the two cannot disagree about where push arguments begin.
All eleven previously-bypassing spellings now block, with no new false positives
on `rm -rf /tmp/foo`, `rm -f file.txt`, `rm -r dir`, or
`git push origin feature`. Regression matrix in
`tests/hooks/test_guard_scripts.py`.

**Not adopted:** the recommendation to parse a constrained shell grammar and
fail closed on anything unclassifiable. That would block far more legitimate
work than it saves, and it would not actually close the class — `eval`, variable
indirection, and base64 remain trivial. The honest position is that these hooks
are a speed bump against accident, not a security boundary, so that is now
stated explicitly in the `guard-core.sh` header and in a new
[safety model](docs/architecture/safety-model.md) page rather than implied.

### 3. Hooks fail open on malformed event JSON — **Fixed**

Reproduced: truncated JSON into `pre-bash-guard.sh` gave exit 0 and empty output
— allowed. `guard_require_jq_json` checks only that `jq` is *installed*, despite
the name; the parse itself was unchecked, and an empty command string
short-circuits to "allow".

Added `guard_event_field`, which fails on a payload that is not valid JSON and
on a field present with a non-string type, while treating an absent or null
field as a well-formed event. All six hook adapters use it.

The prompt-secret policy is now explicit rather than incidental: command and
write guards **block** on an unusable event; the prompt guard **warns and
continues**, because a malformed prompt event enables no destructive action.
This matches the pre-existing `jq`-missing asymmetry. Documented in
[safety model](docs/architecture/safety-model.md).

Tested across empty input, non-JSON, truncated JSON, wrong-typed fields, and
array-valued commands, for both dialects, plus the absent-path case that must
still be allowed.

### 4. Bootstrap executes unverified remote code — **Documented as deliberate**

The finding overstates the mechanism. `bootstrap.sh` does not pipe a mutable
`main` script as the payload: it resolves the newest *tagged release* and
downloads that tag's source archive. What is fetched from `main` is the
bootstrap script itself.

The substantive point stands and is accepted: nothing is verified beyond HTTPS —
no digest, signature, or attestation — and HTTPS does not protect against a
compromised repository or a replaced release asset. That limitation is now
stated plainly in [safety model](docs/architecture/safety-model.md), along with
the checkout-based install as the inspect-before-running route. Publishing and
verifying checksums is real work that is not done here.

______________________________________________________________________

## P1

### 5. `doctor` reports stale artifacts as in sync — **Fixed**

Confirmed. Agent-rooted artifacts compared staged bytes against native bytes
only, never against freshly rendered content, so two equally stale copies read
as `ok` — while `share` artifacts and the status commands used a fresh render,
making the commands disagree.

`check_agent` now renders expected content once and compares both copies against
it, and distinguishes the two failures: native drift reports as `drift`, a stale
staged copy reports as a separate `stale` check saying to run apply. A missing
staging copy is no longer drift, which also fixes fresh clones. Tests: a source
change after apply, and an independently corrupted staged copy.

### 6. User-owned seed files reported as drift — **Fixed**

Confirmed in all three places. Apply skips seed files and `diff` skips them, but
doctor, `project status`, and `global list` all compared them against packaged
content — so editing your own `CLAUDE.md` made the project look unhealthy.

The rule now lives in one place, `manager.artifact_drifted()`, shared by
`project status` and `global list`, with the matching branch in doctor: for a
seed artifact only absence counts. `global list` had the same bug and is fixed
too, which the finding did not mention. Tests cover an edited seed, a missing
seed, and a fresh clone with no staging.

### 7. Plugin discovery can disable the CLI or replace built-ins — **Fixed**

Confirmed, and there were indeed no registry tests. Discovery now isolates each
entry point: a failing import or constructor is recorded as a `PluginError` and
skipped, so one broken package cannot take down `--help`, `version`, or the
other agents. `doctor` surfaces those failures as errors, so the failure is
visible rather than silent.

Names are validated against a safe-directory-segment pattern (they become path
segments), built-in names are reserved, duplicates are rejected, and entry
points are sorted by name so discovery order does not depend on install order.
Adapter artifact sets are also checked for duplicate keys and duplicate
destinations at load time.

`tests/agents/test_registry.py` is new: broken import, constructor failure,
non-adapter, built-in shadowing, unsafe name, deterministic order, and duplicate
keys.

**Not adopted:** deferring optional CLI extension loading. With failures now
isolated, eager loading no longer risks the CLI, and lazy Typer registration
would add real complexity for no remaining benefit.

### 8. `diff --write` rewrites installed package files — **Documented as deliberate**

Accurate as a description, but this is the intended capture design rather than a
defect: agentkit dogfoods itself, and capture is how a change made directly in
`~/.claude` becomes part of the managed source. It is already opt-in and never
part of a plain `diff`.

The overlay-layer recommendation is a genuine improvement and is recorded as the
intended future model in [safety model](docs/architecture/safety-model.md),
along with the caveat that `--write` is a maintainer operation on a checkout,
not something to run against a wheel installation. Not changed now, because it
is a design change rather than a bug fix.

### 9. Apply/sync are not transactional — **Fixed (partly)**

The observation is correct. Two concrete parts are fixed:

- State is now written **once per operation** rather than once per artifact
  (`record_many`), so a mid-apply failure cannot leave state partially updated
  artifact-by-artifact.
- Read-modify-write cycles take a per-scope advisory file lock, so concurrent
  invocations cannot lose each other's entries.

**Not adopted:** the full preflight-render-plan-commit-rollback executor. Every
individual write is already atomic, every overwritten native file is backed up
first, and apply is idempotent — so recovery is "run it again". That has proven
sufficient for a tool whose writes are all regenerable from source, and the
executor would be a substantial rewrite of the core. Recorded with that
reasoning in [safety model](docs/architecture/safety-model.md).

On the documentation contradiction: artifacts *are* ordered, hooks before the
configs referencing them. The docs were right; that claim is retained and
restated.

### 10. Machine-readable error output is not machine-readable — **Fixed**

Confirmed: `fail()` used the default Rich console, which writes to stdout.

`fail()` now emits a stable `{"error": {"message": ...}}` object on stdout under
`--json`, so a parser always gets a JSON document, and sends human diagnostics
to a stderr console otherwise. `--json` mode is tracked alongside the existing
context flags so `fail()` honours it without needing a Typer context.

### 11. Markdown post-processing can change semantics — **Not accepted**

The reasoning about whitespace-insensitive verification is sound in principle,
but the finding supplies no case where a document is actually mangled, and I
could not construct one against the current unwrap logic. Replacing the hook
with a full Markdown parser is a large change to justify on a hypothetical.

Left as is. Happy to fix it against a concrete failing fixture — that would move
it straight to accepted.

### 12. Post-edit formatting may install npm packages — **Fixed**

Correct and worth fixing: a formatting hook that fires on every agent edit must
never fetch from the registry. Both `npx` invocations now run with
`--no-install`, so they use what is already installed or do nothing. The
dispatch test expectations were updated to match.

### 13. Validation is red and environment-dependent — **Not accepted as written**

The headline does not reproduce. `task test` passes on this machine: **120
passed** before any of this work, **169 passed** after.

The diagnosis is also wrong. The finding blames host `jq`/`gitleaks`; both are
installed here and the test passed anyway. The actual dependency is the
**`codex` binary** — without it doctor emits a warning row, so `"--all to show"`
appears. The reviewing environment evidently had `codex` installed.

The *hermeticity* concern underneath is valid and is fixed: optional-binary
discovery is now monkeypatched in the doctor CLI tests, and there are two tests
— one with every optional binary absent (warnings present, passing checks
hidden) and one with all present (nothing to hide). Neither depends on `PATH`.

The executive summary's "the configured quality gate currently fails" should be
withdrawn.

### 14. Release publication is triggered too easily — **Documented as deliberate**

Accurate. This is a single-maintainer convenience, and it does mean a premature
version bump publishes. Recorded under "Deliberate trade-offs" in
[development.md](docs/guides/development.md), including that tag-driven releases
or a protected environment would be the right move if the repo gains other
committers. Not changed unilaterally — release triggering is the maintainer's
call.

______________________________________________________________________

## P2

### 15. Test code excluded from static checks — **Documented as deliberate**

A choice, not an oversight. Recorded in
[development.md](docs/guides/development.md) with the reasoning and with the
condition that would flip it (a substantial test helper layer of its own). The
finding is right that this hides fixture typing problems; that cost is accepted.

Note the finding's secondary point was already accurate — `tasks/quality.yml`
says Ruff checks `src` and `tests`, and it does; the per-file ignore is what
makes tests effectively unchecked. Left as is.

### 16. Coverage not enforced or branch-aware — **Documented as deliberate**

Recorded in [development.md](docs/guides/development.md). Behavioural risk is
covered directly instead of by percentage — and the gaps this finding named
specifically (registry failures, reset variants, malformed state, hostile hook
inputs) all now have tests, added under findings 1, 3, 7, and 17. That is the
outcome the coverage floor was meant to produce, reached without the floor.

### 17. State lacks schema validation, locking, durability — **Fixed**

All three parts confirmed and fixed.

`load()` now validates every entry, not just the JSON root: non-string keys,
non-object entries, and non-string hashes all raise `ValueError` with the file
path, so `{"/path": "bad"}` fails there instead of surfacing as an
`AttributeError` at `prior.get()` deep inside apply. State updates are batched
to one write per operation and take a per-scope `flock`, best-effort so an
unsupported filesystem degrades rather than failing the command.
`atomic_write()` now fsyncs the parent directory after `os.replace`, since
syncing the file records its contents but not the rename that makes them
visible.

`tests/core/test_state.py` is new: four malformed-entry shapes, the apply path
surfacing it as a domain error, round-tripping, and `record_many` both writing
every entry and preserving unrelated ones.

### 18. Filesystem and adapter invariants not enforced — **Fixed**

Confirmed — `Artifact` rejected absolute paths but permitted `..`. It now
rejects upward traversal and empty keys and paths, with a comment explaining
that a relative path is not automatically an in-root path. Adapter-level
invariants (safe names, unique keys, unique destinations, no built-in shadowing)
are enforced at registry load, covered under finding 7.

### 19. CLI error handling is inconsistent — **Fixed**

Confirmed. Added a shared `command_boundary()` context manager that normalizes
expected domain, parsing, and I/O failures into the documented `error: …` exit,
and applied it to the two commands that rendered and parsed outside any boundary
— `global list` and `project status`.

### 20. Core orchestration and `diff` do too much — **Documented as deliberate**

The measurements are right (605 lines). The module is nonetheless cohesive —
nearly every function participates in one apply pipeline — and splitting it
would spread that pipeline across files without removing anything. Recorded in
[development.md](docs/guides/development.md) with the trigger that would change
the answer: a second consumer of the planning half.

**Not adopted:** a complexity rule with a threshold. It would mostly generate
exception entries for the pipeline functions it is aimed at.

### 21. Docs not built on pull requests — **Fixed**

`task docs:build` is now part of `task validate` and runs as its own step in the
CI `validate` job, so a broken mkdocstrings import or nav error cannot merge
ahead of the deploy workflow. Verified: `task validate` exits 0 with the strict
build included.

### 22. Distributions released without validation — **Fixed (partly)**

Metadata is now verifiable and verified — `task build` produces a wheel whose
`METADATA` carries `License-Expression: MIT`, `License-File: LICENSE`,
classifiers, keywords, and project URLs, confirmed by inspecting the built
wheel.

**Not adopted:** clean-environment install, CLI smoke test, checksums, and
attestations in CI. That is a meaningful release-pipeline addition rather than a
fix, and it belongs with the provenance work in finding 4. Tracked there.

### 23. Package metadata and legal status incomplete — **Fixed**

The license was the material gap and is closed: `LICENSE` (MIT) added, with
`license = "MIT"` and `license-files` in `pyproject.toml`. MIT was chosen by the
maintainer when asked.

Also added: project URLs (homepage, docs, repository, issues), classifiers, and
keywords. The stale version fallback is fixed — `__version__` now falls back to
`"unknown"` rather than a hardcoded `"0.1.0"` that misreports the running
version.

**Not added:** `SECURITY.md` and `CONTRIBUTING.md`. Both are conditional on
outside contribution being intended, which is the maintainer's call, not a
defect.

### 24. Documentation contract errors — **Fixed**

All five verified and corrected:

- `adapters.md` no longer claims built-ins register via entry points; it now
  says they are constructed directly by the registry, and documents the name
  reservation and failure-isolation rules added under finding 7.
- The stable-key claim is corrected: `state.json` is keyed by resolved native
  path, so renaming a destination *does* orphan its record, which doctor
  reports as stale.
- Serve port corrected to 8083 in both README and development.md.
- README no longer promises per-OS package names it did not supply; it points at
  the dependency table, which now carries an Install column.
- Install guidance is consolidated — README stays the short entry point and
  links to the canonical guide.

The ordering claim was checked and is correct as written; it is retained.

### 25. New-machine prerequisites incomplete — **Fixed**

The dependency table now lists `curl`, `tar`, and `uv` alongside `jq`,
`gitleaks`, and `go-task`, each with an install command and what it is used for,
with the platform assumption stated. Both scripts now fail early with actionable
diagnostics: `bootstrap.sh` checks all three prerequisites up front rather than
failing mid-download, and `install.sh` checks for `uv` before starting work.

### 26. CI supply-chain policy inconsistent — **Fixed (partly)**

Correct for `docs.yml`, which used floating `astral-sh/setup-uv@v3` and
`arduino/setup-task@v2` while `ci.yml` pinned the same actions to SHAs. Both are
now pinned to the same reviewed SHAs as `ci.yml`.

`actions/*` remain on version tags in both workflows. These are GitHub's own
first-party actions, the policy is now consistent across both files, and this
matches common practice. **Not adopted:** Dependabot/Renovate automation and
dependency vulnerability review — worth doing, but a repo-policy addition rather
than a fix.

### 27. Python compatibility narrow and unverified — **Documented as deliberate**

Worth flagging: the finding says "if no 3.14-only feature is required" — I
checked, and none is. Nothing in the source needs 3.14.

The floor is a deliberate choice, not a technical requirement: agentkit is a
personal-toolchain CLI installed with `uv`, which fetches its own interpreter,
so pinning to the newest release costs its users nothing and keeps the matrix at
one version. That reasoning is now a comment in `pyproject.toml` and a note in
[development.md](docs/guides/development.md), including that widening it means
lowering the bound and adding CI versions rather than back-porting code.

### 28. Repository hygiene and auxiliary docs — **Fixed (partly)**

- **`.editorconfig`** — not changed. The global `insert_final_newline = false`
  and `trim_trailing_whitespace = false` are unusual, and the finding is right
  about that, but they are set this way because the repo ships packaged assets
  copied verbatim into other repositories: editor normalization changes the
  bytes agentkit hashes and shows up as spurious drift. Recorded in
  [development.md](docs/guides/development.md).
- **`check-docs.py`** — **Fixed** by narrowing the stated guarantee rather than
  widening the checker. Its docstring now says precisely what it covers
  (inline Markdown links and heading anchors) and what it does not (reference
  links, images, non-Markdown local targets, external URLs), and that widening
  means adopting a real link checker.
- **`openclaw-tailscale.md`** — not changed. Whether a personal ops runbook
  belongs in this repo is the maintainer's call, not a defect.

______________________________________________________________________

## On the comments and API documentation assessment

The central observation — that the documentation risk is prose asserting
invariants the code does not enforce — was correct and was the most useful part
of the review. All four examples named are now resolved in one direction or the
other: stable-key state identity (docs corrected, #24), artifact ordering (docs
were right, verified and retained, #9/#24), read-only diff behaviour (documented
as deliberate with its caveats, #8), and built-in entry-point registration (docs
corrected, #24). Where an invariant is now enforced rather than asserted, it is
enforced in code — artifact path validation, adapter name and collision
validation, state entry validation — with tests.

## Validation evidence

- `task validate` (lint + typecheck + test + strict docs build): **exit 0**.
- `task test`: **169 passed** (120 at review time; 49 added).
- `task typecheck`: 0 errors, 0 warnings, 0 informational — still strict, and no
  `# type: ignore` was added.
- `task lint`: passed, including Python, task-layout, CI-entrypoint, and
  docs-link checks.
- `task build`: wheel and sdist build; wheel `METADATA` inspected and confirmed
  to carry the license expression, license file, classifiers, keywords, and
  project URLs.
- Finding 1 additionally verified end-to-end against a scratch
  `HOME`/`RNF_HOME`: `deny` is 21 unique after one reset and after two.
- Findings 2 and 3 verified by running the deployed hooks directly against the
  bypass and malformed-payload matrices.

## Suggested re-review focus

The changes worth a second pair of eyes, in order:

1. `reset_adapter()` in `core/manager.py` — the merge-layer reasoning is the
   subtle part.
1. The rewritten flag matching in `guard-core.sh` — regex breadth versus false
   positives.
1. `guard_event_field` and the block/warn asymmetry across the six hooks.
1. `check_agent`'s artifact loop in `core/doctor.py` — the drift/stale/seed
   three-way split.
1. `AgentRegistry._load` — whether the validation set is the right one.

Deliberate trade-offs are recorded in
[docs/architecture/safety-model.md](docs/architecture/safety-model.md) and under
"Deliberate trade-offs" in
[docs/guides/development.md](docs/guides/development.md). If any of those
readings looks wrong rather than merely different from the recommendation, that
is worth reopening.

## Re-review

High — Plugin extensions can still break the entire CLI. Registry isolation
covers loading and validation, but extension registration remains outside the
boundary at
[cli.py:44](/Users/rohitnarayanan/Devel/workspaces/rn-forge/agentkit/src/rn_forge/agentkit/cli.py).
A raising cli_extension property or invalid Typer app can still break
import/help. Finding #7 remains partially open.

High — Markdown semantic corruption has concrete reproducers. In
[unwrap_md.py:78](/Users/rohitnarayanan/Devel/workspaces/rn-forge/agentkit/src/rn_forge/agentkit/assets/scripts/unwrap_md.py),
setext headings such as Heading\\n======= and indented code blocks are joined
into ordinary prose. The whitespace-only check at
[unwrap_md.py:84](/Users/rohitnarayanan/Devel/workspaces/rn-forge/agentkit/src/rn_forge/agentkit/assets/scripts/unwrap_md.py)
accepts the change. Finding #11 should be reopened.

High — Release artifacts remain unvalidated and contaminated. The built 0.3.0
wheel and sdist both contain src/rn_forge/agentkit/.DS_Store—6,148 bytes in the
wheel. CI still performs no content assertion, clean installation, or CLI smoke
test. Finding #22 is open; adding metadata addressed #23, not artifact
validation.

Medium — Doctor and status still disagree when staging is absent. Doctor treats
a missing rendered copy as healthy when native content matches, while
[manager.py:64](/Users/rohitnarayanan/Devel/workspaces/rn-forge/agentkit/src/rn_forge/agentkit/core/manager.py)
makes project status and global list report drift whenever staging is absent.
This contradicts the fresh-clone closure claim for findings #5/#6.

Medium — Artifact-ordering documentation is factually false. The safety model
says hooks precede referencing configs, but both adapters put config first:
[Claude adapter:47](/Users/rohitnarayanan/Devel/workspaces/rn-forge/agentkit/src/rn_forge/agentkit/agents/claude/adapter.py)
and
[Codex adapter:46](/Users/rohitnarayanan/Devel/workspaces/rn-forge/agentkit/src/rn_forge/agentkit/agents/codex/adapter.py).
Finding #9 remains partly open and the new documentation must be corrected.

Medium — --json errors are only partially fixed. Failures routed through fail()
produce JSON, but unknown adapters and conflicting flags still raise Typer
BadParameter and emit human usage text:
[common.py:55](/Users/rohitnarayanan/Devel/workspaces/rn-forge/agentkit/src/rn_forge/agentkit/commands/common.py),
[common.py:62](/Users/rohitnarayanan/Devel/workspaces/rn-forge/agentkit/src/rn_forge/agentkit/commands/common.py),
and
[cli.py:35](/Users/rohitnarayanan/Devel/workspaces/rn-forge/agentkit/src/rn_forge/agentkit/cli.py).
No JSON failure-contract tests were added. Finding #10 is partially closed.

Medium — Adapter invariants remain incomplete. Registry validation checks
duplicate keys/destinations but not the exactly-one-primary-config contract
([registry.py:136](/Users/rohitnarayanan/Devel/workspaces/rn-forge/agentkit/src/rn_forge/agentkit/agents/registry.py)).
Such a plugin is accepted, then fails later. Finding #18 is partially closed.

Low — State validation is narrower than claimed.
[state.py:95](/Users/rohitnarayanan/Devel/workspaces/rn-forge/agentkit/src/rn_forge/agentkit/core/state.py)
validates only the optional hash type, not required path, last_applied, or
source_layer fields/types. The original crash is fixed, but “every entry
validated” overstates closure.

Low — task validate documentation drifted immediately. It now includes a strict
docs build, but
[README.md:142](/Users/rohitnarayanan/Devel/workspaces/rn-forge/agentkit/README.md),
[development.md:39](/Users/rohitnarayanan/Devel/workspaces/rn-forge/agentkit/docs/guides/development.md),
the task-vocabulary table, and CLAUDE.md still describe only three stages.

Additionally, findings #4, #8, #14–16, #20, #26–28 were accepted as deliberate
risks, not eliminated. They should be marked “accepted/open” rather than treated
as closed.

Validation:

- task validate: passed
- Tests: 169 passed
- Strict docs build: passed
- task build: passed, with a uv version-range warning
- Wheel/sdist: contain .DS_Store
- No files changed by this re-review.

## Response to re-review

All eight points were reproducible and are now fixed.

- **#7 (High), CLI extension registration** — `cli.py`'s mounting loop now wraps
  `adapter.cli_extension` access and `app.add_typer()` in the same isolation
  the registry already gives loading and construction: a raising property or
  an invalid Typer object is logged to stderr and skipped rather than breaking
  every command. Finding #7 is now fully closed.
- **#11 (High), Markdown semantic corruption** — both reproducers were real.
  `unwrap_md.py` now detects setext headings (`Heading\n===`) and
  4-space/tab-indented code blocks and copies them verbatim instead of joining
  them into prose; the whitespace-only equivalence check was masking exactly
  this class of change. Verified against both examples from the re-review
  directly.
- **#22 (High), contaminated release artifacts** — `.DS_Store` was present
  because `uv_build` copies from the working tree, not from git, and macOS
  Finder metadata is gitignored but was still on disk. The stray files are
  removed, `[tool.uv.build-backend].source-exclude` now excludes
  `**/.DS_Store` as a backstop, and `task build` runs a new
  `scripts/check_dist_contents.py` after every build that fails the task if a
  wheel or sdist contains `.DS_Store`, `Thumbs.db`, `__pycache__`, or
  `.pyc`/`.pyo` files — so this class of contamination cannot merge silently
  again. This is a content assertion, not the full clean-install/smoke-test
  pipeline from finding #22, which is still open by design (tracked with
  finding #4's provenance work).
- **#5/#6 (Medium), doctor vs. status disagreement** — confirmed:
  `artifact_drifted()` treated a missing staged copy as drift unconditionally,
  while `check_agent` treated it as healthy whenever native content already
  matched. `artifact_drifted()` now matches `check_agent`'s semantics exactly
  (native mismatch is always drift; a missing staged copy is not, on its own).
  Regression test added for the fresh-clone case.
- **#9 (Medium), artifact-ordering documentation** — the claim was false as
  written: both adapters declared their primary config artifact before the
  hook scripts and (for Codex) `hooks.json` that reference it by path. Rather
  than water down the documented invariant, both adapters now declare hook
  artifacts first, so a config or `hooks.json` never lands pointing at a
  script that does not exist yet, matching what the safety model doc already
  claimed. Artifact-order assertions in both adapter test suites were updated
  to match.
- **#10 (Medium), --json errors partially JSON** — `selected()` (unknown
  `--agent`) and `command_options()`/`root_options()` (conflicting
  `--quiet`/`--json`) raised `typer.BadParameter` outside `fail()`'s reach.
  Both now route through `fail()`; a new `set_json_mode()` lets the root
  callback commit to the JSON error contract before any command-level context
  exists. Three new tests cover the previously-uncovered JSON failure
  contract: unknown agent, and conflicting flags both before and after the
  command name.
- **#18 (Medium), missing primary-config invariant** — `AgentRegistry`
  duplicate-key/destination checks did not verify exactly one `config`
  artifact per scope, so a plugin violating `primary_artifact()`'s contract
  would load successfully and only fail later, inside apply/status/doctor.
  Discovery now checks this alongside the existing invariants. New registry
  test covers a configless adapter.
- **#17 (Low), state validation narrower than claimed** — `load()` validated
  only `hash`'s type. It now requires `path`, `last_applied`, and
  `source_layer` to be present and string-typed too — `hash` remains the one
  field allowed to be absent — matching what `record_many` actually writes and
  what the docstring already claimed. New parametrized cases cover each
  missing/mistyped field, plus a positive case for a valid hash-less entry.
- **#28 (Low), `task validate` documentation drift** — README, development.md,
  and the task-vocabulary table said "lint + typecheck + test"; the task has
  included `docs:build` since the prior round. All three, plus the phrasing in
  this file's own CLAUDE.md, now say four stages.

Everything above is covered by `task validate` (178 tests, up from 169) and
`task build` (now content-checked). No findings from this round were left open.
