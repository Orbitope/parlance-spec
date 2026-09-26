#!/usr/bin/env python3
"""
build_choicescript_example.py — the mapping step of a ChoiceScript migration, as
a script.

ChoiceScript's flow is indentation and fall-through, and `parse_choicescript.py`
already turns that into an explicit graph — every `next`, every option's
`goto`, every `*finish` into the next scene — because it can do so exactly and a
mapper re-deriving it could only do so worse. What is left here is the part that
is a decision rather than a derivation, written down so it is reproducible:

- the whole game is ONE dialogue. `*goto_scene` and `*finish` cross scene files,
  and a Parlance `goto` is within-dialogue only, so splitting by scene file
  would sever every scene boundary.
- the registry: each variable's kind as the parser derived it, `*create`'s
  literal as the default, `writtenBy: "engine"` for `*input_text` targets, and
  one flag per `*hide_reuse`/`*disable_reuse` option (the COOKBOOK one-shot
  recipe), named after the scene and line that declared it.
- the declared `${` -> `{` rewrite, applied to every string written, exactly as
  check.py applies it to the source side.

It also builds the committed fixture (`fixtures/lighthouse_stair_imported/`), so
the fixture is the output of a procedure rather than a hand-kept file.
"""
import json
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
LIB = os.path.join(HERE, "..", "lib")
sys.path.insert(0, HERE)


def ir_of(path):
    p = subprocess.run([sys.executable, os.path.join(LIB, "parse_choicescript.py"), path,
                        "--emit", "ir"], capture_output=True, text=True)
    if p.returncode != 0:
        sys.exit(p.stderr)
    return json.loads(p.stdout)


def build(ir, ns):
    rewrites = [tuple(r) for r in ir["rewrites"]]

    def text(s):
        for a, b in rewrites:
            s = s.replace(a, b)
        return s

    nodes = []
    for n in ir["nodes"]:
        n = json.loads(json.dumps(n))
        if "text" in n:
            n["text"] = text(n["text"])
        for c in n.get("choices") or []:
            c["text"] = text(c["text"])
        nodes.append(n)
    if not ir.get("entry"):
        raise SystemExit("the game's opening produced no node — nothing to import")
    dialogue = {"id": f"dlg_{ns}", "title": ir.get("title") or "startup",
                "entry": ir["entry"], "nodes": nodes, "replayable": False}
    return [dialogue]


def variables(ir):
    out = []
    for name in sorted(ir["variableKinds"]):
        kind = ir["variableKinds"][name]
        if kind not in ("flag", "counter", "text"):
            continue
        entry = {"id": name, "kind": kind, "description": f"ChoiceScript {name}",
                 "default": ir["defaults"].get(name,
                                               {"flag": False, "counter": 0, "text": ""}[kind])}
        if name in ir["engineWritten"]:
            entry["writtenBy"] = "engine"
        out.append(entry)
    for flag, where in sorted(ir["onceFlags"].items()):
        out.append({"id": flag, "kind": "flag", "description": where, "default": False})
    return {"variables": sorted(out, key=lambda v: v["id"])}


def main():
    import argparse
    import write_project as W
    ap = argparse.ArgumentParser()
    ap.add_argument("source")
    ap.add_argument("out")
    ap.add_argument("--ns", required=True)
    a = ap.parse_args()
    ir = ir_of(a.source)
    dialogues = build(ir, a.ns)
    W.write_project(a.out, dialogues, variables(ir), {})
    print(f"{len(dialogues)} dialogue, {sum(len(d['nodes']) for d in dialogues)} nodes")


if __name__ == "__main__":
    main()
