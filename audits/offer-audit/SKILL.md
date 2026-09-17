---
name: offer-audit
description: Intent audit for a Parlance character's dialogue offers. Use when reviewing the dialogues that OFFER for a character to check whether SALIENCY resolution (priority tier, then condition specificity, then id) tells the intended story — not whether it is mechanically valid. Runs after the validator is clean. Traces, for each offer, when it first wins and when it stops winning, then compares that sequence to the character's stated arc. Trigger when a character has more than ~4 offers, after a change to a character's arc, or as an editorial pass over a cast.
---

# Offer Audit

A character's dialogues each **self-declare** candidacy with an `offer` object; at runtime
`resolveCharacterDialogue` gathers the character's eligible offers and plays the **most
salient** — highest priority tier, then highest condition specificity, then lowest id. The
validator already catches *mechanical* faults — no fallback (resolution can return nothing),
a prioritized fallback that shadows every lower tier forever, an unbreakable tie, an
offer-only stranded dialogue, dangling ids. This audit does what static checks cannot: judge
whether the **saliency resolution tells the intended story**.

**This audit reports; it never writes.** It does not edit `data/`, and it never drafts or
rewrites a line of dialogue. Findings name structural fixes — retune a gate, add or drop a
priority tier, add an offer, clear a flag — and stop there.

## When to use

- A character has grown past ~4 competing offers and the resolution is hard to trace by eye.
- After a change to a character's arc (a new betrayal path, a reordered quest).
- As an editorial pass over a cast or a story chain.

