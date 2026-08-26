---
name: ladder-audit
description: Intent audit for a Parlance character's dialogue ladder. Use when reviewing a character's ordered `dialogues` list to check whether the ORDERING tells the intended story — not whether it is mechanically valid. Runs after the validator is clean. Traces, for each rung, when it first wins and when it stops winning, then compares that sequence to the character's stated arc. Trigger when a ladder has grown past ~4 rungs, after a change to a character's arc, or as an editorial pass over a cast.
---

# Ladder Audit

A character's `dialogues` ladder is an **ordered list**; at runtime the game plays the first
rung whose `showIf` is true. The validator already catches *mechanical* faults — dead rungs
below an unconditional one, a top rung with effects that re-fires forever, a last rung with a
`showIf` and so no fallthrough, dangling ids. This audit does what static checks cannot:
judge whether the **ordering tells the intended story**.

**This audit reports; it never writes.** It does not edit `data/`, and it never drafts or
rewrites a line of dialogue. Findings name structural fixes — reorder a rung, change a gate,
add a rung, clear a flag — and stop there.

## When to use

- A ladder has grown past ~4 rungs and the ordering is hard to trace by eye.
- After a change to a character's arc (a new betrayal path, a reordered quest).
- As an editorial pass over a cast or a story chain.

Do **not** use this to catch dangling ids or dead rungs — the validator owns those, and
feeding this audit an unvalidated ladder wastes it on mechanical noise. Run
`python tooling/validate.py` (or the editor's validation panel) first.

## 1. Gather — never trace a ladder by eye

Run this from the project root for the character under audit. It prints the ladder in
priority order and, for every piece of state a rung reads, everything in the project that
writes it.

Rungs print as `[0]`, `[1]`, `[2]` — the character's `dialogues` index, which is also
priority order: **`[0]` is the top of the ladder and the first one tested**, and the
first whose `showIf` passes wins. Say `[2]` rather than "the third rung" throughout,
because that is what the gather prints and what the validator's `dialogues[2]` warnings
say. "Above" always means a LOWER index. That writer map is the audit's raw material: you cannot say when a rung first
wins without knowing when its gate can first be true.

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

CHAR = "char_id_here"          # <- the character under audit

def walk(o, path=""):
    if isinstance(o, dict):
        yield path, o
        for k, v in o.items(): yield from walk(v, f"{path}.{k}")
    elif isinstance(o, list):
        for i, v in enumerate(o): yield from walk(v, f"{path}[{i}]")

def reads(c, acc=None):
    acc = set() if acc is None else acc
    if not isinstance(c, dict): return acc
    t = c.get("type")
    if   t == "flag":         acc.add(f"flag:{c['flag']}={c['value']}")
    elif t == "counter":      acc.add(f"counter:{c['counter']}")
    elif t == "quest":        acc.add(f"quest:{c['quest']}")
    elif t == "questOutcome": acc.add(f"questOutcome:{c['quest']}:{c['outcome']}")
    elif t == "reputation":   acc.add(f"reputation:{c['faction']}")
    elif t == "relationship": acc.add(f"relationship:{c['character']}")
    elif t == "item":         acc.add(f"item:{c['item']}")
    elif t == "skill":        acc.add(f"skill:{c['skill']}")
    elif t in ("all", "any"):
        for s in c.get("of", []): reads(s, acc)
    elif t == "not":          reads(c.get("of"), acc)
    return acc

# --- who writes what, anywhere in the project ---
writers = {}
for p in sorted(g.glob(os.path.join(DATA, "**", "*.json"), recursive=True)):
    try: doc = json.load(open(p))
    except Exception: continue
    for path, o in walk(doc):
        t = o.get("type") if isinstance(o, dict) else None
        key = None
        if   t == "set_flag":           key = f"flag:{o['flag']}={o['value']}"
        elif t == "adjust_counter":     key = f"counter:{o['counter']}"
        elif t == "advance_quest":      key = f"quest:{o['quest']}"
        elif t == "adjust_reputation":  key = f"reputation:{o['faction']}"
        elif t == "adjust_relationship":key = f"relationship:{o['character']}"
        elif t in ("give_item","take_item"): key = f"item:{o['item']}"
        # set_active_dialogue does NOT name a dialogue at runtime: it sets
        # active_dialogue__{character}, and the character's own ladder resolves
        # from there (see tooling/validate.py's flags_written for the same rule).
        # Missing this made the audit announce, in capitals, that the format's
        # own routing flag is written by nothing — on the protagonist's ladder,
        # in a project that writes it thirteen times.
        elif t == "set_active_dialogue":
            key = f"flag:active_dialogue__{o['character']}=True"
        if key: writers.setdefault(key, []).append(f"{os.path.basename(p)}{path}")
    # quest outcomes are reached by condition, not written by an effect
    if "outcomes" in doc:
        for oc in doc.get("outcomes", []):
            writers.setdefault(f"questOutcome:{doc['id']}:{oc['id']}", []).append(
                f"{os.path.basename(p)} outcome reachedWhen")

ch = load_char(CHAR)
if ch is None:
    raise SystemExit(f"no character with id {CHAR!r} — check the id, not the filename")
print(f"{ch['id']} — {ch.get('name')}   style: {ch.get('dialogueStyle','(none declared)')}\n")
for i, rung in enumerate(ch.get("dialogues") or []):
    gate = rung.get("showIf")
    print(f"[{i}] {rung['dialogue']}")
    print(f"     showIf: {json.dumps(gate) if gate else 'NONE (unconditional fallthrough)'}")
    for k in sorted(reads(gate)) if gate else []:
        w = writers.get(k) or []
        # A `=False` read asks "what CLEARS this?". Falling back to the `=True`
        # writer answered with the thing that closes the gate forever and did not
        # say so — inverting the semantics of the audit's own "narrative
        # permanence" finding. Report the asymmetry instead.
        opposite = []
        if not w and k.endswith("=False"):
            opposite = writers.get(k[:-len("=False")] + "=True") or []
        print(f"     reads {k}")
        for src in w[:6]: print(f"        written by  {src}")
        if not w and opposite:
            print(f"        never set false — only ever set TRUE, by {len(opposite)} site(s):")
            for src in opposite[:3]: print(f"           {src}")
            print( "        so once it flips, this gate never reopens (is that the intent?)")
        elif not w:
            print( "        written by  *** NOTHING — this gate can never open ***")
        if len(w) > 6: print(f"        ... and {len(w)-6} more")
    print()
PY
```

Then get a one-line **stance gloss** per rung — what that dialogue *is* emotionally
(`cold, won't engage` / `warm recap` / `recruits you`). Read the entry node of each; you do
not need the full text, only enough to judge stance.

## 2. The anchor: the intended arc

You cannot judge an ordering against an unstated intent. Before tracing, get the author's
**intended arc** in one to three sentences — how this character is meant to evolve across
the game ("wary stranger → ally → betrayed, then hostile").

**If no arc is stated, the audit's entire output is: state the arc first.** Stop there. Do
not infer an arc from the ladder and then judge the ladder against it — that reasoning is
circular and will confidently ratify whatever ordering already exists.

If the project has an `AUDIT_CONVENTIONS.md`, read it now. A character listed under
`## Unresolvable` has deliberate ambiguity: any finding of yours that would *resolve* it is
not a finding, and you flag your own recommendation instead of making it.

## 3. Per-rung lifespan trace

For **each rung**, top to bottom, state precisely:

- **First wins when** — the earliest world state in which this rung is the first passing
  rung: its condition true AND every rung above it false. Use the writer map to know when
  its gate can actually first be set.
- **Stops winning when** — the world change that makes a rung *above* it win, or makes its
  own condition false. If nothing ever does, say **"wins forever from first win."**
- **Reachable at all?** — if some rung above it is always true by the time this rung's
  condition could become true, it never wins. The validator catches the blunt version of
  this; ordering intent creates subtler ones it cannot see.

## 4. Compare the lifespan sequence to the arc

Lay the spans in timeline order and check they trace the stated arc. Look for:

- **Priority inversions** — a rung that should dominate sits below one that shadows it in
  overlapping states. The classic: a betrayal rung ordered *below* a quest-chatter rung,
  where the quest flag is still true after the betrayal, so the betrayal stance never lands.
  Technically valid, narratively wrong — this is the failure the audit exists for.
- **Premature or delayed stances** — a stance that wins earlier or later than the arc wants
  (the "warm ally" rung winning before the quest that was supposed to earn it).
- **Orphaned stances** — a rung whose gate is never set by anything reachable, or is set so
  early or late that the intended beat never lands in play.
- **Missing transitions** — the arc calls for a stance the ladder has no rung for, so the
  character jumps from warm to hostile with nothing in between.
- **Narrative permanence** — a rung that wins forever where the arc implies it should later
  give way. Distinct from the mechanical stuck-rung check: here it is about the story, not
  about effects re-firing.

## 5. Report

In this order:

1. **Arc restatement** — one line, or `NO STATED ARC — provide one` and stop.
2. **Lifespan table** — one row per rung: `dialogue id | first wins when | stops winning
   when | stance gloss`. This is the backbone; it makes the ordering legible even before
   any findings.
3. **Findings** — real issues only, each as *what is wrong* → *the play-experience symptom*
   → *the structural fix*. No praise, no filler. If the ladder is sound, say so in one line
   and stop.

## Rules

- **Trace, don't vibe.** Every finding cites specific rungs and the states where the problem
  manifests. "This feels off" is not a finding. "After `flag_x` is set, `[0]` still wins
  because it sits above `[2]`, whose gate is also true" is.
- **Mechanical faults are out of scope.** Note them in one line and defer to the validator.
- **Shallow gates are the design discipline.** Ladder conditions are meant to be simple —
  usually one flag — with priority carrying the logic. If you need deep condition reasoning
  to trace a rung, *that is itself the finding*: the ladder is over-clever.
- **The fix is usually a reorder or one added rung**, not new machinery. Prefer the smallest
  change that makes the lifespan sequence match the arc.
- **You advise; the author decides.** A "wins forever" rung may be an intended one-way door.
  Flag and ask rather than asserting it is wrong.
- **Never propose dialogue text.** "Add a cooling-off rung between 2 and 3" is the finding.
  What that rung says is the author's business.

## Example finding (shape to match)

> **Priority inversion — `[0]` shadows `[2]`.**
> `[0]` `d_qm_quest_active` (`showIf quest_open`) sits above `[2]` `d_qm_betrayed`
> (`showIf betrayed_qm`). `quest_open` is set by `q_supply_run` stage 2 and is *not* cleared
> on betrayal; `betrayed_qm` is set by `d_warehouse_confront`. **Symptom:** after the player
> betrays him, walking up still plays neutral quest chatter, because both gates are true and
> the quest rung is tested first — the betrayal stance never lands. **Fix:** move
> `d_qm_betrayed` above `d_qm_quest_active`, or clear `quest_open` in the betrayal effect.
