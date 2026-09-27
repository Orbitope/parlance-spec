#!/usr/bin/env python3
"""
check.py — the deterministic gate for an import convergence loop.

An import loop that repairs its own output has exactly one dangerous failure
mode: the cheapest way to silence "flag read but never set" is to invent a
setter, and the cheapest way to satisfy a missing line is to write one. Both
turn conversion into authorship, silently, and the validator accepts the result.

So the loop does not get to decide when to stop. This script does. It runs the
reference validator AND a content-preservation check over the same output, then
returns one of:

    CONTINUE          defects remain, the last pass reduced them, keep going
    STOP converged    clean: no errors, nothing lost, nothing invented
    STOP no-progress  the last pass did not strictly reduce the defect count
    STOP cap          iteration cap reached
    STOP invented     output contains prose that is not in the source

"invented" is a hard stop and is never retried. Another repair pass cannot
un-invent a line; a human has to look.

Usage:
    python3 check.py --root <project> --manifest <manifest.json> [--reset]
                     [--validator <path to validate.py>] [--max-passes N]

Exit codes:  0 converged   1 continue   2 stop, needs a human
"""
import argparse, hashlib, json, glob, os, re, sys
from collections import Counter

STATE = ".parlance-import-state.json"

# Rewrites are a laundering channel if left unbounded: `s.replace(a, b)` with
# arbitrary a/b can turn one whole sentence into a different whole sentence and
# the comparison still passes. They exist for real, small format differences
# (Yarn's {$var} vs Parlance's {var}), so they are capped at token scale.
MAX_REWRITE_LEN = 8
MAX_REWRITES = 8

# `$name` -> `{name}`: SugarCube's naked variable re-spelled as a Parlance
# placeholder. The id side must be the source name lowercased and nothing else
# (the importers' one id derivation, conditions.var_id), so the swap can carry
# no words of its own. Anything looser is an ordinary, capped rewrite.
SIGIL = re.compile(r"^\$([A-Za-z_]\w*)$")


def is_sigil_swap(a, b):
    m = SIGIL.match(a or "")
    return bool(m) and re.match(r"^[a-z][a-z0-9_]*$", m.group(1).lower() or "") is not None \
        and b == "{" + m.group(1).lower() + "}"


sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import manifest as _manifest

# One definition, shared with the parsers. See manifest.py for why it is not
# three, and for why an ABSENT trusted field is not the same as an empty one.
manifest_digest = _manifest.digest


def norm(s, rewrites):
    """Whitespace-normalize, then apply the manifest's DECLARED rewrites.

    Real format differences exist (Yarn's {$var} vs Parlance's {var}). They are
    allowed only when the manifest names them, so every transformation between
    source and output is auditable instead of assumed.
    """
    for a, b in rewrites:
        s = s.replace(a, b)
    return re.sub(r"\s+", " ", s).strip()


def _load_json(path):
    # utf-8-sig, as validate.py reads a project: a BOM (Windows PowerShell 5.1,
    # older Notepad) is an encoding signature, not content, and json.load on a
    # plain utf-8 handle raised on it — so a BOM'd dialogue's prose reached
    # neither side of the comparison.
    with open(path, encoding="utf-8-sig") as f:
        return json.load(f)


def _data_dir(root):
    """Honour parlance.config.json's `data` override, exactly as validate.py does."""
    try:
        cfg = _load_json(os.path.join(root, "parlance.config.json"))
        return (cfg.get("data") if isinstance(cfg, dict) else None) or "data"
    except Exception:
        return "data"


# Row kinds and what each is compared against (see main):
#   line / option        a node's text, a choice's text  — the source's units;
#                        also the two counts the report leads with
#   locked / prose       a choice's lockedText; quest, codex, location, ending,
#                        item and skill prose — the source's units, like a line
#   name                 a character's name — the source's speakers and literals
#   literal              a set_text value    — the source's literals
# Not a row: a dialogue's `title`. The runtime never renders it — it labels the
# dialogue in the editor's sidebar, the way `id` does — so it is authoring
# metadata an importer may derive from a file name, not a sentence a player
# reads. Every field a player CAN read is above.
SPOKEN_KINDS = ("line", "option")
UNIT_KINDS = SPOKEN_KINDS + ("locked", "prose")

