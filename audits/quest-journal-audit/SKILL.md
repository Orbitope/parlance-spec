---
name: quest-journal-audit
description: Check a quest's journal text against the tense, voice, and knowledge rules the Parlance quest schema states — stage descriptions are RETROSPECTIVE (what the protagonist did), objectives are forward-looking protagonist-voice intentions, and an objective must be gated if the protagonist could not yet name that route. Use after authoring or importing a quest, when journal entries read oddly in playtest, or as a pass before a milestone. The validator cannot check tense or voice; this does.
---

# Quest Journal Audit

Parlance's quest schema is unusually opinionated about journal text, and the rules are
easy to break without breaking validation. Every one of them is stated in
`quest.schema.json` itself — this audit checks the content against the schema's own
prose, not against anyone's taste.

| Field | The schema's rule |
|---|---|
| `stage.description` | "RETROSPECTIVE line — what the protagonist **did**, shown in the journal once this stage is complete. **Not a to-do**." |
| `objective.text` | "Protagonist-voice **INTENTION** line — what the protagonist has decided to do, shown while this stage is current." |
| `objective.showIf` | "Gates on **knowledge and acquaintance** — an objective shows only if the protagonist could actually name that route." |
| `outcome.description` | Names an end-state (`success` / `failure` / `neutral`). |

The failure this audit exists for: a writer fills `stage.description` with a to-do
("Find out who moved the body"), because that is what a quest log looks like in most
games. It validates cleanly. Then in play the journal shows the player a task they
have already finished, phrased as though they had not.

**This audit reports; it never writes.** It flags the field and names which rule it
breaks. It does not draft replacement journal text — not for a tense fix, not for a
one-word change.

## 1. Gather

```bash
python3 - <<'PY'
import json, glob as g, os

# --- project layout, resolved the way the validators resolve it ------------
def _data_dir():
    """Honour parlance.config.json's `data` override (validate.py does)."""
    try:
        return json.load(open("parlance.config.json", encoding="utf-8")).get("data") or "data"
    except Exception:
        return "data"

DATA = _data_dir()

def ents(kind):
    """Every entity file of a kind, RECURSIVELY.

    Dir-mode entities may be nested in zone/chapter subdirs (validate.py globs
    `**` for exactly this). A flat glob silently under-reads, and an under-read
    is indistinguishable from a clean project — the failure this bundle promises
    not to have.
    """
    return sorted(g.glob(os.path.join(DATA, kind, "**", "*.json"), recursive=True))

def load_char(cid):
    """Find a character by ID. The schema does not require filename == id, so
    assuming it either crashes or silently reports zero for a real character."""
    for p in ents("characters"):
        try:
            d = json.load(open(p, encoding="utf-8"))
        except Exception:
            continue
        if d.get("id") == cid:
            return d
    return None

QUEST = None          # <- set to a quest id, or leave None for every quest

for p in ents("quests"):
    q = json.load(open(p))
    if QUEST and q["id"] != QUEST: continue
    print(f"=== {q['id']} — {q.get('name')}")
    print(f"    giver: {q.get('giverId','-')}   summary: {q.get('summary','')}")
    for st in sorted(q.get("stages", []), key=lambda s: s.get("order", 0)):
        print(f"\n  [stage {st.get('order')}] {st['id']}")
        print(f"    description (RETROSPECTIVE): {st.get('description','')!r}")
        print(f"    completeWhen: {json.dumps(st.get('completeWhen')) if st.get('completeWhen') else 'NONE'}")
        for ob in st.get("objectives", []) or []:
            gate = json.dumps(ob["showIf"]) if ob.get("showIf") else "ALWAYS VISIBLE"
            print(f"      - objective {ob['id']}: {ob['text']!r}")
            print(f"        showIf: {gate}")
    for oc in q.get("outcomes", []) or []:
        print(f"\n  [outcome {oc['id']} / {oc['kind']}] {oc.get('description','')!r}")
        print(f"    reachedWhen: {json.dumps(oc.get('reachedWhen')) if oc.get('reachedWhen') else 'NONE'}")
    print()
PY
```

Run the validator first. `QUEST`, `OBJ`, and `FLAG` warnings — stages out of order, a
stage with `completeWhen` and no objectives, every objective gated, an unknown tag —
are mechanical and belong to the validator, not here.

## 2. The checks

**A. Stage descriptions are retrospective.** Each should read as a line in a journal
the protagonist has already written: past tense, completed action, what they *did*.
Flag any that read as a task, an instruction, or an open question. The clearest tells
are an imperative opening ("Find", "Talk to", "Investigate"), a future or modal
construction ("must", "needs to", "should"), and a question mark.

**B. Objectives are intentions, not instructions.** Each should read as something the
protagonist has decided to do, rather than the game telling the player what to do. The
distinction is whose sentence it is — the protagonist's or the game's.

**Grammatical person is NOT the test.** The schema says "protagonist-voice INTENTION
line"; it does not mandate first, second, or third person, and real projects differ:
this repo's own `data/` writes objectives in second person ("Give the gatekeeper a name")
while the demo writes them in first ("I established that Vane was poisoned"). Both are
correct. Flag an objective that reads as a *system instruction* ("Complete the tutorial",
"Collect 5 herbs"), not one that merely uses a person you did not expect. If a project is
internally consistent in its person, that is a house style and there is nothing to report.

**C. Objectives are gated on knowledge the protagonist has.** This is the check that
finds real bugs. For every objective naming a person, place, object, or fact, ask
whether the protagonist could name it at the moment this stage becomes current.

- If they could not, the objective needs a `showIf` gating on the flag that
  establishes it, and one of the two is missing.
- If the objective *has* a `showIf`, confirm the gate actually corresponds to learning
  the thing it names — a gate on an unrelated flag satisfies the validator and still
  shows the player a route they cannot know about.

Trace the flag to whatever sets it before ruling either way. An ungated objective is
correct when the knowledge is guaranteed at that stage.

**D. Stage order reads as a story.** Read the stage descriptions in `order`, alone,
top to bottom. They are what the player sees as the record of what happened, so they
should read as a coherent account. Flag jumps that only make sense if you have also
read the dialogue.

**E. Outcomes name end-states, and their `kind` matches.** A `failure` described as a
partial win, or a `neutral` that reads as a defeat, will mis-colour the journal and
any UI that groups by kind.

## 3. What is not a finding

- Style, rhythm, or word choice in journal text. Out of scope, as everywhere here.
- A terse description. Journals are terse.
- A stage that is mechanically odd — send it to the validator.
- Present-tense narration where the project has clearly chosen present tense
  throughout as a house convention. Check `AUDIT_CONVENTIONS.md` and, if the whole
  project is consistent, report it once as a project-level observation rather than
  once per stage. **A schema rule broken identically everywhere is one finding, not
  forty.**

## 4. Report

1. **Quest and stage count**, and whether the validator is clean.
2. **Findings by check (A–E)**, each as: field path (`quest id / stage id / objective
   id`) → the quoted text → which rule it breaks. Group repeats: if eleven stages are
   all written as to-dos, that is one finding naming eleven paths.
3. **Journal read-through** — the stage descriptions in order, quoted, so the author
   can see what the player sees. This is often more persuasive than any finding.
4. **One-line verdict.**
