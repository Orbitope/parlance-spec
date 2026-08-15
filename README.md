# Parlance — narrative format specification

The data format, runtime semantics, and conformance suite for
[Parlance](https://github.com/Orbitope/parlance), a narrative design tool for
branching dialogue, quests, and progression.

**MIT.** Copying this is the intent: an engine port cannot be written without it,
and "engine-agnostic" is not a checkable claim unless anyone may vendor the
conformance vectors and run them.

## Status

**Empty until Parlance tags v0.9.0.** A spec repository pinned to an untagged
version gives a port nothing to pin to, which is the whole point of publishing.
Contents arrive via the one-way `sync-spec` publication from the upstream repo.

## What will live here

| Path | What it is |
|---|---|
| `schema/` | JSON Schema for every entity — the shape of the format |
| `conformance/` | Executable vectors any port must pass. Where prose and vectors disagree, the vectors win |
| `validate/` | The standalone reference validator (Python) |
| `docs/` | Runtime contract, integration guide, naming standards, versioning policy, migrations |

## Using it

Pin an exact tag — never a branch, never a range — and vendor the conformance
vectors at that tag. Moving the pin is a deliberate act with a re-run of your
suite, not a dependency bump. `docs/INTEGRATION.md` describes the mechanism.

Pre-1.0: breaking changes may land in any minor release, and there is no
deprecation window. `docs/VERSIONING.md` is the promise; read it before pinning.

## Contributing

Issues welcome. **Pull requests are not accepted here** — this repository is a
one-way publication from a private upstream, so a change merged here would be
overwritten by the next sync. File an issue and it will be fixed at the source.