# Player-facing prose outside dialogues: (directory or registry, list key or
# None, [path]) — "*" walks a list. The same fields validate.py's TEXT pass
# interpolates, plus the names a journal or codex shows.
PROSE_FIELDS = [
    ("quests", None, [("journalName",), ("stages", "*", "description"),
                      ("stages", "*", "objectives", "*", "text"), ("outcomes", "*", "name")]),
    ("codex", None, [("name",), ("body",)]),
    ("locations", None, [("name",), ("description",)]),
    ("endings", None, [("name",), ("summary",)]),
    ("items.json", "items", [("name",), ("description",)]),
    ("skills.json", "skills", [("name",), ("description",)]),
]


def _strings_at(obj, path, where=""):
    """(where, string) for every non-empty string at `path`; "*" walks a list."""
    if not path:
        if isinstance(obj, str) and obj:
            yield where, obj
        return
    head, rest = path[0], path[1:]
    if head == "*":
        if isinstance(obj, list):
            for i, item in enumerate(obj):
                yield from _strings_at(item, rest, f"{where}[{i}]")
    elif isinstance(obj, dict) and head in obj:
        yield from _strings_at(obj[head], rest, f"{where}/{head}" if where else head)


def project_texts(root):
    """Every authored player-facing string in the project, with its kind and
    location — see the kinds table above.

    Globbed RECURSIVELY, and through the configured data dir, because that is how
    `validate.py` reads a project: dir-mode entities may be nested in zone or
    chapter subdirs, and `parlance.config.json` may move `data/` entirely.

    Reading less of the project than the validator does is not a cosmetic gap
    here. This function is the ONLY thing that computes `invented`, and invention
    is the one verdict that latches and is never retried. A flat glob meant prose
    in `data/dialogues/act1/` reached neither side of the comparison: an invented
    line there was invisible, and the whole subdir counted as missing. The
    guarantee this file exists to make — no line reaches the output that was not
    in the source — held only for projects that happened to be flat. And reading
    only node and choice text meant a lockedText, a character name, a `set_text`
    value or a quest description could say anything at all: every player-facing
    string field an importer writes is a place a sentence can be written, so
    every one of them is read here."""
    out = []
    data = os.path.join(root, _data_dir(root))
    for p in sorted(glob.glob(os.path.join(data, "dialogues", "**", "*.json"), recursive=True)):
        d = _load_json(p)
        if not isinstance(d, dict):
            continue
        did = d.get("id") or os.path.basename(p)
        for n in d.get("nodes") or []:
            if not isinstance(n, dict):
                continue
            nid = n.get("id")
            if n.get("text"):
                out.append(("line", did, nid, n["text"], n.get("showIf")))
            effects = list(n.get("onEnter") or [])
            for c in n.get("choices") or []:
                if not isinstance(c, dict):
                    continue
                if c.get("text"):
                    out.append(("option", did, f"{nid}/{c.get('id')}", c["text"], c.get("showIf")))
                if isinstance(c.get("lockedText"), str) and c["lockedText"]:
                    out.append(("locked", did, f"{nid}/{c.get('id')}/lockedText", c["lockedText"], None))
                effects += c.get("effects") or []
            for e in effects:
                if isinstance(e, dict) and e.get("type") == "set_text" \
                        and isinstance(e.get("value"), str) and e["value"]:
                    out.append(("literal", did, f"{nid}/set_text {e.get('variable')}", e["value"], None))
    for p in sorted(glob.glob(os.path.join(data, "characters", "**", "*.json"), recursive=True)):
        c = _load_json(p)
        if isinstance(c, dict) and isinstance(c.get("name"), str) and c["name"]:
            out.append(("name", c.get("id") or os.path.basename(p), "name", c["name"], None))
    for sub, list_key, paths in PROSE_FIELDS:
        if list_key is None:
            files = sorted(glob.glob(os.path.join(data, sub, "**", "*.json"), recursive=True))
            entities = [(_load_json(f), f) for f in files]
        else:
            f = os.path.join(data, sub)
            doc = _load_json(f) if os.path.exists(f) else None
            entities = [(e, f) for e in ((doc or {}).get(list_key) or [])] if isinstance(doc, dict) else []
        for e, f in entities:
            if not isinstance(e, dict):
                continue
            eid = e.get("id") or os.path.basename(f)
            for path in paths:
                for where, text in _strings_at(e, path):
                    out.append(("prose", eid, where, text, None))
    return out


