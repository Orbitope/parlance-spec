#!/usr/bin/env python3
"""
build_ink_example.py — the mapping step of an Ink migration, written as a script.

Same standing as `build_yarn_example.py`: the `ink-import` skill has a model do
the mapping, and at the scale of the worked example here (63 containers, ~1000
units) that is neither reliable nor reproducible, so the decisions are written
down as code. `check.py` still decides whether the result is faithful.

Every player-facing string is copied from the parser's IR byte for byte. Nothing
here composes a string, fills an optional field, or invents an id.

The weave is the hard part and is worth stating once. Ink's nesting is the number
of `*`/`+`/`-` markers, NOT indentation and NOT the linear `parent` link — that
link records the previous marker, so two sibling options are parent and child in
it. So a choice run is "consecutive options at the same level", an option's body
runs until the next option or gather at that level or shallower, and the
`gathersTo` the parser computed says where the branches rejoin.
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
    p = subprocess.run([sys.executable, os.path.join(LIB, "parse_ink.py"), path,
                        "--emit", "ir"], capture_output=True, text=True)
    if p.returncode != 0:
        sys.exit(p.stderr)
    return json.loads(p.stdout)


def effect_of(eff):
    """One `~` assignment as a Parlance effect, or None where there is none."""
    op, var = eff.get("op"), eff.get("var")
    if not var:
        return None
    ident = var.lower()
    if op == "set":
        return {"type": "set_flag", "flag": ident, "value": bool(eff["value"])}
    if op == "add":
        return {"type": "adjust_counter", "counter": ident, "delta": eff["delta"]}
    if op == "settext":
        return {"type": "set_text", "variable": ident, "value": eff["value"]}
    # `setnum` is an ABSOLUTE assignment to a counter and the vocabulary has no
    # such effect — only `adjust_counter` with a delta, which would need the
    # value at that point in the story. `temp` and `expr` the parser already
    # reports. None of the three is guessed at.
    return None


class Builder:
    def __init__(self, ir, ns):
        self.ns = ns
        self.containers = {c["title"]: c for c in ir["containers"]}
        self.order = [c["title"] for c in ir["containers"]]
        self.kinds = dict(ir["variableKinds"])
        self.decls = ir["declarations"]
        self.nodes = {}
        self.owner = {}                  # node id -> container title
        self.entry_of = {}               # container title -> entry node id
        self.at_item = {}                # (container, item index) -> node id
        self.seen_ids = {}
        self.speakers = {}
        self.notes = []
        # container -> where its `->->` goes, for tunnels whose call sites all
        # agree. Resolved by the parser; see WHY_TUNNEL_AMBIGUOUS for the rest.
        self.tunnel_returns = dict(ir.get("tunnelReturns") or {})
        self.container = None

    # -- ids, all derived --------------------------------------------------
    def uid(self, base):
        self.seen_ids[base] = self.seen_ids.get(base, 0) + 1
        n = self.seen_ids[base]
        return base if n == 1 else f"{base}_{n}"

    def node_id(self, title):
        return self.uid(f"n_{self.ns}_{slug(title)}")

    def choice_id(self, text):
        return self.uid(f"c_{self.ns}_" + "_".join(slug(text).split("_")[:4]))

    # -- divert targets ----------------------------------------------------
    def divert_target(self, container, div):
        """A placeholder for whatever this divert points at.

        Resolved after every container is built, because a divert may point
        forward. A label divert names a position INSIDE a container, so it
        carries the item index too.
        """
        if not div:
            return None
        if div.get("conditional"):
            # Only fires when a condition holds, which no unconditional `next`
            # can express. Declared by the parser (WHY_COND_DIVERT).
            return None
        if div["kind"] == "terminal":
            return "@@END"
        if div["kind"] == "tunnel_return":
            # `->->` goes back to whichever container called in. Where every call
            # site wanted the same place, that IS one node id, so an ordinary
            # goto expresses it — pointing backwards if need be, which is legal.
            onward = self.tunnel_returns.get(container["title"])
            if onward:
                return f"@entry:{onward}"
            if container["title"] in self.tunnel_returns:
                # Called with an empty onward (`-> knot ->`): the caller wanted
                # control back at its own position, which is not a node id.
                self.notes.append(f"{container['title']}: `->->` returns to the caller's "
                                  f"own position, which is not a node — branch ends here")
                return "@@END"
            self.notes.append(f"{container['title']}: tunnel return (->->) with no "
                              f"agreed target — branch ends here")
            return "@@END"
        if div["kind"] == "tunnel":
            # Into the scene. Its `->->` carries the caller onward.
            return f"@entry:{div['target']}"
        if div.get("resolvedLabel"):
            c, idx = div["resolvedLabel"]
            return f"@item:{c}#{idx}"
        if div.get("resolved"):
            return f"@entry:{div['resolved']}"
        self.notes.append(f"{container['title']}: divert to '{div['target']}', which "
                          f"resolves to nothing — the branch ends there")
        return "@@END"

    # -- the weave ---------------------------------------------------------
    @staticmethod
    def body_end(items, start, level, hi):
        """Where an option's body stops: the next option or gather at its own
        level or shallower. Lines carry no weave level, so only markers count."""
        for k in range(start, hi):
            if items[k]["kind"] in ("option", "gather") and items[k]["level"] <= level:
                return k
        return hi

    def emit(self, container, lo, hi, incoming=()):
        """items[lo:hi] as a chain. Returns (entry node id, still-open tails).

        `incoming` are the branches that flow INTO this region — the tails of the
        option bodies that gathered here. They start out WAITING, exactly like a
        tail produced inside the region: whatever this region reaches first (a
        node, or a divert) is what they connect to. That is the whole of the
        weave's join behaviour, and writing it any other way lost it — wiring
        them by hand in the caller meant a divert immediately after a gather
        (`- -> waited`) caught nothing, and every branch that gathered there was
        closed with `isEnd` instead of continuing.

        A choice set opening the region has no line of its own to hang off, so it
        BORROWS one from `incoming` — but only when there is exactly one, since
        with several the line the player just read differs per path.
        """
        items = container["items"]
        entry, prev = None, None
        waiting = list(incoming)
        borrowed = None
        # Item indices walked past that produced no node of their own — a bare
        # gather, a command, a declared-loss line. A divert may target a LABEL on
        # any of them (`-> opts` in The Intercept targets a text-less gather), so
        # they resolve to the next node actually emitted.
        unclaimed = []
        i = lo
        while i < hi:
            it = items[i]

            if it["kind"] == "option":
                level = it["level"]
                run, j = [], i
                while j < hi and items[j]["kind"] == "option" \
                        and items[j]["level"] == level:
                    b0 = j + 1
                    b1 = self.body_end(items, b0, level, hi)
                    run.append((j, b0, b1))
                    j = b1
                run = [r for r in run if not items[r[0]].get("unmappable")]
                if not run:
                    unclaimed.extend(range(i, j))
                    i = j
                    continue
                if prev is None:
                    usable = [t for t in waiting
                              if not t.get("_choice") and not t.get("choices")
                              and not t.get("isEnd")]
                    if len(usable) != 1:
                        raise SystemExit(
                            f"{container['title']}: a choice list with no line to host "
                            f"it (source line {items[i]['lineno']}), which the parser "
                            f"did not declare")
                    prev = borrowed = usable[0]
                    waiting.remove(borrowed)
                host = prev
                for idx in unclaimed:
                    self.at_item.setdefault((container["title"], idx), host["id"])
                unclaimed = []
                host["choices"] = host.get("choices", [])
                body_tails = []
                for oi, b0, b1 in run:
                    host["choices"].append(
                        self.build_choice(container, oi, b0, b1, body_tails, host))
                host.pop("next", None)
                # Everything after the choice set is where the branches rejoin.
                # They are handed down as `incoming` rather than wired here,
                # because what they connect to may be a divert rather than a node.
                cont_entry, cont_tails = self.emit(container, j, hi,
                                                   incoming=body_tails + waiting)
                return (entry or host["id"],
                        cont_tails if cont_entry else body_tails + waiting)

            if it["kind"] in ("line", "gather") and it.get("text") \
                    and not it.get("unmappable"):
                node = {"id": self.node_id(container["title"]), "text": it["text"]}
                if it.get("speaker"):
                    sid = "char_" + slug(it["speaker"])
                    self.speakers[sid] = it["speaker"]
                    node["speakerId"] = sid
                if it.get("showIf"):
                    node["showIf"] = it["showIf"]
                eff = [e for e in (effect_of(x) for x in it.get("effects") or []) if e]
                if eff:
                    node["onEnter"] = eff
                self.nodes[node["id"]] = node
                self.owner[node["id"]] = container["title"]
                for idx in unclaimed + [it["index"]]:
                    self.at_item.setdefault((container["title"], idx), node["id"])
                unclaimed = []
                if prev is not None:
                    prev["next"] = node["id"]
                for t in waiting:
                    self.terminate(t, node["id"])
                waiting = []
                entry = entry or node["id"]
                prev = node
                target = self.divert_target(
                    container, None if it.get("conditionalDivert") else it.get("divert"))
                if target:
                    self.terminate(node, target)
                    prev = None
                i += 1
                continue

            # commands, diverts, threads, tunnel returns, and declared-loss lines
            unclaimed.append(it["index"])
            eff = [e for e in (effect_of(x) for x in it.get("effects") or []) if e]
            if eff and prev is not None:
                prev.setdefault("onEnter", []).extend(eff)
            target = self.divert_target(
                container, None if it.get("conditionalDivert") else it.get("divert"))
            if target:
                for t in ([prev] if prev else []) + waiting:
                    self.terminate(t, target)
                prev, waiting = None, []
            i += 1

        return entry, ([prev] if prev is not None else []) + waiting

    def build_choice(self, container, oi, b0, b1, body_tails, host):
        items = container["items"]
        opt = items[oi]
        choice = {"id": self.choice_id(opt["text"]), "text": opt["text"]}
        if opt.get("showIf"):
            choice["showIf"] = opt["showIf"]
        eff = [e for e in (effect_of(x) for x in opt.get("effects") or []) if e]
        if eff:
            choice["effects"] = eff
        self.at_item.setdefault((container["title"], oi), host["id"])

        entry, tails = self.emit(container, b0, b1)
        if entry:
            choice["goto"] = entry
            body_tails.extend(tails)
            return choice
        target = self.divert_target(container, opt.get("divert"))
        if target:
            choice["goto"] = target
            return choice
        choice["_choice"] = True
        choice["_host"] = host
        body_tails.append(choice)
        return choice

    @staticmethod
    def terminate(node, target):
        if node is None:
            return
        key = "goto" if node.get("_choice") else "next"
        if node.get("choices") or node.get(key) or node.get("isEnd"):
            return
        node[key] = target

    @staticmethod
    def close(node):
        """A tail with nowhere to go: the conversation stops there."""
        if node is None:
            return
        if node.get("_choice"):
            if "goto" not in node:
                node["_host"]["isEnd"] = True
            return
        if node.get("choices") or node.get("next"):
            return
        if node.get("showIf"):
            raise SystemExit(f"node '{node['id']}' ends the conversation but carries a "
                             f"guard the parser did not declare")
        node["isEnd"] = True


def build(ir, ns):
    """One Ink file into dialogues. Returns (builder, dialogues)."""
    b = Builder(ir, ns)

    for title in b.order:
        c = b.containers[title]
        entry, tails = b.emit(c, 0, len(c["items"]))
        if entry:
            b.entry_of[title] = entry
        # Running off the end of an Ink container is a story that stops there.
        for t in tails:
            b.close(t)

    # Containers joined by a divert become ONE dialogue: a Parlance `goto` is
    # within-dialogue only, so a divert that crossed dialogues could not be
    # expressed. Undirected, because reachability is not the question — whether
    # the two must live in one file is.
    parent = {t: t for t in b.order}

    def find(a):
        while parent[a] != a:
            parent[a] = parent[parent[a]]
            a = parent[a]
        return a

    for title in b.order:
        for it in b.containers[title]["items"]:
            d = it.get("divert") or {}
            other = d.get("resolved") or (d.get("resolvedLabel") or [None])[0]
            if other in parent and find(title) != find(other):
                parent[find(other)] = find(title)

    groups = {}
    for t in b.order:
        groups.setdefault(find(t), []).append(t)
    comps = [groups[r] for r in dict.fromkeys(find(t) for t in b.order)]

    # Placeholders become real ids now that every container has been emitted.
    def resolve(holder, key):
        v = holder.get(key)
        if not (isinstance(v, str) and v.startswith("@")):
            return
        if v == "@@END":
            del holder[key]
            b.close(holder)
            return
        kind, rest = v[1:].split(":", 1)
        target = (b.at_item.get((rest.split("#")[0], int(rest.split("#")[1])))
                  if kind == "item" else b.entry_of.get(rest))
        if target:
            holder[key] = target
            return
        del holder[key]
        b.notes.append(f"divert to '{rest}', which produced no node — every line of it "
                       f"is declared loss, so the branch ends there")
        b.close(holder)

    for n in list(b.nodes.values()):
        resolve(n, "next")
        for c in n.get("choices") or []:
            resolve(c, "goto")
    for n in b.nodes.values():
        for c in n.get("choices") or []:
            if "goto" not in c:
                n["isEnd"] = True
            c.pop("_choice", None)
            c.pop("_host", None)

    # An Ink divert may point back into a chain already walked. A Parlance
    # `next` ring can never be escaped, so the validator refuses one; the edge
    # that closes the loop is cut and reported.
    for n in b.nodes.values():
        seen, cur = set(), n
        while cur is not None and cur["id"] not in seen and not cur.get("choices"):
            seen.add(cur["id"])
            nxt = b.nodes.get(cur.get("next"))
            if nxt is not None and nxt["id"] in seen:
                b.notes.append(f"`next` loop at '{cur['id']}' — an Ink divert may point "
                               f"back into a chain, a Parlance next-chain may not; the "
                               f"conversation ends there instead")
                cur.pop("next")
                b.close(cur)
                break
            cur = nxt

    out = []
    for comp in comps:
        members = set(comp)
        nodes = [n for n in b.nodes.values() if b.owner.get(n["id"]) in members]
        if not nodes:
            continue
        entry = next((b.entry_of[t] for t in comp if t in b.entry_of), None)
        if entry is None:
            continue
        out.append({"id": f"dlg_{ns}_{slug(comp[0])}", "title": comp[0],
                    "entry": entry, "nodes": nodes, "replayable": False})

    placed = {n["id"] for d in out for n in d["nodes"]}
    missing = [nid for nid in b.nodes if nid not in placed]
    if missing:
        raise SystemExit(f"{len(missing)} nodes belong to no dialogue and would be "
                         f"dropped silently: {missing[:5]}")
    return b, out
