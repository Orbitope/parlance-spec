#!/usr/bin/env python3
"""
parse_choicescript.py — deterministic ChoiceScript parser.

Reads a ChoiceScript game — `startup.txt` and the scenes its `*scene_list`
names — and emits an intermediate representation for an importer to MAP from
and a reconciliation manifest for check.py to verify against. The model never
transcribes prose: every string in the output of an import must have come from
here, byte for byte, apart from one declared rewrite (`${` -> `{`, the two
formats' spellings of the same interpolation).

ChoiceScript differs from the other formats in the one way that matters for
an importer: its structure is INDENTATION, and its flow falls through. A line
after an `*if` block runs whether or not the block did; an option's body runs
and then — for `*fake_choice` — rejoins the text below the menu; `*finish`
moves to the next scene in `*scene_list`. None of that is written down as an
edge. So this parser does not stop at a flat item list the way the Twine
parsers do: it builds the GRAPH, with every fall-through made explicit, and the
IR carries it. The mapping step's judgment is spent where it belongs — scene
grouping, what to register — and not on re-deriving control flow a script can
derive exactly.

What maps:

- `*choice` / `*fake_choice` and `#option` bodies -> choices; `*if (c) #opt` and
  an `*if` block around options -> `choice.showIf`; `*selectable_if (c) #opt`
  -> `showIf` with `whenLocked: "show"` (0.15's locked choice, exactly);
  `*hide_reuse` / `*disable_reuse` -> the COOKBOOK one-shot recipe (a flag per
  option, derived from its scene and line, set by the choice and gating it).
- `*label` / `*goto` / `*goto_scene` / `*finish` / `*ending` -> edges.
- `*if` / `*elseif` / `*else` whose bodies only narrate and set state ->
  `node.showIf` on every beat inside, the later branches under the NEGATION of
  every branch above. An `*if` whose body moves the flow (a `*goto` inside a
  branch) is a jump chosen by a condition, and is declared.
- `*set v true` / `*set v +2` / `*set v -1` / `*set v "text"` -> set_flag /
  adjust_counter / set_text. `*create` / `*temp` -> registry entries with the
  literal as default.
- `*page_break Text` -> a node whose one choice carries the button text;
  bare `*page_break` / `*line_break` are presentation and map to nothing.
- `*image` / `*sound` -> `engine` effects.
- `${name}` for a text variable -> `{name}`.

Everything else — fairmath, `*rand`, `*gosub`, `*achievement`, `*stat_chart`,
`*input_text`, computed text (`$!{}`, `@{}`, `${}` of a number) — is named, with
its file and line, in "unmapped".

Usage:
    python3 parse_choicescript.py path/to/scenes --emit ir        > ir.json
    python3 parse_choicescript.py path/to/scenes/startup.txt --emit manifest > manifest.json
"""
import argparse, json, os, re, sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from residue import find_residue
import conditions
import manifest as _manifest
import source as _source

WHY_FAIRMATH = ("fairmath (`%+` / `%-`) — an increase or decrease proportional to the "
                "distance from 0 or 100. `adjust_counter` adds a fixed delta, and "
                "approximating one with the other changes every later stat test")
WHY_ABSOLUTE = ("an absolute assignment to a counter. The effect vocabulary has "
                "`adjust_counter` with a delta and nothing else; computing a delta would "
                "need the value at that point, which is not knowable statically")
WHY_EXPR = ("an assignment whose value is an expression rather than a literal; a "
            "Parlance effect writes a literal")
WHY_KIND = ("an assignment to a variable whose kind (flag / counter / text) the game "
            "does not settle — it is created from an expression, or assigned as more "
            "than one kind — so it has no registry entry to write")
WHY_TEMP_COUNTER = ("a `*temp` counter is re-initialised every time its scene runs; "
                    "a Parlance variable is global, so only its FIRST value (the "
                    "registry default) is carried")
WHY_COMPUTED_TEXT = ("text computed at play time — `$!{}`, `@{}` multireplace, or `${}` "
                     "of a variable that is not text. A Parlance node holds one authored "
                     "string, and only a TEXT variable can fill a `{placeholder}`")
WHY_FLOW_IF = ("inside an `*if` whose branch moves the flow (`*goto`, `*finish`, a "
               "`*choice`, …) — a jump chosen by a condition. A Parlance edge is "
               "unconditional, so the branch cannot be carried")
WHY_OPTION_LOST = "inside the body of an option that could not be carried"
WHY_NO_CARRIER = ("a state change with no node that fires exactly when it would: "
                  "Parlance applies effects on arrival at a node, and the only "
                  "candidates here are gated differently, sit across a label a jump can "
                  "land on, or would reorder a read of the same variable")
WHY_DEAD = "after an unconditional jump, so the source never runs it either"
WHY_COMMAND = ("a ChoiceScript command with no Parlance equivalent — the effect "
               "vocabulary is closed and calls nothing")
WHY_ACHIEVEMENT = ("an achievement or stat screen — engine UI, not a line of the story; "
                   "its text is declared with it")
WHY_INPUT = ("player text or number input — Parlance data collects nothing from the "
             "player (the variable is registered `writtenBy: \"engine\"`)")
WHY_SUBROUTINE = ("a subroutine call that RETURNS (`*gosub`, `*gosub_scene`, `*return`) "
                  "— a Parlance edge does not come back to its caller")
