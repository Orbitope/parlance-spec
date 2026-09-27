#!/usr/bin/env python3
"""
parse_renpy.py — deterministic Ren'Py script parser.

Emits an intermediate representation for an importer to MAP from, and a
reconciliation manifest for check.py to verify against. The model never
transcribes prose: every string in the output of an import must have come from
here, byte for byte.

Ren'Py is a Python-flavoured screenplay language, and most of a story written in
it is four statements: `label`, a say statement (`e "Hello."`), `menu:` and
`jump`. Those carry. So do `define e = Character("Eileen")` (a character),
`default x = …` (a registered variable), `$ x = literal` / `$ x += n` (effects),
an `if`/`elif`/`else` block around lines (`node.showIf`, with the negations
worked out), and the staging statements — `show`, `scene`, `hide`, `play`,
`stop`, `queue`, `with`, `pause`, `window`, `voice`, `nvl`, `camera` — which
are statement-shaped engine commands with literal arguments and ride as 0.15
`engine` effects.

What does NOT carry is named, with its source line, in "unmapped": `call` /
`return` as a subroutine (ROADMAP decided no cross-dialogue call/return),
`python:` and `init` blocks, screens, transforms, a jump or a menu inside an
`if` (a destination chosen by a condition), and any `$` line that is not an
assignment of a literal.

TEXT TAGS ARE MARKUP, NOT PROSE. `{b}Good Ending{/b}.` is three words and two
formatting instructions. The unit's text is the string with the tags removed —
every character of it is a character of the source, in order, and nothing is
added — and each tag is recorded in `unmapped` as a presentation loss. That is
the same accounting the Twine parser applies to a styling macro: the macro is
declared, the words inside it stay required. Decoding a string literal's escapes
(`\\"` → `"`) is decoding, not a rewrite, for the reason Twine's entity decoding
is: the escape is something the file format did to the author's text, and
decoding returns their bytes.

Usage:
    python3 parse_renpy.py script.rpy --emit ir        > ir.json
    python3 parse_renpy.py script.rpy --emit manifest  > manifest.json
"""
import argparse, json, os, re, sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from residue import find_residue, strip_hash_comment
import conditions
import manifest as _manifest
import source as _source

# --- the reasons, spelled once ------------------------------------------------
WHY_CALL = ("`call` runs a label as a subroutine and `return`s to the caller. Parlance "
            "has no cross-dialogue call/return (ROADMAP: decided), and a `goto` names one "
            "node rather than 'back where you came from'. The flow continues after the "
            "call as if the called label were never run")
WHY_COND_JUMP = ("a jump (or return) inside an `if` block — the story goes somewhere else "
                 "only when the condition holds. A Parlance `next` and `goto` are "
                 "unconditional; `showIf` gates whether a NODE is shown, not where the "
                 "conversation goes next")
WHY_COND_MENU = ("a menu inside an `if` block. A gated node that carries choices still "
                 "offers them (0.15 hides only the LINE), so the menu cannot be gated as a "
                 "whole without changing when the player sees it")
WHY_PYTHON = ("Python — a `python:` / `init python:` block or a `$` line that is not an "
              "assignment of a literal. The Parlance effect vocabulary is closed and calls "
              "nothing")
WHY_BLOCK = ("a definition block (`screen`, `transform`, `style`, `init`, `image`, "
             "`layeredimage`, `translate`) — presentation and engine configuration, not "
             "story, and no Parlance field holds it")
WHY_TEXT_TAG = ("a Ren'Py text tag — formatting or timing inside a line (`{b}`, `{i}`, "
                "`{w}`, `{color=…}`). Parlance text is plain; the words inside the tag are "
                "carried, the formatting is not")
WHY_INTERP = ("text computed at runtime — a `[…]` interpolation of something other than a "
              "text variable (a number, an expression, a format flag). A Parlance "
              "placeholder `{var}` names a registered TEXT variable and nothing else")
WHY_ABS_COUNTER = ("an absolute assignment to a number (`$ x = 3`). The effect vocabulary "
                   "has `adjust_counter` with a delta and no absolute set, which would need "
                   "the value at this point in the story")
WHY_UNHOSTED = ("an effect with no line after it in the same scope to carry it — a Parlance "
                "effect rides on a node or a choice, and moving it onto another line would "
                "change when it fires relative to that line's gate")
