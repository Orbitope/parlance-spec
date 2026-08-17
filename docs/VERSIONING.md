# Versioning & stability policy

What changes, what breaks, and what you can rely on. This ships with the published
spec, so it is a promise to adopters — not an internal note.

## What "the contract" means

Three things, versioned together as one unit:

1. **`schema/`** — the shape of every entity file.
2. **Runtime semantics** — [`RUNTIME_CONTRACT.md`](RUNTIME_CONTRACT.md): what the data
   *means* when executed (condition evaluation, effect application, check resolution,
   dialogue stepping, quest resolution, RNG).
3. **`tooling/conformance/`** — the executable definition of #2. If the vectors and the
   prose disagree, **the vectors win**.

Anything else — the editor, its UI, the host API, the MCP server — is not the contract
and carries no compatibility promise to third parties.

## Current status: pre-1.0. Nothing is LTS.

**No release before `1.0.0` is long-term supported, and none will be designated so
retroactively.** Concretely, during 0.x:

- **Breaking contract changes may land in any minor release.** Required fields may be
  added or removed, enum values may change, runtime semantics may be corrected.
- **There is no deprecation window.** A wrong default gets fixed, not carried.
- **There are no backports.** Fixes land on the current release only.
- **Ports must pin an exact tag** (`v0.9.0`, never a range or a branch) and vendor the
  conformance vectors at that tag — the mechanism described in
  [`INTEGRATION.md`](INTEGRATION.md). Moving the pin is a deliberate act with a
  re-run of your suite, not a dependency bump.

This is a deliberate trade, not neglect. The format currently carries modelling
inherited from its first project (see "Known contract debt" below), and fixing that is
cheap now and expensive after 1.0. Freezing early would mean carrying someone else's
game vocabulary forever.

Every breaking change ships with a migration note in the release; the conformance
vectors are the ground truth for what actually changed.

## Known contract debt (to be resolved before 1.0)

Tracked because these are *breaking* fixes and therefore gated by this policy:

**Vocabulary debt: cleared.** The items tracked here — a required project-taxonomy field
on `character`, a closed `gateType` enum on location exits, a hardcoded quest tag
vocabulary, a required `cluster` on `skill`, and a magic `sp_main` spawn id baked into
the published validator — were resolved in one batched break. See `MIGRATIONS.md` for the
before/after and the upgrade recipe.

A lint in Parlance's own CI guards against new debt of this kind: project-specific
vocabulary in an enum value or a required field fails the build. Its limits are worth
stating — it caught neither of the last two items, which hid in a *required field* and a
*string literal* rather than in prose. Reading still finds what a denylist cannot.

**Modelling debt: outstanding.** Breaking fixes too, and deliberately not batched with the
vocabulary work, because each needs design rather than a rename:

| Item | Why it is debt | Cost of deferring |
|---|---|---|
| `choice.goto` and `variable.default` are reserved words | `goto` is a keyword in C# and Java; `default` in those plus JavaScript. A port cannot name a field either one, so both need attribute mapping (`[JsonPropertyName("goto")]`) rather than a plain binding. Parlance rejected `class` for exactly this reason when naming `archetype`. | Friction, not breakage — every port pays a small annotation cost forever. Renaming reaches every choice in every dialogue and every conformance vector, so it wants its own release. |

Restated here rather than left in internal planning because this file is the promise
adopters read, and a debt list that says "none outstanding" while items are open is worse
than no list at all.

An audit of all 150 property names against the five languages ports are written in
(TypeScript, Python, C#, Java, GDScript) found only the two above; the rest are clear.

## Reaching 1.0

1.0 is earned, not scheduled. All of the following must hold:

- [ ] **Contract debt cleared** — no project-specific vocabulary in any normative
      position (enum values, required field names).
- [ ] **Dogfooded on a real, finished project** — a complete game's narrative authored
      and shipped on the format, not placeholder content.
- [ ] **At least one independent engine port passing the full conformance suite**, built
      by someone reading only the published spec.
- [ ] **Two consecutive minor releases with no breaking contract change** — evidence the
      shape has settled.
- [ ] **Every conformance file has a runner** in at least two implementations, so
      "passing" means the same thing twice.

## After 1.0

- **Semantic versioning on the contract.** Breaking changes require a major bump.
- **Deprecation window:** a field or behaviour marked deprecated in `X.Y` keeps working
  until at least the next major, with the replacement documented at deprecation time.
- **LTS designation** becomes possible: a specific major line nominated for extended
  support, with security and correctness fixes backported for a stated period. No line
  is LTS until it is announced as such, in writing, with dates.
- **Additive-only minors:** new optional fields and new effect/condition types may land
  in a minor; existing data stays valid.

## Version numbers you will see

The contract version is the repository release tag (`vX.Y.Z`) — the same tag that
versions the editor. The published spec repo mirrors those tags exactly, so
"pinned to `v0.9.0`" is unambiguous across both repos.