def canon_condition(cond):
    """A condition as a comparable string, insensitive to the order of an
    all/any list — that order carries no meaning, and demanding it would report
    a difference where there is none."""
    if cond is None:
        return None

    def norm_cond(c):
        if not isinstance(c, dict):
            return c
        if c.get("type") in ("all", "any") and isinstance(c.get("of"), list):
            return {**c, "of": sorted((norm_cond(x) for x in c["of"]),
                                      key=lambda x: json.dumps(x, sort_keys=True))}
        if "of" in c:
            return {**c, "of": norm_cond(c["of"])}
        return c

    return json.dumps(norm_cond(cond), sort_keys=True, ensure_ascii=False)


def condition_defects(units, got_rows, rewrites):
    """Guards the output does not agree with the manifest about.

    This is the one defect class the string comparison structurally cannot see.
    Both Yarn and Ink write an `else` branch without restating what it is the
    alternative to, so the tempting mapping gives both branches the SAME guard —
    and then, whenever it holds, the player reads two lines where the author
    wrote one. Nothing is missing and nothing is invented, so `missing` and
    `invented` are both empty and the import converges on a defect.

    Two directions, because either alone leaves half the hole open:
    a mapped guard that the output dropped or altered, and a gate on output text
    the source did not gate at all. A unit the parser declared UNMAPPABLE is left
    out of the second check on purpose — carrying one of those by hand is the
    documented escape hatch, and the author is already being shown it.
    """
    want = {}
    for u in units:
        if not u.get("text"):
            continue
        key = norm(u["text"], rewrites)
        if u.get("showIf"):
            want.setdefault(key, []).append(canon_condition(u["showIf"]))
        elif not u.get("unmappable"):
            want.setdefault(key, []).append(None)

    got = {}
    for _kind, did, nid, text, cond in got_rows:
        got.setdefault(norm(text, []), []).append((f"{did}::{nid}", canon_condition(cond)))

    out = []
    for key, expected in sorted(want.items()):
        present = got.get(key)
        if not present:
            continue        # a missing line, already counted as such
        for exp in sorted(set(expected), key=lambda x: (x is None, x or "")):
            if any(actual == exp for _at, actual in present):
                continue
            out.append({"text": key,
                        "expected": json.loads(exp) if exp else None,
                        "found": [{"at": at, "showIf": json.loads(a) if a else None}
                                  for at, a in present]})
    return out


def run_validator(root, validator_path):
    """Import the reference validator as a library rather than parsing stdout.

    validate.py is MIT and vendored verbatim by engine ports, so this reads it
    instead of asking for a --json flag it does not have.
    """
    vdir = os.path.dirname(os.path.abspath(validator_path))
    sys.path.insert(0, vdir)
    try:
        import validate as V
    except ImportError as e:
        return None, [f"could not import validator from {vdir}: {e}"]
    finally:
        sys.path.pop(0)
    v = V.validate_project(root)
    errs = [f"[{i.code}] {i.message}" for i in v.errors]
    warns = [f"[{i.code}] {i.message}" for i in v.warnings]
    return {"errors": errs, "warnings": warns}, []


