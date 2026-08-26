---
name: character-presence-audit
description: Audit whether a character has enough presence, re-entry, and player-chosen investment to carry the scenes that depend on them. Use when a character's footprint feels thin ("does X have enough dialogue?"), before or after authoring a scene whose impact depends on the player caring about someone (a death, disappearance, betrayal, reunion), or as an editorial pass over a cast. Complements ladder-audit, which judges rung ORDERING; this one judges presence, weight, and reachability.
---

# Character Presence Audit

Answers a question no static check can: **has this character been established enough
to carry what the story asks of them, and did the player get any say in it?**

This is not `ladder-audit`, which traces a ladder's *ordering*. Run that for "does this
ordering tell the story I meant." Run *this* for "is there enough here at all, and
could the player choose to spend time with them." A ladder can be perfectly ordered and
still describe a character the player never had a relationship with.

Run it after the mechanical gates are clean, so you are judging content rather than
chasing broken references.

**This audit reports; it never writes.** Its output names what does not exist and what
it would cost. It never drafts the missing content.

## 1. Measure first — never eyeball a footprint

"How many dialogues does X have?" is the wrong unit and will mislead you. A character's
ladder lists the conversations they *own*; most characters also speak inside scenes
owned by nobody. Count spoken nodes and words across every file, and count where they
are *named* separately.

```bash
python3 - <<'PY'
import json, glob as g, os, re

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

_c = load_char(CHAR)
name = _c.get("name") if _c else None

# Prose almost never repeats a character's full registered name. "Wren Halloway"
# is addressed as "Wren" and referred to as "Halloway", and a substring test for
# the whole string finds neither — which reads as "this character is never named"
# and quietly turns check D into a no-op. So match on NAME PARTS, at word
# boundaries: a bare `in` test also fires on "Ana" inside "Anastasia".
#
# Particles are dropped because "de" and "the" match everything; two-letter
# names are kept, because "Ed" is a name and dropping it would reintroduce the
# silent miss this replaces. The matched part is reported next to every hit, so
# a first name that is also an English word ("Will", "May", "Rose") is visible
# as such rather than being silently counted or silently dropped.
PARTICLES = {"de", "van", "von", "del", "della", "di", "du", "la", "le", "el",
             "al", "bin", "ibn", "mac", "mc", "of", "the", "san", "st"}

def parts_of(nm):
    return [t for t in re.findall(r"[^\W\d_]+", nm or "", re.UNICODE)
            if t.lower() not in PARTICLES]

PARTS = parts_of(name)
NAME_RE = re.compile(r"\b(" + "|".join(map(re.escape, PARTS)) + r")\b") if PARTS else None

# A name part shared with another character is not evidence about THIS one.
# A real project is the case that made this necessary: a chorus id whose name
# was the bare word "Sister", in a cast that also held two named Sisters — so
# every "Sister" in the prose counted as a reference to all three, and check D
# read five ambient lines as this character being named.
# The audit says which other characters share the part rather than choosing;
# choosing would be a guess presented as a measurement.
SHARED = {}
for _p in ents("characters"):
    try: _o = json.load(open(_p, encoding="utf-8"))
    except Exception: continue
    if _o.get("id") == CHAR: continue
    for _t in parts_of(_o.get("name")):
        if _t in PARTS: SHARED.setdefault(_t, []).append(_o.get("id"))

def names_in(text):
    """Which parts of the name this string uses, and whether they are this
    character's alone. An ambiguous hit is reported, never silently counted."""
    if not NAME_RE: return []
    out = []
    for t in sorted(set(NAME_RE.findall(text or ""))):
        out.append(f"{t} — AMBIGUOUS, also {', '.join(SHARED[t])}" if t in SHARED else t)
    return out

spoken, named = [], []
for p in ents("dialogues"):
    d = json.load(open(p)); f = os.path.basename(p); root = d.get("speakerId")
    for n in d.get("nodes", []):
        sid = n.get("speakerId") or root
        if sid == CHAR:
            # Tagged so the ratio in check A can be read honestly: an inherited
            # node may be narration ABOUT this character rather than a line BY
            # them, and counting stage directions as footprint inflates exactly
            # the number this audit leads with.
            kind = "explicit" if n.get("speakerId") == CHAR else "inherited"
            spoken.append((f, f"{n['id']} [{kind}]", len(n.get("text","").split())))
        else:
            hits = names_in(n.get("text", ""))
            if hits: named.append((f, n["id"], f"narration  ({', '.join(hits)})"))
        for c in n.get("choices", []) or []:
            hits = names_in(c.get("text", ""))
            if hits: named.append((f, f"{n['id']}/{c['id']}", f"CHOICE TEXT  ({', '.join(hits)})"))
print(f"{CHAR}: {len(spoken)} spoken nodes, {sum(w for _,_,w in spoken)} words, "
      f"across {len({f for f,_,_ in spoken})} dialogues")
for f, n, w in spoken: print(f"   speaks   {f:<34} {n:<20} {w}w")
if PARTS:
    print(f"   (matching name parts: {', '.join(PARTS)})")
    for _t, _who in sorted(SHARED.items()):
        print(f"   *** '{_t}' is shared with {', '.join(_who)} — hits on it prove nothing "
              f"about {CHAR} ***")
for f, n, k in named: print(f"   named    {f:<34} {n:<20} {k}")
PY
```