Do **not** use this to catch dangling ids or missing fallbacks — the validator owns those,
and feeding this audit an unvalidated project wastes it on mechanical noise. Run
`python tooling/validate.py` (or the editor's validation panel) first.

## 1. Gather — never trace saliency by eye

Run this from the project root for the character under audit. It collects every dialogue
that offers for the character, prints them **in saliency order** (priority tier, then
condition specificity, then id), and, for every piece of state an `offer.when` reads,
everything in the project that writes it.

Offers print with their id and their saliency key `(tier, specificity)`. **The first line
printed is the most salient — the one that wins when every gate is eligible.** Say
"`d_betrayed` (tier 0, spec 1)" rather than "the second offer", because the id and the key
are what the validator's warnings and the resolution preview use. That writer map is the
audit's raw material: you cannot say when an offer first wins without knowing when its gate
can first be true.

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

def specificity(c):
    """Mirror runtime.conditionSpecificity: leaf 1, all sum, any MIN, not operand,
    absent 0. This is what breaks ties after the priority tier."""
    if not isinstance(c, dict): return 0
    t = c.get("type")
    if t == "all": return sum(specificity(s) for s in c.get("of", []))
    if t == "any":
        of = c.get("of", [])
        return min((specificity(s) for s in of), default=0)
    if t == "not": return specificity(c.get("of"))
    return 1

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
        # active_dialogue__{character}, read by a forced (tier-1) offer (see
        # tooling/validate.py's flags_written for the same rule). Missing this
        # made the audit announce, in capitals, that the format's own routing
        # flag is written by nothing — in a project that writes it thirteen times.
        elif t == "set_active_dialogue":
            key = f"flag:active_dialogue__{o['character']}=True"
        if key: writers.setdefault(key, []).append(f"{os.path.basename(p)}{path}")
    # quest outcomes are reached by condition, not written by an effect
    if "outcomes" in doc:
        for oc in doc.get("outcomes", []):
            writers.setdefault(f"questOutcome:{doc['id']}:{oc['id']}", []).append(
                f"{os.path.basename(p)} outcome reachedWhen")

# --- collect the character's offers, sorted the way the runtime ranks them ---
char_name = None
offers = []
for p in ents("characters"):
    try: d = json.load(open(p, encoding="utf-8"))
    except Exception: continue
    if d.get("id") == CHAR: char_name = d.get("name")
for p in ents("dialogues"):
    try: d = json.load(open(p, encoding="utf-8"))
    except Exception: continue
    offer = d.get("offer")
    if not isinstance(offer, dict): continue
    if (offer.get("character") or d.get("speakerId")) != CHAR: continue
    offers.append((d["id"], offer))

if not offers:
    raise SystemExit(f"no dialogue offers for {CHAR!r} — check the id, not the filename")

# saliency order: priority tier desc, specificity desc, id asc
offers.sort(key=lambda t: (-(t[1].get("priority") or 0), -specificity(t[1].get("when")), t[0]))

print(f"{CHAR} — {char_name}\n")
for did, offer in offers:
    when = offer.get("when")
    tier = offer.get("priority") or 0
    spec = specificity(when) if when else 0
    print(f"{did}   (tier {tier}, spec {spec})")
    print(f"     when: {json.dumps(when) if when else 'NONE (fallback — offered whenever nothing more salient is eligible)'}")
    for k in sorted(reads(when)) if when else []:
        w = writers.get(k) or []
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

Then get a one-line **stance gloss** per offer — what that dialogue *is* emotionally
(`cold, won't engage` / `warm recap` / `recruits you`). Read the entry node of each; you do
not need the full text, only enough to judge stance.

## 2. The anchor: the intended arc

You cannot judge a resolution against an unstated intent. Before tracing, get the author's
**intended arc** in one to three sentences — how this character is meant to evolve across
the game ("wary stranger → ally → betrayed, then hostile").

**If no arc is stated, the audit's entire output is: state the arc first.** Stop there. Do
not infer an arc from the offers and then judge the offers against it — that reasoning is
circular and will confidently ratify whatever resolution already exists.

If the project has an `AUDIT_CONVENTIONS.md`, read it now. A character listed under
`## Unresolvable` has deliberate ambiguity: any finding of yours that would *resolve* it is
not a finding, and you flag your own recommendation instead of making it.

## 3. Per-offer lifespan trace

For **each offer**, in saliency order, state precisely:

- **First wins when** — the earliest world state in which this offer is the most salient
  eligible one: its `when` true, and every offer that would outrank it (higher tier, or same
  tier and higher specificity, or same key and lower id) ineligible. Use the writer map to
  know when its gate can actually first be set.
- **Stops winning when** — the world change that makes a *more salient* offer eligible, or
  makes its own `when` false. If nothing ever does, say **"wins forever from first win."**
- **Reachable at all?** — if a more salient offer is always eligible by the time this one's
  `when` could become true, it never wins. The validator catches the blunt version (an
  unbreakable tie); saliency intent creates subtler ones it cannot see.

## 4. Compare the lifespan sequence to the arc

Lay the spans in timeline order and check they trace the stated arc. Look for:

- **Salience inversions** — an offer that should dominate is *less* salient than one that
  shadows it in overlapping states. The classic: a betrayal offer at the same tier and
  specificity as a quest-chatter offer, where the quest flag is still true after the
  betrayal, so the id decides and the betrayal stance never reliably lands. The fix is a
  priority tier or a more specific `when`, not a reorder — order does not exist here.
- **Premature or delayed stances** — a stance that wins earlier or later than the arc wants
  (the "warm ally" offer winning before the quest that was supposed to earn it).
- **Orphaned stances** — an offer whose gate is never set by anything reachable, or is set so
  early or late that the intended beat never lands in play.
- **Missing transitions** — the arc calls for a stance no offer covers, so the character
  jumps from warm to hostile with nothing in between.
- **Narrative permanence** — an offer that wins forever where the arc implies it should later
  give way. Distinct from the mechanical prioritized-fallback check: here it is about the
  story, not about a tier-1 gate re-firing.

## 5. Report

In this order:

1. **Arc restatement** — one line, or `NO STATED ARC — provide one` and stop.
2. **Lifespan table** — one row per offer: `dialogue id | tier/spec | first wins when |
   stops winning when | stance gloss`. This is the backbone; it makes the resolution legible
   even before any findings.
3. **Findings** — real issues only, each as *what is wrong* → *the play-experience symptom*
   → *the structural fix*. No praise, no filler. If the resolution is sound, say so in one
   line and stop.

## Rules

- **Trace, don't vibe.** Every finding cites specific offers and the states where the problem
  manifests. "This feels off" is not a finding. "After `flag_x` is set, `d_quest` still wins
  over `d_betrayed` because they tie on (tier 0, spec 1) and `d_betrayed`'s id sorts later"
  is.
- **Mechanical faults are out of scope.** Note them in one line and defer to the validator.
- **Shallow gates are the design discipline.** An `offer.when` is meant to be simple —
  usually one flag — with the priority tier carrying any "this dominates that" logic. If you
  need deep condition reasoning to trace an offer, *that is itself the finding*: the offer is
  over-clever.
- **The fix is usually a tier or one added offer**, not new machinery. Prefer the smallest
  change that makes the lifespan sequence match the arc.
- **You advise; the author decides.** A "wins forever" offer may be an intended one-way door.
  Flag and ask rather than asserting it is wrong.
- **Never propose dialogue text.** "Add a cooling-off offer between the ally and hostile
  stances" is the finding. What that dialogue says is the author's business.

## Example finding (shape to match)

> **Salience tie — `d_qm_active_quest` and `d_qm_betrayed` are indistinguishable.**
> Both offer for `char_qm` at tier 0 with a single-leaf `when` (spec 1): `d_qm_active_quest`
> reads `quest_open`, `d_qm_betrayed` reads `betrayed_qm`. `quest_open` is set by
> `q_supply_run` stage 2 and is *not* cleared on betrayal; `betrayed_qm` is set by
> `d_warehouse_confront`. **Symptom:** after the player betrays him, walking up plays
> neutral quest chatter every time, because both gates are true, the two offers tie, and
> the lower id wins — `d_qm_active_quest` sorts before `d_qm_betrayed` — so the betrayal
> stance never lands. **Fix:** raise `d_qm_betrayed`'s `offer.priority` to 1, or clear
> `quest_open` in the betrayal effect so the offers stop overlapping.
