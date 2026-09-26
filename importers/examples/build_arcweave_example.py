#!/usr/bin/env python3
"""
build_arcweave_example.py — the mapping step of an Arcweave migration, as a script.

Same standing as its siblings: the skill has a model do the mapping, and for a
fixture that is neither reliable nor reproducible, so the decisions are written
down as code. `check.py` still decides whether the result is faithful.

Arcweave is already a graph, which makes the mapping short. An element is a
scene: its paragraphs become nodes chained by `next`, and its outputs hang off
the last of them — one unlabelled output as `next`, labelled outputs as
choices, none as the end. A jumper is just the element it points at. The parser
has already turned a labelled route through a branch into one gated choice per
arm, so the only structural judgment left here is which elements share a
dialogue.

Every player-facing string is copied from the parser's IR byte for byte.
Nothing here composes a string, fills an optional field, or invents an id: node
ids come from element titles, choice ids from labels, character ids from
component names.
"""
import json
import os
import re
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
LIB = os.path.join(HERE, "..", "lib")


def slug(s):
    out = re.sub(r"[^a-z0-9]+", "_", (s or "").lower()).strip("_")
    return out if re.match(r"^[a-z]", out or "") else ("x_" + out if out else "x")


def ir_of(path):
    p = subprocess.run([sys.executable, os.path.join(LIB, "parse_arcweave.py"), path,
                        "--emit", "ir"], capture_output=True, text=True)
    if p.returncode != 0:
        sys.exit(p.stderr)
    return json.loads(p.stdout)


class Builder:
    def __init__(self, ir, ns):
        self.ir, self.ns = ir, ns
        self.nodes, self.owner, self.entry = {}, {}, {}
        self.seen, self.notes = {}, []
        self.char_id = {cid: slug(name) for cid, name in ir["characters"].items() if name}

    def uid(self, base):
        self.seen[base] = self.seen.get(base, 0) + 1
        n = self.seen[base]
        return base if n == 1 else f"{base}_{n}"

    def title_of(self, el):
        return el.get("title") or el["id"]

    def emit(self, el):
        """One element as a chain of nodes; returns (first node, last node)."""
        first = prev = None
        base = f"n_{self.ns}_" + "_".join(slug(self.title_of(el)).split("_")[:4])
        for it in el["items"]:
            if it.get("unmappable"):
                continue
            n = {"id": self.uid(base), "text": it["text"]}
            if it.get("speaker") in self.char_id:
                n["speakerId"] = self.char_id[it["speaker"]]
            if it.get("showIf"):
                n["showIf"] = it["showIf"]
            if it.get("effects"):
                n["onEnter"] = list(it["effects"])
            self.nodes[n["id"]] = n
            self.owner[n["id"]] = el["id"]
            if prev is not None:
                prev["next"] = n["id"]
            first = first or n
            prev = n
        options = [r for r in el["routes"] if r["kind"] == "option" and not r.get("unmappable")]
        gated_fx = prev is not None and prev.get("showIf") and (
            prev.get("onEnter") or el.get("trailingEffects"))
        if options and (prev is None or gated_fx):
            # Choices with no line before them: a text-less choice node (0.15).
            # Also when the last line is GATED and carries effects: on a node
            # with choices a failed gate hides only the line and onEnter still
            # fires, so the choices move to a node of their own and the gated
            # line stays interstitial — skipped, effects and all.
            n = {"id": self.uid(base)}
            self.nodes[n["id"]] = n
            self.owner[n["id"]] = el["id"]
            if prev is not None:
                prev["next"] = n["id"]
            first = first or n
            prev = n
        if prev is not None and el.get("trailingEffects"):
            if prev.get("showIf") and not options:
                # Skipped, it would not fire them; as an end it would, but an
                # interstitial is the common case and the difference is silent.
                raise SystemExit(f"{prev['id']}: unguarded effects would ride on a "
                                 "gated line")
            prev["onEnter"] = prev.get("onEnter", []) + el["trailingEffects"]
        return first, prev

    def finish(self, el, last):
        """Hang an element's outputs off its last node."""
        routes = [r for r in el["routes"] if not r.get("unmappable")]
        options = [r for r in routes if r["kind"] == "option"]
        nxt = [r for r in routes if r["kind"] == "next"]
        if options:
            last.pop("next", None)
            last["choices"] = []
            for r in options:
                c = {"id": self.uid(f"c_{self.ns}_" + "_".join(slug(r["text"]).split("_")[:4])),
                     "text": r["text"]}
                if r.get("showIf"):
                    c["showIf"] = r["showIf"]
                target = self.resolve(r["target"])
                if target:
                    c["goto"] = target
                last["choices"].append(c)
        elif nxt and self.resolve(nxt[0]["target"]):
            last["next"] = self.resolve(nxt[0]["target"])
        else:
            last["isEnd"] = True
        if last.get("showIf") and last.get("onEnter") and last.get("isEnd"):
            # A line-only gate on an end fires onEnter even when the line is
            # hidden, which would make guarded effects unconditional.
            raise SystemExit(f"{last['id']}: a gated last beat carries effects the "
                             "gate would no longer hold back")

    def resolve(self, eid, seen=()):
        """An element's first node, passing through elements that carry nothing."""
        while eid and eid not in seen:
            seen = seen + (eid,)
            if self.entry.get(eid):
                return self.entry[eid]
            el = self.by_id.get(eid)
            nxt = [r for r in (el or {}).get("routes", []) if r["kind"] == "next"]
            eid = nxt[0]["target"] if el and nxt else None
        return None


