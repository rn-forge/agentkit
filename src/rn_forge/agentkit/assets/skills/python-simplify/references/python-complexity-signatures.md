# Complexity signatures in model-written Python

What to look for, and — as important — what looks like a finding and isn't.

Model-written Python has a characteristic profile. It is rarely *bad* code: it
is idiomatic, typed, docstringed, and locally clean. It scores well on every
complexity metric because each function is short. The debt is in the
**arrangement** — the same decision expressed in several places, generality
nobody asked for, and defenses against states that cannot occur. That is why
this review reads modules rather than trusting `radon`.

The bias throughout: **more modules is not the problem; complex modules are.**
Splitting is cheap and reversible, and duplication that a reader can see beats
an abstraction they have to reconstruct. Prefer the fix that leaves fewer things
to hold in your head, not the one that leaves fewer lines.

Each signature below gives the tell, the fix, and the trap.

______________________________________________________________________

## A. Duplication across siblings

### A1. Identical method bodies in every subclass

Two or three implementations of an ABC where a method body is byte-identical, or
identical except for one literal. The base declares it `@abstractmethod`, so the
type checker is satisfied and nothing flags it.

**Fix.** Lift the body to the base. Where bodies differ by one value, that value
becomes a **class attribute**, not a hook method:

```python
class Adapter:
    _dump_mode: Literal["json", "python"] = "json"   # TOML has native date types;
                                                     # JSON mode would stringify them.
    def render(self, cfg: dict[str, Any]) -> str:
        return self._engine.render(self.schema().model_validate(cfg)
                                   .model_dump(mode=self._dump_mode))
```

**Trap.** Do not replace the duplication with a `_dump()` hook for subclasses to
override — that is the same duplication with an extra indirection. And when the
difference is load-bearing for a reason no test exercises, write the reason next
to the attribute or someone "simplifies" the two modes into one.

### A2. A hand-rolled reimplementation of a utility the repo already has

One subclass forwards to a shared helper; its sibling reimplements the helper's
logic inline, usually with a bespoke error message. Both are correct, which is
why neither was flagged.

**Fix.** Delete both overrides; make the base call the shared helper.

**Trap.** Check the exception *types* line up, not just the behaviour — callers
may catch `ValueError` and the reimplementation may raise something else. Check
whether any test asserts on the bespoke message string; if none does, the
message change is free and should be stated as the one observable delta.

### A3. The same concept implemented twice for two input forms

`parse_file(path)` dispatches on extension while `parse_text(s, suffix)`
dispatches on a passed suffix, with divergent logic. Two halves of one concept,
implemented two different ways.

**Fix.** Route both through one dispatcher.

### A4. The same loop with different nouns

Two scans over different roots that differ only in a root path, a label, and a
message string. Common in validators, orphan scans, and report builders.

**Fix.** One function taking the varying parts as arguments. **Preserve output
ordering** — it is often asserted on, and often only incidentally.

______________________________________________________________________

## B. Repetition within a module

### B1. Constructing the same record N times, differing in two literals

A dataclass built in five branches where each branch sets the same five fields
and only two differ. The *decision* — the precedence rule the branches encode —
is buried under the repeated fields, and the rule is what a reader came for.

**Fix.** Split the decision from the construction. A pure classifier returns
just the varying part; one construction at the call site.

```python
def _status(...) -> tuple[Status, Severity]:
    if not writable: return "unwritable", "error"
    if differs:      return "drift", "warning"
    if stale:        return "stale", "warning"
    return "ok", "info"
```

The precedence is now readable top to bottom. Keep the rationale comments
attached to the branches they explain, not stranded at the top.

### B2. A field that is derivable from another in almost every case

`severity` set to the same value for a given `status` in nine of eleven
constructions. The two real exceptions are invisible among the fifteen identical
literals.

**Fix.** A module-level `_DEFAULT: dict[Status, Severity]` table and a default
in `__post_init__`. The value is that the exceptions become visible *as*
exceptions. (On a frozen dataclass this needs `object.__setattr__`; that is
acceptable for one line sitting next to the table it reads.)

**Trap.** Confirm the field is still populated on every instance if it is part
of a serialization contract (`--json` output, an API response).

### B3. Repeated literal dicts / if-elif ladders over a closed set

A mapping written as control flow. Six branches returning six constants.

**Fix.** A module-level table. If the set is closed and typed, a `Literal` or
`Enum` plus a dict gives you exhaustiveness checking for free under a strict
type checker.

______________________________________________________________________

## C. Generality nobody asked for

### C1. An abstraction with exactly one implementation

An ABC, `Protocol`, factory, or registry with one concrete member and no plugin
story. Models reach for extension points by default.