WHY_RANDOM = "chosen at play time rather than by the author (`*rand`)"
WHY_BOTH_GATES = ("an option under both `*if` and `*selectable_if` — Parlance has one "
                  "gate per choice, shown locked or hidden, not both at once")
WHY_DISABLE_WITH_IF = ("`*disable_reuse` on an option that also has an `*if`: the "
                       "one-shot flag is carried, but the spent option is HIDDEN rather "
                       "than greyed, since a hide-gate and a lock-gate cannot share one "
                       "`whenLocked`")
WHY_NESTED_OPTION = "a nested option menu (`#` directly inside an option body)"
WHY_DANGLING = "a jump to a label or scene this game does not define"
WHY_NO_OPTIONS = "a `*choice` every one of whose options was declared"
WHY_OPTION_OUTSIDE = "an option (`#…`) outside any `*choice`"

ENGINE_COMMANDS = {"image", "sound", "text_image"}
DECLARED = {
    "rand": WHY_RANDOM, "gosub": WHY_SUBROUTINE, "gosub_scene": WHY_SUBROUTINE,
    "return": WHY_SUBROUTINE, "params": WHY_SUBROUTINE,
    "achieve": WHY_ACHIEVEMENT, "check_achievements": WHY_ACHIEVEMENT,
    "achievement": WHY_ACHIEVEMENT, "stat_chart": WHY_ACHIEVEMENT,
    "input_text": WHY_INPUT, "input_number": WHY_INPUT,
}
METADATA = {"title", "author", "ifid", "product", "scene_list", "bug", "looplimit",
            "save_checkpoint", "restore_checkpoint", "check_purchase", "purchase",
            "restore_purchases", "delay_break", "delay_ending", "share_this_game",
            "show_password", "abort", "restart", "advertisement", "feedback",
            "more_games", "redirect_scene", "config"}
FLOW = {"goto", "goto_scene", "finish", "ending", "choice", "fake_choice",
        "label", "gosub", "gosub_scene", "return", "goto_random_scene", "gotoref",
        "restart", "abort", "redirect_scene", "page_break_text"}
INTERP = re.compile(r"\$!{1,2}\{|@!?\{|\$\{([^}]*)\}")


# ---------------------------------------------------------------------------
# Lines and blocks.

def read_lines(path):
    text = _source.read_text(path)
    out = []
    for n, raw in enumerate(text.splitlines(), 1):
        if not raw.strip():
            continue
        exp = raw.expandtabs(4)
        out.append({"lineno": n, "indent": len(exp) - len(exp.lstrip()),
                    "text": raw.strip()})
    return text, out


def split_cmd(t):
    m = re.match(r"^\*([A-Za-z_]+)\s*(.*)$", t)
    return (m.group(1).lower(), m.group(2)) if m else (None, None)


def paren_prefix(s):
    """`(a > 1) and (b) #Text` -> ('(a > 1) and (b)', '#Text') for an inline
    option gate. The gate runs to the `#` that is not inside parentheses or a
    string, which is how ChoiceScript reads it."""
    depth, quote = 0, None
    for k, c in enumerate(s):
        if quote:
            if c == quote:
                quote = None
        elif c == '"':
            quote = c
        elif c == "(":
            depth += 1
        elif c == ")":
            depth -= 1
        elif depth == 0 and (c == "#" or s.startswith("*", k)) and k > 0:
            return s[:k].strip(), s[k:].strip()
    return s.strip(), ""


