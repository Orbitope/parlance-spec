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


def _data_dir(root):
    """Honour parlance.config.json's `data` override, exactly as validate.py does."""
    try:
        with open(os.path.join(root, "parlance.config.json"), encoding="utf-8") as f:
            return json.load(f).get("data") or "data"
    except Exception:
        return "data"


def project_texts(root):
    """Every authored player-facing string in the project, with its location.

    Globbed RECURSIVELY, and through the configured data dir, because that is how
    `validate.py` reads a project: dir-mode entities may be nested in zone or
    chapter subdirs, and `parlance.config.json` may move `data/` entirely.

    Reading less of the project than the validator does is not a cosmetic gap
    here. This function is the ONLY thing that computes `invented`, and invention
    is the one verdict that latches and is never retried. A flat glob meant prose
    in `data/dialogues/act1/` reached neither side of the comparison: an invented
    line there was invisible, and the whole subdir counted as missing. The
    guarantee this file exists to make — no line reaches the output that was not
    in the source — held only for projects that happened to be flat."""
    out = []
    pat = os.path.join(root, _data_dir(root), "dialogues", "**", "*.json")
    for p in sorted(glob.glob(pat, recursive=True)):
        d = json.load(open(p, encoding="utf-8"))
        for n in d.get("nodes", []):
            if n.get("text"):
                out.append(("line", d["id"], n["id"], n["text"], n.get("showIf")))
            for c in n.get("choices") or []:
                if c.get("text"):
                    out.append(("option", d["id"], f"{n['id']}/{c['id']}", c["text"],
                                c.get("showIf")))
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
    for key in ("units", "unmapped", "residue"):
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
    if len(rewrites) > MAX_REWRITES:
        print(f"TOO MANY REWRITES ({len(rewrites)} > {MAX_REWRITES}).", file=sys.stderr)
        return 2
    for a_, b_ in rewrites:
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
    got = Counter(norm(t, []) for _, _, _, t, _c in got_rows)

    missing = src - got          # in the source, absent from the output
    invented = got - src         # in the output, absent from the source
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
    cond_defects = condition_defects(man["units"], got_rows, rewrites)
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