WHY_CHAR_KWARGS = ("Character() presentation arguments (colour, image, window style). A "
                   "Parlance character carries a name; how the engine draws it is not data")
WHY_SAY_ATTRS = ("image attributes on a say statement (`e happy \"…\"`) — an expression "
                 "change the engine applies while the line shows. Not carried")
WHY_SAY_EXTRA = ("say-statement arguments (`id`, `(…)`, `nointeract`) with no Parlance "
                 "field")
WHY_UNKNOWN = "a Ren'Py statement this parser does not map"
WHY_TOPLEVEL_SAY = "a say statement outside any label — nothing can reach it"
WHY_LABEL_PARAMS = ("a label that takes parameters — it is only meaningful as a `call` "
                    "target, and call/return is not carried")
WHY_SPEAKER = ("a say statement whose speaker is not a `define`d Character — the line is "
               "carried as narration and the attribution is lost")

ENGINE_STATEMENTS = ("show", "scene", "hide", "play", "stop", "queue", "with", "pause",
                     "window", "voice", "nvl", "camera")
BLOCK_STATEMENTS = ("init", "python", "screen", "transform", "style", "image",
                    "layeredimage", "translate", "testcase")
CHARACTER_CTORS = ("Character", "DynamicCharacter", "ADVCharacter", "NVLCharacter")

IDENT = r"[A-Za-z_]\w*"
STRING = r'"(?:[^"\\]|\\.)*"|\'(?:[^\'\\]|\\.)*\''
SAY = re.compile(r"^(?:(?P<who>" + IDENT + r"(?:\." + IDENT + r")*|" + STRING +
                 r")\s+(?P<attrs>(?:[@-]?" + IDENT + r"\s+)*))?"
                 r"(?P<str>" + STRING + r")(?P<rest>.*)$", re.S)
CHOICE = re.compile(r"^(?P<str>" + STRING + r")\s*(?P<args>\([^)]*\))?\s*"
                    r"(?:if\s+(?P<cond>.+?))?\s*:$", re.S)
ASSIGN = re.compile(r"^(" + IDENT + r")\s*(=|\+=|-=)\s*(.+)$")
TEXT_TAG = re.compile(r"\{(?!\{)/?[A-Za-z#][^{}]*\}")
INTERP = re.compile(r"\[(?!\[)([^\[\]]*)\]")


# --- lexical layer ----------------------------------------------------------

# Where a `#` comment starts is shared with residue.py, so the parser and the
# accounting cannot disagree about it.
strip_comment = strip_hash_comment


def logical_lines(text):
    """(first lineno, [linenos], indent, code) — continuation lines joined.

    A logical line continues while a bracket or a string is open. Ren'Py lets a
    say statement's string run over several lines, and a Character() call spread
    one argument per line is common.
    """
    out, buf, nums, depth, quote, indent = [], [], [], 0, None, 0
    for lineno, raw in enumerate(text.split("\n"), 1):
        code, quote_after = strip_comment(raw, quote)
        if not buf:
            if not code.strip():
                quote = quote_after
                continue
            indent = len(code) - len(code.lstrip(" \t"))
        buf.append(code if buf else code.strip())
        nums.append(lineno)
        # Bracket depth outside strings.
        q = quote
        i = 0
        while i < len(code):
            c = code[i]
            if q:
                if code.startswith(q, i) and code[i - 1:i] != "\\":
                    i += len(q)
                    q = None
                    continue
            elif c in "([{":
                depth += 1
            elif c in ")]}":
                depth -= 1
            elif c in "\"'":
                q = code[i:i + 3] if code[i:i + 3] in ('"""', "'''") else c
                i += len(q)
                continue
            i += 1
        quote = quote_after
        if depth <= 0 and not quote:
            joined = "\n".join(buf).strip()
            out.append((nums[0], nums, indent, joined))
            buf, nums, depth = [], [], 0
    if buf:
        out.append((nums[0], nums, indent, "\n".join(buf).strip()))
    return out