class Scene:
    def __init__(self, name, path, unmapped):
        self.name, self.path, self.unmapped = name, path, unmapped
        self.text, self.lines = read_lines(path)
        self.accounted = []           # (lineno, text)
        self.meta = {}
        self.scene_list = []

    def account(self, lineno, text):
        if text:
            self.accounted.append((lineno, text))

    def declare(self, ln, construct, why, text=None):
        e = {"file": os.path.basename(self.path), "node": self.name,
             "lineno": ln["lineno"], "construct": construct, "why": why}
        if text:
            e["text"] = text
        self.unmapped.append(e)

    # -- block structure ---------------------------------------------------
    def children(self, i):
        """Indices of the block indented under line i, and the index after it."""
        base = self.lines[i]["indent"]
        j = i + 1
        while j < len(self.lines) and self.lines[j]["indent"] > base:
            j += 1
        return i + 1, j

    def parse(self):
        self.stmts = self.block(0, len(self.lines))

    def block(self, a, b):
        out, i = [], a
        while i < b:
            i = self.statement(i, b, out)
        return out

    def statement(self, i, b, out):
        ln = self.lines[i]
        t = ln["text"]
        ca, cb = self.children(i)
        cb = min(cb, b)
        if t.startswith("#"):
            self.declare(ln, "#option", WHY_OPTION_OUTSIDE, text=t[1:].strip())
            self.declare_block(ca, cb, WHY_OPTION_OUTSIDE)
            return cb
        cmd, rest = split_cmd(t)
        if cmd is None:
            out.append({"kind": "line", "text": t, "ln": ln})
            # A prose line with an indented block under it is not ChoiceScript;
            # read the block as following statements rather than drop it.
            out.extend(self.block(ca, cb))
            return cb
        if cmd == "comment":
            return cb
        if cmd in ("if", "elseif", "elsif"):
            return self.if_chain(i, b, out)
        if cmd == "else":
            # An `*else` with no `*if` before it at this level.
            self.declare(ln, "*else", WHY_COMMAND)
            out.extend(self.block(ca, cb))
            return cb
        if cmd in ("choice", "fake_choice"):
            opts = self.options(ca, cb, [])
            out.append({"kind": "choice", "fake": cmd == "fake_choice", "ln": ln,
                        "options": opts})
            return cb
        if cmd == "scene_list":
            for k in range(ca, cb):
                name = self.lines[k]["text"]
                self.account(self.lines[k]["lineno"], name)
                self.scene_list.append(re.sub(r"^\$\S*\s+", "", name).strip())
            return cb
        if cmd in ("title", "author"):
            self.meta[cmd] = rest
            self.account(ln["lineno"], rest)
            return cb
        if cmd in ("achievement", "stat_chart"):
            self.declare(ln, f"*{cmd} {rest}".strip(), WHY_ACHIEVEMENT)
            for k in range(ca, cb):
                self.declare(self.lines[k], f"*{cmd} body", WHY_ACHIEVEMENT,
                             text=self.lines[k]["text"])
            return cb
        stmt = self.simple(cmd, rest, ln)
        if stmt:
            out.append(stmt)
        out.extend(self.block(ca, cb))
        return cb

    def declare_block(self, a, b, why):
        for k in range(a, b):
            ln = self.lines[k]
            cmd, rest = split_cmd(ln["text"])
            if cmd is None:
                self.declare(ln, "line", why, text=ln["text"].lstrip("#").strip())
            elif cmd != "comment":
                self.declare(ln, ln["text"], why)

    def simple(self, cmd, rest, ln):
        """A one-line command as a statement, or None once declared/accounted."""
        n = ln["lineno"]
        if cmd == "label":
            self.account(n, rest)
            return {"kind": "label", "name": rest.strip().lower(), "ln": ln}
        if cmd == "goto":
            self.account(n, rest)
            return {"kind": "goto", "label": rest.strip().lower(), "ln": ln}
        if cmd == "goto_scene":
            self.account(n, rest)
            parts = rest.split()
            return {"kind": "goto_scene", "scene": parts[0] if parts else "",
                    "label": parts[1].lower() if len(parts) > 1 else None, "ln": ln}
        if cmd == "finish":
            return {"kind": "finish", "text": rest.strip() or None, "ln": ln}
        if cmd == "ending":
            return {"kind": "ending", "ln": ln}
        if cmd == "page_break":
            return {"kind": "page_break", "text": rest.strip() or None, "ln": ln}
        if cmd == "line_break":
            return None
        if cmd == "set":
            self.account(n, rest)
            return {"kind": "set", **parse_set(rest), "ln": ln}
        if cmd in ("create", "temp"):
            self.account(n, rest)
            m = re.match(r"^(\w+)\s*(.*)$", rest.strip())
            if not m:
                self.declare(ln, f"*{cmd} {rest}", WHY_EXPR)
                return None
            return {"kind": cmd, "var": m.group(1).lower(), "value": m.group(2).strip(),
                    "ln": ln}
        if cmd in ENGINE_COMMANDS:
            self.account(n, rest)
            toks = re.findall(r'"[^"]*"|\S+', rest)
            args = [t[1:-1] if t.startswith('"') else
                    (int(t) if re.match(r"^-?\d+$", t) else t) for t in toks]
            eff = {"type": "engine", "command": cmd}
            if args:
                eff["args"] = args
            return {"kind": "engine", "effect": eff, "ln": ln}
        if cmd in ("hide_reuse", "disable_reuse", "allow_reuse"):
            return {"kind": "reuse", "mode": cmd.split("_")[0], "ln": ln}
        if cmd in ("input_text", "input_number"):
            self.declare(ln, f"*{cmd} {rest}", WHY_INPUT)
            var = (rest.split() or [""])[0].lower()
            return {"kind": "input", "var": var,
                    "vkind": "text" if cmd == "input_text" else "counter", "ln": ln}
        if cmd in DECLARED:
            self.declare(ln, f"*{cmd} {rest}".strip(), DECLARED[cmd])
            if cmd in ("return", "gosub", "gosub_scene"):
                return {"kind": "declared_flow", "ln": ln}
            return None
        if cmd in METADATA:
            self.account(n, rest)
            if cmd in ("restart", "abort", "redirect_scene"):
                self.declare(ln, f"*{cmd} {rest}".strip(), WHY_COMMAND)
            return None
        self.declare(ln, f"*{cmd} {rest}".strip(), WHY_COMMAND)
        return None

    # -- *if chains ----------------------------------------------------------
    def if_chain(self, i, b, out):
        branches, els = [], None
        k = i
        while k < b:
            ln = self.lines[k]
            cmd, rest = split_cmd(ln["text"])
            if k > i and (ln["indent"] != self.lines[i]["indent"]
                          or cmd not in ("elseif", "elsif", "else")):
                break
            ca, cb = self.children(k)
            cb = min(cb, b)
            self.account(ln["lineno"], rest)
            if cmd == "else":
                els = {"body": self.block(ca, cb), "ln": ln}
                k = cb
                break
            branches.append({"cond": rest.strip(), "body": self.block(ca, cb), "ln": ln})
            k = cb
        out.append({"kind": "if", "branches": branches, "else": els,
                    "ln": self.lines[i]})
        return k

    # -- options -------------------------------------------------------------
    def options(self, a, b, gates):
        """Options under a `*choice`, each with the `*if` gates around it.

        `gates` is a list of (expression, negated) — the enclosing `*if`/`*else`
        groups, each else carrying the negation of the branches above it.
        """
        out, k = [], a
        while k < b:
            ln = self.lines[k]
            ca, cb = self.children(k)
            cb = min(cb, b)
            t = ln["text"]
            cmd, rest = split_cmd(t)
            if cmd in ("if", "elseif", "elsif", "else") and "#" not in \
                    (paren_prefix(rest)[1] if cmd != "else" else rest):
                # A block of options under a condition; an else-chain carries
                # the negation of every branch above it.
                prior = []
                j = k
                while j < b:
                    lj = self.lines[j]
                    cj, rj = split_cmd(lj["text"])
                    if j > k and (lj["indent"] != ln["indent"]
                                  or cj not in ("elseif", "elsif", "else")):
                        break
                    ja, jb = self.children(j)
                    jb = min(jb, b)
                    self.account(lj["lineno"], rj)
                    here = [(p, True) for p in prior]
                    if cj != "else":
                        here.append((rj.strip(), False))
                        prior.append(rj.strip())
                    out.extend(self.options(ja, jb, gates + here))
                    j = jb
                    if cj == "else":
                        break
                k = j
                continue
            opt = {"ln": ln, "gates": list(gates), "selectable": None, "reuse": None,
                   "text": None}
            s = t
            while s.startswith("*"):
                c2, r2 = split_cmd(s)
                if c2 in ("if", "selectable_if"):
                    cond, s = paren_prefix(r2)
                    self.account(ln["lineno"], cond)
                    if c2 == "if":
                        opt["gates"].append((cond, False))
                    else:
                        opt["selectable"] = cond
                elif c2 in ("hide_reuse", "disable_reuse", "allow_reuse"):
                    self.account(ln["lineno"], c2)
                    opt["reuse"] = c2.split("_")[0]
                    s = r2.strip()
                else:
                    break
            if s.startswith("#"):
                opt["text"] = s[1:].strip()
                body_lines = [self.lines[x] for x in range(ca, cb)]
                if body_lines and body_lines[0]["text"].startswith("#") and \
                        body_lines[0]["indent"] == min(x["indent"] for x in body_lines):
                    opt["nested"] = True
                    self.declare_block(ca, cb, WHY_NESTED_OPTION)
                    opt["body"] = []
                else:
                    opt["body"] = self.block(ca, cb)
                out.append(opt)
            else:
                self.declare(ln, t, WHY_COMMAND)
                self.declare_block(ca, cb, WHY_COMMAND)
            k = cb
        return out


