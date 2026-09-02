---
name: cookbook-conformance-audit
description: Conformance audit for the Parlance pattern cookbook. Use when a project leans on the common narrative-logic recipes (say-it-once, skip-the-setup, one-shot option, hub-and-spoke) and you want to know whether each use trips the recipe's documented pitfall. Runs after the validator is clean. Finds the mechanically-detectable-but-unvalidated mistakes: an effect on a skippable node that silently never fires, a one-shot choice that never spends itself, a say-it-once flag set on a branch the player can miss. Reports; never writes.
---

# Cookbook Conformance Audit

`tooling/COOKBOOK.md` is eighteen recipes for the narrative-logic problems every project
hits — say-it-once, skip-the-setup, one-shot option, hub-and-spoke, and the rest. Each
recipe carries a **Pitfalls** section: the small, specific way the arrangement goes wrong.
Some of those pitfalls are *mechanical* — visible in the data, not in the author's head —
but the validator does not catch them, because the broken version is still valid JSON with
valid types and valid references. It plays; it just does the wrong thing.

This audit finds those. It is anchored on the cookbook itself: every finding names the
recipe, quotes its pitfall, and points at the site in your data that trips it.

**This audit reports; it never writes.** It does not edit `data/`, and it never drafts or
rewrites a line of dialogue. Findings name structural fixes — move this effect, gate this
choice, set this flag on that beat — and stop there.

## What it owns, and what it doesn't

Three walkers already cover most of this ground. Keep the boundary crisp or you will
re-report their findings as noise:

- **The validator** owns *invalid*: dangling ids, dead rungs below an unconditional one, a
  top rung whose effects re-fire forever, the FLOW rule (a `showIf` node must have `next`
  and must not have `choices`/`isEnd`). Run `python tooling/validate.py` first. This audit
  assumes a clean validator and never repeats it.
- **`ladder-audit`** owns *intent*: whether a ladder's ordering tells the character's arc.
  It needs a stated arc. This audit needs no arc — its anchor is the recipe, not the story.
- **This audit** owns the seam between them: arrangements that are valid and say nothing
  about arc, but still do the wrong thing because a recipe was followed most of the way and
  not all of it. The effect on a skipped node. The choice that forgets to spend itself.

Findings are **advisory**, like every audit here. None of these is wrong often enough to
gate CI — a skipped effect can be intended, a "never spent" option can be spent by state
you set three dialogues away. Each finding is a question with the evidence attached, not a
verdict.

## 1. Gather — the three pitfalls, located

Run this from the project root. It reads the whole project (recursively, honouring a
`parlance.config.json` `data` override) and prints three candidate lists — one per
mechanical pitfall. It writes nothing.

