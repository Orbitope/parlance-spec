#!/usr/bin/env python3
"""
build_sugarcube_example.py — the mapping step of a SugarCube migration, as a script.

Same standing as its Yarn, Ink and Twine siblings: the skill has a model do the
mapping, and at the scale of a worked example that is neither reliable nor
reproducible, so the decisions are written down as code. `check.py` still
decides whether the result is faithful. It also builds the committed fixture
project (`fixtures/cellar_door_imported/`), so the fixture is the output of a
procedure rather than a hand-kept file.

The shape is Twine's — a passage is a scene of beats with all its links on the
last beat, and link-connected passages share one dialogue — with the three
decisions a SugarCube passage adds already made by the parser:

- every state change arrives with a `carrier` (the beat whose `onEnter` it
  rides, or "exit" for the text-less node holding a linkless passage's
  choices); a change the parser could not carry is not in the IR at all.
- a top-level `<<goto>>` is the passage's exit: its last beat's `next`.
- the declared `$name` -> `{name}` rewrites are applied to every string this
  writes, which is exactly what check.py applies to the source side.

Every player-facing string is copied from the parser's IR byte for byte, apart
from those declared sigil swaps. Nothing here composes a string, fills an
optional field, or invents an id.
"""
import json
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
LIB = os.path.join(HERE, "..", "lib")
sys.path.insert(0, HERE)

from build_twine_example import slug      # noqa: E402  one id derivation, shared


def ir_of(path):
    p = subprocess.run([sys.executable, os.path.join(LIB, "parse_sugarcube.py"), path,
                        "--emit", "ir"], capture_output=True, text=True)
    if p.returncode != 0:
        sys.exit(p.stderr)
    return json.loads(p.stdout)


class Builder:
    def __init__(self, ir, ns):
        self.ns = ns
        self.passages = {n["title"]: n for n in ir["nodes"]}
        self.order = [n["title"] for n in ir["nodes"]]
        self.kinds = dict(ir["variableKinds"])
        self.rewrites = [tuple(r) for r in ir["rewrites"]]
        self.nodes, self.owner, self.entry_of, self.alias = {}, {}, {}, {}
        self.seen_ids = {}
        self.notes = []

    def text(self, s):
        for a, b in self.rewrites:
            s = s.replace(a, b)
        return s

    def uid(self, base):
        self.seen_ids[base] = self.seen_ids.get(base, 0) + 1
        n = self.seen_ids[base]
        return base if n == 1 else f"{base}_{n}"

    def node_id(self, title):
        return self.uid(f"n_{self.ns}_{slug(title)}")

    def choice_id(self, text):
        return self.uid(f"c_{self.ns}_" + "_".join(slug(text).split("_")[:4]))

    def emit(self, title):
        p = self.passages[title]
        by_index, chain, links, exit_fx = {}, [], [], []
        for it in p["items"]:
            if it["kind"] == "line" and not it.get("unmappable"):
                node = {"id": self.node_id(title), "text": self.text(it["text"])}
                if it.get("showIf"):
                    node["showIf"] = it["showIf"]
                by_index[it["index"]] = node
                chain.append(node)
            elif it["kind"] == "option" and not it.get("unmappable"):
                links.append(it)
        for it in p["items"]:
            if it["kind"] != "command" or not it.get("parlance"):
                continue
            c = it.get("carrier")
            if c == "exit":
                exit_fx += it["parlance"]
            elif c is not None:
                by_index[c].setdefault("onEnter", []).extend(it["parlance"])

        for a, z in zip(chain, chain[1:]):
            a["next"] = z["id"]
        ex = p["exit"]
        if ex["kind"] == "choices":
            if not chain:
                host = {"id": self.node_id(title)}     # text-less: legal since 0.15
                if exit_fx:
                    host["onEnter"] = exit_fx
                chain.append(host)
            last = chain[-1]
            for it in links:
                ch = {"id": self.choice_id(it["text"]), "text": self.text(it["text"]),
                      "goto": "@" + it["target"]}
                if it.get("showIf"):
                    ch["showIf"] = it["showIf"]
                if it.get("parlance"):
                    ch["effects"] = it["parlance"]
                last.setdefault("choices", []).append(ch)
        elif ex["kind"] == "goto":
            if chain:
                chain[-1]["next"] = "@" + ex["target"]
            else:
                self.alias[title] = ex["target"]
        elif chain:
            chain[-1]["isEnd"] = True
        for node in chain:
            self.nodes[node["id"]] = node
            self.owner[node["id"]] = title
        if chain:
            self.entry_of[title] = chain[0]["id"]

    def resolve(self, title):
        """A passage's first node, following passages that only `<<goto>>` on."""
        seen = set()
        while title in self.alias and title not in seen:
            seen.add(title)
            title = self.alias[title]
        return self.entry_of.get(title)