def parse_set(rest):
    m = re.match(r"^(\w+)\s*(.*)$", rest.strip())
    if not m:
        return {"var": None, "op": "expr", "raw": rest}
    var, val = m.group(1).lower(), m.group(2).strip()
    rec = {"var": var, "raw": rest.strip()}
    if re.match(r"^%\s*[+-]", val):
        return {**rec, "op": "fair"}
    a = re.match(r"^([+-])\s*(\d+)$", val)
    if a:
        return {**rec, "op": "add", "delta": int(a.group(2)) * (1 if a.group(1) == "+" else -1)}
    a = re.match(r"^" + re.escape(var) + r"\s*([+-])\s*(\d+)$", val, re.I)
    if a:
        return {**rec, "op": "add", "delta": int(a.group(2)) * (1 if a.group(1) == "+" else -1)}
    if val.lower() in ("true", "false"):
        return {**rec, "op": "set", "value": val.lower() == "true"}
    if re.match(r"^\d+$", val):
        return {**rec, "op": "setnum", "value": int(val)}
    if re.match(r'^"(?:[^"\\]|\\.)*"$', val) and "${" not in val:
        return {**rec, "op": "settext", "value": val[1:-1].replace('\\"', '"')}
    return {**rec, "op": "expr"}


def literal_kind(value):
    v = (value or "").strip()
    if v.lower() in ("true", "false"):
        return "flag", v.lower() == "true"
    if re.match(r"^-?\d+$", v):
        return "counter", int(v)
    if re.match(r'^"(?:[^"\\]|\\.)*"$', v) and "${" not in v:
        return "text", v[1:-1].replace('\\"', '"')
    if v == "":
        return None, None
    return "unknown", None


# ---------------------------------------------------------------------------
# Kinds.

def walk_stmts(stmts):
    for st in stmts:
        yield st
        if st["kind"] == "if":
            for br in st["branches"]:
                yield from walk_stmts(br["body"])
            if st["else"]:
                yield from walk_stmts(st["else"]["body"])
        if st["kind"] == "choice":
            for o in st["options"]:
                yield from walk_stmts(o.get("body") or [])


def infer(scenes):
    seen, defaults, engine = {}, {}, set()
    for sc in scenes:
        for st in walk_stmts(sc.stmts):
            if st["kind"] in ("create", "temp"):
                kind, val = literal_kind(st["value"])
                if kind:
                    seen.setdefault(st["var"], set()).add(kind)
                    if kind != "unknown" and st["var"] not in defaults:
                        defaults[st["var"]] = val
            elif st["kind"] == "set" and st.get("var"):
                kind = {"set": "flag", "setnum": "counter", "add": "counter",
                        "fair": "counter", "settext": "text"}.get(st["op"])
                seen.setdefault(st["var"], set()).add(kind or "unknown")
            elif st["kind"] == "input":
                seen.setdefault(st["var"], set()).add(st["vkind"])
                engine.add(st["var"])
    kinds = {}
    for name, ks in seen.items():
        det = ks - {"unknown"}
        kinds[name] = det.pop() if len(det) == 1 else "unknown"
    return kinds, {k: v for k, v in defaults.items() if kinds.get(k) not in (None, "unknown")}, engine