def blocks(lines):
    """Logical lines as a tree: a line ending in `:` owns the deeper ones after it."""
    root = {"indent": -1, "children": []}
    stack = [root]
    for first, nums, indent, code in lines:
        node = {"lineno": first, "linenos": nums, "indent": indent, "code": code,
                "children": []}
        while stack[-1]["indent"] >= indent:
            stack.pop()
        stack[-1]["children"].append(node)
        stack.append(node)
    return root["children"]


def decode_string(lit):
    """A Ren'Py string literal's value: quotes off, escapes decoded, `_()` unwrapped.

    Ren'Py collapses a run of whitespace inside a say string to one space (a
    string spread over lines reads as one line), so that is applied too; the
    check compares whitespace-normalised text either way.
    """
    s = lit.strip()
    m = re.match(r"^_\(\s*(.*)\s*\)$", s, re.S)
    if m:
        s = m.group(1).strip()
    for q in ('"""', "'''", '"', "'"):
        if s.startswith(q) and s.endswith(q) and len(s) >= 2 * len(q):
            s = s[len(q):-len(q)]
            break
    else:
        return None
    s = re.sub(r"\s+", " ", s)
    out, i = [], 0
    while i < len(s):
        if s[i] == "\\" and i + 1 < len(s):
            nxt = s[i + 1]
            out.append({"n": "\n", "t": " ", "\\": "\\", '"': '"', "'": "'",
                        " ": " ", "%": "%"}.get(nxt, "\\" + nxt))
            i += 2
            continue
        out.append(s[i])
        i += 1
    return "".join(out)


def split_top_level(arg):
    """Split on commas outside quotes and brackets."""
    out, depth, quote, cur = [], 0, None, []
    for ch in arg:
        if quote:
            if ch == quote:
                quote = None
        elif ch in "'\"":
            quote = ch
        elif ch in "([{":
            depth += 1
        elif ch in ")]}":
            depth -= 1
        elif ch == "," and depth == 0:
            out.append("".join(cur).strip())
            cur = []
            continue
        cur.append(ch)
    if "".join(cur).strip():
        out.append("".join(cur).strip())
    return out


def literal(raw):
    """(kind, value) for a Python literal, or (None, None)."""
    v = raw.strip()
    if v in ("True", "False"):
        return "flag", v == "True"
    if re.match(r"^-?\d+$", v):
        return "counter", int(v)
    s = decode_string(v)
    if s is not None and not v.startswith("_("):
        return "text", s
    return None, None


def engine_args(rest):
    """Literal tokens of a staging statement, or None if any is an expression."""
    args, pos, rest = [], 0, rest.strip()
    tok = re.compile(r"(" + STRING + r"|-?\d+\.\d+|-?\d+|[A-Za-z_][\w.]*)(?:\s+|$)")
    while pos < len(rest):
        m = tok.match(rest, pos)
        if not m:
            return None
        t = m.group(1)
        if t[0] in "\"'":
            args.append(decode_string(t))
        elif re.match(r"^-?\d+$", t):
            args.append(int(t))
        elif re.match(r"^-?\d+\.\d+$", t):
            args.append(float(t))
        elif t in ("True", "False"):
            args.append(t == "True")
        else:
            args.append(t)
        pos = m.end()
    return args


def split_tags(text):
    """(text with Ren'Py text tags removed, [tags]).

    `{{` is an escaped literal brace and is decoded to one; everything else in
    braces that opens with a letter, `/` or `#` is a tag.
    """
    tags = TEXT_TAG.findall(text)
    return TEXT_TAG.sub("", text).replace("{{", "{"), tags


# --- the interpreter -----------------------------------------------------------

