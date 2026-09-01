# Safety model

What agentkit's guards and write paths actually promise — and, just as
importantly, what they do not. Several of these are deliberate trade-offs
rather than gaps, and they are recorded here so a future reviewer does not have
to rediscover the reasoning.

## The command and write guards are a speed bump, not a boundary

`pre-bash-guard` and `pre-write-protect` pattern-match a command string or a
path. They do not parse shell grammar, and they are not a security control.

Any determined bypass is trivial — variable indirection, `eval`, base64, a
wrapper script, `$(printf ...)`. Closing that class of hole would need a real
shell parser plus a fail-closed default that rejects anything it cannot
classify, which would block far more legitimate work than it saves.

What the guards *do* cover is the spellings a person or an agent plausibly
reaches for by mistake:

- combined, separated, and long flags — `rm -rf`, `rm -r -f`,
  `rm --recursive --force`, with unrelated flags interleaved;
- executable paths and wrappers — `/bin/rm`, `command rm`;
- Git global options before the subcommand — `git -C . push --force`.

Treat a block as "you probably did not mean that", not as "this was
prevented". The regression matrix in `tests/hooks/test_guard_scripts.py` is the
contract.

## Guards fail closed on their inputs

The pattern matching is advisory; the *input handling* is not. A hook that
cannot understand its own event has no idea what it is being asked to allow, so
it must not allow it.

`guard_event_field` rejects a payload that is not valid JSON, and rejects a
field that is present with a non-string type. On either, the command and write
guards block. An absent or null field is a well-formed event, not an error —
"no path in this event" is allowed.

The prompt-secret guard is the deliberate exception: it warns and continues. A
malformed prompt event enables no destructive action, so blocking the user's
turn would cost more than it protects. The same asymmetry governs a missing
`jq`: the command and write guards block, the prompt guard warns.

## `diff --write` writes into the packaged source

`diff --scope <scope> --write` captures native changes back into the artifact's
packaged source. In a source checkout this edits the working tree; in a wheel
installation it edits environment-managed files, and a later upgrade discards
them.

This is intended — agentkit dogfoods itself, and capture is how a change made
directly in `~/.claude` becomes part of the managed source. But it means
`--write` is a maintainer operation on a checkout, not something to run against
an installed wheel. A separate user-owned overlay layer would be the cleaner
model and is a known future change; until then, `--write` is opt-in, never part
of a plain `diff`.

## Install and release provenance

`bootstrap.sh` is fetched from `main` and resolves the newest tagged release,
then downloads and runs that tag's `install.sh`. The payload is a tagged
archive rather than a moving branch, but nothing is verified beyond HTTPS:
there is no digest check, signature, or attestation.

That is a real limitation, and HTTPS does not protect against a compromised
repository or a replaced release asset. Installing from a checkout
(`./install.sh`) avoids the remote path entirely and is the recommended route
for anyone who wants to inspect before running. Publishing and verifying
checksums is tracked as future work.

## Apply is ordered but not transactional

Artifacts are written in adapter-declared order, and hook scripts are declared
before the configs that reference them, so a config never lands pointing at a
script that does not exist yet.

Apply is not, however, atomic across artifacts: a failure part-way through
leaves earlier native files, staging copies, and state already written. What
mitigates it is that every individual write is atomic, every overwritten native
file is backed up under `backups/<timestamp>/` first, and re-running apply is
idempotent — so recovery is "run it again", not "repair by hand". State is
written once per operation rather than per artifact, and read-modify-write
cycles take a per-scope lock, so a concurrent invocation cannot interleave
entries.

A full preflight-then-commit executor with rollback would be stronger. It is
not implemented, because the backup-and-retry path has proven sufficient for a
tool whose writes are all regenerable from source.
