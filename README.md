# Parlance — narrative format specification

The data format, runtime semantics, and conformance suite for
[Parlance](https://github.com/Orbitope/parlance), a narrative design tool for
branching dialogue, quests, and progression.

**MIT.** Copying this is the intent: an engine port cannot be written without it,
and "engine-agnostic" is not a checkable claim unless anyone may vendor the
conformance vectors and run them.

## Status

Published through **v0.15.0**. Each release is a tag here, synced one way from the
upstream repository by `sync-spec`; `PUBLICATION.json` names the upstream commit the
current contents came from, and [`CHANGELOG.md`](CHANGELOG.md) says what each release
changed and what a port must do about it.

## Contents

| Path | What it is |
|---|---|
| `schema/` | JSON Schema for every entity — the shape of the format |
| `conformance/` | Executable vectors any port must pass. Where prose and vectors disagree, the vectors win |
| `validate/` | The standalone reference validator (Python) |
| `docs/` | Runtime contract, integration guide, naming standards, versioning policy, migrations |
| `audits/` | Review-only editorial audit skills to run against a project |
| `importers/` | Format importers (Claude skills) with worked examples |
| `PUBLISHED_SKILLS.md` | What the audits and importers have in common |
| `CHANGELOG.md` | One entry per release, newest first |

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
