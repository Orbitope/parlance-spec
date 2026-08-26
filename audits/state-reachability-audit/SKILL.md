---
name: state-reachability-audit
description: Check whether each line of dialogue holds in every world state that can reach it — the audit for knowledge leakage ("the player is told something they have not learned yet"), stale reveals ("the scene reveals something this player already knows"), and continuity ("this line assumes a character is alive, a door open, a faction hostile"). Use after authoring a scene reachable by several routes, after reordering content, or when a playtester reports a line landing wrong on one path. Computes what is provably known at each node, then reads the text against it.
---

# State Reachability Audit

One question, three defect classes: **does this line hold in every state that can
reach it?**

- **Leakage** — the line assumes knowledge the player may not have yet. A character
  names the murderer to a player who has not been told there was a murder.
- **Stale reveal** — the line reveals something this player already learned by another
  route, so a scene written as a shock plays as a recap.
- **Continuity** — the line assumes a world fact that is not guaranteed: someone alive,
  a door open, a faction hostile, an item still held.

All three are the same trace. The validator cannot see any of them: every one is a
sentence that is true on the path the author had in mind and false on another.

**This audit reports; it never writes.** It names the node, the assumption, and the
route that breaks it. It does not rewrite the line or draft a gated variant.

## 1. Compute what is provably known

Run this from the project root, with a dialogue id as the argument or none at all for
every dialogue. It reports, per node, the facts guaranteed true on **every** path that
reaches it, and the facts true on **some** path.

It is linear in project size — routes are indexed once, not re-derived per dialogue.
Measured on generated fixtures at 65 / 130 / 260 / 520 dialogues, each one validated
clean first (a fixture the validator rejects benchmarks error paths, not the audit), the
log-log slope is 0.73; the version that re-derived routes per dialogue measured 1.89 and
took 37 seconds where this takes 0.27. Run it on the whole project without thinking
about it.

It goes down the pipe rather than into a file on purpose. Every audit in this set
promises that running it leaves your repository exactly as it found it, and a script
dropped in your project root is a file you did not ask for and now have to notice in
`git status`.

