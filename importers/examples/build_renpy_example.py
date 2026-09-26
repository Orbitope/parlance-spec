#!/usr/bin/env python3
"""
build_renpy_example.py — the mapping step of a Ren'Py migration, as a script.

Same standing as its siblings: the skill has a model do the mapping, and for a
worked example or a fixture that is neither reliable nor reproducible, so the
decisions are written down as code. `check.py` still decides whether the result
is faithful.

Ren'Py maps closely, because a Ren'Py script is already a sequence of beats. A
label is a run of statements; a say statement is a node; `menu:` is a node with
choices whose blocks run and then FALL THROUGH to whatever follows the menu; a
label with no `jump` or `return` at its end falls through into the next label
in the file. Every one of those is an ordinary `next` or `goto`.

The graph is built BACKWARDS through each statement list: a statement's
successor is whatever the rest of its scope reaches, so walking from the end
knows the answer at every step. Forward construction has to patch edges in
after the fact, and a patched edge is where a fall-through goes missing.

Every player-facing string is copied from the parser's IR byte for byte, with
one declared, token-for-token rewrite: Ren'Py's `[var]` interpolation becomes
Parlance's `{var}`, and the parser only lets that through where `var` is a
registered text variable. Nothing here composes a string, fills an optional
field, or invents an id.
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
    p = subprocess.run([sys.executable, os.path.join(LIB, "parse_renpy.py"), path,
                        "--emit", "ir"], capture_output=True, text=True)
    if p.returncode != 0:
        sys.exit(p.stderr)
    return json.loads(p.stdout)


def interp(text):
    """`[name]` → `{name}`: the rewrite the manifest declares, and nothing else."""
    return text.replace("[", "{").replace("]", "}")


class Builder:
    def __init__(self, ir, ns):
        self.ir, self.ns = ir, ns
        self.labels = {lab["name"]: lab for lab in ir["labels"]}
        self.order = [lab["name"] for lab in ir["labels"]]
        self.nodes, self.owner = {}, {}
        self.entry = {}            # label (or menu label) -> node id or "@label" or None
        self.edges = []            # (label, label) — for grouping into dialogues
        self.notes = []
        self.counts = {}
        self.cur = None

    def uid(self, prefix):
        key = f"{prefix}_{self.ns}_{slug(self.cur)}"
        self.counts[key] = self.counts.get(key, 0) + 1
        n = self.counts[key]
        return key if n == 1 else f"{key}_{n}"

    def node(self, **fields):
        nid = self.uid("n")
        n = {"id": nid, **{k: v for k, v in fields.items() if v not in (None, [], "")}}
        self.nodes[nid] = n
        self.owner[nid] = self.cur
        return n

    def link(self, n, cont):
        """Point a node at its continuation: a node id, `@label`, or the end."""
        if cont is None:
            n["isEnd"] = True
        else:
            n["next"] = cont

    def seq(self, items, cont):
        """The entry of a statement list whose successor is `cont`.

        Items are visited LAST first, so each one knows what follows it. Nodes
        are pre-allocated in source order (see `alloc`) so ids read top to
        bottom in the file, which is how an author will look for them.
        """
        for it in reversed(items):
            k = it["kind"]
            if k == "jump":
                cont = "@" + it["target"]
                self.edges.append((self.cur, it["target"]))
            elif k == "return":
                cont = None
            elif k == "line":
                if it.get("unmappable"):
                    continue
                n = it["_node"]
                self.link(n, cont)
                if n.get("showIf") and n.get("isEnd") and n.get("onEnter"):
                    # A line-only gate (0.15) still fires onEnter when the line
                    # is hidden, so the effects would stop being conditional.
                    raise SystemExit(f"{n['id']}: a gated last beat carries effects the "
                                     "gate would no longer hold back")
                cont = n["id"]
            elif k == "menu":
                n = it["_node"]
                for c, choice in zip(it["choices"], n["choices"]):
                    target = self.seq(c["items"], cont)
                    if target is not None:
                        choice["goto"] = target
                for c in it.get("_skipped", []):
                    self.seq(c["items"], cont)
                if it.get("label"):
                    self.entry[it["label"]] = n["id"]
                    self.edges.append((self.cur, it["label"]))
                cont = n["id"]
        return cont

    def alloc(self, items):
        """Create the nodes of a statement list in source order."""
        for it in items:
            if it["kind"] == "line" and not it.get("unmappable"):
                it["_node"] = self.node(speakerId=it.get("speaker"),
                                        text=interp(it["text"]),
                                        showIf=it.get("showIf"),
                                        onEnter=it.get("effects"))
            elif it["kind"] == "menu":
                cap = it.get("caption")
                carried_cap = cap and not cap.get("unmappable")
                n = self.node(speakerId=cap.get("speaker") if carried_cap else None,
                              text=interp(cap["text"]) if carried_cap else None,
                              showIf=cap.get("showIf") if carried_cap else None,
                              onEnter=(cap.get("effects") if carried_cap else []) +
                              it.get("effects", []))
                n["choices"] = []
                it["_node"] = n
                for c in it["choices"]:
                    if c.get("unmappable"):
                        c["_skip"] = True
                    ch = {"id": self.uid("c"), "text": interp(c["text"])}
                    for key in ("showIf", "whenLocked"):
                        if c.get(key):
                            ch[key] = c[key]
                    if c.get("effects"):
                        ch["effects"] = c["effects"]
                    if not c.get("_skip"):
                        n["choices"].append(ch)
                    self.alloc(c["items"])
                # Keep the IR's choices and the node's choices in step for seq().
                # A declared choice's block is still linked (seq visits it) so its
                # nodes are well-formed — unreachable, and reported as such.
                it["_skipped"] = [c for c in it["choices"] if c.get("_skip")]
                it["choices"] = [c for c in it["choices"] if not c.get("_skip")]
                if not n["choices"]:
                    raise SystemExit(f"{n['id']}: a menu whose every choice is declared")

    def resolve(self, ref, seen=()):
        """`@label` → that label's first node, following labels that only jump."""
        while isinstance(ref, str) and ref.startswith("@"):
            name = ref[1:]
            if name in seen:
                return None
            seen = seen + (name,)
            ref = self.entry.get(name)
        return ref