def normalize_expr(expr):
    """ChoiceScript's `=` is equality; the shared translator spells it `==`."""
    return re.sub(r"(?<![<>!=])=(?!=)", "==", expr)


# ---------------------------------------------------------------------------
# The graph.

class Compiler:
    def __init__(self, scenes, order, kinds, unmapped):
        self.scenes = {s.name: s for s in scenes}
        self.order = order
        self.kinds = kinds
        self.unmapped = unmapped
        self.nodes, self.labels, self.entry = {}, {}, {}
        self.status = {}        # (file, lineno) -> unmappable reason
        self.showif = {}        # (file, lineno) -> guard of a carried unit
        self.flags = {}         # one-shot flags: id -> description
        self.order_of = {}
        self.scene = None

    # -- bookkeeping -----------------------------------------------------------
    def file(self):
        return os.path.basename(self.scenes[self.scene].path)

    def key(self, ln):
        return (self.file(), ln["lineno"])

    def declare(self, ln, construct, why, text=None):
        self.scenes[self.scene].declare(ln, construct, why, text)
        if text:
            self.status[self.key(ln)] = why

    def declare_stmts(self, stmts, why):
        """Every unit and state change under `stmts`, declared with one reason."""
        for st in walk_stmts(stmts):
            k = st["kind"]
            if k == "line":
                if self.key(st["ln"]) not in self.status:
                    self.declare(st["ln"], "line", why, st["text"])
            elif k == "choice":
                for o in st["options"]:
                    if o.get("text") is not None and self.key(o["ln"]) not in self.status:
                        self.declare(o["ln"], "#option", why, o["text"])
            elif k in ("page_break", "finish") and st.get("text"):
                self.declare(st["ln"], f"*{k}", why, st["text"])
            elif k in ("set", "engine", "create", "temp", "goto", "goto_scene"):
                self.declare(st["ln"], st["ln"]["text"], why)

    def cond(self, expr):
        return conditions.translate(normalize_expr(expr), self.kinds)

    def text_ok(self, text):
        """None if the line's interpolation maps, else the reason it does not."""
        for m in INTERP.finditer(text):
            name = m.group(1)
            if name is None or not re.match(r"^[a-z][a-z0-9_]*$", name) \
                    or self.kinds.get(name) != "text":
                return WHY_COMPUTED_TEXT
        return None

    def new(self, ln, suffix=""):
        nid = f"n_{self.scene_id()}_{ln['lineno']}{suffix}"
        node = {"id": nid}
        # Source order, for the reader of the output: nodes are compiled
        # backwards from each block's continuation.
        self.order_of[nid] = (self.order.index(self.scene), ln["lineno"])
        self.nodes[nid] = node
        return node

    def scene_id(self):
        s = re.sub(r"[^a-z0-9]+", "_", self.scene.lower()).strip("_")
        return s if re.match(r"^[a-z]", s) else "s_" + s

    def effect(self, st):
        """(Parlance effect or None, reason or None) for a state statement."""
        k = st["kind"]
        if k == "engine":
            return st["effect"], None
        var = st.get("var")
        ident = conditions.var_id(var or "")
        if not ident:
            return None, conditions.WHY_BAD_ID if var else WHY_EXPR
        kind = self.kinds.get(var)
        if k in ("create", "temp"):
            lk, val = literal_kind(st["value"])
            if k == "create":
                # `*create` IS the registry default; nothing happens at play time.
                return None, (WHY_KIND if lk == "unknown" else None)
            if lk is None:
                return None, None               # `*temp x` with no value: nothing to do
            if kind in (None, "unknown") or lk != kind:
                return None, WHY_KIND
            if kind == "flag":
                return {"type": "set_flag", "flag": ident, "value": val}, None
            if kind == "text":
                return {"type": "set_text", "variable": ident, "value": val}, None
            return None, WHY_TEMP_COUNTER
        op = st["op"]
        if op == "fair":
            return None, WHY_FAIRMATH
        if op == "expr":
            return None, WHY_EXPR
        if kind in (None, "unknown"):
            return None, WHY_KIND
        if op == "set" and kind == "flag":
            return {"type": "set_flag", "flag": ident, "value": st["value"]}, None
        if op == "add" and kind == "counter":
            return {"type": "adjust_counter", "counter": ident, "delta": st["delta"]}, None
        if op == "settext" and kind == "text":
            return {"type": "set_text", "variable": ident, "value": st["value"]}, None
        if op == "setnum" and kind == "counter":
            return None, WHY_ABSOLUTE
        return None, WHY_KIND

    @staticmethod
    def interstitial(node):
        return not node.get("choices")

    @staticmethod
    def writes(effects):
        return {e.get("flag") or e.get("counter") or e.get("variable") for e in effects}

    def reads(self, expr, names):
        return any(re.search(r"(?<!\w)" + re.escape(n) + r"(?!\w)", expr or "", re.I)
                   for n in names if n)

    # -- flow ------------------------------------------------------------------
    @staticmethod
    def moves_flow(stmts):
        for st in walk_stmts(stmts):
            if st["kind"] in ("goto", "goto_scene", "finish", "ending", "choice",
                              "label", "declared_flow", "reuse") or \
                    (st["kind"] == "page_break" and st.get("text")):
                return True
        return False

    def seq(self, stmts, cont, guard):
        """Compile a statement list backwards from its continuation.

        Returns (entry ref, effects still looking for a node). A state change
        rides the node that follows it when that node fires exactly when the
        change would; otherwise it is handed back to ride the node BEFORE it —
        which is still before anything that could read it — and a change that
        reaches the start of its block with no node is the caller's to place or
        declare.
        """
        cur, fresh, back = cont, None, []
        for st in reversed(stmts):
            k = st["kind"]
            ln = st["ln"]
            if k == "line":
                why = self.status.get(self.key(ln)) or self.text_ok(st["text"])
                if why:
                    if self.key(ln) not in self.status:
                        self.declare(ln, "line", why, st["text"])
                    continue
                f = self.nodes.get(fresh) if fresh else None
                if f is not None and f.get("choices") and "text" not in f and \
                        not back and not self.reads(st["text"], self.writes(f.get("onEnter") or [])):
                    # The menu's own node carries the line above it: one beat,
                    # line then options, as the source shows it.
                    f["text"] = st["text"]
                    if guard is not None:
                        f["showIf"] = guard
                        self.showif[self.key(ln)] = guard
                    f["_units"] = f.get("_units", []) + [self.key(ln)]
                    cur = ("node", f["id"])
                    continue
                n = self.new(ln)
                n["text"] = st["text"]
                n["_next"] = cur
                if guard is not None:
                    n["showIf"] = guard
                    self.showif[self.key(ln)] = guard
                if back:
                    if guard is not None and cur == ("end",):
                        for e in back:
                            self.declare(ln, json.dumps(e), WHY_NO_CARRIER)
                    else:
                        n["onEnter"] = back
                back = []
                cur, fresh = ("node", n["id"]), n["id"]
            elif k in ("set", "engine", "create", "temp"):
                eff, why = self.effect(st)
                if why:
                    self.declare(ln, ln["text"], why)
                    continue
                if eff is None:
                    continue
                f = self.nodes.get(fresh) if fresh else None
                if f is not None and (guard is None or self.interstitial(f)):
                    f["onEnter"] = [eff] + (f.get("onEnter") or [])
                else:
                    back.insert(0, eff)
            elif k == "label":
                self.labels[(self.scene, st["name"])] = cur
                for e in back:
                    self.declare(ln, json.dumps(e), WHY_NO_CARRIER)
                back, fresh = [], None
            elif k in ("goto", "goto_scene", "finish", "ending"):
                for e in back:
                    self.declare(ln, json.dumps(e), WHY_DEAD)
                back, fresh = [], None
                if k == "goto":
                    cur = ("label", self.scene, st["label"])
                elif k == "goto_scene":
                    cur = ("scene", st["scene"], st["label"])
                elif k == "ending":
                    cur = ("end",)
                else:
                    cur = ("next", self.scene)
                    if st.get("text"):
                        why = self.text_ok(st["text"])
                        if why:
                            self.declare(ln, "*finish", why, st["text"])
                        else:
                            n = self.new(ln)
                            n["choices"] = [{"id": f"c_{self.scene_id()}_{ln['lineno']}",
                                             "text": st["text"], "_goto": cur}]
                            cur, fresh = ("node", n["id"]), n["id"]
            elif k == "page_break":
                if not st.get("text"):
                    continue
                why = self.text_ok(st["text"])
                if why:
                    self.declare(ln, "*page_break", why, st["text"])
                    continue
                n = self.new(ln)
                ch = {"id": f"c_{self.scene_id()}_{ln['lineno']}", "text": st["text"],
                      "_goto": cur}
                if back:
                    ch["effects"] = back         # fire as the button is pressed
                n["choices"] = [ch]
                back, cur, fresh = [], ("node", n["id"]), n["id"]
            elif k == "if":
                cur, fresh, back = self.compile_if(st, cur, fresh, back, guard)
            elif k == "choice":
                for e in back:
                    self.declare(ln, json.dumps(e), WHY_NO_CARRIER)
                back = []
                n = self.compile_choice(st, cur)
                if n is not None:
                    cur, fresh = ("node", n["id"]), n["id"]
            elif k == "reuse":
                pass                                # applied to options up front
            elif k == "input":
                pass                                # declared when parsed
            elif k == "declared_flow":
                fresh = None
        return cur, back

    def compile_if(self, st, cur, fresh, back, guard):
        bodies = [br["body"] for br in st["branches"]] + \
                 ([st["else"]["body"]] if st["else"] else [])
        conds, why = [], None
        for br in st["branches"]:
            c, w = self.cond(br["cond"])
            if w:
                why = w
                break
            conds.append(c)
        if not why and any(self.moves_flow(b) for b in bodies):
            why = WHY_FLOW_IF
        if why:
            for b in bodies:
                self.declare_stmts(b, why)
            self.declare(st["ln"], st["ln"]["text"], why)
            return cur, fresh, back
        # Changes waiting for an earlier node must not jump ahead of a test
        # that reads them.
        exprs = " ".join(br["cond"] for br in st["branches"])
        if back and self.reads(exprs, self.writes(back)):
            for e in back:
                self.declare(st["ln"], json.dumps(e), WHY_NO_CARRIER)
            back = []
        branch_guards = []
        for i in range(len(bodies)):
            parts = [conditions.negate(c) for c in conds[:i]]
            if i < len(conds):
                parts.append(conds[i])
            if guard is not None:
                parts = [guard] + parts
            flat = []
            for p in parts:
                flat.extend(p["of"] if p.get("type") == "all" else [p])
            branch_guards.append(flat[0] if len(flat) == 1 else {"type": "all", "of": flat})
        nxt = cur
        for body, g in reversed(list(zip(bodies, branch_guards))):
            nxt, left = self.seq(body, nxt, g)
            for e in left:
                self.declare(st["ln"], json.dumps(e), WHY_NO_CARRIER)
        return nxt, None, back

    def compile_choice(self, st, cont):
        sc = self.scenes[self.scene]
        choices = []
        for o in st["options"]:
            ln = o["ln"]
            if o.get("text") is None:
                continue
            why = self.text_ok(o["text"])
            parts, lock = [], None
            for expr, neg in o["gates"]:
                if why:
                    break
                c, why = self.cond(expr)
                if c:
                    parts.append(conditions.negate(c) if neg else c)
            if not why and o.get("selectable"):
                if parts:
                    why = WHY_BOTH_GATES
                else:
                    lock, why = self.cond(o["selectable"])
            if why:
                self.declare(ln, "#option", why, o["text"])
                self.declare_stmts(o.get("body") or [], WHY_OPTION_LOST)
                continue
            effects = []
            reuse = o.get("reuse") or sc.reuse
            when_locked = "show" if lock else None
            if reuse in ("hide", "disable"):
                flag = f"reuse_{self.scene_id()}_{ln['lineno']}"
                self.flags[flag] = f"ChoiceScript *{reuse}_reuse on {sc.name}.txt line {ln['lineno']}"
                spent = {"type": "flag", "flag": flag, "value": False}
                effects.append({"type": "set_flag", "flag": flag, "value": True})
                if reuse == "disable" and parts:
                    self.declare(ln, "*disable_reuse", WHY_DISABLE_WITH_IF)
                    parts.append(spent)
                elif reuse == "disable":
                    lock = spent if lock is None else {"type": "all", "of": [lock, spent]}
                    when_locked = "show"
                else:
                    if lock is not None:
                        # A spent option disappears even if it would show locked.
                        self.declare(ln, "*hide_reuse", WHY_BOTH_GATES)
                    parts.append(spent)
            if lock is not None:
                parts.append(lock)
            show = None
            flat = []
            for p in parts:
                flat.extend(p["of"] if p.get("type") == "all" else [p])
            if flat:
                show = flat[0] if len(flat) == 1 else {"type": "all", "of": flat}
            entry, left = self.seq(o.get("body") or [], cont, None)
            ch = {"id": f"c_{self.scene_id()}_{ln['lineno']}", "text": o["text"],
                  "_goto": entry}
            if effects or left:
                ch["effects"] = effects + left
            if show:
                ch["showIf"] = show
                self.showif[self.key(ln)] = show
            if when_locked:
                ch["whenLocked"] = when_locked
            choices.append(ch)
        if not choices:
            self.declare(st["ln"], "*choice", WHY_NO_OPTIONS)
            return None
        n = self.new(st["ln"])
        n["choices"] = choices
        return n

    # -- the whole game ----------------------------------------------------------
    def run(self):
        for name in self.order:
            self.scene = name
            sc = self.scenes[name]
            sc.reuse = next((st["mode"] for st in sc.stmts if st["kind"] == "reuse"), None)
            entry, left = self.seq(sc.stmts, ("next", name), None)
            for e in left:
                self.declare(sc.lines[0] if sc.lines else {"lineno": 0},
                             json.dumps(e), WHY_NO_CARRIER)
            self.entry[name] = entry
        for n in self.nodes.values():
            if "_next" in n:
                target = self.resolve(n.pop("_next"))
                if target:
                    n["next"] = target
                else:
                    n["isEnd"] = True
            for c in n.get("choices") or []:
                target = self.resolve(c.pop("_goto"))
                if target:
                    c["goto"] = target
                else:
                    # A choice with no goto ends the dialogue, which Parlance
                    # allows only on a node that may end it.
                    n["isEnd"] = True
            if not n.get("next") and not n.get("choices") and not n.get("isEnd"):
                n["isEnd"] = True
            n.pop("_units", None)

    def resolve(self, ref, seen=None):
        seen = seen or set()
        while ref is not None and ref not in seen:
            seen.add(ref)
            kind = ref[0]
            if kind == "node":
                return ref[1]
            if kind == "end":
                return None
            if kind == "label":
                nxt = self.labels.get((ref[1], ref[2]))
                if nxt is None:
                    self.dangling(f"*goto {ref[2]}", ref)
                ref = nxt
            elif kind == "scene":
                scene, label = ref[1], ref[2]
                if scene not in self.entry:
                    self.dangling(f"*goto_scene {scene}", ref)
                    return None
                ref = self.labels.get((scene, label)) if label else self.entry[scene]
                if ref is None:
                    self.dangling(f"*goto_scene {scene} {label}", ref)
            elif kind == "next":
                # `*finish`: the next scene in *scene_list, or the end of the game.
                listed = [s for s in self.order_list if s in self.entry]
                if ref[1] in listed and listed.index(ref[1]) + 1 < len(listed):
                    ref = self.entry[listed[listed.index(ref[1]) + 1]]
                else:
                    return None
            else:
                return None
        return None

    def dangling(self, construct, ref):
        key = ("dangling", construct)
        if key in self.status:
            return
        self.status[key] = True
        self.unmapped.append({"file": None, "node": None, "lineno": None,
                              "construct": construct, "why": WHY_DANGLING})