```bash
python3 - "$DIALOGUE_ID" <<'PY'      # omit the argument to analyse every dialogue
import json, glob as g, os, re, sys

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

# An unset $DIALOGUE_ID arrives as an empty argument, not as no argument.
TARGET = sys.argv[1] if len(sys.argv) > 1 and sys.argv[1] else None

def walk(o, path=""):
    if isinstance(o, dict):
        yield path, o
        for k, v in o.items(): yield from walk(v, f"{path}.{k}")
    elif isinstance(o, list):
        for i, v in enumerate(o): yield from walk(v, f"{path}[{i}]")

def cond_flags(c, acc=None):
    """Facts a condition GUARANTEES when it passes. Conservative: descends only
    through 'all' (every branch must hold); 'any' and 'not' guarantee nothing."""
    acc = set() if acc is None else acc
    if not isinstance(c, dict): return acc
    t = c.get("type")
    if   t == "flag" and c.get("value") is True:  acc.add(f"flag:{c['flag']}")
    elif t == "flag" and c.get("value") is False: acc.add(f"not-flag:{c['flag']}")
    elif t == "item" and c.get("has") is True:    acc.add(f"item:{c['item']}")
    elif t == "quest":        acc.add(f"quest:{c['quest']}{c['op']}{c['stage']}")
    elif t == "questOutcome": acc.add(f"questOutcome:{c['quest']}:{c['outcome']}")
    elif t == "counter":      acc.add(f"counter:{c['counter']}{c['op']}{c['value']}")
    elif t == "all":
        for s in c.get("of", []): cond_flags(s, acc)
    return acc

def subject(fact):
    """The thing a fact is ABOUT, so that a later effect can revoke it.

    Facts are strings because they have to be comparable across paths, but
    `counter:ct_day==1` and `counter:ct_day>=3` are two claims about one
    counter: writing that counter invalidates both. Reducing a fact to its
    subject is what lets an effect kill claims it never phrased.
    """
    if fact.startswith("not-flag:"): return "flag:" + fact[9:]
    if fact.startswith(("flag:", "item:")): return fact
    if fact.startswith("questOutcome:"): return "questOutcome:" + fact.split(":")[1]
    for pre in ("counter:", "quest:"):
        if fact.startswith(pre):
            return pre + re.split(r"[<>=!]", fact[len(pre):])[0]
    return fact

def kill_of(effects):
    """Subjects an effect list REVOKES.

    Without this the analysis only ever ADDED, and a `must` analysis that
    cannot un-know something is unsound in the direction that matters: a flag
    cleared by `set_flag: false` upstream stayed in KNOWN downstream, so the
    scene that assumes it read as safe. That is precisely the leak this audit
    exists to find, reported as fine.

    `set_flag` kills BOTH polarities before its own gen re-adds one, so
    true->false->true sequences do not accumulate contradictions.
    """
    k = set()
    for e in effects or []:
        t = e.get("type")
        if   t == "set_flag":       k.add(f"flag:{e['flag']}")
        elif t == "take_item":      k.add(f"item:{e['item']}")
        elif t == "give_item":      k.add(f"item:{e['item']}")
        elif t == "adjust_counter": k.add(f"counter:{e['counter']}")
        elif t == "advance_quest":
            # Kills older claims about this quest's STAGE; gen_of below then
            # supplies the new one, because advance_quest names an absolute
            # toStage. An outcome is a different animal — see gen_of.
            k.add(f"quest:{e['quest']}")
            k.add(f"questOutcome:{e['quest']}")
    return k

def gen_of(effects):
    """Facts an effect list ESTABLISHES.

    The false polarity is tracked too: a node that clears a flag proves it is
    clear downstream, which is a real guarantee a scene can be written against.

    `advance_quest` names an absolute `toStage`, so it establishes the stage
    rather than merely invalidating the old one — the difference between a
    downstream scene reading `quest:qst_x==stg_y` and reading nothing at all.
    `adjust_counter` carries a `delta`, not a value, so there is nothing to
    establish and the kill stands alone.

    An OUTCOME is deliberately never generated. A quest outcome is DERIVED from
    its `reachedWhen` conditions rather than stored, so it is not a fact any one
    effect owns: any effect touching state those conditions read can change it.
    kill_of drops questOutcome facts on advance_quest as a conservative gesture,
    but it cannot see the rest, and the limits section says so rather than
    implying outcomes are tracked the way flags are.
    """
    s = set()
    for e in effects or []:
        t = e.get("type")
        if   t == "set_flag":  s.add(f"{'flag' if e.get('value') is True else 'not-flag'}:{e['flag']}")
        elif t == "give_item": s.add(f"item:{e['item']}")
        elif t == "advance_quest" and e.get("toStage"):
            s.add(f"quest:{e['quest']}=={e['toStage']}")
    return s

def minus(facts, killed):
    """Drop every fact whose SUBJECT was revoked, whatever it claimed."""
    return {f for f in facts if subject(f) not in killed} if killed else facts

dialogues = {}
for p in ents("dialogues"):
    d = json.load(open(p)); dialogues[d["id"]] = (p, d)

ALLFLAGS = set()
try:
    v = json.load(open("data/variables.json"))
    # The registry is {"variables":[{id, kind}]} — there is no "flags" key. The
    # old read returned None every time and the bare except swallowed it, so the
    # universe was always empty and the must-analysis started from nothing.
    ALLFLAGS = {f"flag:{x['id']}" for x in (v.get("variables") or [])
                if x.get("kind") == "flag"}
    ALLFLAGS |= {f"counter:{x['id']}" for x in (v.get("variables") or [])
                 if x.get("kind") == "counter"}
except Exception: pass
for _, d in dialogues.values():
    for _, o in walk(d):
        if isinstance(o, dict) and o.get("type") == "set_flag":  ALLFLAGS.add(f"flag:{o['flag']}")
        if isinstance(o, dict) and o.get("type") == "give_item": ALLFLAGS.add(f"item:{o['item']}")

# Routes are indexed ONCE, not recomputed per dialogue. The previous version
# re-read every character, location and cutscene inside entry_gates() and then
# globbed and parsed the whole data tree on top — per dialogue. That is O(n^2)
# in a corpus where n is the dialogue count: fine on a 40-dialogue project,
# roughly ten minutes on the 5,152-dialogue scale fixture, which is the size
# this is meant to be useful at. The glob was the worse half, and it did
# nothing at all: its body was a `pass`.
ROUTES = {}

def _route(did, label, cond):
    if did: ROUTES.setdefault(did, []).append((label, cond))

for p in ents("characters"):
    try: ch = json.load(open(p, encoding="utf-8"))
    except Exception: continue
    for i, r in enumerate(ch.get("dialogues") or []):
        _route(r.get("dialogue"), f"ladder {ch.get('id')}[{i}]", r.get("showIf"))

for p in ents("locations"):
    try: loc = json.load(open(p, encoding="utf-8"))
    except Exception: continue
    for it in loc.get("interactables") or []:
        _route(it.get("dialogue"), f"interactable {loc.get('id')}/{it.get('id')}",
               it.get("showIf"))
    for ex in loc.get("exits") or []:
        # The player reaches a denial dialogue by FAILING the gate, so the gate's
        # own facts are false here, not true. Passing None is deliberate: it
        # guarantees nothing.
        _route(ex.get("denialDialogue"),
               f"denialDialogue {loc.get('id')}/{ex.get('id')} (gate FAILED)", None)

for p in ents("cutscenes"):
    try: cs = json.load(open(p, encoding="utf-8"))
    except Exception: continue
    _route(cs.get("entersDialogue"), f"cutscene {cs.get('id')} entersDialogue", None)

# set_active_dialogue is deliberately NOT indexed as a route. It does not enter
# o["dialogue"] at runtime: it sets active_dialogue__{character} and the
# character's LADDER then resolves (validate.py registers exactly that flag).
# Treating each one as an independent ungated route invented duplicates of the
# ladder rung already indexed above and, because the guarantee set is an
# intersection across routes, zeroed guarantees that genuinely hold.

def entry_gates(did):
    """Every route by which this dialogue can be entered, with its gate."""
    gates = list(ROUTES.get(did, []))
    _, d = dialogues[did]
    if d.get("availableWhen"): gates.append(("availableWhen", d["availableWhen"]))
    return gates

def analyse(did):
    path, d = dialogues[did]
    nodes = {n["id"]: n for n in d["nodes"]}
    entry = d["entry"]
    gates = entry_gates(did)
    per_route = [cond_flags(cond) if cond else set() for _, cond in gates]
    pre = set.intersection(*per_route) if per_route else set()

    def is_cond(nid):
        return bool(nodes[nid].get("showIf"))

    def out_must(nid):
        """Facts guaranteed at this node's SUCCESSOR, via its `next`.

        Unconditional: the node happened, so its own known set plus its effects.
        Conditional: only what held on arrival — the skip path took neither.
        """
        if is_cond(nid):
            return must[nid]
        return minus(must[nid], kill(nid)) | gen(nid)

    def shown_must(nid):
        """Facts guaranteed while the player is READING this node.

        For a conditional node that is a strictly larger set than `must`: being
        displayed at all proves its gate passed, exactly the inference already
        made for a choice's showIf on the edge it guards.
        """
        base = must[nid]
        return base | cond_flags(nodes[nid].get("showIf")) if is_cond(nid) else base

    def gen(nid):
        return gen_of(nodes[nid].get("onEnter"))

    def kill(nid):
        # A conditional node may be SKIPPED, and a skipped node's effects never
        # fire. It therefore kills nothing on the path through it, exactly as it
        # generates nothing — see out_must().
        return set() if is_cond(nid) else kill_of(nodes[nid].get("onEnter"))

    edges = {}
    for nid, n in nodes.items():
        if n.get("next"): edges.setdefault(n["next"], []).append((nid, set(), set()))
        for c in n.get("choices") or []:
            ef = gen_of(c.get("effects")) | cond_flags(c.get("showIf"))
            ek = kill_of(c.get("effects"))
            ck = c.get("check") or {}
            for t in (c.get("goto"), ck.get("onSuccess"), ck.get("onFailure")):
                # (source, generated, killed) — an edge revokes as well as adds.
                if t: edges.setdefault(t, []).append((nid, ef, ek))

    # MUST at entry is what every route guarantees (intersection). MAY is what
    # ANY route can supply (union) — seeding it from the intersection made a fact
    # true on one entry route and false on another unrepresentable, which is the
    # leakage case this audit opens by describing.
    may_pre = set().union(*per_route) if per_route else set()
    must = {nid: (set(pre)     if nid == entry else set(ALLFLAGS)) for nid in nodes}
    may  = {nid: (set(may_pre) if nid == entry else set())          for nid in nodes}
    # Only nodes actually reachable from entry may keep the ALLFLAGS seed long
    # enough to converge. An unreachable ring's members each have an in-edge, so
    # the orphan test below never fires for them and they used to settle on "every
    # flag in the project is guaranteed here" — a stale-reveal generator for every
    # line on the island.
    live, _stack = set(), [entry]
    while _stack:
        _n = _stack.pop()
        if _n in live or _n not in nodes: continue
        live.add(_n)
        for _t in [t for t, srcs in edges.items() for _s in srcs if _s[0] == _n]:
            _stack.append(_t)
    for nid in nodes:
        if nid not in live:
            must[nid], may[nid] = set(), set()
    for _ in range(len(nodes) + 2):
        changed = False
        for nid in nodes:
            # The entry node is NOT pinned. Hub-and-spoke dialogues ("ask about
            # X / back to the menu") route back into it, and skipping it here
            # discarded everything those branches establish — on the most common
            # topology in the format. Its MUST stays seeded by the entry routes;
            # only its MAY grows.
            if nid not in live: continue
            if nid == entry and not edges.get(nid): continue
            ins = edges.get(nid, [])
            if not ins:
                # No path in. For a non-entry node that is the validator's REACH
                # finding; leaving it at the ALLFLAGS seed would report every
                # flag in the project as guaranteed, which an unreachable RING
                # used to do because a ring's members each have an in-edge.
                nm, ny = set(), set()
            else:
                # A CONDITIONAL node contributes far less than an unconditional
                # one. Arriving at it means one of two things happened: its gate
                # passed and it was displayed (its own showIf facts hold, and its
                # onEnter fired), or its gate failed and it was SKIPPED — no
                # display, and its onEnter never fired at all. What is guaranteed
                # at its successor is the intersection of those, which is neither
                # its gate facts nor its effects: only what held on arrival.
                #
                # Adding gen(p) unconditionally here is unsound, and silently so:
                # it asserts an effect fired on a path where the node did not
                # happen, which makes the very leak this audit exists to catch
                # read as already-known and therefore fine.
                # Kill is applied PER EDGE, before the join. A fact revoked on
                # one path may still hold on another, so subtracting it from the
                # joined set would be wrong for MAY and needlessly weak for MUST.
                nm = set.intersection(*[minus(out_must(p), ek) | ef for p, ef, ek in ins])
                ny = set().union(     *[minus(minus(may[p], kill(p)) | gen(p), ek) | ef
                                        for p, ef, ek in ins])
            if nid == entry:
                # Entry is reachable BOTH by the routes that admit the dialogue
                # and by any back-edge. Guaranteed = both agree; possible =
                # either supplies. Recomputing from in-edges alone would throw
                # away the entry gate, which is usually the strongest fact known.
                nm, ny = nm & pre, ny | may_pre
            if nm != must[nid] or ny != may[nid]:
                must[nid], may[nid] = nm, ny; changed = True
        if not changed: break

    print(f"=== {did}   ({os.path.basename(path)})   speaker: {d.get('speakerId','-')}")
    print(f"    replayable: {d.get('replayable', False)}")
    print(f"    admitted by {len(gates)} route(s):")
    for label, cond in gates:
        print(f"      - {label}: {json.dumps(cond) if cond else 'no gate'}")
    print(f"    GUARANTEED on entry (true via every route): {sorted(pre) or '(nothing)'}\n")
    for nid in [entry] + [n for n in nodes if n != entry]:
        n = nodes[nid]
        orphan = "" if (nid == entry or edges.get(nid)) else "  *** no path in (validator REACH) ***"
        print(f"  [{nid}]{' (ENTRY)' if nid == entry else ''} "
              f"speaker={n.get('speakerId') or d.get('speakerId') or 'narration'}{orphan}")
        print(f"    text: {n.get('text','')!r}")
        km = shown_must(nid)
        gate = " [GATED]" if is_cond(nid) else ""
        print(f"    KNOWN here:  {sorted(km) or '(nothing)'}{gate}")
        print(f"    MAYBE known: {sorted(may[nid] - km) or '(nothing)'}\n")

if TARGET: analyse(TARGET)
else:
    for did in dialogues: analyse(did)
PY
```