class Parser:
    def __init__(self, text):
        self.text = text
        self.tree = blocks(logical_lines(text))
        self.unmapped = []
        self.accounted = []          # (lineno, text) the parser recognised
        self.characters = {}         # var -> {"name":…}
        self.kinds, self.defaults, self.consts = {}, {}, {}
        self.labels, self.order = {}, []
        self.include_disabled = False
        self.guard_seq = 0
        self.units_declared = []     # units under a construct declared whole
        self.cur_label = None

    # -- bookkeeping -----------------------------------------------------------
    def account(self, node):
        """Every physical line of a recognised statement, whole."""
        raw = self.text.split("\n")
        for n in node["linenos"]:
            self.accounted.append((n, raw[n - 1]))

    def declare_block(self, node, why, construct=None):
        """A statement and everything under it, declared as loss line by line."""
        raw = self.text.split("\n")
        for n in node["linenos"]:
            self.unmapped.append({"node": self.cur_label, "lineno": n,
                                  "construct": construct or raw[n - 1].strip(),
                                  "why": why})
        for ch in node["children"]:
            self.declare_block(ch, why)

    # -- pass 1: declarations and kinds -----------------------------------------
    def prescan(self):
        """Characters, variables, constants and their kinds, before any story."""
        seen = {}

        def note(name, kind):
            seen.setdefault(name, set()).add(kind)

        def walk(nodes):
            for n in nodes:
                code = n["code"]
                m = re.match(r"^(define|default)\s+([\w.]+)\s*=\s*(.+)$", code, re.S)
                if m:
                    stmt, name, val = m.groups()
                    ctor = re.match(r"^(" + "|".join(CHARACTER_CTORS) + r")\((.*)\)$",
                                    val.strip(), re.S)
                    if stmt == "define" and ctor:
                        args = split_top_level(ctor.group(2))
                        pos = [a for a in args if not re.match(r"^\w+\s*=", a)]
                        name_str = decode_string(pos[0]) if pos else None
                        self.characters[name] = {"name": name_str,
                                                 "kwargs": [a.split("=")[0].strip()
                                                            for a in args if a not in pos]}
                    elif name == "config.menu_include_disabled":
                        self.include_disabled = val.strip() == "True"
                    else:
                        kind, value = literal(val)
                        if stmt == "default" and "." not in name:
                            note(name, kind or "unknown")
                            if kind:
                                self.defaults[name] = value
                        elif stmt == "define" and kind:
                            self.consts[name] = val.strip()
                a = re.match(r"^\$\s*(.+)$", code, re.S)
                if a:
                    am = ASSIGN.match(a.group(1).strip())
                    if am:
                        name, op, val = am.groups()
                        if op in ("+=", "-="):
                            note(name, "counter" if re.match(r"^-?\d+$", val.strip())
                                 else "unknown")
                        else:
                            note(name, literal(val)[0] or "unknown")
                walk(n["children"])
        walk(self.tree)
        # Only from evidence that admits one reading, as in the other parsers:
        # conflicting literal kinds resolve to unknown rather than to a majority.
        for name, ks in seen.items():
            det = ks - {"unknown"}
            self.kinds[name] = det.pop() if len(det) == 1 else "unknown"

    # -- pass 2: the story ------------------------------------------------------
    def run(self):
        self.prescan()
        self.cur_label = None
        for n in self.tree:
            code = n["code"]
            head = code.split()[0] if code.split() else ""
            lm = re.match(r"^label\s+(" + IDENT + r")\s*(\(.*\))?\s*:$", code, re.S)
            if lm:
                name = lm.group(1)
                self.cur_label = name
                self.account(n)
                if lm.group(2):
                    self.declare_block(n, WHY_LABEL_PARAMS)
                    continue
                self.labels[name] = {"name": name, "lineno": n["lineno"],
                                     "items": self.scope(n["children"], [])}
                self.order.append(name)
                continue
            self.cur_label = None
            if head in ("define", "default"):
                self.account(n)
                m = re.match(r"^define\s+(\w+)\s*=", code)
                if m and m.group(1) in self.characters:
                    kw = self.characters[m.group(1)]["kwargs"]
                    if kw:
                        self.unmapped.append({"node": None, "lineno": n["lineno"],
                                              "construct": f"Character({', '.join(kw)}=…)",
                                              "why": WHY_CHAR_KWARGS})
                elif head == "define" and not code.startswith("define config."):
                    pass            # a constant: inlined into conditions that use it
                continue
            if head.rstrip(":") in BLOCK_STATEMENTS or head.startswith("init"):
                self.declare_block(n, WHY_PYTHON if "python" in code.split(":")[0]
                                   else WHY_BLOCK)
                continue
            if SAY.match(code):
                self.declare_block(n, WHY_TOPLEVEL_SAY)
                continue
            self.declare_block(n, WHY_UNKNOWN)
        self.analyse_links()

    def new_frame(self, expr, prior):
        self.guard_seq += 1
        return {"id": self.guard_seq, "current": expr, "prior": list(prior)}

    def scope(self, nodes, guard):
        """A block's statements as a flat item list, with effects hosted.

        `guard` is the stack of enclosing if-frames. An if/elif/else chain does
        not produce a nested structure: its lines are flattened into this scope,
        each with the guard of its branch — the if's test, or the NEGATION of
        every branch above it and the elif's own test. Ren'Py writes neither
        negation down, which is exactly why it is computed here.
        """
        items, chain = [], None
        for n in nodes:
            code = n["code"]
            head = re.split(r"[\s:(]", code, 1)[0]
            if head in ("if", "elif") or code == "else:" or head == "else":
                expr = None
                if head != "else":
                    expr = code[len(head):].rstrip(":").strip()
                if head == "if" or chain is None:
                    chain = []
                frame = self.new_frame(expr, chain)
                if expr is not None:
                    chain.append(expr)
                self.account(n)
                items += self.scope(n["children"], guard + [frame])
                continue
            chain = None
            items += self.statement(n, guard)
        return self.host(items)

    def guard_of(self, guard):
        parts = []
        for frame in guard:
            for expr, invert in ([(p, True) for p in frame["prior"]] +
                                 ([(frame["current"], False)]
                                  if frame["current"] is not None else [])):
                expr = re.sub(r"\bis\s+not\b", "!=", expr)
                cond, why = conditions.translate(expr, self.kinds, self.consts)
                if why:
                    return None, why
                parts.append(conditions.negate(cond) if invert else cond)
        if not parts:
            return None, None
        return (parts[0] if len(parts) == 1 else {"type": "all", "of": parts}), None

    def statement(self, n, guard):
        code, lineno = n["code"], n["lineno"]
        head = re.split(r"[\s:(]", code, 1)[0]
        gkey = tuple(f["id"] for f in guard)

        if head == "pass":
            self.account(n)
            return []
        if head == "jump" or head == "return":
            self.account(n)
            target = code.split()[1] if head == "jump" and len(code.split()) > 1 else None
            if head == "jump" and (target == "expression" or len(code.split()) != 2):
                self.unmapped.append({"node": self.cur_label, "lineno": lineno,
                                      "construct": code, "why": WHY_UNKNOWN})
                return []
            if guard:
                self.unmapped.append({"node": self.cur_label, "lineno": lineno,
                                      "construct": code, "why": WHY_COND_JUMP})
                return []
            return [{"kind": head, "target": target, "lineno": lineno}]
        if head == "call":
            self.declare_block(n, WHY_CALL, code)
            return []
        if head == "menu":
            if guard:
                self.declare_menu(n, WHY_COND_MENU)
                return []
            self.account(n)
            return [self.menu(n)]
        if head == "$":
            return self.python_line(n, guard, gkey)
        if head in ENGINE_STATEMENTS:
            args = engine_args(code[len(head):])
            if args is None or (head in ("show", "scene", "hide") and args[:1] ==
                                ["expression"]):
                self.declare_block(n, WHY_PYTHON if "(" in code else WHY_UNKNOWN, code)
                return []
            self.account(n)
            eff = {"type": "engine", "command": head}
            if args:
                eff["args"] = args
            return [{"kind": "effect", "effect": eff, "lineno": lineno, "guard": gkey}]
        if head.rstrip(":") in BLOCK_STATEMENTS:
            self.declare_block(n, WHY_PYTHON if head.startswith("python") else WHY_BLOCK)
            return []
        m = SAY.match(code)
        if m and not n["children"]:
            return [self.say(n, m, guard)]
        self.declare_block(n, WHY_UNKNOWN)
        return []

    def python_line(self, n, guard, gkey):
        code, lineno = n["code"], n["lineno"]
        body = code[1:].strip()
        am = ASSIGN.match(body)
        eff, why = None, WHY_PYTHON
        if am:
            name, op, val = am.groups()
            kind, ident = self.kinds.get(name), conditions.var_id(name)
            lk, lv = literal(val)
            if not ident or kind not in ("flag", "counter", "text"):
                why = conditions.WHY_UNKNOWN_VAR if ident else conditions.WHY_BAD_ID
            elif op in ("+=", "-=") and kind == "counter" and lk == "counter":
                eff = {"type": "adjust_counter", "counter": ident,
                       "delta": lv if op == "+=" else -lv}
            elif op == "=" and kind == "flag" and lk == "flag":
                eff = {"type": "set_flag", "flag": ident, "value": lv}
            elif op == "=" and kind == "text" and lk == "text":
                eff = {"type": "set_text", "variable": ident, "value": lv}
            elif op == "=" and kind == "counter" and lk == "counter":
                why = WHY_ABS_COUNTER
        if eff is None:
            self.declare_block(n, why, code)
            return []
        self.account(n)
        return [{"kind": "effect", "effect": eff, "lineno": lineno, "guard": gkey}]

    def text_of(self, lit, lineno, who=None):
        """A string literal as unit text, with its tags declared."""
        text = decode_string(lit)
        text, tags = split_tags(text)
        for t in tags:
            self.unmapped.append({"node": self.cur_label, "lineno": lineno,
                                  "construct": t, "why": WHY_TEXT_TAG})
        return text

    def interp_reason(self, text):
        """None if every `[…]` names a text variable, else why not."""
        if "[[" in text:
            return WHY_INTERP
        for inner in INTERP.findall(text):
            if not (re.match(r"^" + IDENT + r"$", inner)
                    and self.kinds.get(inner) == "text" and conditions.var_id(inner) == inner):
                return WHY_INTERP
        return None

    def say(self, n, m, guard):
        lineno, raw = n["lineno"], self.text.split("\n")
        who, attrs, rest = m.group("who"), (m.group("attrs") or "").split(), m.group("rest")
        speaker = None
        if who:
            if who[0] in "\"'":
                name = decode_string(who)
                ident = conditions.var_id(re.sub(r"\s+", "_", name or ""))
                if ident:
                    self.characters.setdefault(ident, {"name": name, "kwargs": [],
                                                       "literal": True})
                    speaker = ident
            elif who in self.characters and self.characters[who].get("name"):
                speaker = who
            elif who not in ("narrator", "extend", "centered"):
                self.unmapped.append({"node": self.cur_label, "lineno": lineno,
                                      "construct": who, "why": WHY_SPEAKER})
        text = self.text_of(m.group("str"), lineno)
        item = {"kind": "line", "lineno": lineno, "speaker": speaker, "text": text,
                "effects": [], "guard": tuple(f["id"] for f in guard)}
        if attrs:
            self.unmapped.append({"node": self.cur_label, "lineno": lineno,
                                  "construct": " ".join(attrs), "why": WHY_SAY_ATTRS})
        rest = rest.strip()
        wm = re.match(r"^with\s+(" + IDENT + r")\s*$", rest)
        if wm:
            item["effects"].append({"type": "engine", "command": "with",
                                    "args": [wm.group(1)]})
        elif rest:
            self.unmapped.append({"node": self.cur_label, "lineno": lineno,
                                  "construct": rest, "why": WHY_SAY_EXTRA})
        # Every physical line the statement spans; the text is the unit, the rest
        # (speaker, attributes, `with`) was recognised above.
        for k in n["linenos"][1:]:
            self.accounted.append((k, raw[k - 1]))
        self.accounted.append((lineno, (who or "") + " " + rest))
        why = self.interp_reason(text)
        cond, gwhy = self.guard_of(guard)
        why = gwhy or why
        if why:
            item["unmappable"] = why
            self.unmapped.append({"node": self.cur_label, "lineno": lineno,
                                  "construct": "say", "text": text, "why": why})
        elif cond:
            item["showIf"] = cond
        return item

    def menu(self, n):
        lineno = n["lineno"]
        mm = re.match(r"^menu(?:\s+(" + IDENT + r"))?\s*(\(.*\))?\s*:$", n["code"], re.S)
        item = {"kind": "menu", "lineno": lineno, "caption": None, "choices": [],
                "effects": [], "label": mm.group(1) if mm else None, "guard": ()}
        for ch in n["children"]:
            code = ch["code"]
            cm = CHOICE.match(code)
            if cm:
                item["choices"].append(self.choice(ch, cm))
                continue
            sm = SAY.match(code)
            if sm and not ch["children"] and item["caption"] is None and not item["choices"]:
                item["caption"] = self.say(ch, sm, [])
                continue
            self.declare_block(ch, WHY_UNKNOWN)
        return item

    def choice(self, n, cm):
        lineno, raw = n["lineno"], self.text.split("\n")
        text = self.text_of(cm.group("str"), lineno)
        opt = {"kind": "option", "lineno": lineno, "speaker": None, "text": text,
               "effects": [], "items": []}
        for k in n["linenos"]:
            self.accounted.append((k, (cm.group("args") or "") + " if " +
                                   (cm.group("cond") or "") if k == lineno else raw[k - 1]))
        if cm.group("args"):
            self.unmapped.append({"node": self.cur_label, "lineno": lineno,
                                  "construct": cm.group("args"), "why": WHY_SAY_EXTRA})
        why = self.interp_reason(text)
        if cm.group("cond") and not why:
            cond, why = self.guard_of([self.new_frame(cm.group("cond").strip(), [])])
            if cond:
                opt["showIf"] = cond
                if self.include_disabled:
                    opt["whenLocked"] = "show"
        if why:
            opt["unmappable"] = why
            self.unmapped.append({"node": self.cur_label, "lineno": lineno,
                                  "construct": "menu choice", "text": text, "why": why})
        items = self.scope(n["children"], [])
        # Effects before the block's first line ride on the choice itself: they
        # fire when it is picked, which is when Ren'Py runs them.
        while items and items[0]["kind"] == "effect" and not items[0]["guard"]:
            opt["effects"].append(items.pop(0)["effect"])
        opt["items"] = items
        return opt

    def declare_menu(self, n, why):
        """A menu that cannot be carried: every unit under it, declared."""
        self.account(n)
        for ch in n["children"]:
            cm = CHOICE.match(ch["code"])
            sm = SAY.match(ch["code"])
            if cm or (sm and not ch["children"]):
                lit = (cm or sm).group("str")
                text = self.text_of(lit, ch["lineno"])
                self.unmapped.append({"node": self.cur_label, "lineno": ch["lineno"],
                                      "construct": "menu", "text": text, "why": why})
                self.units_declared.append({"kind": "option" if cm else "line",
                                            "node": self.cur_label,
                                            "speaker": None, "text": text,
                                            "lineno": ch["lineno"], "unmappable": why})
                self.accounted.append((ch["lineno"], ch["code"]))
                for sub in ch["children"]:
                    self.declare_deep(sub, why)
            else:
                self.declare_block(ch, why)

    def declare_deep(self, n, why):
        """Declare a subtree, keeping the text of any say statement in it as a unit."""
        sm = SAY.match(n["code"])
        cm = CHOICE.match(n["code"])
        if (sm and not n["children"]) or cm:
            text = self.text_of((cm or sm).group("str"), n["lineno"])
            self.units_declared.append({"kind": "option" if cm else "line",
                                        "node": self.cur_label, "speaker": None,
                                        "text": text, "lineno": n["lineno"],
                                        "unmappable": why})
            self.unmapped.append({"node": self.cur_label, "lineno": n["lineno"],
                                  "construct": "say", "text": text, "why": why})
            self.accounted.append((n["lineno"], n["code"]))
        else:
            self.declare_block(n, why) if not n["children"] else (
                self.unmapped.append({"node": self.cur_label, "lineno": n["lineno"],
                                      "construct": n["code"], "why": why}))
        for ch in n["children"]:
            self.declare_deep(ch, why)

    def host(self, items):
        """Attach each effect to the next line or menu in the SAME guard, or declare it.

        Same guard, and immediately next: an effect moved past a gated line, or
        onto one, would fire in states the source did not fire it in — and the
        gated line's own test may read the variable it sets.
        """
        out, pending = [], []
        for it in items:
            if it["kind"] == "effect":
                pending.append(it)
                continue
            if it["kind"] in ("line", "menu") and pending and all(
                    p["guard"] == it.get("guard", ()) for p in pending) and not it.get(
                    "unmappable"):
                it["effects"] = [p["effect"] for p in pending] + it.get("effects", [])
                pending = []
            elif pending and it["kind"] in ("line", "menu", "jump", "return"):
                self.unhosted(pending)
                pending = []
            out.append(it)
        # Effects left at the END of a scope are handed back to the caller: a
        # choice block takes its leading ones, and a label's trailing ones fall
        # through into whatever comes next — which only the builder knows. They
        # are declared there if nothing takes them.
        out += pending
        return out

    def unhosted(self, pending):
        for p in pending:
            eff = p["effect"]
            self.unmapped.append({"node": self.cur_label, "lineno": p["lineno"],
                                  "construct": eff.get("command") or eff["type"],
                                  "why": WHY_UNHOSTED})

    def analyse_links(self):
        """Declare what cannot land: jumps to undefined labels, trailing effects."""
        known = set(self.labels)

        def menus(items):
            for it in items:
                if it["kind"] == "menu" and it.get("label"):
                    known.add(it["label"])
                for c in it.get("choices") or []:
                    menus(c["items"])
        for lab in self.labels.values():
            menus(lab["items"])

        def walk(items, owner):
            for it in list(items):
                if it["kind"] == "jump" and it["target"] not in known:
                    self.unmapped.append({"node": owner, "lineno": it["lineno"],
                                          "construct": f"jump {it['target']}",
                                          "why": "a jump to a label this script does not "
                                                 "define"})
                    items.remove(it)
                for c in it.get("choices") or []:
                    walk(c["items"], owner)
            # Trailing effects: nothing after them in this scope to ride on.
            while items and items[-1]["kind"] == "effect":
                self.cur_label = owner
                self.unhosted([items.pop()])
        for lab in self.labels.values():
            walk(lab["items"], lab["name"])