def build(ir, ns):
    b = Builder(ir, ns)
    b.by_id = {el["id"]: el for el in ir["elements"]}
    lasts = {}
    for el in ir["elements"]:
        first, last = b.emit(el)
        if first:
            b.entry[el["id"]] = first["id"]
            lasts[el["id"]] = last
    for el in ir["elements"]:
        if el["id"] in lasts:
            b.finish(el, lasts[el["id"]])

    # Elements joined by a route become ONE dialogue: a Parlance `goto` is
    # within-dialogue only.
    parent = {el["id"]: el["id"] for el in ir["elements"]}

    def find(a):
        while parent[a] != a:
            parent[a] = parent[parent[a]]
            a = parent[a]
        return a

    for el in ir["elements"]:
        for r in el["routes"]:
            t = r.get("target")
            if t in parent and not r.get("unmappable") and find(t) != find(el["id"]):
                parent[find(t)] = find(el["id"])

    groups = {}
    for el in ir["elements"]:
        groups.setdefault(find(el["id"]), []).append(el["id"])
    out = []
    for comp in groups.values():
        members = set(comp)
        nodes = [n for n in b.nodes.values() if b.owner[n["id"]] in members]
        head = ir["start"] if ir.get("start") in members else comp[0]
        entry = b.resolve(head) or next((b.resolve(e) for e in comp if b.resolve(e)), None)
        if not nodes or entry is None:
            continue
        title = b.title_of(b.by_id[head])
        out.append({"id": "dlg_" + "_".join([ns] + slug(title).split("_")[:4]),
                    "title": title, "entry": entry, "nodes": nodes,
                    "replayable": False})
    placed = {n["id"] for d in out for n in d["nodes"]}
    missing = [nid for nid in b.nodes if nid not in placed]
    if missing:
        raise SystemExit(f"{len(missing)} nodes belong to no dialogue and would be "
                         f"dropped silently: {missing[:5]}")
    return b, out


def write(root, ir, ns):
    """Build and write a project from one parsed export. Returns the builder."""
    sys.path.insert(0, HERE)
    import write_project as W
    b, dialogues = build(ir, ns)
    used = {n.get("speakerId") for d in dialogues for n in d["nodes"]} - {None}
    chars = {b.char_id[c]: {"id": b.char_id[c], "name": name}
             for c, name in sorted(ir["characters"].items())
             if c in b.char_id and b.char_id[c] in used}
    ladders = {}
    for d in dialogues:
        for n in d["nodes"]:
            sid = n.get("speakerId")
            if sid and d["id"] not in ladders.setdefault(sid, []):
                ladders[sid].append(d["id"])
    W.write_project(root, W.offer_entries(dialogues, ladders),
                    W.variables_of(ir["variableKinds"], ir["defaults"], "Arcweave variable"),
                    chars)
    return b, dialogues
