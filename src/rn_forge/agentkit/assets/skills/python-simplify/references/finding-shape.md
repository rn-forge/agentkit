# Finding and phase shape

## Why the shape matters

The plan is read by a session that was not present for the review. Everything it
needs to execute without a design decision has to be on the page. The two fields
that get dropped and shouldn't are **behaviour class** (with its argument) and
**the rejected alternative** — the first is what makes the phase safe, the
second is what stops the next session from undoing the reasoning.

## Per-finding template

```markdown
**<id> — <one-line claim, stated as a fact about the code>. (<open|done YYYY-MM-DD>)**

<What is there today, with numbers: file, line count, how many times the thing
repeats. Then why it is hard to read — the specific comprehension cost, not
"it's messy".>

<The fix, concrete. Code sketch if the shape isn't obvious from a sentence.>

<Behaviour: preserving, and the argument for it — or the exact observable
delta, named.>

<The rejected alternative and why. Also the wrong fix a reader might reach
for.>

<Tests: which suite proves it, or which assertions change.>
```

The id and the status live on that first line because they are what the rest of
the workflow matches on: `--fix <id>` finds the finding by it, and execute mode
flips `open` to `done <date>` there and nowhere else. An id belongs to a finding
for life — a re-run carries it forward unchanged rather than renumbering, so the
same handle keeps working across reviews.

## Worked example

> **B1 — split the artifact decision from the artifact construction.**
> `_artifact_result()` takes eight parameters, three of them booleans computed
> at the call site, and constructs `CheckResult` five times where each branch
> differs only in two literals. The precedence rule its docstring describes —
> unwritable beats drift beats stale beats absence — is buried under the
> repeated fields.
>
> Replace with a pure classifier returning just the outcome:
>
> ```python
> def _artifact_status(
>     native: Path, *, exists: bool, differs: bool, stale: bool, rendered_exists: bool
> ) -> tuple[Status, Severity]:
>     if not _parent_writable(native):
>         return "unwritable", "error"
>     if differs:
>         return "drift", "warning"
>     ...
> ```
>
> plus a single `CheckResult(...)` at the call site. `_seed_result()` folds into
> the same shape and stops being a separate function. Keep the existing
> rationale comments — the reason a seed file is never content-compared —
> attached to the branches they explain.
>
> Preserving: the classifier returns the same `(status, severity)` pair for
> every input the branches covered, and the call site sets the other three
> fields exactly as each branch did. `tests/core/test_doctor.py` passes
> unchanged.

Note what it does: exact numbers, the buried rule named, the code shape given,
the folded-in second function called out, an instruction to preserve comments,
and the preservation argument spelled out rather than asserted.

## Per-phase template

```markdown
### Phase <letter> — <what a reader gets out of it, not what you do>

<Behaviour class in the first sentence. Current size → target size.>

<Findings, as above.>

<What NOT to do in this phase, if there's an obvious over-reach.>

Docs to update in <letter>: <files, and what specifically changes in them>.
```

Phase titles state the outcome — "make `core/doctor.py` readable", "make the
previewer agree with the merge it describes" — not the activity ("refactor
doctor").

## The out-of-scope subsection

Ends every review. Two lists, both one line per module:

- **Park** — reviewed, has findings, deliberately not doing them now, *with the
  reason*. "The merge engine is the one place where a subtle change is
  expensive and the current code is correct" is a reason. "Later" is not.
- **Fine** — reviewed, needs nothing. This list is short to write and is what
  makes the next run cheap.

A third list appears on a re-run: **carried forward** — findings a prior review
already marked `done`, with their id and date. They are not re-derived and not
re-proposed; they are there so the document reads as the whole history rather
than as today's slice of it.

Also record here anything you found and deliberately deferred *within* a phase —
a known wart with a known fix that isn't worth the blast radius today. Say it is
deferred, not overlooked; the difference matters to whoever reads it next.