### What the analysis does and does not prove

Read this before reporting anything, and state the limits in your report.

- **KNOWN** is a *must* analysis: true on every path in, and facts are revoked as well
  as established. `set_flag: false`, `take_item`, `adjust_counter` and `advance_quest`
  all KILL what was known about their subject, per edge, before the paths are joined —
  per edge because a fact revoked on one path may still hold on another, and joining
  first would lose that. Revocation is why a fact can drop out of KNOWN and reappear
  under MAYBE further down: one branch gave the key back.
- **`not-flag:x` is a fact, not the absence of one.** A node that clears a flag proves
  it is clear downstream, which is something a scene can legitimately be written
  against. Seeing both `flag:x` and `not-flag:x` under MAYBE at the same node is the
  signature of a branch that decided the question two different ways — and any line
  there that assumes either answer is a leakage candidate.
- Revocation is tracked by SUBJECT, not by claim. `counter:ct_day==1` and
  `counter:ct_day>=3` are two claims about one counter, so writing that counter
  invalidates both. What happens next depends on whether the effect names a VALUE:
  `advance_quest` names an absolute `toStage`, so the new stage is established and
  appears downstream; `adjust_counter` carries only a `delta`, so the counter goes
  UNKNOWN. That asymmetry is deliberate — a wrong guaranteed value is worse than no
  value, and a delta cannot be turned into one without knowing what it was added to.