# ---------------------------------------------------------------------------

def locate(path):
    if os.path.isdir(path):
        return path
    return os.path.dirname(os.path.abspath(path))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("source", help="the scenes directory, or its startup.txt")
    ap.add_argument("--emit", choices=["ir", "manifest"], default="ir")
    a = ap.parse_args()
    root = locate(a.source)
    startup = os.path.join(root, "startup.txt")
    if not os.path.exists(startup):
        sys.exit(f"no startup.txt in {root} — a ChoiceScript game starts there")

    unmapped, scenes, order = [], [], []
    queue = ["startup"]
    while queue:
        name = queue.pop(0)
        if name in order:
            continue
        path = os.path.join(root, name + ".txt")
        if not os.path.exists(path):
            unmapped.append({"file": None, "node": name, "lineno": None,
                             "construct": f"scene {name}",
                             "why": "a scene named by the game with no file beside startup.txt"})
            continue
        sc = Scene(name, path, unmapped)
        sc.parse()
        scenes.append(sc)
        order.append(name)
        nxt = list(sc.scene_list)
        for st in walk_stmts(sc.stmts):
            if st["kind"] == "goto_scene" and st["scene"]:
                nxt.append(st["scene"])
        queue += [n for n in nxt if n not in order]

    scene_list = next((s.scene_list for s in scenes if s.name == "startup"), [])
    listed = ["startup"] + [s for s in scene_list if s != "startup"]
    kinds, defaults, engine = infer(scenes)
    comp = Compiler(scenes, order, kinds, unmapped)
    comp.order_list = listed
    comp.run()

    by_name = {s.name: s for s in scenes}
    units = []
    for sc in scenes:
        f = os.path.basename(sc.path)

        def unit(kind, ln, text):
            key = (f, ln["lineno"])
            u = {"kind": kind, "node": sc.name, "file": f, "speaker": None,
                 "text": text, "lineno": ln["lineno"]}
            if key in comp.status:
                u["unmappable"] = comp.status[key]
            elif key in comp.showif:
                u["showIf"] = comp.showif[key]
            units.append(u)
        for st in walk_stmts(sc.stmts):
            if st["kind"] == "line":
                unit("line", st["ln"], st["text"])
            elif st["kind"] == "choice":
                for o in st["options"]:
                    if o.get("text") is not None:
                        unit("option", o["ln"], o["text"])
            elif st["kind"] in ("page_break", "finish") and st.get("text"):
                unit("option", st["ln"], st["text"])

    # Declared prose that never became a statement — an achievement's text, an
    # option outside any menu — is still a unit: the author is shown it under
    # `missing_declared` like every other line the import could not carry.
    have = {(u["file"], u["lineno"]) for u in units}
    for e in unmapped:
        if e.get("text") and e.get("file") and (e["file"], e["lineno"]) not in have:
            units.append({"kind": "line", "node": e["node"], "file": e["file"],
                          "speaker": None, "text": e["text"], "lineno": e["lineno"],
                          "unmappable": e["why"]})
            have.add((e["file"], e["lineno"]))

    title = by_name["startup"].meta.get("title") if "startup" in by_name else None
    entry = comp.resolve(comp.entry.get("startup")) if "startup" in comp.entry else None
    if a.emit == "ir":
        print(json.dumps({"source": a.source, "format": "choicescript",
                          "title": title, "scenes": order, "sceneList": listed,
                          "entry": entry,
                          "nodes": sorted(comp.nodes.values(),
                                          key=lambda n: comp.order_of[n["id"]]),
                          "variables": sorted(kinds), "variableKinds": kinds,
                          "defaults": defaults, "engineWritten": sorted(engine),
                          "onceFlags": comp.flags, "rewrites": [["${", "{"]],
                          "unmapped": unmapped}, indent=2, ensure_ascii=False))
        return 0

    residue = []
    for sc in scenes:
        f = os.path.basename(sc.path)
        mine = [u for u in units if u["file"] == f]
        um = [e for e in unmapped if e.get("file") == f]
        for r in find_residue(sc.text, mine, um, sc.accounted, fmt="choicescript"):
            residue.append({**r, "file": f})
    man = {"source": a.source, "format": "choicescript", "units": units,
           "literals": _manifest.literals_of(list(comp.nodes.values())),
           "variables": sorted(kinds), "variableKinds": kinds, "nodes": order,
           "unmapped": unmapped,
           # ChoiceScript writes `${name}`, Parlance `{name}`: one token, the
           # same interpolation. A line interpolating anything but a TEXT
           # variable is declared, so the swap never produces a dangling
           # placeholder.
           "rewrites": [["${", "{"]], "residue": residue}
    print(json.dumps(_manifest.stamp(man), indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
