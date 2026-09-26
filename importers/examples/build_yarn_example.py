#!/usr/bin/env python3
"""
build_yarn_example.py — the mapping step of a Yarn migration, written as a script.

The `yarn-import` skill has a model do the mapping, because structure needs
judgment. At the scale of the worked examples here — hundreds of lines across
dozens of nodes — doing that by hand is neither reliable nor reproducible, so the
decisions are written down as code instead. They are the same decisions the
skill's mapping table names, and the same gate checks the result: `check.py` still
has to agree that no prose was lost, none invented, and no guard altered.

WHAT IT DOES NOT DO matters as much. Every player-facing string is copied from the
parser's IR byte for byte; nothing here composes a string, fills an optional field,
or invents an id. Every id is derived from a node title, a speaker name or a
variable name in the source.

    python3 build_yarn_example.py <out-project-dir> <name> <source.yarn> [...]
"""
import json
import os
import re
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
LIB = os.path.join(HERE, "..", "lib")

SET = re.compile(r"^(?:set|declare)\s+\$(\w+)\s*(?:to|=|(?P<plus>\+=)|(?P<minus>-=))\s*(.+)$")


def slug(s):
    out = re.sub(r"[^a-z0-9]+", "_", (s or "").lower()).strip("_")
    return out if re.match(r"^[a-z]", out or "") else ("x_" + out if out else "x")


def head_of(command):
    parts = command.split()
    return parts[0] if parts else ""


def ir_of(path):
    p = subprocess.run([sys.executable, os.path.join(LIB, "parse_yarn.py"), path,
                        "--emit", "ir"], capture_output=True, text=True)
    if p.returncode != 0:
        sys.exit(p.stderr)
    return json.loads(p.stdout)


# Yarn's own control flow and state commands; every other head is a custom
# command the host game registered (mirrors KNOWN in lib/parse_yarn.py).
YARN_BUILTIN = ("jump", "set", "if", "elseif", "else", "endif", "declare", "stop")


def engine_command_name(head):
    """`addForegroundImage` -> `add_foreground_image`: the validator requires an
    engine command to be lowercase snake_case. Deterministic and documented in
    the report — a spelling of the source's own name, not a new one."""
    snake = re.sub(r"(?<=[a-z0-9])(?=[A-Z])", "_", head).lower()
    snake = re.sub(r"[^a-z0-9_]+", "_", snake).strip("_")
    return snake if re.match(r"^[a-z]", snake) else "cmd_" + snake


def engine_arg(tok):
    """A Yarn command argument, typed as the source wrote it."""
    if len(tok) >= 2 and tok[0] == tok[-1] == '"':
        return tok[1:-1]
    if re.match(r"^-?\d+$", tok):
        return int(tok)
    if re.match(r"^-?\d+\.\d+$", tok):
        return float(tok)
    if tok in ("true", "false"):
        return tok == "true"
    return tok


def engine_of(command):
    """A custom Yarn command (`<<addForegroundImage student-group-1 30 440>>`)
    as a Parlance `engine` effect: the runtime hands it to the game in order,
    the way Yarn's dialogue runner hands it to a registered command handler."""
    toks = re.findall(r'"[^"]*"|\S+', command.strip())
    eff = {"type": "engine", "command": engine_command_name(toks[0])}
    if len(toks) > 1:
        eff["args"] = [engine_arg(t) for t in toks[1:]]
    return eff


def effect_of(command, kinds):
    """A Yarn command as a Parlance effect, or None where there is no equivalent.

    None is not a silent drop — the parser has already listed the command under
    `unmapped` and the report carries it. It only means this script will not
    invent an effect to stand in for one.

    A custom command (any head Yarn itself does not define) becomes an
    `engine` effect; the parser no longer declares those as loss.
    """
    if head_of(command) and head_of(command) not in YARN_BUILTIN:
        return engine_of(command)
    if head_of(command) != "set":
        # `<<declare>>` states a variable's INITIAL value. That is the registry
        # entry's `default`, not something that happens during the story.
        return None
    m = SET.match(command.strip())
    if not m:
        return None
    name, val = m.group(1), m.group(4).strip()
    kind, ident = kinds.get(name), name.lower()
    if m.group("plus") or m.group("minus"):
        if not re.match(r"^-?\d+$", val):
            return None
        return {"type": "adjust_counter", "counter": ident,
                "delta": int(val) * (-1 if m.group("minus") else 1)}
    inc = re.match(r"^\$" + re.escape(name) + r"\s*([-+])\s*(\d+)$", val)
    if inc:
        return {"type": "adjust_counter", "counter": ident,
                "delta": int(inc.group(2)) * (1 if inc.group(1) == "+" else -1)}
    if kind == "flag" and val in ("true", "false"):
        return {"type": "set_flag", "flag": ident, "value": val == "true"}
    if kind == "counter" and re.match(r"^-?\d+$", val):
        # No absolute counter assignment exists: the vocabulary has
        # `adjust_counter` with a delta and nothing else. Computing a delta would
        # need the value at that point in the story, which is not knowable
        # statically, so this is declined rather than guessed.
        return None
    if kind == "text" and re.match(r'^".*"$', val):
        return {"type": "set_text", "variable": ident, "value": val[1:-1]}
    return None