def verify_manifest(man):
    """0 if this manifest is the one a parser produced, else the exit code to use."""
    # Presence first, because a MISSING field is the quiet failure. Reading each
    # one with a default made `residue` absent indistinguishable from `residue`
    # empty: deleting the key from a stamped manifest left the stamp valid and
    # skipped the residue gate outright, and a parser at a pre-residue version
    # did the same thing without anyone editing anything.
    absent = _manifest.missing_fields(man)
    if absent:
        print(f"MANIFEST INCOMPLETE — no {', '.join(absent)}. Every field this gate "
              "trusts must be present, because a field it cannot see is a field it "
              "cannot check. Re-emit the manifest with the parser at this version.",
              file=sys.stderr)
        return 2

    stamped = (man.get("integrity") or {}).get("sha256")
    actual = manifest_digest(man)
    if not stamped:
        print("MANIFEST NOT STAMPED — re-emit it with the parser at this version. "
              "An unstamped manifest cannot be distinguished from an edited one.",
              file=sys.stderr)
        return 2
    if stamped != actual:
        print(f"MANIFEST TAMPERED — stamped {stamped[:12]}, computed {actual[:12]}. "
              "Units, rewrites or residue changed after parsing. Re-parse the source; do not "
              "hand-edit a manifest to make the check pass.", file=sys.stderr)
        return 2
    return 0


