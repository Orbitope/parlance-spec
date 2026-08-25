# Validator conformance cases

Shared fixtures both validators must agree on: the TypeScript one the editor
runs (`editor/core/src/validator.ts`) and the Python reference one CI runs
(`tooling/validate.py`).

The two are separate implementations of one rule set, and they drift — quietly,
because nothing compared them. A rule that silently stops firing looks exactly
like a project with no defects. These cases pin the behavior from both sides:

- `editor/core/test/conformanceValidator.test.ts` (vitest) runs them against the
  TypeScript validator.
- `tooling/tests/test_conformance.py` (pytest) runs them against the Python one.

## Layout

```
cases/<case-name>/
  project/        a complete, minimal project root (data/…)
  expected.json   what the validators must say about it
```

Every case is the same clean base project with **one** seeded defect (or none,
for `clean-minimal`), so a failure names the rule directly.

## expected.json

```json
{
  "noErrors": true,
  "must":    [{ "code": "REF", "contains": "n_typo" }],
  "mustNot": [{ "code": "ENDING" }]
}
```

- `noErrors` — the validator emits zero error-severity issues.
- `must` — at least one issue with that `code`, whose message contains
  `contains` and whose severity equals `severity`, when either is given.
  **State the severity.** It is part of the contract, not decoration: an error
  fails CI and a warning does not, so a rule quietly demoted to a warning
  changes what ships while a code-only assertion stays green. A mutation probe
  confirmed exactly that — demoting the reserved-`end` rule passed the entire
  suite until severity was asserted here.
- `mustNot` — no issue matches (same fields, same matching rule).
- `validators` — which implementations the case applies to, e.g.
  `["python"]`. Both when absent. Only for rules that genuinely live at
  different layers in the two: duplicate-id detection, for instance, happens in
  the loader on the TypeScript side, because `validate()` there is handed an
  id-keyed project in which duplicates have already collapsed.

Codes are the shared vocabulary: `CHECK`, `CODEX`, `COVERAGE`, `CUT`, `DUP`,
`ENDING`, `FLAG`, `FLOW`, `GATE`, `LADDER`, `LOC`, `LOGIC`, `LORE`, `OBJ`,
`PORT`, `PROG`, `QUEST`, `REACH`, `REF`, `REL`, `REP`, `ROUTE`, `RULES`,
`SCHEMA`, `SNAP`, `TEXT`, `XP`. When the two validators disagree on a code
today, the TypeScript one is the target — the editor is where an author sees
the message.

An uncovered family is not "probably fine". Every family here had a case added
only after an audit found it unpinned, and writing those cases turned up three
live drifts in one pass (spawnless exit targets, unwalked snapshot state, an
XP advisory keyed on its own message text). Keep the coverage total.

## Known open drifts

Two cases pass on both sides while the implementations still disagree about
something the assertions do not name. Both are TypeScript-side, so they are
recorded here rather than papered over with a `validators` key:

- `duplicate-node-id` — the TypeScript validator keys nodes into a `Map`
  (last wins) before walking reachability, so it also reports the *first*
  node's successor unreachable. The runtime resolves a node with `nodes.find`
  (first wins), which is what the Python validator models. Only reachable in
  data that already fails on the `DUP` error.
- `project-rules-bad-dice` — the Python validator JSON-Schema-checks
  `rules.json` and `progression.json`; the TypeScript one has no zod schema for
  either, so a malformed singleton is a `SCHEMA` error in CI and silent in the
  editor.

## Adding a case

Run `python3 tooling/conformance/validator/build_cases.py` to regenerate the
`project/` trees from the base project defined in that script; it writes
canonically serialized JSON, so `npm run normalize -- --check` stays green.
Add the case's seed function there and its `expected.json` alongside.
