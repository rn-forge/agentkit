# Complexity review — 2026-09-02

## 1. Origin and scope

A whole-tree sweep of the area `docs/specs/initial.md` §15.6 explicitly did not
cover — `commands/`, `core/operations/`, `agents/base.py`, and
`agents/registry.py` — because most of it (the `commands/` package specifically)
did not exist until phase 5C (§14.3) built it.

Not swept: `core/doctor.py`, `core/state.py`, `core/config.py`, `core/io.py`,
`core/render.py`, `core/paths.py`, `core/artifacts.py`, `core/diff.py`, and
`cli.py`. Those are §15's territory (phase 6), which is designed and not yet
implemented; re-reviewing them before that lands would produce findings that
contradict a plan already agreed.

Radon flags four hot spots in scope: `RootCommand.diff` (D, 25),
`core/operations/apply.apply_resolved` (D, 21), `ProjectCommand.status` (C, 18),
and `SelfCommand.uninstall` (C, 16). Reading them shows the debt is the same
shape in each case: a helper that already exists once in this codebase was
written a second or third time instead of shared, at the two points (§14.2's
`core/operations` split and §14.3's command-object split) where the natural home
for a shared helper changed out from under the code.

## 2. Behaviour summary

**Every finding here is `preserving`.** Each phase ends with `tests/` passing
unchanged — a test needing a changed assertion means the refactor changed
behaviour; stop and report rather than editing the assertion.

## 3. Ground rules

**One phase, one commit, one green gate.** A → B → C → D, each ending at
`task format && task validate` clean and independently revertable. None depends
on another; the order is by how mechanical the extraction is, cheapest first, so
the suite stays proven green longest before the riskiest phase (D).

**The existing conventions still apply.** No positional indexing into
`artifacts()` or operation-result lists (select by `.key` / `.artifact`); no new
`# type: ignore`; `task` remains the only entrypoint; `pyright src` stays at
zero errors in strict mode.

**Docs move with the code.** `docs/reference/python-api.md` lists modules
explicitly; a new private helper does not need an entry, but a module whose
public surface changes does.

## 4. Phase A — collapse the repeated `OperationResult` outcome ladders

*Behaviour contract: the test suite passes unchanged; a test that needs a
changed assertion is a signal the refactor changed behaviour — stop and report
rather than updating the assertion.*

### A1 — three call sites hand-roll the same four-way remove outcome. (open)

`ProjectCommand.remove` (`commands/project_command.py:256-278`) and
`SelfCommand.uninstall` (`commands/self_command.py:274-297` for the share root,
`299-316` for the install directory) each hand-roll the same four-way outcome —
`already absent` / `dry-run` / `removed` (after a confirm prompt, or `yes`) /
`kept — not confirmed` — ending in an identical
`OperationResult(..., "remove", ...)` construction. Three call sites, same
shape, differing only in the target path, the confirmation prompt text, and the
`(agent, key)` pair on the result.

Add to `BaseCommand` (`commands/base.py`, alongside
`boundary`/`emit_operations`, since both callers already extend it):

```python
def remove_confirmed(
    self, target: Path, *, agent: str, key: str, yes: bool, dry_run: bool, prompt: str
) -> OperationResult:
    """Ask, then remove a directory, reporting one of four outcomes.

    Shared by every "remove an entire owned directory" step (project's working
    data, the global share root, the install directory) so the confirm/dry-run/
    already-absent logic exists once.
    """
    if not target.is_dir():
        removed, message = False, "already absent"
    elif dry_run:
        removed, message = True, "dry-run"
    elif yes or typer.confirm(prompt):
        removed, message = True, "removed"
        shutil.rmtree(target)
    else:
        removed, message = False, "kept — not confirmed"
    return OperationResult(agent, key, "remove", removed, target, target, message=message)
```

`SelfCommand.uninstall`'s install-directory branch is not a straight call: it
also removes `bin_link` and treats "either the directory or the symlink exists"
as present. Leave that branch as its own code — forcing it through
`remove_confirmed` would grow the helper's signature to cover a case it does not
otherwise have. The two directory-only removals (project's `data_root`,
`uninstall`'s `share_root`) are the ones this finding moves; the install-link
removal stays as it is, with a comment noting why it wasn't folded in.

**Rejected alternative:** a free function in `core/operations/remove.py` instead
of a `BaseCommand` method. Rejected because the three call sites are all in
`commands/`, the confirmation prompt is presentation (it calls `typer.confirm`),
and `core/operations` functions do not call into Typer anywhere else — keeping
it a `BaseCommand` method matches that boundary.

Tests: `tests/commands/test_cli.py` already asserts the four outcomes for both
call sites; this finding's proof is that those assertions pass unchanged.

### A2 — `core/operations/remove.py` builds the same result seven times. (open)

`strip_native_hooks` (`core/operations/remove.py:62-124`) returns
`OperationResult(adapter.name, artifact.key, "strip-hooks", ...)` four times,
differing only in `changed`, `message`, and whether `backup_path` is set;
`remove_owned_artifacts` (`129-202`) does the same three times with `"remove"`.
Seven eight-argument constructions where the first five arguments are always
identical within a function, which is ~40 lines of the module's 214 and buries
the four decisions the function is actually making.

The early-return-per-outcome control flow is right and stays. Only the
construction moves — a local closure at the top of each function, after `native`
and `artifact` are known:

```python
def outcome(changed: bool, message: str, backup: Path | None = None) -> OperationResult:
    return OperationResult(
        adapter.name, artifact.key, "strip-hooks", changed, native, native,
        backup_path=backup, message=message,
    )
```

so each return reads `return outcome(False, "no native config")` and the branch
condition is the whole line.

**Rejected alternative:** a module-level shared builder across both functions.
Rejected because they differ in `action` and in what varies (`remove_owned_
artifacts` builds inside a loop over artifacts, so `artifact` and `native` are
not stable across calls) — the closure captures exactly what is stable in each,
which a shared function would have to take as parameters, giving back the arity
this is meant to remove.

**Not a finding here:** the drift check that leaves a modified file in place is
duplicated logic-shaped, but it is the same drift-safety contract
`capture_assets` documents and it reads correctly where it is.

Tests: `tests/core/test_manager.py` and the uninstall paths in
`tests/commands/test_cli.py` assert each of the seven messages; all pass
unchanged.

## 5. Phase B — one artifact-drift-row helper

*Behaviour contract: as phase A.*

### B1 — two commands rebuild the same positional drift tuple. (open)

`GlobalCommand.list` (`commands/global_command.py:92-104`) and
`ProjectCommand.status` (`commands/project_command.py:153-165`) independently
build the same list comprehension: for every artifact, a
`(artifact, native_path, rendered_or_native_path, expected_hash)` tuple, used
both to compute "is everything rendered" (`artifact.seed_only` filtered) and "is
everything in sync" (via `artifact_drifted(*entry)`). The tuple is positional
and gets re-destructured at each use site
(`for artifact, _, rendered, _ in paths`), which is exactly the kind of
unnamed-tuple indexing the rest of this codebase's conventions avoid for
`OperationResult` and `artifacts()`.

Add a small frozen dataclass and a builder function to
`core/operations/apply.py` (next to `artifact_drifted`, which every caller of
the new helper also calls):

```python
@dataclass(frozen=True, slots=True)
class ArtifactDriftRow:
    artifact: Artifact
    native: Path
    rendered: Path
    expected_hash: str


def artifact_drift_rows(
    adapter: AgentAdapter, scope: Scope, repo_root: Path, scope_dir: Path, merged: MergeResult
) -> list[ArtifactDriftRow]:
    rows: list[ArtifactDriftRow] = []
    for artifact in adapter.artifacts(scope):
        native = adapter.native_path(scope, repo_root, artifact)
        rows.append(
            ArtifactDriftRow(
                artifact,
                native,
                managed_copy_path(adapter, scope_dir, scope, artifact, native),
                content_hash(adapter.render_artifact(artifact, merged.config, scope)),
            )
        )
    return rows
```

Note `managed_copy_path` — `core/operations/result.py:29-38` is already exactly
the `native if artifact.root == "share" else adapter.rendered_path(...)` branch
both command sites inline by hand. This finding calls it rather than writing the
branch a third time, which is also why the builder is a loop and not a
comprehension: `native` is needed twice.

`artifact_drifted` keeps its four positional parameters — it is called from
`apply.py` itself with values that were never tupled, and giving it an
`ArtifactDriftRow` parameter instead would make that internal caller build a
dataclass just to unpack it back out. Only the two command-layer call sites
change; update `artifact_drifted(*entry)` to
`artifact_drifted(row.artifact, row.native, row.rendered, row.expected_hash)` at
both.

Tests: none need new assertions — same reasoning as phase A.

## 6. Phase C — share the backup-then-write step in `core/operations/apply.py`

*Behaviour contract: as phase A.*

### C1 — `apply_resolved` and `sync_adapter` duplicate the native-write block. (open)

`apply_resolved` (D, 21) and `sync_adapter` (C, 14) are two different pipelines
— apply renders and writes to both `rendered/` and the native path; sync only
copies an already-rendered file to the native path — but the inner block each
uses to write the *native* path is identical: compute whether a backup is needed
(`native.is_file() and current_hash != digest`, guarded by
`prior is None or prior.get("hash") != current_hash`), take it, then either
`atomic_write` or `os.chmod` depending on whether content or only mode changed.

Extract that block, and only that block, as a private helper in the same module:

```python
def _write_native(
    native: Path, content: bytes, digest: str, current_hash: str | None,
    mode: int | None, mode_changed: bool, store: StateStore, root: Path,
) -> Path | None:
    """Back up and (re)write one native file; return the backup path taken, if any."""
    backup = None
    if native.is_file() and current_hash != digest:
        prior = store.get(native)
        if prior is None or prior.get("hash") != current_hash:
            backup = backup_file(native, root)
    if current_hash != digest:
        atomic_write(native, content, mode=mode)
    elif mode_changed:
        os.chmod(native, 0o755)
    return backup
```

**Rejected alternative:** merging `apply_resolved` and `sync_adapter` into one
function parameterized by "also write rendered/ first". Rejected because the
result would be a function whose middle third is an `if` no reader needs once
they know which of the two operations they're looking at — the two functions
read, today, as two different pipelines that happen to share one step, which is
the honest shape. Only the shared step moves.

`apply_resolved` additionally needs `drifted = prior is not None` for its result
message, which `_write_native` does not have (it only returns the backup path).
Compute `drifted` at the call site from the same `store.get(native)` lookup
`_write_native` will redo internally — an extra `StateStore.get` call per
artifact, which is an in-memory dict lookup after `StateStore.load()` caches it,
not a second file read. Do not thread `drifted` out through the helper's return
value for one caller's benefit.

Tests: none need new assertions.

## 7. Phase D — extract `RootCommand.diff`'s record builder

*Behaviour contract: as phase A.*

### D1 — `RootCommand.diff` mixes three capture paths with record construction. (open)

`RootCommand.diff` (`commands/root_command.py:196-307`, complexity D/25) does
five things in one function body: parse overrides, optionally capture (config,
assets, defaults — three different write paths, each conditionally run), run
`resolve_config` and the per-artifact diff loop, and assemble a six-key nested
dict per adapter for `--json`/table output. This is the same "construction mixed
with decision logic" pattern §15.2 (B1, B4) already fixes in `core/doctor.py:
check_agent` — `diff()` just didn't exist as a `RootCommand` method yet when
that plan was written.

Extract the per-adapter body of the `for adapter in self.selected(agent):` loop
(lines 213-295) into a private method:

```python
def _diff_record(
    self, adapter: AgentAdapter, scope: Scope, root: Path, overrides: dict[str, Any],
    *, write: bool, promote_defaults: bool,
) -> dict[str, Any]:
    """Capture (if asked), resolve, diff every artifact, and shape one adapter's record."""
```

with the same body, returning the dict that today gets `records.append(...)`'d.
`diff()` itself becomes: build `overrides`, loop calling `_diff_record`, compute
`drift = any(...)`, emit. The `except (OSError, ValueError)` boundary stays
around the loop in `diff()`, not inside `_diff_record` — `self.fail()` calls
`raise typer.Exit`, which must unwind out of the loop, not just one call to the
helper.

**Rejected alternative:** splitting the three capture paths out as well, into
their own method. Rejected for now because they are already three
one-line-guarded calls into `core/operations/capture`; moving them buys a
shorter `_diff_record` and costs a second hop for a reader following what
`--write` does. Revisit if a fourth capture path appears.

Tests: `tests/commands/test_cli.py` diff assertions check the emitted records
and table/JSON output, which are unchanged by moving where the dict is built.

## 8. Verdicts

Every module in scope, one line each.

| Module | Verdict |
|---|---|
| `commands/__init__.py` | fine — re-export surface, 7 lines |
| `commands/base.py` | act (A1) — gains `remove_confirmed`; nothing wrong with what is there today |
| `commands/global_command.py` | act (B1) — one of the two duplicated drift-tuple call sites |
| `commands/project_command.py` | act (A1, B1) — the four-way remove outcome and the drift tuple |
| `commands/root_command.py` | act (D1) — `diff()` only; the rest of the module's methods are A/B complexity and read fine |
| `commands/self_command.py` | act (A1) — the share-root removal; the install-link branch stays as it is |
| `core/operations/__init__.py` | fine — re-export surface, 29 lines |
| `core/operations/apply.py` | act (B1, C1) |
| `core/operations/capture.py` | park — see §9 |
| `core/operations/init.py` | fine — two functions, one guard each, no duplication |
| `core/operations/remove.py` | act (A2) — the result ladders; `_prune_empty_dirs` and the drift check are correct as written |
| `core/operations/result.py` | fine — six small single-purpose helpers; `managed_copy_path` is the one B1 should have been calling all along |
| `agents/base.py` | fine — see §9 |
| `agents/registry.py` | fine — read in full, needs nothing |

## 9. Park list and non-findings

`core/operations/capture._capture_updates` (C, 18) was read in full: it is a
recursive structural-diff over nested dicts and append-only lists, with removal
detection, and every branch is doing genuinely different work (missing key, new
key, unchanged, nested dict, append-list suffix, plain replace). It is already
the shape a recursive diff has to be; splitting it would produce several
functions that only make sense read together, which is worse than one function
read top to bottom with its docstring. **Parked as correct** — revisit only if a
seventh case arrives.

`core/operations/capture.capture_adapter` / `capture_assets` /
`capture_defaults` share an `OperationResult`-construction pattern but are
parked rather than merged: each has a different validation-and-raise shape (one
raises on unsupported removals, two report "unwritable" instead of raising), and
forcing a shared builder across three different error-handling policies is
over-abstraction, not simplification. This is the line A2 stays on the right
side of — there, the three-to-four constructions being collapsed sit inside one
function with one error policy.

`agents/base.py`'s complexity numbers are all A/B because it is genuinely 30-odd
small single-purpose methods, which is the target shape §14.1/§15.1 were written
to produce, not a finding against it.

Ruff's `B008` (25 hits) is the `typer.Option(...)`-as-default idiom Typer
requires; `TRY003` (36 hits) is `raise ValueError(f"...")` with an inline
message, which is house style throughout this codebase already. Neither is a
finding.

## 10. Carried forward

None — this is the first review in this directory. Prior refactor phases 1–6
live in `docs/specs/initial.md` §12, §14, and §15 and were read as input, not
re-derived here.
