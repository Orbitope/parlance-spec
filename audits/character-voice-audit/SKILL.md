---
name: character-voice-audit
description: Check every line a character speaks against the voice the author declared for them in their `dialogueStyle` field. Use when a character has been written by several hands or over a long stretch, after merging contributed dialogue, or as an editorial pass before a milestone. Judges consistency with the author's OWN stated intent — never against a house style, and never by rewriting. Complements ladder-audit (which judges rung ordering) and character-presence-audit (which judges footprint).
---

# Character Voice Audit

Answers one question: **does every line this character speaks hold to the voice the
author declared for them?**

The anchor is the character's `dialogueStyle` field — the author's own one-line
statement of how this person talks ("Over-explains. Offers detail nobody asked for,
then hears himself doing it and stops."). The audit judges the lines against *that*,
and against nothing else.

**This audit has no opinion about good dialogue.** It does not know what a strong line
is, it is not measuring quality, and it must never say a line is weak, flat, clichéd,
or in need of polish. It compares written lines to a written intent and reports where
they diverge. If `dialogueStyle` is absent, the audit stops and asks for one rather
than inventing a standard.

**It reports; it never writes.** No suggested rewrites, no example lines, no "consider
something like…". A finding quotes the existing line, names the clause of
`dialogueStyle` it contradicts, and stops. Fixing it is the author's work, and the
whole point of the constraint is that the author's voice is the thing being protected.

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

CHAR = "char_id_here"          # <- the character under audit

ch = load_char(CHAR)
if ch is None:
    raise SystemExit(f"no character with id {CHAR!r} — check the id, not the filename")
style = ch.get("dialogueStyle")
print(f"{ch['id']} — {ch.get('name')}")
print(f"declared style: {style or '*** NONE — stop, ask the author ***'}")
print(f"archetype: {ch.get('archetype','-')}   faction: {ch.get('factionId','-')}\n")

# A node with no speakerId INHERITS the dialogue's. The runtime resolves it to
# this character, but authors routinely use that slot for third-person narration
# in a character-owned scene. Folding the two together hands the model stage
# directions to judge as dialogue — on one character in this repo, every single
# "spoken" word is narration. So they are counted and printed apart, and only
# the explicit set is the character's voice.
explicit, inherited = [], []
for p in ents("dialogues"):
    d = json.load(open(p, encoding="utf-8")); root = d.get("speakerId")
    for n in d.get("nodes", []):
        row = (os.path.basename(p), n["id"], n.get("text",""))
        if n.get("speakerId") == CHAR: explicit.append(row)
        elif not n.get("speakerId") and root == CHAR: inherited.append(row)
w = lambda rs: sum(len(r[2].split()) for r in rs)
print(f"EXPLICIT (node names this character): {len(explicit)} nodes, {w(explicit)} words")
print(f"INHERITED (node names nobody; the dialogue's speaker is this character): "
      f"{len(inherited)} nodes, {w(inherited)} words")
print("Both are this character at runtime. Setting a root speaker and letting nodes")
print("inherit is the normal pattern, so INHERITED is usually most of their dialogue —")
print("but it is also where third-person narration lives. Sort it before judging:")
print("a line ABOUT the character is not a line BY them.\n")
for label, rows in (("EXPLICIT", explicit), ("INHERITED", inherited)):
    for f, nid, text in rows:
        print(f"--- [{label}] {f} :: {nid}")
        print(f"    {text}\n")
PY
```

If the project has an `AUDIT_CONVENTIONS.md`, read it before judging:

- `## Voice` — a project-level register system. It applies *in addition to*
  `dialogueStyle`, never instead of it. Per-character intent always wins.
- `## Chorus ids` — if this id is listed, it is a pool every passing extra speaks
  from, not a person. Judge the pool for consistent seasoning; never judge it as a
  character, and never report "inconsistent voice" for a chorus.

## 2. Calibrate before you judge

Do not start by hunting for violations. Start by finding the character:

1. Read all the lines.
2. Pick the **three lines that best exemplify the declared style** and say why. This
   is the calibration step and it is not optional — it forces the style statement to
   become concrete (what *does* "prices everything" look like in this project's
   prose?) before anything is measured against it.
3. If you cannot find three exemplars, that is the headline finding: the declared
   style is not present in the writing at all, and the question for the author is
   whether the field or the lines are out of date. Report that and stop.

Calibrating first is what separates this audit from a language model free-associating
about tone. Every later finding must be an outlier *from the exemplars you named*, not
from your own sense of how such a character ought to sound.

## 3. Judge

For each line, ask only: **does this contradict a specific clause of the declared
style?** Report a line only when you can name the clause.

Real finding classes:

- **Direct contradiction** — the style says "never raises voice" and the line shouts;
  "short declaratives" and the line runs four clauses; "never commits" and the line
  gives a straight yes.
- **Tic drift** — a distinctive habit named in the style appears in early files and
  vanishes in later ones. Report *where* it stops; that usually dates a handoff
  between writers.
- **Register bleed** — the line is in another character's voice. Strongest signal:
  the line would be unremarkable if attributed to a specific other character in the
  cast. Say which one.
- **Style declared but never expressed** — the field describes a voice the lines never
  perform. Distinct from a contradiction; the fix is likelier to be the field.
- **Narration wearing the character's voice** — a node with no `speakerId` inherits the
  dialogue's, so in a character-owned scene the same slot carries both their lines and
  third-person narration about them. The gather prints those as `INHERITED`: read them
  first and set aside any that are stage directions, because judging "The stair creaks
  under the weight of the pause." against a character's declared voice is judging the
  narrator. If narration in this character's scenes has adopted their tics, the scene
  has no narrator any more. Check it separately from spoken lines.

## 4. What is not a finding

Discipline here is most of the value. Do not report:

- A line you find weak, generic, or unpolished. Not this audit. Not any audit here.
- A deliberate break at a dramatic hinge. Characters break their own patterns when
  something lands — that is craft, not drift. **Before flagging any single line, check
  what happens around it in the graph.** If it sits at a reveal, a death, a betrayal,
  or a confession, the burden flips: assume intent and stay quiet unless the break
  contradicts the style in a way the moment does not explain.
- Variation across an arc. A character written as warm who is cold after the player
  betrays them is not inconsistent.
- A short functional line ("This way.") that simply had no room to express a style.
- Anything about a `## Chorus ids` entry as though it were a person.

The failure mode to avoid is a report of nineteen findings, sixteen of which are
"technically the style says X." A voice audit that flags a fifth of a character's
lines has told the author nothing and cost them an afternoon. **If more than roughly
one line in ten looks like a violation, your calibration is wrong — go back to step 2.**

## 5. Report

1. **Declared style**, quoted verbatim. Or `NO dialogueStyle DECLARED — provide one`
   and stop.
2. **Calibration** — the three exemplar lines and what each demonstrates.
3. **Findings**, each as: the quoted line (file :: node id) → the clause it
   contradicts → confidence (**clear** / **arguable**). Mark arguable ones as
   arguable; do not launder them into certainty by omitting the label.
4. **One-line verdict** — consistent, drifting (say where), or the style field is
   stale.

If the character is consistent, say so in one line. That is a real and common result,
and an audit that never returns it is not being run honestly.