def all_units(p):
    """Units in source order: every line and option, mapped or declared."""
    out = []

    def walk(items, owner):
        for it in items:
            if it["kind"] == "line":
                out.append((owner, it))
            elif it["kind"] == "menu":
                if it["caption"]:
                    out.append((owner, it["caption"]))
                for c in it["choices"]:
                    out.append((owner, c))
                    walk(c["items"], owner)
    for name in p.order:
        walk(p.labels[name]["items"], name)
    return out


_stamp = _manifest.stamp


def parse_file(path):
    # utf-8-sig: The Question itself starts with a BOM, and a BOM'd first line is
    # unrecognisable to every line-anchored pattern here.
    text = _source.read_text(path).replace("\r\n", "\n")
    p = Parser(text)
    p.run()
    return text, p


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("source")
    ap.add_argument("--emit", choices=["ir", "manifest"], default="ir")
    a = ap.parse_args()
    text, p = parse_file(a.source)

    characters = {k: v["name"] for k, v in p.characters.items() if v.get("name")}
    if a.emit == "ir":
        print(json.dumps({"source": a.source, "format": "renpy",
                          "labels": [p.labels[n] for n in p.order],
                          "start": "start" if "start" in p.labels else
                          (p.order[0] if p.order else None),
                          "characters": characters,
                          "variables": sorted(p.kinds), "variableKinds": p.kinds,
                          "defaults": p.defaults,
                          "menuIncludeDisabled": p.include_disabled,
                          "unmapped": p.unmapped}, indent=2, ensure_ascii=False))
        return 0

    units = [{"kind": it["kind"], "node": owner, "speaker": it.get("speaker"),
              "text": it["text"], "lineno": it["lineno"],
              **({"unmappable": it["unmappable"]} if it.get("unmappable") else {}),
              **({"showIf": it["showIf"]} if it.get("showIf") else {})}
             for owner, it in all_units(p) if it.get("text")]
    units += p.units_declared
    man = {
        "source": a.source, "format": "renpy", "units": units,
        # A `define` gives a speaker a display name the project carries as the
        # character's `name`; the units name the speaker by its variable.
        "literals": _manifest.literals_of([p.labels[n] for n in p.order], extra=characters.values()),
        "variables": sorted(p.kinds), "variableKinds": p.kinds,
        "nodes": list(p.order),
        "unmapped": p.unmapped,
        # Ren'Py interpolates `[var]`, Parlance `{var}`. A unit is only carried
        # when every bracket in it names a registered TEXT variable (see
        # interp_reason), so the swap is token for token.
        "rewrites": [["[", "{"], ["]", "}"]],
    }
    man["residue"] = find_residue(text, man["units"], man["unmapped"],
                                  [(n, s) for n, s in p.accounted if s], fmt="renpy")
    print(json.dumps(_stamp(man), indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
