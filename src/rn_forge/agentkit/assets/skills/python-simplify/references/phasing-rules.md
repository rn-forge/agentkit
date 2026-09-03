# Phasing rules

## Order by behaviour risk, not dependency

```
preserving  →  changes-output  →  adds-surface
```

The reason is evidence, not tidiness. Preserving phases end with the suite green
and unchanged, which *proves* the refactor was safe. Run them first and every
later phase starts from a known-good baseline. Run them after an output-changing
phase and a failure is ambiguous.

Within the preserving group, order by what later phases depend on — a phase that
collapses an interface should land before one that reorganizes its callers.

In a web app the chain gains a fourth link — `changes-contract`, for anything a
client you do not control can see — and it goes last. See the behaviour-class
section of `web-framework-signatures.md`; a green suite does not discharge one
of those.

## One phase, one commit, one green gate

Each phase must be independently revertable and must end at the repo's own full
validation command (`task validate`, `make check`, `nox`, whatever §1 found). A
phase that cannot be described in one commit message is two phases.

## The behaviour contract sentence

Every phase states its class in its first sentence. Preserving phases carry this
rule **verbatim**:

> The test suite passes unchanged. A test that needs a *changed assertion* is a
> signal that the refactor changed behaviour — stop and report it rather than
> updating the assertion.

This is the load-bearing sentence of the whole document. Without it, an
executing session hits a red test, adjusts the assertion to match the new
behaviour, and gets a green gate on a silently-changed program. With it, the
suite is a real contract.

For output-changing phases, invert it explicitly: name which assertions change
and state that *the changed assertion is the deliverable*. A phase that changes
output without naming its test updates in advance will have them written to
match whatever the code now does, which proves nothing.

## Cap the plan

Five phases is a plan. Twelve is a wish list abandoned at phase three. If you
have twelve findings-worth of work, the bottom seven are a park list — and the
park list is a better artifact than seven phases nobody runs.

Prefer one phase per module or per coherent concern. Phases that touch six files
across four concerns cannot be reverted usefully.

## Re-state the surviving conventions

The executing session should not have to re-derive the repo's rules. Copy the
ones the refactor could violate into the plan's ground rules: typing strictness,
the single command entrypoint, test conventions (no positional indexing into
result lists), docs that must move with a module rename, no new dependencies.

## Say what the phase must not become

Refactor phases attract scope. Pre-empt the obvious over-reach in the phase
itself: "do not split this into a package — after these four changes it is one
coherent module at a size that reads in one sitting, and a package would add a
directory without adding a boundary." One sentence there saves an argument
later, and saves a session from doing the larger thing on its own initiative.

## No new features

No new flags, output modes, commands, or dependencies inside a
behaviour-preserving phase — the value of the exercise depends on being able to
say afterwards that nothing about the tool's behaviour changed. If the review
turned up a genuinely missing capability, it is its own phase at the end, or its
own piece of work entirely.