```bash
python3 - <<'PY'
import json, glob as g, os

def _data_dir():
    """Honour parlance.config.json's `data` override (validate.py does)."""
    try:
        return json.load(open("parlance.config.json", encoding="utf-8")).get("data") or "data"
    except Exception:
        return "data"

DATA = _data_dir()

def all_json():
    # Recursive: dir-mode entities nest in zone/chapter subdirs. A flat glob
    # under-reads, and an under-read looks exactly like a clean project.
    return sorted(g.glob(os.path.join(DATA, "**", "*.json"), recursive=True))

def dialogue_files():
    return sorted(g.glob(os.path.join(DATA, "dialogues", "**", "*.json"), recursive=True))

def load(p):
    try:
        return json.load(open(p, encoding="utf-8"))
    except Exception:
        return None

def walk(o, path=""):
    if isinstance(o, dict):
        yield path, o
        for k, v in o.items(): yield from walk(v, f"{path}.{k}")
    elif isinstance(o, list):
        for i, v in enumerate(o): yield from walk(v, f"{path}[{i}]")

def cond_summary(c):
    return json.dumps(c) if c else "NONE"

# --- who writes what, anywhere in the project (the same map ladder-audit builds) ---
writers = {}
for p in all_json():
    doc = load(p)
    if doc is None: continue
    b = os.path.basename(p)
    for path, o in walk(doc):
        if not isinstance(o, dict): continue
        t, key = o.get("type"), None
        if   t == "set_flag":            key = f"flag:{o.get('flag')}={o.get('value')}"
        elif t == "give_item":           key = f"item+:{o.get('item')}"
        elif t == "take_item":           key = f"item-:{o.get('item')}"
        elif t == "set_active_dialogue": key = f"flag:active_dialogue__{o.get('character')}=True"
        if key: writers.setdefault(key, []).append(f"{b}{path}")

# --- dialogue index by id (schema does not require filename == id) ---
dlg_by_id, dlg_file = {}, {}
for p in dialogue_files():
    d = load(p)
    if isinstance(d, dict) and d.get("id"):
        dlg_by_id[d["id"]] = d
        dlg_file[d["id"]] = os.path.basename(p)

def unset_gates(cond, acc=None):
    """Flags/items a condition requires ABSENT, for the canonical one-shot shapes:
    not(flag=true), flag=false, item(has:false). Nested inside all/any is followed;
    arbitrary deeper negation is deliberately NOT modelled — those get judged by eye."""
    acc = [] if acc is None else acc
    if not isinstance(cond, dict): return acc
    t = cond.get("type")
    if t == "not" and isinstance(cond.get("of"), dict):
        of = cond["of"]
        if of.get("type") == "flag" and of.get("value") is True:
            acc.append(("flag", of.get("flag")))
        elif of.get("type") == "item" and of.get("has", True) is True:
            acc.append(("item", of.get("item")))
    elif t == "flag" and cond.get("value") is False:
        acc.append(("flag", cond.get("flag")))
    elif t == "item" and cond.get("has") is False:
        acc.append(("item", cond.get("item")))
    elif t in ("all", "any"):
        for s in cond.get("of", []) or []: unset_gates(s, acc)
    return acc

def own_spends(effects):
    """(flags set true, items given) by this effect list — the writes that flip an
    unset-gate and hide a self-spending choice."""
    fset, igive = set(), set()
    for e in effects or []:
        if not isinstance(e, dict): continue
        if e.get("type") == "set_flag" and e.get("value") is True: fset.add(e.get("flag"))
        elif e.get("type") == "give_item": igive.add(e.get("item"))
    return fset, igive

def reachable_spend(d, start):
    """Flags-set-true and items-given on every node reachable from `start` WITHIN
    this dialogue, following `next` and each choice's goto/next. This is the state
    the player's own path spends after taking the choice — recipe 5 is satisfied
    whether the write sits on the choice's effects OR on the beat it routes into,
    and both are correct, so both must count or the check floods with false alarms."""
    nodes = {n.get("id"): n for n in d.get("nodes", []) or [] if n.get("id")}
    seen, stack, fset, igive = set(), [start], set(), set()
    while stack:
        nid = stack.pop()
        if nid in seen or nid not in nodes: continue
        seen.add(nid)
        n = nodes[nid]
        f, i = own_spends(n.get("onEnter")); fset |= f; igive |= i
        if n.get("next"): stack.append(n["next"])
        for c in n.get("choices", []) or []:
            f2, i2 = own_spends(c.get("effects")); fset |= f2; igive |= i2
            tgt = c.get("goto") or c.get("next")
            if tgt: stack.append(tgt)
    return fset, igive

# ============================================================================
# A. Skipped effect — recipe 2 pitfall: "onEnter on a skipped node never fires."
#    A node with BOTH showIf AND onEnter: when the gate fails the node is skipped
#    and every effect on it silently does not fire.
# ============================================================================
print("=" * 74)
print("A. SKIPPED EFFECT  (cookbook recipe 2 — 'onEnter on a skipped node never fires')")
print("   A node gated by showIf whose onEnter fires ONLY when the node is shown.")
print("   Intended when the effect should track being SEEN. A defect when the effect")
print("   is state the story needs regardless — move it to the surviving beat (next).")
print("=" * 74)
hitA = 0
for did, d in sorted(dlg_by_id.items()):
    for n in d.get("nodes", []) or []:
        if n.get("showIf") and n.get("onEnter"):
            hitA += 1
            eff = ", ".join(e.get("type", "?") for e in n["onEnter"] if isinstance(e, dict))
            print(f"\n  {dlg_file.get(did, did)}  dialogue {did}")
            print(f"    node {n.get('id')}   next -> {n.get('next', '(none)')}")
            print(f"    showIf : {cond_summary(n.get('showIf'))}")
            print(f"    onEnter: {eff}   <- fires only when this node is NOT skipped")
if not hitA:
    print("\n  none.")

# ============================================================================
# B. Option that never spends — recipe 5 pitfall: a one-shot choice hides on a
#    flag/item it is supposed to set, but its OWN effects don't set it.
# ============================================================================
print("\n" + "=" * 74)
print("B. OPTION THAT NEVER SPENDS  (cookbook recipe 5 — 'a choice that spends itself')")
print("   A choice offered only while X is unset, whose own effects do NOT set X.")
print("   If nothing anywhere sets X, the option is offered every visit, forever.")
print("=" * 74)
hitB = 0
for did, d in sorted(dlg_by_id.items()):
    for n in d.get("nodes", []) or []:
        for c in n.get("choices", []) or []:
            gates = unset_gates(c.get("showIf"))
            if not gates: continue
            own_f, own_i = own_spends(c.get("effects"))
            tgt = c.get("goto") or c.get("next")
            rch_f, rch_i = reachable_spend(d, tgt) if tgt else (set(), set())
            for kind, name in gates:
                if kind == "flag" and (name in own_f or name in rch_f): continue   # spent on the taken path — correct
                if kind == "item" and (name in own_i or name in rch_i): continue
                flip_key = f"flag:{name}=True" if kind == "flag" else f"item+:{name}"
                elsewhere = writers.get(flip_key) or []
                hitB += 1
                print(f"\n  {dlg_file.get(did, did)}  dialogue {did}")
                print(f"    node {n.get('id')}  choice {c.get('id')}  goto -> {tgt or '(none)'}")
                print(f"    offered while {kind} {name!r} is unset; the path taken from this choice never sets it.")
                if not elsewhere:
                    print(f"    *** {kind} {name!r} is set by NOTHING in the project — offered every visit, forever ***")
                else:
                    print(f"    {kind} {name!r} is set by {len(elsewhere)} site(s), but none on this choice's path:")
                    for s in elsewhere[:4]: print(f"        {s}")
                    print(f"    -> a defect only if the player can return here without crossing one of those sites.")
if not hitB:
    print("\n  none.")

# ============================================================================
# C. Say-it-once flag on a skippable branch — recipe 1 pitfall: "set the flag on
#    a beat the player actually reaches." An intro rung gated `not flag=true` with
#    an unconditional rung below it, where the flag is not set on every ending.
# ============================================================================
print("\n" + "=" * 74)
print("C. SAY-IT-ONCE FLAG PLACEMENT  (cookbook recipe 1 — 'set the flag on a beat")
print("   the player actually reaches'). Intro rung gated on `not flag`; if the flag")
print("   is not set on every ending of the intro, some paths replay the intro.")
print("=" * 74)
hitC = 0
for p in sorted(g.glob(os.path.join(DATA, "characters", "**", "*.json"), recursive=True)):
    ch = load(p)
    if not isinstance(ch, dict): continue
    ladder = ch.get("dialogues") or []
    has_fallthrough_below = lambda i: any(not r.get("showIf") for r in ladder[i + 1:])
    for i, rung in enumerate(ladder):
        for kind, name in unset_gates(rung.get("showIf")):
            if kind != "flag" or not has_fallthrough_below(i): continue
            intro_id = rung.get("dialogue")
            intro = dlg_by_id.get(intro_id)
            flip_key = f"flag:{name}=True"
            all_sites = writers.get(flip_key) or []
            hitC += 1
            print(f"\n  {os.path.basename(p)}  character {ch.get('id')}")
            print(f"    say-it-once rung [{i}] {intro_id}  gated on `not flag {name}`")
            if not all_sites:
                print(f"    *** flag {name!r} is set by NOTHING — the intro plays every time ***")
            if intro is None:
                print(f"    (intro dialogue {intro_id!r} not found as a file — check the id)")
                continue
            ends = [n for n in intro.get("nodes", []) or [] if n.get("isEnd")]
            print(f"    intro {intro_id} has {len(ends)} ending node(s); which set {name!r}:")
            for n in ends:
                sets_it = name in own_spends(n.get("onEnter"))[0]
                mark = "sets it" if sets_it else "does NOT set it  <-- a play ending here replays the intro"
                print(f"        end node {n.get('id')}: {mark}")
if not hitC:
    print("\n  none.")
print()
PY
```