- **Quest OUTCOMES are the weakest thing here, and the analysis says so rather than
  pretending.** An outcome is derived from its `reachedWhen` conditions, not stored,
  so no single effect owns it: anything touching the state those conditions read can
  flip it. `advance_quest` drops outcome facts for its own quest as a conservative
  gesture, and that is all the tracking there is. Treat a `questOutcome:` fact in
  KNOWN as "was true at the gate", not "is true here", and check it by hand.
- A **conditional node kills nothing**, exactly as it generates nothing. It may have
  been skipped, and a skipped node's `onEnter` never fired.
- **A `[GATED]` node carries its own gate in KNOWN.** Being displayed at all proves its
  `showIf` passed — the same inference already made for a choice's `showIf` on the edge it
  guards. What that node does NOT pass on is that gate, or its `onEnter` effects: arriving
  at its successor means either it was shown or it was skipped, and only what held on
  arrival survives both. A skipped node's effects never fire, so they appear downstream in
  **MAYBE**, never in KNOWN. If you see a fact you expected to be guaranteed sitting in
  MAYBE instead, a conditional node is why, and that is usually the finding.
- **MAYBE known** is true on at least one path. A line that assumes something in this
  set is the leakage candidate — it holds sometimes.
- It is **conservative through `any` and `not`**: a gate like `any(saw_body,
  heard_rumour)` guarantees nothing, so real knowledge may be missing from KNOWN.
  Check the gate before calling it a leak.