def build(ir, ns):
    b = Builder(ir, ns)
    for i, name in enumerate(b.order):
        b.cur = name
        b.alloc(b.labels[name]["items"])
    for i, name in enumerate(b.order):
        b.cur = name
        # A label with no jump or return at its end FALLS THROUGH into the next
        # label in the file — Ren'Py's rule, not a guess. The last one ends.
        after = "@" + b.order[i + 1] if i + 1 < len(b.order) else None
        items = b.labels[name]["items"]
        if after and not (items and items[-1]["kind"] in ("jump", "return")):
            b.edges.append((name, b.order[i + 1]))
        b.entry[name] = b.seq(b.labels[name]["items"], after)

    for n in b.nodes.values():
        if n.get("next"):
            target = b.resolve(n["next"])
            if target is None:
                b.notes.append(f"{n['id']}: continues into '{n['next'][1:]}', which "
                               f"produced no node — the dialogue ends there")
                del n["next"]
                n["isEnd"] = True
            else:
                n["next"] = target
        for c in n.get("choices") or []:
            if c.get("goto"):
                target = b.resolve(c["goto"])
                if target is None:
                    b.notes.append(f"{c['id']}: leads to '{c['goto'][1:]}', which "
                                   f"produced no node — the choice ends the dialogue")
                    del c["goto"]
                else:
                    c["goto"] = target

    # Labels joined by a jump or a fall-through become ONE dialogue: a Parlance
    # `goto` is within-dialogue only.
    parent = {t: t for t in list(b.order) + [k for k in b.entry if k not in b.order]}

    def find(a):
        while parent[a] != a:
            parent[a] = parent[parent[a]]
            a = parent[a]
        return a

    for a, z in b.edges:
        if a in parent and z in parent and find(a) != find(z):
            parent[find(z)] = find(a)

    groups = {}
    for t in b.order:
        groups.setdefault(find(t), []).append(t)
    out = []
    start = ir.get("start")
    for comp in groups.values():
        members = set(comp)
        nodes = [n for n in b.nodes.values() if b.owner.get(n["id"]) in members]
        head = start if start in members else comp[0]
        entry = b.resolve("@" + head)
        if entry is None:
            entry = next((b.resolve("@" + t) for t in comp if b.resolve("@" + t)), None)
        if not nodes or entry is None:
            continue
        for n in nodes:
            n.pop("_node", None)
        out.append({"id": f"dlg_{ns}_{slug(head)}", "title": head, "entry": entry,
                    "nodes": nodes, "replayable": False})
    placed = {n["id"] for d in out for n in d["nodes"]}
    missing = [nid for nid in b.nodes if nid not in placed]
    if missing:
        raise SystemExit(f"{len(missing)} nodes belong to no dialogue and would be "
                         f"dropped silently: {missing[:5]}")
    return b, out


def characters(ir, dialogues):
    """A character per `define`d Character that actually speaks a carried line."""
    used = {n.get("speakerId") for d in dialogues for n in d["nodes"]} - {None}
    return {cid: {"id": cid, "name": name}
            for cid, name in sorted(ir["characters"].items()) if cid in used}


def write(root, ir, ns):
    """Build and write a project from one parsed script. Returns the builder."""
    sys.path.insert(0, HERE)
    import write_project as W
    b, dialogues = build(ir, ns)
    chars = characters(ir, dialogues)
    ladders = {}
    for d in dialogues:
        for n in d["nodes"]:
            sid = n.get("speakerId")
            if sid and d["id"] not in ladders.setdefault(sid, []):
                ladders[sid].append(d["id"])
    W.write_project(root, W.offer_entries(dialogues, ladders),
                    W.variables_of(ir["variableKinds"], ir["defaults"], "Ren'Py default"),
                    chars)
    return b, dialogues
