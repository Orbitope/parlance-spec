#!/usr/bin/env python3
"""
build_twine_example.py — the mapping step of a Twine migration, as a script.

Same standing as its Yarn and Ink siblings: the skill has a model do the mapping,
and at the scale of a worked example that is neither reliable nor reproducible,
so the decisions are written down as code. `check.py` still decides whether the
result is faithful.

Twine is the simplest of the three to map, and it is worth saying why. There is
no weave and no nesting: a passage is a linear run of lines with its links at the
end, and a link LEAVES the passage rather than opening a branch inside it. So the
graph is passages-as-scenes joined by links, and the only structural judgment is
which passages belong in one dialogue.

Every player-facing string is copied from the parser's IR byte for byte. Nothing
here composes a string, fills an optional field, or invents an id.
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
    p = subprocess.run([sys.executable, os.path.join(LIB, "parse_twine.py"), path,
                        "--emit", "ir"], capture_output=True, text=True)
    if p.returncode != 0:
        sys.exit(p.stderr)
    return json.loads(p.stdout)


def effect_of(eff, kinds=None):
    """One `(set:)` as a Parlance effect, or None where there is none.

    A variable whose kind the parser could not derive is NOT registered in
    `variables.json`, so an effect naming it would be a dangling reference the
    validator rejects (REF). Declined here rather than emitted — the parser
    already reports the assignment.
    """
    op, var = eff.get("op"), eff.get("var")
    if not var:
        return None
    if kinds is not None and kinds.get(var) not in ("flag", "counter", "text"):
        return None
    ident = var.lower()
    if op == "set":
        return {"type": "set_flag", "flag": ident, "value": bool(eff["value"])}
    if op == "add":
        return {"type": "adjust_counter", "counter": ident, "delta": eff["delta"]}
    if op == "settext":
        return {"type": "set_text", "variable": ident, "value": eff["value"]}
    # `setnum` is an absolute assignment to a counter, and the vocabulary has no
    # such effect — only `adjust_counter` with a delta, which would need the value
    # at that point in the story. `expr` the parser already reports.
    return None


class Builder:
    def __init__(self, ir, ns):
        self.ns = ns
        self.passages = {n["title"]: n for n in ir["nodes"]}
        self.order = [n["title"] for n in ir["nodes"]]
        self.kinds = dict(ir["variableKinds"])
        self.nodes, self.owner, self.entry_of = {}, {}, {}
        self.seen_ids = {}
        self.notes = []

    def uid(self, base):
        self.seen_ids[base] = self.seen_ids.get(base, 0) + 1
        n = self.seen_ids[base]
        return base if n == 1 else f"{base}_{n}"

    def node_id(self, title):
        return self.uid(f"n_{self.ns}_{slug(title)}")

    def choice_id(self, text):
        return self.uid(f"c_{self.ns}_" + "_".join(slug(text).split("_")[:4]))

    def emit(self, title):
        """One passage as a chain of nodes, with ALL its links on the last one.

        Harlowe renders a whole passage at once and shows every link in it
        together, so the links are not positional the way an Ink choice list is —
        text after a link is still on the same screen as the link. Attaching each
        link where it happens to appear split one passage's three choices across
        two nodes and made the second unreachable.

        The cost is stated rather than hidden: a Parlance node is a discrete beat,
        so a passage becomes several beats the player advances through, and the
        choices arrive at the end of them instead of beside the text. It is the
        same difference Ink's glue has, one level up.
        """
        items = self.passages[title]["items"]
        entry, prev, pending, links = None, None, [], []
        for it in items:
            if it["kind"] == "command":
                pending += [e for e in (effect_of(x, self.kinds) for x in it.get("effects") or [])
                            if e]
                continue

            if it["kind"] == "option":
                if not it.get("unmappable"):
                    links.append(it)
                continue

            if it.get("unmappable") or not it.get("text"):
                continue
            node = {"id": self.node_id(title), "text": it["text"]}
            if it.get("showIf"):
                node["showIf"] = it["showIf"]
            eff = pending + [e for e in (effect_of(x, self.kinds)
                                         for x in it.get("effects") or []) if e]
            if eff:
                node["onEnter"] = eff
            pending = []
            self.nodes[node["id"]] = node
            self.owner[node["id"]] = title
            if prev is not None and not prev.get("choices"):
                prev["next"] = node["id"]
            entry = entry or node["id"]
            prev = node

        for it in links:
            if prev is None:
                raise SystemExit(
                    f"{title}: a link with no line to host it (source line "
                    f"{it['lineno']}), which the parser did not declare")
            choice = {"id": self.choice_id(it["text"]), "text": it["text"],
                      "goto": "@" + it["target"]}
            if it.get("showIf"):
                choice["showIf"] = it["showIf"]
            prev.setdefault("choices", []).append(choice)
            prev.pop("next", None)
        return entry


def build(ir, ns):
    b = Builder(ir, ns)
    for title in b.order:
        entry = b.emit(title)
        if entry:
            b.entry_of[title] = entry

    # `@Title` becomes that passage's entry node. A link to a passage whose every
    # line is declared loss has nothing to point at, and the branch ends there.
    for n in b.nodes.values():
        for c in n.get("choices") or []:
            target = b.entry_of.get(c["goto"][1:])
            if target:
                c["goto"] = target
                continue
            b.notes.append(f"link to '{c['goto'][1:]}', which produced no node — "
                           f"the branch ends there")
            del c["goto"]
            n["isEnd"] = True

    # A passage with no live link out ends the conversation.
    for n in b.nodes.values():
        if not n.get("next") and not n.get("choices"):
            if n.get("showIf"):
                raise SystemExit(f"node '{n['id']}' ends the conversation but carries a "
                                 f"guard the parser did not declare")
            n["isEnd"] = True

    # Passages joined by a link become ONE dialogue: a Parlance `goto` is
    # within-dialogue only, so a link that crossed dialogues could not be
    # expressed. Undirected, because the question is whether the two must live in
    # one file, not whether one reaches the other.
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
        # The story's own start passage, when this component holds it — Twee
        # names it in StoryData and it need not be the first passage in the file.
        ordered = ([ir["start"]] if ir.get("start") in members else []) + comp
        entry = next((b.entry_of[t] for t in ordered if t in b.entry_of), None)
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