Then establish how they are placed and whether the player can choose to meet them:

```bash
# Which interactables place them, and under what condition?
grep -rn "char_id_here" data/locations/*.json

# Are their own conversations replayable, and do they gate progression?
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

CHAR = "char_id_here"
for p in ents("dialogues"):
    d = json.load(open(p))
    if d.get("speakerId") != CHAR: continue
    cuts = [e.get("cutscene") for n in d["nodes"]
            for e in (n.get("onEnter") or []) if e.get("type") == "play_cutscene"]
    print(d["id"], "| replayable:", d.get("replayable"), "| fires:", cuts)
PY
```

A conversation that fires the cutscene which is the only route onward is **mandatory** —
every player gets it. One that fires nothing and hangs off an optional interactable is
**skippable**. That distinction drives half the findings below.

**Sweep the whole cast in one pass** when you want to know who to look at, rather than
auditing a name you already suspect:

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

# Key by the id INSIDE the file, not the filename — the schema does not tie them,
# and keying by basename silently drops any character whose file is named
# differently, which reads as "this character has no presence".
chars = {}
for p in ents("characters"):
    _d = json.load(open(p, encoding="utf-8"))
    if _d.get("id"): chars[_d["id"]] = _d
_dlg_by_id = {}
for p in ents("dialogues"):
    _d = json.load(open(p, encoding="utf-8"))
    if _d.get("id"): _dlg_by_id[_d["id"]] = _d
spoken, by_dlg = {}, {}
for p in ents("dialogues"):
    d = json.load(open(p)); root = d.get("speakerId")
    for n in d.get("nodes", []):
        sid = n.get("speakerId") or root
        if sid in chars:
            s = spoken.setdefault(sid, [0, 0, set()])
            s[0] += 1; s[1] += len(n.get("text","").split()); s[2].add(d["id"])
            # Per-dialogue words, so check A's ratio is computed rather than
            # eyeballed. `top` below is the share of everything a character says
            # that sits in their single largest scene.
            by_dlg.setdefault(sid, {}).setdefault(d["id"], 0)
            by_dlg[sid][d["id"]] += len(n.get("text","").split())
placed = {}
for p in ents("locations"):
    for it in json.load(open(p)).get("interactables", []) or []:
        if it.get("character"): placed.setdefault(it["character"], []).append(bool(it.get("showIf")))
print(f"{'character':<26}{'nodes':>6}{'words':>7}{'files':>6}{'top':>6}"
      f"{'rungs':>7}{'reentry':>9}  placed")