class Builder:
    def __init__(self, ir, ns):
        """One SOURCE FILE, with `ns` namespacing every id it produces.

        Not one builder for the whole story: two Yarn files are two Yarn
        projects, and they reuse node titles freely — `Start`, `Bedroom2` and
        seven others are defined in both episodes of the worked example here, as
        different scenes. Keyed by title alone, the second file's versions
        vanished silently and took their prose with them.
        """
        self.ns = ns
        self.kinds, self.yarn, self.order = dict(ir["variableKinds"]), {}, []
        for n in ir["nodes"]:
            if n["title"] and n["title"] not in self.yarn:
                self.yarn[n["title"]] = n
                self.order.append(n["title"])
        self.nodes = {}
        self.entry_of = {}
        self.seen_ids = {}
        self.speakers = {}
        self.owner = {}          # parlance node id -> source Yarn node title
        self.engine_src = {}     # id(engine effect) -> (title, lineno, command), while pending
        self.stranded = []       # custom commands with no node to carry them

    # -- ids, all derived -------------------------------------------------
    def uid(self, base):
        self.seen_ids[base] = self.seen_ids.get(base, 0) + 1
        n = self.seen_ids[base]
        return base if n == 1 else f"{base}_{n}"

    def node_id(self, title):
        return self.uid(f"n_{self.ns}_{slug(title)}")

    def choice_id(self, text):
        return self.uid(f"c_{self.ns}_" + "_".join(slug(text).split("_")[:4]))

    # -- one dialogue per jump-connected component ------------------------
    def components(self):
        """`<<jump>>`-connected Yarn nodes become ONE dialogue: a Parlance `goto`
        is within-dialogue only, so a jump that crossed dialogues could not be
        expressed at all."""
        parent = {t: t for t in self.order}

        def find(a):
            while parent[a] != a:
                parent[a] = parent[parent[a]]
                a = parent[a]
            return a

        for title, n in self.yarn.items():
            for it in n["items"]:
                for c in it["commands"]:
                    if head_of(c) == "jump":
                        tgt = c.split()[-1]
                        if tgt in parent and find(title) != find(tgt):
                            parent[find(tgt)] = find(title)

        groups = {}
        for t in self.order:
            groups.setdefault(find(t), []).append(t)
        return [groups[r] for r in dict.fromkeys(find(t) for t in self.order)]

    # -- the chain --------------------------------------------------------
    def chain(self, title, items, lo, hi):
        """items[lo:hi] as a chain. Returns (entry node id, unterminated tails)."""
        entry, prev, tails, waiting, pending = None, None, [], [], []
        i = lo
        while i < hi:
            it = items[i]

            if it["kind"] == "command":
                jump = None
                for c in it["commands"]:
                    if head_of(c) == "jump":
                        jump = "@" + c.split()[-1]
                        continue
                    eff = effect_of(c, self.kinds)
                    if eff:
                        if eff["type"] == "engine":
                            # Remembered while pending so a stranded one can be
                            # named in the notes; stripped once it has a host.
                            self.engine_src[id(eff)] = (title, it["lineno"], c)
                        pending.append(eff)
                if jump:
                    for t in ([prev] if prev else []) + waiting:
                        self.terminate(t, jump)
                    prev, waiting = None, []
                i += 1
                continue

            if it["kind"] == "option":
                indent = it["indent"]
                groups = []
                j = i
                while j < hi and items[j]["kind"] == "option" and items[j]["indent"] == indent:
                    body_lo = j + 1
                    body_hi = body_lo
                    while body_hi < hi and items[body_hi]["indent"] > indent:
                        body_hi += 1
                    groups.append((j, body_lo, body_hi))
                    j = body_hi
                # An option whose own guard the parser declared (a function
                # call, an untyped variable) is skipped along with its body — the
                # report carries it.
                for g in groups:
                    if items[g[0]].get("unmappable"):
                        # The whole group is declared loss, so the custom
                        # commands under it go nowhere either — say so.
                        for k in range(g[0], g[2]):
                            for c in items[k]["commands"]:
                                if head_of(c) and head_of(c) not in YARN_BUILTIN:
                                    self.stranded.append((title, items[k]["lineno"], c, "under a choice that is declared loss"))
                groups = [g for g in groups if not items[g[0]].get("unmappable")]
                if not groups:
                    i = j
                    continue
                if prev is None:
                    # No narration line to hang the options off — they follow
                    # another option block, or open the Yarn node. Since 0.15 a
                    # node may carry choices with no `text`: the option-block
                    # shape, exactly what the source wrote.
                    host = {"id": self.node_id(title)}
                    if pending:
                        host["onEnter"] = pending
                        pending = []
                    self.nodes[host["id"]] = host
                    self.owner[host["id"]] = title
                    for t in waiting:
                        self.terminate(t, host["id"])
                    waiting = []
                    entry = entry or host["id"]
                else:
                    host = prev
                body_tails = []
                host["choices"] = []
                for oi, blo, bhi in groups:
                    host["choices"].append(self.build_choice(title, items, oi, blo, bhi,
                                                             body_tails, host))
                host.pop("next", None)
                prev, waiting = None, waiting + body_tails
                i = j
                continue

            if it.get("unmappable"):
                # Declared loss. Emitting it anyway would put a line in the
                # project that the source shows only sometimes — the exact
                # silent-fidelity defect the declaration exists to prevent, and
                # one no string comparison could see, since the text IS in the
                # source.
                i += 1
                continue
            node = {"id": self.node_id(title), "text": it["text"]}
            if it.get("speaker"):
                sid = "char_" + slug(it["speaker"])
                self.speakers[sid] = it["speaker"]
                node["speakerId"] = sid
            if it.get("showIf"):
                node["showIf"] = it["showIf"]
            if pending:
                node["onEnter"] = pending
                pending = []
            self.nodes[node["id"]] = node
            self.owner[node["id"]] = title
            if prev is not None:
                prev["next"] = node["id"]
            for t in waiting:
                self.terminate(t, node["id"])
            waiting = []
            entry = entry or node["id"]
            prev = node
            i += 1

        if pending and prev is not None:
            # A trailing `<<set>>` with no line after it. Attached to the last
            # node rather than dropped; it fires as that line is entered rather
            # than after it, which is a timing difference the report names.
            prev.setdefault("onEnter", []).extend(pending)
        elif pending:
            # No line in this chain to host them: a Yarn node made only of
            # commands, or commands after a jump or an option block. Engine
            # commands are NAMED here rather than dropped without a word.
            for e in pending:
                if e["type"] == "engine" and id(e) in self.engine_src:
                    t, ln, c = self.engine_src[id(e)]
                    self.stranded.append((t, ln, c, "no narration line after it in its Yarn node to carry it"))
        tails = ([prev] if prev is not None else []) + waiting
        return entry, tails

    def build_choice(self, title, items, oi, blo, bhi, body_tails, host):
        opt = items[oi]
        eff = [e for e in (effect_of(c, self.kinds) for c in opt["commands"]) if e]
        # Commands opening the body, before any of its prose, belong to the
        # choice rather than to the node it leads to — that is when Yarn runs them.
        b = blo
        while b < bhi and items[b]["kind"] == "command" and not any(
                head_of(c) == "jump" for c in items[b]["commands"]):
            eff += [e for e in (effect_of(c, self.kinds) for c in items[b]["commands"]) if e]
            b += 1
        choice = {"id": self.choice_id(opt["text"]), "text": opt["text"]}
        if opt.get("showIf"):
            choice["showIf"] = opt["showIf"]
        if eff:
            choice["effects"] = eff
        bentry, btails = self.chain(title, items, b, bhi)
        if bentry:
            choice["goto"] = bentry
            body_tails.extend(btails)
        else:
            jump = None
            for k in range(b, bhi):
                for c in items[k]["commands"]:
                    if head_of(c) == "jump":
                        jump = "@" + c.split()[-1]
            if jump:
                choice["goto"] = jump
            else:
                # No body and no jump: Yarn continues after the option block, so
                # this choice waits for whatever the block is followed by.
                choice["_choice"] = True
                choice["_host"] = host
                body_tails.append(choice)
        return choice

    @staticmethod
    def terminate(node, target):
        """Wire a waiting tail — a node's `next`, or a bodyless choice's `goto`."""
        if node is None:
            return
        key = "goto" if node.get("_choice") else "next"
        if node.get("choices") or node.get(key) or node.get("isEnd"):
            return
        node[key] = target

    @staticmethod
    def close(node):
        """A tail the source ran off the end of: the conversation stops there.

        For a choice with no body and nothing after it, that is `isEnd` on the
        NODE hosting it — the validator reads a gotoless choice on an isEnd node
        as ending the conversation, and rejects one anywhere else as a dead end.
        """
        if node is None:
            return
        if node.get("_choice"):
            if "goto" not in node:
                node["_host"]["isEnd"] = True
            return
        if node.get("choices") or node.get("next"):
            return
        # A guarded last beat is fine since 0.15: `showIf` with `isEnd` hides
        # the line when the gate fails and the conversation still ends.
        node["isEnd"] = True