**Fix.** Inline it. **Trap.** Check for a *documented* extension story first —
third-party adapters, a plugin entry point, an internal consumer in a sibling
repo. If the extension point is real, the abstraction is earning its keep even
at one in-tree implementation, and this is a park, not a finding.

### C2. Boolean-trap helpers

Six-to-eight parameters, three of them booleans computed at the single call
site. The caller reads as `f(p, True, False, True)` and the helper's body is a
truth table.

**Fix.** Usually the same split as B1 — the booleans are the *inputs to a
decision* that wants to be its own function.

### C3. Defensive code for states that cannot occur

`if x is None` where `x` is non-optional and the type checker agrees.
`try/except` around a call that does not raise. `or {}` on a value the
constructor guarantees. A validation re-run on data already validated upstream.

**Fix.** Delete it. **Trap.** Prove the state is unreachable rather than
assuming it — a `# type: ignore`, an untyped boundary, `**kwargs` passthrough,
or a public API entry point can all make the impossible reachable. If the guard
is the only thing standing between a user and a traceback, keep it. When you
delete one, say in the plan why the state cannot occur.

### C4. Configuration parameters with one caller and one value

A `timeout=`/`strict=`/`encoding=` threaded through four layers, always passed
the default. **Fix.** Remove the parameter; keep the constant at the bottom.

### C5. Premature packaging

A directory of three 40-line modules that import only each other and are only
imported as a unit, where one module would read better — or the inverse, a
900-line module doing five unrelated jobs.

**Fix.** Whichever direction restores "one file I can read in one sitting". Say
explicitly when you are *not* splitting something and why: a package adds a
directory, and it should only do so when it adds a boundary.

### C6. A constructor that takes seven collaborators

Seven-plus injected dependencies on one class. The tell is often read as a
dependency-injection problem and "fixed" by introducing a container or a
service-locator; it is not. Arity here is a **count of responsibilities** — the
class needs all seven because it is doing four jobs.

**Fix.** Split the class using the "reason to change" test below. Each resulting
unit's constructor then shrinks on its own, without new machinery. **Trap.** A
dataclass or a settings object that holds seven *values* is fine — this
signature is about seven *collaborators*.

### The "reason to change" test

C5 and C6 both turn on whether one unit is really two, and "it feels big" does
not survive review. Make it checkable: **list every change that could require
editing this module.** If the list draws from different domains — CLI argument
shapes *and* merge semantics *and* on-disk format — it is two modules. If every
item traces to the same domain concern, the module is the size its problem is,
however long it reads.

Write the list into the finding. A reader who disagrees with the split can then
disagree with something specific.

______________________________________________________________________

## D. Hot paths hiding in plain sight

Not performance tuning — these are cases where the *inefficient* version is also
the harder one to reason about, because it obscures when state is read.

### D1. A full load/parse/validate inside a loop

A `store.get()` that parses and validates an entire file, called once per item
in a loop over hundreds of items, for data that cannot change during the loop.

**Fix.** Hoist the load above the loop into a local; index it. Behaviour-
identical, and it makes the "nothing writes until the end" invariant visible.

**Tell.** Writes are already batched but reads are not — batching one and not
the other is the fingerprint of an optimization applied where the profiler
pointed rather than where the pattern was.

### D2. Per-item lock-read-write cycles

`remove()` called once per file, each call taking a lock, reading the whole
file, and rewriting it. **Fix.** Mirror the existing batch API (`remove_many`
next to `record_many`).

______________________________________________________________________

## E. Correctness gaps that read as complexity

The highest-value findings this review produces. Two implementations of one rule
that have drifted — not a bug anyone reported, because both look right.

### E1. A simulation that no longer matches the thing it simulates

A "what would happen if" function (a diff previewer, a dry-run path, a plan
renderer) that reimplements the real engine's logic rather than calling it, and
has since diverged. Typical: the previewer models a merge as per-key overwrite
while the real merger honours append/extend strategies, so the preview
under-reports.

**Fix.** Feed the previewer the real engine's parameters, or call the engine.
Represent the distinction **structurally** in the data (`appends: bool`), not by
encoding it into a display string — `--json` consumers need the fact, and the
rendering stays a rendering choice.

**This is behaviour-changing and it is the point.** The changed assertion is the
deliverable. Say so in the plan.

### E2. A warning with no remedy

A check reports a condition that nothing in the tool can fix, so it accumulates
forever. Worse than no warning: it trains users to ignore the report.

**Fix.** Either make something clear the condition, or stop reporting it. Prefer
having the paths that *create* the condition clean up after themselves.
**Trap.** Do not give a read-only command (a doctor, a status, a lint) the
ability to mutate — that breaks a contract users rely on.

### E3. An error message that states the problem and not the recovery