## 2. Judge each candidate against the recipe

The gather locates candidates; it does not decide. For each one, decide whether the recipe
was tripped or the arrangement is deliberate. The three have different tells:

- **A — skipped effect.** Read what the effect *is*. `set_flag: seen_x` on the very node
  that establishes X is usually intended — it records having seen this beat, which is the
  whole point of gating the beat. `advance_quest`, `give_item`, `grant_xp`, a flag another
  character reads — those are world state the story needs whether or not the player saw
  this particular beat, and hanging them on a skippable node means a re-entering player
  silently loses them. The fix is recipe 2's: move the effect to the surviving beat (the
  `next` node with no `showIf`).

- **B — option that never spends.** If the flag/item is set by **nothing**, it is a real
  defect: the option reappears every visit. If it is set **elsewhere**, trace the path the
  player actually takes after this choice — does that path spend it before they can return?
  Often the answer is yes and the recipe is simply spread across two dialogues; say so and
  move on. The failure is when the "elsewhere" site is on a branch the player taking *this*
  choice never reaches.

- **C — say-it-once placement.** An ending that does not set the flag is only a defect if a
  play can *end there*. A rare bad-outcome ending that also skips the intro next time may be
  intended ("if you blew the first meeting, you get the cold open again"). The finding is
  real when a *normal* completion path ends on a node that forgets to record itself.