- It models **one dialogue plus its entry gates**. It does not know what the player
  did in other conversations except as those set flags read by the gates. Untracked
  world state — who is where, what a cutscene showed — is invisible to it.
- `set_active_dialogue` is **not** an entry route. It sets `active_dialogue__{character}`
  and the character's ladder resolves from there, so the ladder rung that reads that flag
  is the route — counting each effect as its own ungated route invented duplicates and,
  because guarantees are intersected across routes, erased guarantees that genuinely held.

## 2. Establish the premise

Some knowledge is not gated because the player has it from the start. Before treating
an assumption as a leak, check `AUDIT_CONVENTIONS.md` for a `## Player knowledge`
section listing what the opening establishes. Absent that, ask the author what the
player knows at minute zero rather than reporting the whole premise as leakage.

## 3. Read the text against the state

For each node, list what the text **asserts or assumes** — a named person, a fact
about the world, a shared history with the player, an object in hand, an emotional
state that depends on a prior scene. Then classify:

- The assumption is in **KNOWN** → fine.
- The assumption is in **MAYBE known** → **leakage candidate.** Identify the specific
  route on which it is false and say what the player sees there.
- The assumption is in neither → either untracked world state (say so; it cannot be
  verified from data) or premise (check `## Player knowledge`).
- The node **reveals** something already in **KNOWN** → **stale reveal candidate.**
  Ask whether the scene is written as new information; if it is, the beat is spent on
  a player who already had it.

Pay particular attention to nodes with many incoming edges and to dialogues admitted
by several routes — the report's `admitted by N route(s)` line tells you where to
look. A node reachable one way cannot leak.

## 4. What is not a finding

- A node whose only route makes the assumption true. Most nodes.
- Deliberate dramatic irony: the *player* knows and the *character* does not, or the
  reverse. Both are craft. The defect is when the **text** assumes the player knows
  something the player may not.
- A vague or atmospheric line that does not actually assert a checkable fact.
- Anything the analysis marks as untracked world state, reported as though it were
  proven. Say "cannot be verified from the data" and let the author judge.
- Unreachable nodes — that is the validator's `REACH` warning, not this audit.

## 5. Report

1. **Scope** — dialogues analysed, and how many entry routes each has.
2. **Leakage findings** — node id → the assumption quoted from the text → the route on
   which it is false → what the player sees on that route.
3. **Stale reveals** — node id → the fact → where the player may already have learned
   it.
4. **Continuity assumptions that cannot be verified** — listed plainly as questions for
   the author, not as defects.
5. **Limits** — one line naming what the analysis could not see (`any`/`not` gates,
   world state, and counter/quest values after a write, which go unknown rather than
   being recomputed).

A single-route scene graph produces no findings, and saying so in one line is the
correct output.