def merge_manifests(parts):
    """Several per-file manifests as one yardstick.

    A story split across files is parsed per file and imported into one project,
    so the comparison needs every file's units at once. Each part is verified
    against its OWN stamp first (see verify_manifest) and the merge happens after
    — a stamp recomputed here over this script's own input would not be a stamp,
    and would wave through exactly the hand-edit the check exists to refuse. The
    merged object is never re-stamped and never written anywhere.

    Rewrites must agree across parts: they are a property of the FORMAT, and two
    files of one story parsed by one parser cannot legitimately declare different
    ones.
    """
    if len(parts) == 1:
        return parts[0]
    rewrites = [[tuple(r) for r in p["rewrites"]] for p in parts]
    if any(r != rewrites[0] for r in rewrites):
        sys.exit("MANIFESTS DISAGREE ON REWRITES — they describe the format, not the "
                 "file, so two parts of one story cannot declare different ones.")
    merged = dict(parts[0])
    for key in ("units", "unmapped", "residue", "literals"):
        merged[key] = [x for p in parts for x in p.get(key, [])]
    merged["sources"] = [p.get("source") for p in parts]
    merged["nodes"] = [n for p in parts for n in p.get("nodes", [])]
    return merged


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", required=True)
    ap.add_argument("--manifest", required=True, action="append",
                    help="repeatable: a story split across files is parsed per file, "
                         "and every manifest is verified separately before they are "
                         "compared against one project")
    ap.add_argument("--validator", default=None,
                    help="path to tooling/validate.py (default: search upward)")
    ap.add_argument("--max-passes", type=int, default=3)
    ap.add_argument("--reset", action="store_true", help="start a new loop")
    a = ap.parse_args()

    parts = [json.load(open(m, encoding="utf-8")) for m in a.manifest]

    # --- the manifest must be the one the parser produced -------------------
    # Checked per FILE, before anything is merged. Verifying a merged manifest
    # would mean re-stamping it here, and a stamp this script computes over its
    # own input is not a stamp — it would accept exactly the hand-edit the check
    # exists to refuse.
    for one in parts:
        code = verify_manifest(one)
        if code:
            return code
    man = merge_manifests(parts)

    rewrites = [tuple(r) for r in man["rewrites"]]
    # A sigil swap (`$name` -> `{name}`) is exempt from both caps: it is one
    # variable token re-spelled in Parlance's interpolation syntax, provably
    # unable to turn one sentence into another — and a story interpolates as
    # many variables as it has, with names longer than eight characters.
    capped = [r for r in rewrites if not is_sigil_swap(*r)]
    if len(capped) > MAX_REWRITES:
        print(f"TOO MANY REWRITES ({len(capped)} > {MAX_REWRITES}).", file=sys.stderr)
        return 2
    for a_, b_ in capped:
        if len(a_) > MAX_REWRITE_LEN or len(b_) > MAX_REWRITE_LEN:
            print(f"REWRITE TOO WIDE: {a_!r} -> {b_!r}. A rewrite covers a format token "
                  f"(max {MAX_REWRITE_LEN} chars), never a phrase — a wide rewrite can "
                  "turn one sentence into another and still compare equal.", file=sys.stderr)
            return 2

    # Units the parser marked unmappable are DECLARED loss: the author is told
    # about them, but they must not block convergence. If they did, no story with
    # a conditional narration line could ever converge, and the loop's cheapest
    # escape would be to fabricate a mapping — the exact failure this guards.
    mappable = [u for u in man["units"] if u.get("text") and not u.get("unmappable")]
    declared = [u for u in man["units"] if u.get("text") and u.get("unmappable")]
    src = Counter(norm(u["text"], rewrites) for u in mappable)
    got_rows = project_texts(a.root)
    spoken_rows = [r for r in got_rows if r[0] in SPOKEN_KINDS]
    # Prose of every kind is held to the units: a lockedText or a quest
    # description is a sentence a player reads, and the source either wrote it
    # or did not.
    got = Counter(norm(t, []) for k, _, _, t, _c in got_rows if k in UNIT_KINDS)

    missing = src - got          # in the source, absent from the output
    invented = got - src         # in the output, absent from the source

    # Strings the source WROTE rather than spoke have their own yardsticks: a
    # character name is a speaker (or a `define`d display name the parser
    # listed as a literal); a set_text value is a literal. Each is checked
    # against ITS yardstick and no other, so a string assigned to a variable
    # cannot vouch for a line, nor a speaker for a set_text value. Anything
    # outside its yardstick is invention.
    literals_ok = {norm(s, rewrites) for s in man["literals"] if isinstance(s, str)}
    speakers_ok = {norm(u["speaker"], rewrites) for u in man["units"]
                   if isinstance(u.get("speaker"), str)} | literals_ok
    yardstick = {"name": speakers_ok, "literal": literals_ok}
    for k, _did, _nid, t, _c in got_rows:
        if k in yardstick and norm(t, []) not in yardstick[k]:
            invented[norm(t, [])] += 1
    # A declared-unmappable line found in the output was mapped by hand. Fine —
    # it is neither loss nor invention, so clear it from both sides.
    for u in declared:
        t = norm(u["text"], rewrites)
        if t in invented:
            del invented[t]

    where = {}
    for kind, did, nid, t, _cond in got_rows:
        where.setdefault(norm(t, []), []).append(f"{did}::{nid}")

    src_lines = sum(1 for u in mappable if u.get("kind") == "line")
    src_opts = sum(1 for u in mappable if u.get("kind") == "option")
    got_lines = sum(1 for k, *_ in got_rows if k == "line")
    got_opts = sum(1 for k, *_ in got_rows if k == "option")
    output_strings = dict(sorted(Counter(k for k, *_ in got_rows).items()))

    vpath = a.validator
    if not vpath:
        # Two layouts, because these files are published as well as developed in.
        # Upstream the validator is tooling/validate.py; the publish map remaps it
        # to validate/validate.py in parlance-spec, so a reader who clones the
        # PUBLIC repo and runs the command an example's REPORT.md gives them hit
        # "validator not found" — the one command the examples exist to offer.
        # Search both rather than documenting a different command per repo.
        rel = (("tooling", "validate.py"), ("validate", "validate.py"))
        d = os.path.abspath(a.root)
        while d != os.path.dirname(d) and not vpath:
            for parts in rel:
                c = os.path.join(d, *parts)
                if os.path.exists(c):
                    vpath = c
                    break
            d = os.path.dirname(d)
    vres, verr = (run_validator(a.root, vpath) if vpath else (None, ["validator not found"]))

    n_err = len(vres["errors"]) if vres else 0
    cond_defects = condition_defects(man["units"], spoken_rows, rewrites)
    defects = (sum(missing.values()) + n_err + len(cond_defects)
               + abs(src_lines - got_lines) + abs(src_opts - got_opts))

    statep = os.path.join(a.root, STATE)
    prev = {}
    if os.path.exists(statep) and not a.reset:
        prev = json.load(open(statep, encoding="utf-8"))
    npass = prev.get("pass", 0) + 1

    # Invention LATCHES. The verdict used to be written to state and never read
    # back, so a pass that invented prose could be followed by one that converged
    # with the invented line still in the project — the exact opposite of the
    # documented "never retried". Only --reset clears it, and that is a
    # deliberate human act on a project someone has looked at.
    # A gate that cannot run half of itself must say so, not shrug. Without this
    # a missing validator produced defects=0 and a CONTINUE, so a loop could run
    # to its cap having never validated anything — and the run looks ordinary.
    if verr:
        print("VALIDATOR DID NOT RUN — " + "; ".join(verr) +
              "\nPass --validator <path to tooling/validate.py>. Half a gate is not a gate.",
              file=sys.stderr)
        return 2

    # Residue is unaccounted SOURCE prose — the parser lost it before the manifest
    # existed, so no amount of comparing the project to the manifest can see it.
    # It blocks convergence outright: the yardstick itself is short.
    residue = man["residue"]
    if residue:
        print(f"SOURCE NOT FULLY ACCOUNTED FOR — {len(residue)} line(s) contain words that "
              "reached no unit, no declared loss, and no recognised command:", file=sys.stderr)
        for r in residue[:8]:
            print(f"  line {r['lineno']}: {' '.join(r['words'][:12])}   |  {r['line']}", file=sys.stderr)
        if len(residue) > 8:
            print(f"  ... and {len(residue) - 8} more lines", file=sys.stderr)
        print("This is a PARSER gap, not an import mistake. Do not hand-map around it.",
              file=sys.stderr)
        return 2

    latched = bool(prev.get("invented_latched"))
    if invented or latched:
        verdict, code = "STOP invented", 2
    elif defects == 0 and not verr:
        verdict, code = "STOP converged", 0
    elif npass >= a.max_passes:
        verdict, code = "STOP cap", 2
    elif prev and defects >= prev.get("defects", 10**9):
        verdict, code = "STOP no-progress", 2
    else:
        verdict, code = "CONTINUE", 1

    json.dump({"pass": npass, "defects": defects, "verdict": verdict,
               "invented_latched": bool(invented or latched)},
              open(statep, "w", encoding="utf-8"), indent=1)

    report = {
        "verdict": verdict,
        "pass": npass,
        "defects": defects,
        "previous_defects": prev.get("defects"),
        "validator": {"errors": (vres or {}).get("errors", []),
                      "warnings": (vres or {}).get("warnings", [])},
        "validator_problems": verr,
        "counts": {"source_lines": src_lines, "output_lines": got_lines,
                   "source_options": src_opts, "output_options": got_opts},
        # Every string field read, by kind — so a reader can see the comparison
        # covered the titles, names and literals as well as the lines.
        "output_strings": output_strings,
        "missing_unexplained": [{"text": t, "n": c} for t, c in missing.most_common()],
        "missing_declared": [{"text": u["text"], "why": u["unmappable"],
                              "node": u.get("node"), "lineno": u.get("lineno")}
                             for u in declared
                             if norm(u["text"], rewrites) not in got],
        "invented": [{"text": t, "n": c, "at": where.get(t, [])}
                     for t, c in invented.most_common()],
        "condition_mismatch": cond_defects,
        "rewrites_declared": [list(r) for r in rewrites],
    }
    print(json.dumps(report, indent=2, ensure_ascii=False))

    if verdict == "STOP invented":
        note = "" if invented else " (latched from an earlier pass — the invented text was removed, but this import needs a human before it can converge)"
        print(f"\n*** Output contains prose that is not in the source.{note} This is not a "
              "repairable defect:\n*** a further pass cannot un-invent a line. Stop and "
              "show these to the author.", file=sys.stderr)
    return code


if __name__ == "__main__":
    sys.exit(main())