for cid in sorted(chars):
    if cid not in spoken and cid not in placed: continue
    n, w, files = spoken.get(cid, [0, 0, set()])
    reent = 0
    for r in chars[cid].get("dialogues") or []:
        dd = _dlg_by_id.get(r["dialogue"])
        if dd is None: continue
        fx = any(x.get("onEnter") for x in dd["nodes"]) or \
             any(c.get("effects") for x in dd["nodes"] for c in (x.get("choices") or []))
        if dd.get("replayable") and not fx: reent += 1
    dd_words = by_dlg.get(cid) or {}
    top = f"{max(dd_words.values())/w:.0%}" if w and dd_words else "-"
    print(f"{cid:<26}{n:>6}{w:>7}{len(files):>6}{top:>6}"
          f"{len(chars[cid].get('dialogues') or []):>7}{reent:>9}  {len(placed.get(cid, []))}")
PY
```

**Check `AUDIT_CONVENTIONS.md` before judging anyone.** Two sections change the answers:

- `## Chorus ids` — an id that is a pool every passing extra speaks from is not a
  character. It will often carry more words than any named character, and none of them
  are a relationship. Judge the pool for consistent seasoning; none of checks A–F apply.
- `## Re-entry` — the project's policy on returning to a conversation. Without it, check
  B below is guesswork.

## 2. The checks

Work through all six. Each catches a real failure; none is a style opinion.

**A. Setup-versus-payoff weight.** Find the scene whose impact *depends* on this
character mattering — their death, disappearance, betrayal, reunion. Compare its size
to their establishing content. A payoff much larger than the setup is the strongest
signal in this audit: the scene is working to make the player feel something the setup
never funded. Report the ratio in nodes and words, not vibes.

The sweep's `top` column does the arithmetic: the share of everything a character says
that sits in their single largest scene. It is a proxy, not the answer — it finds the
concentrated scene without knowing whether that scene is the payoff — but a character
whose `top` is high has, by definition, very little else.

**There is no threshold here, and inventing one would be worse than having none.**
Measured across the two corpora available when this was written — 14 characters with
40+ words — `top` ran from 17% to 100%, and the shape was not a cutoff but two
populations: chorus and ambient ids sat at 17–48% (many small scenes, no arc), while
the named dramatic characters sat at 40–100%. The highest values, 100%, were characters
with exactly one scene, where the ratio is arithmetically forced and says nothing.
So read `top` as a **sort order** — start with the highest and work down — and let
check A's real question decide: is the big scene a payoff, and did anything fund it?
Two projects is not a sample. If you calibrate a number from your own corpus, write it
into `AUDIT_CONVENTIONS.md`, where it will at least be yours.

**B. Any re-entry at all — but only where re-entry is owed.** Does the character have a
rung the player can return to and simply *visit* — no plot, no flags, no effects?

**Do not flag this blindly.** Split the cast first, because the honest answer differs:

- **Persisting characters** — placed somewhere the player revisits, met across several
  beats, meant to be known. Missing an idle rung here is a real gap: they have no
  relationship, only appointments.
- **One-way hinge characters** — they appear at a single consequential scene and are
  done. Consequential scenes are often one-way, and not every re-entry owes the player
  content; the truthful post-state is silence or a soft refusal. Their one-shot rungs
  are correct, and gating them was a fix rather than a defect.

The discriminator is whether the character is still in the world after their scene.
Flag only the first kind. Expect the measurement to report "no re-enterable rung" for
several characters of whom only one is a finding.

**C. Mandatory versus chosen.** If every scene is on the critical path, the player never
*chose* to spend time with them, and the loss is therefore the author's rather than the
player's. Presence without plot — an idle the player opts into — is what converts
obligation into investment. Flag "100% on rails."

**D. Is the name in choice text, or only narration?** When a beat turns on the player
having used a name casually, the name must appear in **choices the player actively
picks**, not only in narration they read past. The measurement counts the two
separately. Narration-only means the mechanism is not wired to the player's mouth.