If the project has an `AUDIT_CONVENTIONS.md`, read it. A pattern the author has documented
as deliberate there (a re-entry policy, an intentionally repeating beat) is not a finding —
flag your own recommendation instead of making it.

## 3. Report

In this order:

1. **Recipe coverage** — one line: which recipes the project uses that this audit checks
   (say-it-once ladders found, `showIf` nodes with effects, gated one-shot choices). This
   makes "found nothing" legible as *checked and clean* rather than *did not look*.
2. **Findings** — real issues only, each as: *the recipe and its pitfall* → *the site in the
   data* → *the play-experience symptom* → *the structural fix*. No praise, no filler.
3. If every candidate is deliberate, say so in one line and stop.

## Rules

- **Cite the recipe.** Every finding names the cookbook recipe and quotes the pitfall it
  trips. That is the anchor; a finding that cannot point at one is out of scope for this
  audit.
- **Trace, don't vibe.** "This effect looks risky" is not a finding. "`grant_xp` on
  `node_brief`, which is skipped on every re-entry because its `showIf` fails once
  `seen_brief` is set, so a returning player never gets the XP" is.
- **Mechanical validity is the validator's.** If a candidate is actually *invalid* (a
  `showIf` node with `choices`, a dead rung), note it in one line and defer — do not dress
  it as a cookbook finding.
- **Advisory, always.** You advise; the author decides. A skipped effect, a one-shot that
  spends elsewhere, a cold-open ending — each can be intent. Flag and ask.
- **Never propose dialogue text.** "Move the `set_flag` to `node_office_seen`" is the
  finding. What that node says is the author's business.

## Example finding (shape to match)

> **Skipped effect — recipe 2, "onEnter on a skipped node never fires."**
> `dlg_warden_recruit` node `node_brief` carries `showIf: not seen_brief` **and**
> `onEnter: grant_xp 50`. On the first visit the node shows and the XP is granted; on every
> later visit `seen_brief` is set, the gate fails, the node is skipped, and the `grant_xp`
> never fires. **Symptom:** the reward is silently first-visit-only, which is almost
> certainly not intended for XP. **Fix:** move `grant_xp` to the surviving beat
> `node_office_seen` (no `showIf`, so never skipped), exactly as recipe 2 places its
> `set_flag`. If the XP is *meant* to be a one-time seen-bonus, leave it and note the intent.