def build(ir, ns):
    b = Builder(ir, ns)
    for title in b.order:
        b.emit(title)

    for n in b.nodes.values():
        if isinstance(n.get("next"), str) and n["next"].startswith("@"):
            target = b.resolve(n["next"][1:])
            if target:
                n["next"] = target
            else:
                b.notes.append(f"`<<goto>>` to '{n['next'][1:]}', which produced no node "
                               f"— the dialogue ends there")
                del n["next"]
                if n.get("showIf"):
                    n.pop("showIf")
                    b.notes.append(f"{n['id']}: guard dropped with the jump it sat before")
                n["isEnd"] = True
        for c in n.get("choices") or []:
            target = b.resolve(c["goto"][1:])
            if target:
                c["goto"] = target
            else:
                b.notes.append(f"link to '{c['goto'][1:]}', which produced no node — "
                               f"choosing it ends the dialogue")
                del c["goto"]
                n["isEnd"] = True     # a gotoless choice ends only on an isEnd node

    # Passages joined by a link or a jump share a dialogue: a `goto` is
    # within-dialogue only. Undirected, as in the Twine builder.
    parent = {t: t for t in b.order}

    def find(a):
        while parent[a] != a:
            parent[a] = parent[parent[a]]
            a = parent[a]
        return a

    for link in ir["links"]:
        a, z = link["from"], link["to"]
        if a in parent and z in parent and find(a) != find(z):
            parent[find(z)] = find(a)
    groups = {}
    for t in b.order:
        groups.setdefault(find(t), []).append(t)

    out = []
    for comp in [groups[r] for r in dict.fromkeys(find(t) for t in b.order)]:
        members = set(comp)
        nodes = [n for n in b.nodes.values() if b.owner.get(n["id"]) in members]
        ordered = ([ir["start"]] if ir.get("start") in members else []) + comp
        entry = next((b.resolve(t) for t in ordered if b.resolve(t)), None)
        if not nodes or entry is None:
            continue
        title = ir["start"] if ir.get("start") in members else comp[0]
        out.append({"id": f"dlg_{ns}_{slug(title)}", "title": title,
                    "entry": entry, "nodes": nodes, "replayable": False})

    placed = {n["id"] for d in out for n in d["nodes"]}
    missing = [nid for nid in b.nodes if nid not in placed]
    if missing:
        raise SystemExit(f"{len(missing)} nodes belong to no dialogue and would be "
                         f"dropped silently: {missing[:5]}")
    return b, out


def variables(ir):
    """The registry: kinds as the parser derived them, StoryInit's literal
    assignments as defaults, and a variable an input widget writes marked
    `writtenBy: "engine"` — the data's way of saying the player types it."""
    out = []
    for name in sorted(ir["variableKinds"]):
        kind = ir["variableKinds"][name]
        if kind not in ("flag", "counter", "text") or name.startswith("_"):
            continue
        entry = {"id": name.lower(), "kind": kind, "description": f"SugarCube ${name}",
                 "default": ir["defaults"].get(name,
                                               {"flag": False, "counter": 0, "text": ""}[kind])}
        if name in ir["engineWritten"]:
            entry["writtenBy"] = "engine"
        out.append(entry)
    return {"variables": out}


def main():
    import argparse
    import write_project as W
    ap = argparse.ArgumentParser()
    ap.add_argument("source")
    ap.add_argument("out")
    ap.add_argument("--ns", required=True)
    a = ap.parse_args()
    ir = ir_of(a.source)
    b, dialogues = build(ir, a.ns)
    W.write_project(a.out, dialogues, variables(ir), {})
    print(f"{len(dialogues)} dialogues, {sum(len(d['nodes']) for d in dialogues)} nodes")
    for n in b.notes:
        print("  note:", n)


if __name__ == "__main__":
    main()