The gather matches each PART of the registered name at word boundaries, not the whole
string, because prose says "Wren" and "Halloway" and almost never "Wren Halloway".
It prints which part matched beside every hit, and that is there for you to read.

**Two ways a hit can be worthless, both flagged rather than filtered.** A part shared
with another character is marked `AMBIGUOUS` and names who else it belongs to — in one
real project a chorus id called "Sister" collected every reference to two different
named Sisters, which read as five beats of presence the character does not have. And a
name that is also an ordinary word — Will, May, Rose, Grace, Worker, Builder — will
collect hits that are not references at all; nothing can detect that for you, so read
the quoted part before counting a beat as wired.

Neither is filtered out automatically, because a shared part is sometimes the *right*
reference and only the text can say. The audit's job here is to stop you counting a
number it cannot justify.

**E. Absence enforced where?** If a character leaves the story, check *what* removes
them: a ladder rung, the interactable's `showIf`, or both. Absence enforced **only** at
the placement layer is fragile — delete one `showIf` and they walk back into the scene
about their own disappearance. Prefer belt-and-braces: gate the placement AND give the
ladder a terminal rung, even when that rung has nothing to say.

**F. Does the ladder contradict the placement?** Resolve the ladder against the states
the character is actually placed in. A rung that only wins in a state where they are
unplaced is dead in practice, and the static dead-rung check cannot see it because the
two live in different files.

*(Voice and register consistency used to be a seventh check here. It is now
`character-voice-audit`, which is anchored on `dialogueStyle` and calibrates before it
judges. On a thin footprint one off-voice line is a large fraction of the character, so
running it alongside this audit is usually worth it.)*

## 3. What good looks like

- Establishing content is at least comparable to the payoff that leans on it.
- At least one re-enterable, effect-free rung exists for any character the player is
  meant to care about.
- Some presence is player-chosen, not all of it mandatory.
- If a name-recognition beat exists, the name is in choice text.
- Absence is enforced in both the ladder and the placement.

## 4. Reporting

Lead with the ratio from check A — it is usually the finding that matters. Then list
gaps as **missing content**, not defects: say what does not exist and what it would
cost, because "40 words of nothing in particular" is a very different ask from
"rewrite the scene."

Recommend **presence without plot** before more plot. On a character whose power comes
from being unremarkable, extra story actively damages the beat — it converts a quiet,
eerie hole into a conventional death scene, which is both a weaker scene and a far more
common one. More *ordinary* is usually right; more *important* usually is not.

Any rung you recommend should be effect-free and flagless. The moment an idle rung
carries an effect it stops being safe to re-enter, and a rung that changes the world
must not be able to win twice.

**Say what is missing. Do not write it.** "One short re-enterable idle rung under the
day rungs, carrying nothing" is the finding. What that rung says is the author's.

## 5. Worked example — the finding this audit exists for

A character the player meets early and loses partway through, where the loss is meant to
land hard. Invented numbers, real shape:

- They looked like "only two dialogues." The measurement said **15 spoken nodes across 5
  files** — the naive count was wrong, which is why step 1 exists.
- But the bulk of those words sit in the first meeting. The beat that is supposed to make
  the loss land — the last ordinary conversation — is a handful of lines.
- The payoff scene is several times the size of everything establishing it. Setup to
  payoff around 1:5 (check A).
- **Zero re-enterable rungs.** Every conversation is non-replayable *and* mandatory,
  because each one fires the cutscene that advances the story (checks B and C).
- Their absence afterwards is enforced **only** by the interactable's gate. The ladder
  still resolves to an earlier conversation, so deleting that one gate puts them back on
  screen, talking normally, over the scene about their disappearance (check E).

The recommendation was **not** more scenes with them. It was one short re-enterable idle
rung under the others, carrying nothing, plus a defensive terminal rung so the absence is
not one `showIf` away from breaking.