def build_one(ir, ns):
    """One source file into dialogues. Returns (builder, dialogues, notes)."""
    b = Builder(ir, ns)
    notes = []
    dialogues = []
    for comp in b.components():
        ids, all_tails = [], []
        for title in comp:
            items = b.yarn[title]["items"]
            entry, tails = b.chain(title, items, 0, len(items))
            if entry:
                b.entry_of[title] = entry
                ids.append(entry)
            all_tails += tails
        if not ids:
            continue
        for t in all_tails:
            # Running off the end of a Yarn node ends the conversation.
            b.close(t)
        dialogues.append({"titles": comp, "entry": ids[0]})

    # `@Title` placeholders become the entry node of that Yarn node, resolved
    # after every component is built because a jump may point forward. A target
    # the source never defines is a dangling reference in the SOURCE; it is
    # reported and the branch ends there, rather than emitting a broken id.
    def resolve(holder, key):
        v = holder.get(key)
        if not (isinstance(v, str) and v.startswith("@")):
            return
        target = b.entry_of.get(v[1:])
        if target:
            holder[key] = target
            return
        del holder[key]
        known = v[1:] in b.yarn
        # Hoisted out of the f-string: a multi-line f-string expression is a
        # SyntaxError before Python 3.12 (PEP 701), and this repo's CI runs 3.11.
        reason = "every line of which is declared loss" if known else "which this file never defines"
        notes.append(
            f"jump to '{v[1:]}', {reason} — nothing to go to, so the branch ends here")
        if key == "next":
            b.close(holder)

    for n in b.nodes.values():
        resolve(n, "next")
        for c in n.get("choices") or []:
            resolve(c, "goto")

    # Yarn lets a node jump back to itself — "keep listening until you have heard
    # three" is written exactly that way. A Parlance `next` ring can never be
    # escaped, so the validator rejects one; the loop is cut at the edge that
    # closes it and reported, because silently keeping it would not validate and
    # silently dropping it would not be honest.
    for n in b.nodes.values():
        seen, cur = set(), n
        while cur is not None and cur["id"] not in seen and not cur.get("choices"):
            seen.add(cur["id"])
            nxt = b.nodes.get(cur.get("next"))
            if nxt is not None and nxt["id"] in seen:
                notes.append(f"`next` loop at '{cur['id']}' — Yarn allows a node to "
                             f"jump back to itself, a Parlance next-chain may not; "
                             f"the conversation ends there instead")
                cur.pop("next")
                b.close(cur)
                break
            cur = nxt

    # A choice still with nowhere to go ends the conversation, which the
    # validator reads as `isEnd` on the node hosting it.
    for n in b.nodes.values():
        for c in n.get("choices") or []:
            if "goto" not in c:
                n["isEnd"] = True

    for n in b.nodes.values():
        for c in n.get("choices") or []:
            c.pop("_choice", None)
            c.pop("_host", None)

    out = []
    for d in dialogues:
        members = set(d["titles"])
        nodes = [n for n in b.nodes.values() if b.owner.get(n["id"]) in members]
        out.append({"id": f"dlg_{ns}_{slug(d['titles'][0])}",
                    "title": d["titles"][0],
                    "entry": d["entry"],
                    "nodes": nodes,
                    "replayable": False})
    orphans = [nid for nid in b.nodes
               if b.owner.get(nid) not in {t for d in dialogues for t in d["titles"]}]
    if orphans:
        raise SystemExit(f"{ns}: {len(orphans)} nodes belong to no dialogue — they would "
                         f"be dropped silently: {orphans[:5]}")
    # A custom command becomes an `engine` effect only where a node can carry
    # it. The rest are named, one per command, never dropped without a word.
    for title, lineno, command, why in b.stranded:
        notes.append(f"engine command <<{command}>> in '{title}' (line {lineno}) not carried — {why}")
    return b, out, notes


def build(irs, names):
    """Every source file, each in its own namespace. Returns (builders, dialogues, notes)."""
    builders, dialogues, notes = [], [], []
    for ir, ns in zip(irs, names):
        b, d, n = build_one(ir, ns)
        builders.append(b)
        dialogues += d
        notes += [f"{ns}: {x}" for x in n]
    return builders, dialogues, notes


if __name__ == "__main__":
    sys.exit("driven by the per-example scripts beside this file")