Especially on a strict-parse failure that takes down every command at once.
**Fix.** One sentence naming the recovery. Update the message assertions.

______________________________________________________________________

## F. Comprehension, not structure

### F1. Design rationale in a docstring

A module docstring that is three paragraphs of *why*. It is good writing in the
wrong place: docstrings are read by API consumers and rendered into reference
docs, where an essay dilutes the reference.

**Fix.** Move it to the architecture docs and leave a four-line docstring plus a
pointer. Keep definitional docstrings (what each value of a `Literal` means) —
that is reference, not rationale.

### F2. Comments restating the code

`# increment the counter` above `count += 1`. Delete. **Trap.** A comment that
restates the code but is attached to a *non-obvious ordering or precedence* is
often the only record of that constraint — read before deleting.

### F3. Redundant function-level imports

An import inside a function that is already imported at module scope, with no
cycle to break. Dead line; delete. If it *does* break a cycle, the cycle is the
finding.

### F4. Docstrings that lie about the contract

`Raises: ValueError` on a function that now raises a custom exception — check
whether the custom one subclasses it before "fixing" either side. Follow the
repo rule: when docs claim X and code does Y, determine which is wrong before
changing anything, and prefer narrowing the doc unless something concretely
breaks without X.

______________________________________________________________________

## G. Tests that make refactoring expensive

Findings about the suite, because the suite is the refactor's contract.

### G1. Positional indexing into unordered results

`results[0]` to mean "the config one". Breaks on any unrelated reordering, and
then has to be fixed blind. **Fix.** Select by key/name.

### G2. Assertions on incidental formatting

Byte-exact output assertions are fine and valuable **when the output is a
contract**; they are the thing that makes a presentation refactor safe. They are
a liability when they pin whitespace nobody promised. Distinguish the two, and
in the plan name which output is contractual.

### G3. Tests that reach past the public surface

A test importing a private helper pins an implementation detail as an API. Often
the reason a module cannot be reorganized.

### G4. Thin coverage under a module you plan to refactor

Not a defect in the code — but it means "the suite is the contract" does not
hold there, and a characterization test becomes step 1 of that phase.

______________________________________________________________________

## What is not a finding

- A documented deliberate trade-off. Read `CLAUDE.md`/`AGENTS.md` first.
- Deliberate silence — a swallowed fsync error, a skipped broken plugin — where
  the reasoning is recorded. Check the architecture docs before "hardening".
- Duplication of *two* short lines. Three occurrences of a real concept is a
  pattern; two occurrences of `x = x.strip()` is not.
- A high cyclomatic-complexity score on a parser, a dispatcher, or a state
  machine whose branches are the domain.
- Long, explicit code that is simply doing several things in order. Length is
  not complexity; indirection is.
- Style a formatter or linter already governs.
- Anything you would fix by adding a dependency. Out of scope.

______________________________________________________________________

## When the rule points the other way

The list above suppresses false positives. These are the inverse: cases where a
rule this skill leans on is *wrong for the module in front of you*, and
following it mechanically produces a bad plan. Each is a legitimate finding —
name the rule you are overriding, and why.

- **Two copies, not three, but they have already diverged.** The rule of three
  says wait. Ignore it when the copies have drifted *incorrectly* — one was
  fixed and the other was not. Divergence that produced a bug is evidence the
  abstraction is real. Extract now, and make step 1 a test that exercises the
  shared behaviour, so the extraction has a contract before it has a caller.
- **Duplication is preferred, except where the copies must agree.** "Simple
  duplication beats a clever abstraction" holds for code that merely *looks*
  alike. It does not hold where the copies encode one fact that must stay
  consistent — a wire format, a precedence order, a set of enum members
  mirrored in a dispatch table. There, the copies are a correctness hazard,
  not a readability one, and this is a `changes-output` finding rather than a
  cosmetic one.
- **The abstraction has one implementation, and that is correct.** C1 says
  inline it. Do not, when a *documented* extension story exists (see C1's
  trap) — but also do not when the single implementation exists to keep an
  untestable boundary (clock, filesystem, network, subprocess) swappable in
  tests. A seam that the suite actually uses is load-bearing; check the tests
  before calling it speculative generality.
- **Splitting is right, but the split is the whole cost.** C5/C6 point at a
  module that is really two. Park it anyway when the split changes signatures
  across most callers for a comprehension gain alone — that is a park with a
  reason, not a finding you failed to file. Say which callers, so a later
  session can price it without re-deriving the list.
- **Composition is the default, and it has gone too far.** Where the fix is
  "compose instead of inherit", keep it 2–3 levels deep. A chain of wrapper
  objects that must be traced in order to answer "what runs?" has traded a
  shallow inheritance problem for a deeper indirection one. A `Protocol` plus
  plain functions is usually the smaller move.
