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
                out.append(("line", d["id"], n["id"], n["text"]))
            for c in n.get("choices") or []:
                if c.get("text"):
                    out.append(("option", d["id"], f"{n['id']}/{c['id']}", c["text"]))
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


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", required=True)
    ap.add_argument("--manifest", required=True)
    ap.add_argument("--validator", default=None,
                    help="path to tooling/validate.py (default: search upward)")
    ap.add_argument("--max-passes", type=int, default=3)
    ap.add_argument("--reset", action="store_true", help="start a new loop")
    a = ap.parse_args()

    man = json.load(open(a.manifest, encoding="utf-8"))

    # --- the manifest must be the one the parser produced -------------------
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
    got = Counter(norm(t, []) for _, _, _, t in got_rows)

    missing = src - got          # in the source, absent from the output
    invented = got - src         # in the output, absent from the source
    # A declared-unmappable line found in the output was mapped by hand. Fine —
    # it is neither loss nor invention, so clear it from both sides.
    for u in declared:
        t = norm(u["text"], rewrites)
        if t in invented:
            del invented[t]

    where = {}
    for kind, did, nid, t in got_rows:
        where.setdefault(norm(t, []), []).append(f"{did}::{nid}")

    src_lines = sum(1 for u in mappable if u.get("kind") == "line")
    src_opts = sum(1 for u in mappable if u.get("kind") == "option")
    got_lines = sum(1 for k, _, _, _ in got_rows if k == "line")
    got_opts = sum(1 for k, _, _, _ in got_rows if k == "option")

    vpath = a.validator
    if not vpath:
        d = os.path.abspath(a.root)
        while d != os.path.dirname(d):
            c = os.path.join(d, "tooling", "validate.py")
            if os.path.exists(c):
                vpath = c
                break
            d = os.path.dirname(d)
    vres, verr = (run_validator(a.root, vpath) if vpath else (None, ["validator not found"]))

    n_err = len(vres["errors"]) if vres else 0
    defects = sum(missing.values()) + n_err + abs(src_lines - got_lines) + abs(src_opts - got_opts)

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
