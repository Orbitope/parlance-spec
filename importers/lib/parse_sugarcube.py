#!/usr/bin/env python3
"""
parse_sugarcube.py — deterministic Twine (SugarCube 2) parser.

The sibling of parse_twine.py, which reads Harlowe and REFUSES a story that
declares SugarCube: Twine is a tool, not a language, and the two formats share
no syntax. SugarCube writes `<<set $x to 1>>` where Harlowe writes
`(set: $x to 1)`, and reading one with the other's parser does not fail — it
yields a project whose prose is full of unparsed macros.

Emits an intermediate representation for an importer to MAP from, and a
reconciliation manifest for check.py to verify against. The model never
transcribes prose: every string in the output of an import must have come from
here, byte for byte — with one declared exception, below.

Input is the published `.html` (the file a Twine story always has) or Twee
(`.twee`/`.tw`), exactly as for Harlowe; the compiled file's reading and entity
decoding are shared with parse_twine.py.

What maps, and where the answers are worked out HERE rather than left to the
mapping step (each is a place a well-meaning mapper would otherwise guess):

- Links: `[[Text|Target]]`, `[[Text->Target]]`, `[[Target<-Text]]`,
  `[[Target]]`, with a setter `[[…][$x to 1]]`; `<<link>>`/`<<button>>` with a
  literal passage or a `<<goto>>` in their body; a top-level `<<goto "P">>`.
- `<<set>>` with a literal value — `to`/`=`, `+=`/`-=`, `++`/`--`,
  `$x to $x + 1` — as `set_flag` / `adjust_counter` / `set_text`. An absolute
  counter assignment has no Parlance effect; in `StoryInit` it becomes the
  registry default, anywhere else it is declared.
- `<<if>>/<<elseif>>/<<else>>` and `<<switch>>/<<case>>/<<default>>` on literal
  comparisons as `showIf`, the else branch carrying the NEGATION of every branch
  above it — the one defect no string comparison can see.
- A naked `$name` in a line, when `name` is a text variable, as a Parlance
  `{name}` placeholder. That is a DECLARED rewrite (`$name` -> `{name}`), a
  sigil swap check.py polices by shape.
- A statement-like macro the format does not define — a custom widget, an
  audio cue — with literal arguments, as an `engine` effect (0.15).
- Every STATE CHANGE is given a carrier: the node whose `onEnter` it rides.
  Parlance fires effects on arrival at a node, so an effect with no node that
  fires exactly when the source's would is declared, never attached to one
  that fires at another time. `carrier` in the IR is the answer.

Everything else is named, with its source line, in "unmapped".

Usage:
    python3 parse_sugarcube.py story.html --emit ir        > ir.json
    python3 parse_sugarcube.py story.twee --emit manifest  > manifest.json
"""
import argparse, json, os, re, sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from residue import find_residue
import conditions
import manifest as _manifest
from parse_twine import (ATTR, PASSAGEDATA, declared_format, parse_link,
                         split_passages, unescape)

# ---------------------------------------------------------------------------
# Reasons, spelled once so the manifest, the report and the tests agree.

WHY_MACRO = ("a SugarCube macro with no Parlance equivalent — the effect vocabulary is "
             "closed and calls nothing, so input widgets, DOM manipulation and "
             "JavaScript have nowhere to go")
WHY_CONTAINER = ("a SugarCube container macro with no Parlance equivalent (styling, a "
                 "timed or replacing reveal, a notification). The macro is declared; "
                 "the lines inside it are the author's and are carried as ordinary beats")
WHY_COMPUTED_TEXT = ("text computed at play time — `<<print>>`, `<<=>>`, `<<include>>`, or "
                     "a variable Parlance cannot substitute. A Parlance node holds one "
                     "authored string; only a TEXT variable can fill a `{placeholder}`")
WHY_TEMP = ("a temporary variable (`_name`) — scoped to one passage render; Parlance "
            "state is global and persistent")
WHY_ABSOLUTE = ("an absolute assignment to a counter. The effect vocabulary has "
                "`adjust_counter` with a delta and nothing else; computing a delta would "
                "need the value at that point in the story, which is not knowable "
                "statically (in StoryInit it becomes the registry default instead)")
WHY_EXPR = ("an assignment whose value is an expression rather than a literal; a "
            "Parlance effect writes a literal")
WHY_KIND = ("an assignment to a variable whose kind (flag / counter / text) the story "
            "does not settle — it is assigned as more than one kind, or only from "
            "expressions — so it has no registry entry to write")
WHY_NO_CARRIER = ("a state change with no node that fires exactly when it would: Parlance "
                  "applies effects on arrival at a node, and the only candidates here are "
                  "gated differently or would reorder a read of the same variable")
WHY_GUARDED_GOTO = ("a `<<goto>>` inside a conditional — a jump chosen by a condition. A "
                    "Parlance `next` is unconditional")
WHY_DYNAMIC_TARGET = ("a link or jump whose destination is computed (a variable, an "
                      "expression) rather than a passage name")
WHY_NO_PASSAGE = "a link to a passage this story does not define"
WHY_INPLACE_LINK = ("a link that runs code in place rather than going to a passage — "
                    "Parlance choices lead somewhere; there is no in-place action")
WHY_LINK_BODY = ("prose inside a `<<link>>`/`<<button>>` body — SugarCube discards a link "
                 "body's output, so the player never sees it")
WHY_SILENT = "inside `<<silently>>`, whose output SugarCube discards"
WHY_OVERRIDDEN_LINK = ("a link in a passage that `<<goto>>`s away unconditionally, so the "
                       "player is never shown it")
WHY_FLOW = ("flow computed at play time (`<<back>>`, `<<return>>`, `<<include>>`); a "
            "Parlance edge names one node")
WHY_IMAGE_LINK = "an image link; Parlance data carries no images in a line"
SPECIAL_WHY = {
    "StoryInit": ("inside StoryInit, which SugarCube runs once before the first passage "
                  "and never displays — its literal assignments become registry defaults"),
    "chrome": ("a special passage SugarCube renders AROUND every passage (caption, menu, "
               "banner, header, footer) — Parlance has no persistent chrome"),
    "widget": ("the body of a `<<widget>>` definition — rendered wherever the widget is "
               "invoked, which is computed at play time"),
}
CHROME = {"StoryCaption", "StoryMenu", "StoryBanner", "StorySubtitle", "StoryAuthor",
          "StoryDisplayTitle", "StoryShare", "PassageHeader", "PassageFooter",
          "PassageReady", "PassageDone"}
METADATA = {"StoryTitle", "StoryData", "StoryInterface", "StorySettings"}
CODE_TAGS = {"script", "stylesheet", "Twine.image", "Twine.audio", "Twine.video",
             "Twine.vtt", "annotation"}

# SugarCube's own macros that are NOT statement-like cues: input widgets, DOM,
# JavaScript, and anything that computes. Declared, never turned into `engine`.
DECLARED_BUILTIN = {
    "textbox", "textarea", "numberbox", "checkbox", "radiobutton", "listbox", "cycle",
    "option", "optionsfrom", "run", "script", "addclass", "removeclass", "toggleclass",
    "copy", "remove", "replace", "append", "prepend", "timed", "next", "repeat", "stop",
    "type", "do", "redo", "linkreplace", "linkappend", "linkprepend", "actions",
    "choice", "click", "remember", "forget", "unset", "capture", "for", "break",
    "continue", "done", "include", "display", "back", "return", "widget", "nobr",
    "silently", "actions", "back", "return", "css", "addto", "linkreplace",
}
INPUT_BINDS = {"textbox": "text", "textarea": "text", "numberbox": "counter",
               "checkbox": "flag", "listbox": "text", "cycle": "text",
               "radiobutton": None}

MACRO = re.compile(r"<<(/?)([A-Za-z][\w-]*|=|-)")
TAG_ONLY = re.compile(r"^(?:\s*</?[A-Za-z!][^<>\n]*>)+\s*$")
PRINT_MACRO = re.compile(r"<<(?:print|=|-)[\s>]")
NAKED = re.compile(r"(?<![\w$])\$([A-Za-z_]\w*)")
ASSIGN = re.compile(r"^\s*([$_][A-Za-z_]\w*)\s*(to|=|\+=|-=|\+\+|--)\s*(.*?)\s*$", re.S)
ARG = re.compile(r'"(?:\\.|[^"\\])*"|\'(?:\\.|[^\'\\])*\'|`[^`]*`|\[\[.*?\]\]|\S+', re.S)


# ---------------------------------------------------------------------------
# Reading: Twee or the published HTML.

def wrong_format(declared):
    return (f"WRONG STORY FORMAT — this story declares '{declared}', and "
            f"sugarcube-import reads SugarCube.\nHarlowe, Chapbook and Snowman share no "
            f"syntax with it. A Harlowe story has its own importer: twine-import "
            f"(lib/parse_twine.py).")


def is_sugarcube(fmt):
    return fmt is None or fmt.lower().startswith("sugarcube")


def read_source(path):
    """(text as parser and residue see it, passages, start passage name or None)."""
    raw = open(path, encoding="utf-8-sig").read()
    if "<tw-passagedata" not in raw:
        passages = split_passages(raw)
        start = None
        for p in passages:
            if p["title"] == "StoryData":
                try:
                    data = json.loads("\n".join(l for _n, l in p["body"]))
                except (ValueError, TypeError):
                    data = {}
                if not is_sugarcube(data.get("format")):
                    sys.exit(wrong_format(data.get("format")))
                start = data.get("start")
        return raw, passages, start

    fmt = declared_format(raw)
    if not is_sugarcube(fmt):
        sys.exit(wrong_format(fmt))
    out = ["\n" if ch == "\n" else " " for ch in raw]
    passages, start = [], None
    m = re.search(r"<tw-storydata\b([^>]*)>", raw)
    start_pid = dict(ATTR.findall(m.group(1))).get("startnode") if m else None
    for pm in PASSAGEDATA.finditer(raw):
        attrs = dict(ATTR.findall(pm.group("attrs")))
        body = pm.group("body")
        lines = [unescape(line) for line in body.split("\n")]
        offset = pm.start("body")
        for line in body.split("\n"):
            for j, ch in enumerate(unescape(line)):
                out[offset + j] = ch
            offset += len(line) + 1
        first = raw.count("\n", 0, pm.start("body")) + 1
        passages.append({"title": unescape(attrs.get("name", "")),
                         "tags": (attrs.get("tags") or "").split(),
                         "lineno": first, "body": list(enumerate(lines, first))})
        if start_pid and attrs.get("pid") == start_pid:
            start = unescape(attrs.get("name", ""))
    # Stylesheet and script live outside the passages in a compiled file, and
    # are blanked with everything else that is not a passage body.
    return "".join(out), passages, start


# ---------------------------------------------------------------------------
# Small helpers.

def unquote(tok):
    tok = tok.strip()
    if len(tok) >= 2 and tok[0] == tok[-1] and tok[0] in "\"'`":
        return tok[1:-1]
    return None


def split_args(args):
    return ARG.findall(args or "")


def literal_arg(tok):
    """A macro argument as a JSON literal, or raise ValueError if it is not one."""
    q = unquote(tok)
    if q is not None:
        return q
    if re.match(r"^-?\d+$", tok):
        return int(tok)
    if re.match(r"^-?\d+\.\d+$", tok):
        return float(tok)
    if tok in ("true", "false"):
        return tok == "true"
    if re.match(r"^[A-Za-z][\w-]*$", tok):
        return tok          # a bare keyword (`play`, `stop`) — how the source wrote it
    raise ValueError(tok)


def engine_command_name(name):
    """`playSound` -> `play_sound`: the validator's ENGINE rule wants snake_case.
    A spelling of the source's own name, the same derivation Yarn's builder uses."""
    snake = re.sub(r"(?<=[a-z0-9])(?=[A-Z])", "_", name).lower()
    snake = re.sub(r"[^a-z0-9_]+", "_", snake).strip("_")
    return snake if re.match(r"^[a-z]", snake) else "cmd_" + snake


def macro_end(s, i):
    """Index just past the `>>` closing the macro opened at `i`, or None.

    Quote-aware: `<<link "a >> b">>` closes at the second `>>`. A macro may span
    lines (a long `<<set>>`), so newlines are crossed.
    """
    j, quote = i + 2, None
    while j < len(s):
        c = s[j]
        if quote:
            if c == "\\":
                j += 2
                continue
            if c == quote:
                quote = None
        elif c in "\"'`":
            quote = c
        elif s.startswith(">>", j):
            return j + 2
        j += 1
    return None


def split_assignments(arg):
    """`$a to 1, $b to "x; y"` — commas and semicolons at the top level only."""
    out, depth, quote, cur = [], 0, None, []
    for ch in arg:
        if quote:
            if ch == quote:
                quote = None
        elif ch in "'\"`":
            quote = ch
        elif ch in "([{":
            depth += 1
        elif ch in ")]}":
            depth -= 1
        elif ch in ",;" and depth == 0:
            out.append("".join(cur))
            cur = []
            continue
        cur.append(ch)
    if "".join(cur).strip():
        out.append("".join(cur))
    return [x.strip() for x in out if x.strip()]


def parse_assignment(raw):
    """One assignment as an op record. Never raises; unknown shapes are `expr`."""
    m = ASSIGN.match(raw)
    if not m:
        return {"op": "expr", "var": None, "raw": raw}
    sigil_var, op, val = m.group(1), m.group(2), m.group(3).strip()
    var = sigil_var[1:]
    rec = {"var": var, "temp": sigil_var.startswith("_"), "raw": raw.strip()}
    if op == "++":
        return {**rec, "op": "add", "delta": 1}
    if op == "--":
        return {**rec, "op": "add", "delta": -1}
    if op in ("+=", "-="):
        if re.match(r"^\d+$", val):
            return {**rec, "op": "add", "delta": int(val) * (1 if op == "+=" else -1)}
        return {**rec, "op": "expr"}
    inc = re.match(r"^\$" + re.escape(var) + r"\s*([-+])\s*(\d+)$", val)
    if inc:
        return {**rec, "op": "add",
                "delta": int(inc.group(2)) * (1 if inc.group(1) == "+" else -1)}
    if val in ("true", "false"):
        return {**rec, "op": "set", "value": val == "true"}
    if re.match(r"^-?\d+$", val):
        return {**rec, "op": "setnum", "value": int(val)}
    q = unquote(val) if re.match(r'^(["\'`]).*\1$', val, re.S) else None
    if q is not None and "$" not in q and "\n" not in q:
        return {**rec, "op": "settext", "value": q}
    return {**rec, "op": "expr"}


# ---------------------------------------------------------------------------
# The scanner.

class Passage:
    def __init__(self, title, tags, lineno, body, unmapped):
        self.title, self.tags, self.header = title, tags, lineno
        self.text = "\n".join(line for _n, line in body)
        self.first_line = body[0][0] if body else lineno
        self.items, self.frames, self.accounted, self.binds = [], [], [], []
        self.unmapped = unmapped
        self.next_frame = 0

    def lineno_at(self, pos):
        return self.first_line + self.text.count("\n", 0, pos)

    # -- frames ------------------------------------------------------------
    def push(self, kind, name, current=None):
        self.next_frame += 1
        self.frames.append({"kind": kind, "name": name, "id": self.next_frame,
                            "branch": 0, "current": current, "prior": [],
                            "cased": False})

    def top(self, name):
        for f in reversed(self.frames):
            if f["name"] == name:
                return f
        return None

    def pop(self, name):
        for k in range(len(self.frames) - 1, -1, -1):
            if self.frames[k]["name"] == name:
                del self.frames[k:]
                return True
        return False

    def active(self):
        return [f for f in self.frames if f["kind"] in ("if", "switch")
                and (f["current"] is not None or f["prior"])]

    def guard(self):
        return [{"current": f["current"], "prior": list(f["prior"])}
                for f in self.active()]

    def key(self):
        return [[f["id"], f["branch"]] for f in self.active()]

    def silent(self):
        return any(f["kind"] == "silent" for f in self.frames)

    # -- emitting ----------------------------------------------------------
    def add(self, item, pos):
        item.update({"index": len(self.items), "lineno": self.lineno_at(pos),
                     "guard": self.guard() or None, "key": self.key()})
        self.items.append(item)
        return item

    def declare(self, pos, construct, why, text=None):
        e = {"node": self.title, "lineno": self.lineno_at(pos),
             "construct": construct, "why": why}
        if text:
            e["text"] = text
        self.unmapped.append(e)

    def account(self, pos, text):
        """Macro arguments and link targets, recorded per LINE — a `<<set>>` may
        span lines, and crediting the whole argument to its first line left every
        later line's words looking like lost prose."""
        for k, chunk in enumerate((text or "").split("\n")):
            if chunk.strip():
                self.accounted.append((self.lineno_at(pos) + k, chunk))

    def flush(self, start, end):
        pos = start
        for chunk in self.text[start:end].split("\n"):
            stripped = chunk.strip()
            if stripped and not TAG_ONLY.match(stripped):
                it = self.add({"kind": "line", "text": stripped}, pos)
                if self.silent():
                    it["unmappable"] = WHY_SILENT
            pos += len(chunk) + 1


def closer_of(s, name, start):
    """(start, end) of the `<</name>>` matching an opener that ends at `start`."""
    depth, pat = 1, re.compile(r"<<(/?)" + re.escape(name) + r"(?=[\s>])")
    for m in pat.finditer(s, start):
        e = macro_end(s, m.start())
        if e is None:
            continue
        depth += -1 if m.group(1) else 1
        if depth == 0:
            return m.start(), e
    return None


def setter_effects(setter):
    return [parse_assignment(a) for a in split_assignments(setter or "")]


def link_parts(raw):
    """`[[text|target][setter]]` -> (text, target, setter or None)."""
    inner = raw[2:-2]
    setter = None
    if "][" in inner:
        inner, setter = inner.split("][", 1)
    text, target = parse_link("[[" + inner + "]]")
    return text, target, setter


def scan(p):
    s, n = p.text, len(p.text)
    i = buf = 0
    while i < n:
        # ---- comments ------------------------------------------------------
        for open_, close in (("/*", "*/"), ("/%", "%/"), ("<!--", "-->")):
            if s.startswith(open_, i):
                p.flush(buf, i)
                e = s.find(close, i + len(open_))
                i = buf = n if e < 0 else e + len(close)
                break
        else:
            open_ = None
        if open_:
            continue

        # ---- a link --------------------------------------------------------
        if s.startswith("[img[", i) or s.startswith("[[", i):
            e = s.find("]]", i)
            if e < 0:
                i += 1
                continue
            e += 2
            p.flush(buf, i)
            raw = s[i:e]
            if raw.startswith("[img["):
                p.declare(i, raw, WHY_IMAGE_LINK)
            else:
                text, target, setter = link_parts(raw)
                p.add({"kind": "option", "text": text, "target": target,
                       "setter": setter, "setterEffects": setter_effects(setter)}, i)
                p.account(i, target)
                p.account(i, setter)
            i = buf = e
            continue

        # ---- a macro -------------------------------------------------------
        m = MACRO.match(s, i)
        if not m:
            i += 1
            continue
        e = macro_end(s, i)
        if e is None:
            i += 1
            continue
        closing, name = m.group(1) == "/", m.group(2)
        args = s[m.end():e - 2]
        if not closing and name in ("print", "=", "-"):
            # Stays IN the line: the line is computed text, decided below.
            i = e
            continue
        p.flush(buf, i)
        i = buf = handle_macro(p, s, i, e, name, args, closing)
    p.flush(buf, n)


def handle_macro(p, s, i, e, name, args, closing):
    """Returns the index to resume scanning at."""
    if closing:
        p.pop(name)
        return e
    if name.startswith("end") and p.top(name[3:]):
        p.pop(name[3:])              # SugarCube 1's `<<endif>>`
        return e
    p.account(i, args)

    if name == "if":
        p.push("if", "if", args.strip())
        return e
    if name in ("elseif", "else"):
        f = p.top("if")
        if f:
            if f["current"] is not None:
                f["prior"].append(f["current"])
            rest = args.strip()
            if name == "else" and rest.startswith("if "):
                rest, name = rest[3:], "elseif"
            f["current"] = rest if name == "elseif" else None
            f["branch"] += 1
        return e
    if name == "switch":
        p.push("switch", "switch")
        p.frames[-1]["expr"] = args.strip()
        return e
    if name in ("case", "default"):
        f = p.top("switch")
        if f:
            if f["cased"] and f["current"] is not None:
                f["prior"].append(f["current"])
            if name == "case":
                vals = split_args(args)
                f["current"] = "(" + " || ".join(f"{f['expr']} == {v}" for v in vals) + ")"
            else:
                f["current"] = None
            f["cased"] = True
            f["branch"] += 1
        return e
    if name == "set":
        effs = [parse_assignment(a) for a in split_assignments(args)]
        p.add({"kind": "command", "macro": "set", "raw": args.strip(), "effects": effs}, i)
        return e
    if name == "goto":
        toks = split_args(args)
        target = None
        if toks:
            t = toks[0]
            target = parse_link(t)[1] if t.startswith("[[") else unquote(t)
        p.add({"kind": "goto", "target": target, "raw": args.strip()}, i)
        return e
    if name in ("link", "button"):
        return handle_link_macro(p, s, i, e, name, args)
    if name == "script":
        c = closer_of(s, name, e)
        end = c[1] if c else len(s)
        p.declare(i, "<<script>>", WHY_MACRO)
        p.account(i, s[i:end])
        return end
    if name == "silently":
        p.push("silent", name)
        p.declare(i, "<<silently>>", WHY_SILENT)
        return e
    if name == "nobr":
        p.push("plain", name)
        return e
    if name in INPUT_BINDS:
        toks = split_args(args)
        recv = unquote(toks[0]) if toks else None
        if recv and recv.startswith("$"):
            p.binds.append((name, recv[1:]))
    container = closer_of(s, name, e) is not None
    if name in DECLARED_BUILTIN or container:
        p.declare(i, f"<<{name}{(' ' + args.strip()) if args.strip() else ''}>>",
                  WHY_CONTAINER if container else
                  (WHY_FLOW if name in ("back", "return") else
                   WHY_COMPUTED_TEXT if name in ("include", "display") else WHY_MACRO))
        if container:
            p.push("plain", name)
        return e
    # A statement-like macro SugarCube does not define (a custom widget) or an
    # audio cue: an `engine` effect when every argument is a literal.
    try:
        lits = [literal_arg(t) for t in split_args(args)]
    except ValueError:
        p.declare(i, f"<<{name} {args.strip()}>>",
                  "a custom macro whose arguments are not all literals — an engine "
                  "command carries literal arguments only")
        return e
    eff = {"type": "engine", "command": engine_command_name(name)}
    if lits:
        eff["args"] = lits
    p.add({"kind": "command", "macro": name, "raw": args.strip(), "engine": eff,
           "effects": []}, i)
    return e


def handle_link_macro(p, s, i, e, name, args):
    """`<<link "Text" "Passage">>…<</link>>`, `<<link [[Text|P]]>>`, and a body
    whose `<<goto>>` names the destination. A link body's OUTPUT is discarded by
    SugarCube, so prose in one is declared, while its `<<set>>`s ride the choice."""
    c = closer_of(s, name, e)
    body_start, body_end = e, (c[0] if c else e)
    resume = c[1] if c else e
    toks = split_args(args)
    text = target = setter = None
    if toks and toks[0].startswith("[["):
        text, target, setter = link_parts(toks[0])
        p.account(i, target)
        p.account(i, setter)
    elif toks:
        text = unquote(toks[0])
        if len(toks) > 1:
            t = toks[1]
            target = parse_link(t)[1] if t.startswith("[[") else unquote(t)
            p.account(i, t)
    effects, engine = [], []
    body = s[body_start:body_end]
    pos = 0
    for bm in MACRO.finditer(body):
        if bm.start() < pos:
            continue
        be = macro_end(body, bm.start())
        if be is None:
            continue
        # prose between macros in the body
        _body_text(p, s, body_start + pos, body_start + bm.start())
        bname, bargs = bm.group(2), body[bm.end():be - 2]
        closing = bm.group(1) == "/"
        p.account(body_start + bm.start(), bargs)
        if closing:
            pass
        elif bname == "goto":
            bt = split_args(bargs)
            if bt and target is None:
                target = parse_link(bt[0])[1] if bt[0].startswith("[[") else unquote(bt[0])
        elif bname == "set":
            effects += [parse_assignment(a) for a in split_assignments(bargs)]
        else:
            try:
                lits = [literal_arg(t) for t in split_args(bargs)]
                if bname in DECLARED_BUILTIN or bname in ("if", "else", "elseif"):
                    raise ValueError(bname)
                eff = {"type": "engine", "command": engine_command_name(bname)}
                if lits:
                    eff["args"] = lits
                engine.append(eff)
            except ValueError:
                p.declare(body_start + bm.start(), f"<<{bname} {bargs.strip()}>>",
                          "inside a link body: " + WHY_MACRO)
        pos = be
    _body_text(p, s, body_start + pos, body_end)
    if text is None:
        p.declare(i, f"<<{name} {args.strip()}>>", WHY_DYNAMIC_TARGET)
        return resume
    p.add({"kind": "option", "text": text, "target": target, "setter": setter,
           "setterEffects": setter_effects(setter), "bodyEffects": effects,
           "engine": engine, "macro": name}, i)
    return resume


def _body_text(p, s, a, b):
    chunk = s[a:b]
    pos = a
    for line in chunk.split("\n"):
        st = line.strip()
        if st and not TAG_ONLY.match(st):
            p.declare(pos, "<<link>> body", WHY_LINK_BODY, text=st)
        pos += len(line) + 1


# ---------------------------------------------------------------------------
# Analysis: kinds, guards, effects, carriers, interpolation.

def infer_kinds(passages):
    seen = {}
    for p in passages:
        for macro, var in p.binds:
            kind = INPUT_BINDS.get(macro)
            seen.setdefault(var, set()).add(kind or "unknown")
        for it in p.items:
            for eff in _assignments(it):
                if eff.get("var") and not eff.get("temp"):
                    kind = {"set": "flag", "setnum": "counter", "add": "counter",
                            "settext": "text"}.get(eff["op"], "unknown")
                    seen.setdefault(eff["var"], set()).add(kind)
    out = {}
    lowered = {}
    for name in seen:
        lowered.setdefault(name.lower(), []).append(name)
    for name, kinds in seen.items():
        determinate = kinds - {"unknown"}
        kind = determinate.pop() if len(determinate) == 1 else "unknown"
        # `$Gold` and `$gold` are two variables in SugarCube and ONE id in
        # Parlance. Merging them would be a guess about which the author meant.
        if len(lowered[name.lower()]) > 1:
            kind = "unknown"
        out[name] = kind
    return out


def _assignments(it):
    if it["kind"] == "command":
        return it.get("effects") or []
    if it["kind"] == "option":
        return (it.get("setterEffects") or []) + (it.get("bodyEffects") or [])
    return []


def normalize_expr(expr):
    """SugarCube's operator spellings onto the shared translator's."""
    e = expr
    e = re.sub(r"===", "==", e)
    e = re.sub(r"!==", "!=", e)
    e = re.sub(r"\bisnot\b", "!=", e)
    e = re.sub(r"'([^'\"\n]*)'", r'"\1"', e)
    return e


def guard_condition(guard, kinds):
    parts = []
    for frame in guard or []:
        for expr, invert in ([(pr, True) for pr in frame["prior"]] +
                             ([(frame["current"], False)]
                              if frame["current"] is not None else [])):
            if re.search(r"(?<![\w$])_[A-Za-z]\w*", expr or ""):
                return None, WHY_TEMP
            if re.search(r"\bn?def\b", expr or ""):
                return None, ("gated on whether a variable is defined (`def`/`ndef`); "
                              "every Parlance variable is registered, so the test has "
                              "no equivalent")
            cond, why = conditions.translate(normalize_expr(expr), kinds)
            if why:
                return None, why
            parts.append(conditions.negate(cond) if invert else cond)
    if not parts:
        return None, conditions.WHY_UNPARSEABLE
    return (parts[0] if len(parts) == 1 else {"type": "all", "of": parts}), None


def effect_of(eff, kinds, in_init=False):
    """(Parlance effect or None, reason or None)."""
    var = eff.get("var")
    if not var:
        return None, WHY_EXPR
    if eff.get("temp"):
        return None, WHY_TEMP
    kind = kinds.get(var)
    ident = conditions.var_id(var)
    if not ident:
        return None, conditions.WHY_BAD_ID
    op = eff["op"]
    if op == "expr":
        return None, WHY_EXPR
    if kind in (None, "unknown"):
        return None, WHY_KIND
    if op == "set" and kind == "flag":
        return {"type": "set_flag", "flag": ident, "value": eff["value"]}, None
    if op == "add" and kind == "counter":
        return {"type": "adjust_counter", "counter": ident, "delta": eff["delta"]}, None
    if op == "settext" and kind == "text":
        return {"type": "set_text", "variable": ident, "value": eff["value"]}, None
    if op == "setnum" and kind == "counter":
        return None, WHY_ABSOLUTE
    return None, WHY_KIND


def special_reason(p):
    if p.title == "StoryInit":
        return SPECIAL_WHY["StoryInit"]
    if p.title in CHROME:
        return SPECIAL_WHY["chrome"]
    if "widget" in p.tags:
        return SPECIAL_WHY["widget"]
    return None


def analyse(passages, unmapped):
    kinds = infer_kinds(passages)
    titles = {p.title for p in passages if not p.special}
    defaults, engine_written = {}, set()
    for p in passages:
        for macro, var in p.binds:
            engine_written.add(var)

    def declare(p, it, why, construct=None):
        entry = {"node": p.title, "lineno": it["lineno"],
                 "construct": construct or it.get("raw") or it["kind"], "why": why}
        if it.get("text"):
            entry["text"] = it["text"]
            it["unmappable"] = why
        unmapped.append(entry)

    for p in passages:
        for it in p.items:
            # -- state changes -------------------------------------------------
            if it["kind"] == "command":
                mapped = []
                for eff in it.get("effects") or []:
                    if p.special == SPECIAL_WHY["StoryInit"] and not it.get("guard"):
                        val = {"set": eff.get("value"), "setnum": eff.get("value"),
                               "settext": eff.get("value")}.get(eff.get("op"))
                        if val is not None and kinds.get(eff.get("var")) not in (None, "unknown"):
                            defaults[eff["var"]] = val
                            continue
                    got, why = effect_of(eff, kinds)
                    if got:
                        mapped.append(got)
                    else:
                        declare(p, it, why, f"<<set {eff.get('raw')}>>")
                if it.get("engine"):
                    mapped.append(it["engine"])
                it["parlance"] = mapped
            if it["kind"] == "option":
                mapped = []
                for eff in _assignments(it):
                    got, why = effect_of(eff, kinds)
                    if got:
                        mapped.append(got)
                    else:
                        declare(p, {**it, "text": None}, why, f"[[…][{eff.get('raw')}]]")
                it["parlance"] = mapped + (it.get("engine") or [])

        if p.special:
            for it in p.items:
                if it.get("text"):
                    declare(p, it, p.special)
                elif it["kind"] == "command" and it.get("parlance"):
                    declare(p, it, p.special)
                elif it["kind"] == "goto":
                    declare(p, it, p.special, f"<<goto {it.get('raw')}>>")
            continue

        for it in p.items:
            if it.get("unmappable"):
                continue
            if it.get("guard"):
                cond, why = guard_condition(it["guard"], kinds)
                if why:
                    if it["kind"] in ("line", "option"):
                        declare(p, it, why, "<<if …>>")
                    else:
                        declare(p, it, why, f"<<if …>> {it.get('raw', '')}")
                        it["dead"] = True
                    continue
                it["showIf"] = cond
            if it["kind"] == "option":
                if it.get("target") is None or "$" in (it.get("target") or ""):
                    declare(p, it, WHY_DYNAMIC_TARGET if it.get("target") is not None
                            else WHY_INPLACE_LINK)
                elif it["target"] not in titles:
                    declare(p, it, WHY_NO_PASSAGE, f"[[…|{it['target']}]]")
            if it["kind"] == "goto":
                if it.get("guard"):
                    declare(p, it, WHY_GUARDED_GOTO, f"<<goto {it['raw']}>>")
                    it["dead"] = True
                elif not it.get("target") or it["target"] not in titles:
                    declare(p, it, WHY_DYNAMIC_TARGET if not it.get("target")
                            else WHY_NO_PASSAGE, f"<<goto {it['raw']}>>")
                    it["dead"] = True

    rewrites = interpolation(passages, kinds, unmapped)

    for p in passages:
        if not p.special:
            carriers(p, unmapped)
    return kinds, defaults, engine_written, rewrites


def interpolation(passages, kinds, unmapped):
    """Which naked variables become `{placeholder}`s, as declared rewrites.

    Only a TEXT variable can fill a Parlance placeholder, and the rewrite is a
    plain substring replacement in check.py, so a name is swapped only if no
    longer name starting with it appears in any unit (`$name` inside `$names`).
    A line interpolating anything else is computed text, and declared.
    """
    units = [it for p in passages for it in p.items
             if it["kind"] in ("line", "option") and it.get("text")]
    names = {}
    for it in units:
        for m in NAKED.finditer(it["text"]):
            names.setdefault(m.group(1), []).append((it, m))
    ok = set()
    for name, occ in names.items():
        if name.startswith("_") or kinds.get(name) != "text" or not conditions.var_id(name):
            continue
        if any(re.search(r"\$" + re.escape(name) + r"\w", u["text"]) for u in units):
            continue
        if any(re.match(r"\.[A-Za-z_]|\[", it["text"][m.end():m.end() + 2])
               for it, m in occ):
            continue
        ok.add(name)
    for p in passages:
        for it in p.items:
            if it["kind"] not in ("line", "option") or not it.get("text") \
                    or it.get("unmappable"):
                continue
            bad = [m.group(1) for m in NAKED.finditer(it["text"]) if m.group(1) not in ok]
            if bad or PRINT_MACRO.search(it["text"]):
                it["unmappable"] = WHY_COMPUTED_TEXT
                it.pop("showIf", None)
                unmapped.append({"node": p.title, "lineno": it["lineno"],
                                 "construct": ("<<print …>>" if PRINT_MACRO.search(it["text"])
                                               else "$" + bad[0]),
                                 "text": it["text"], "why": WHY_COMPUTED_TEXT})
    return [["$" + n, "{" + n.lower() + "}"]
            for n in sorted(ok, key=lambda x: (-len(x), x))]


def _reads(it, var_ids):
    g = json.dumps(it.get("showIf") or {})
    return any(f'"{v}"' in g for v in var_ids)


def carriers(p, unmapped):
    """Decide, per state change, which node's `onEnter` carries it.

    Parlance fires `onEnter` on arrival; a guarded interstitial node that is
    skipped fires nothing, and a node that holds choices or ends the dialogue
    fires its effects even when its own line is hidden. So:

    - an UNGUARDED change rides the next beat if that beat is unguarded; else
      the next unguarded beat, provided no guarded beat in between reads what
      it writes; else the beat before it; else, in a passage of nothing but
      links, the text-less node that holds them.
    - a GUARDED change rides a beat under exactly the same guard — the next
      one, else the one before — and never the passage's last beat when that
      beat holds choices or ends the dialogue.

    Anything else is declared, never attached where it would fire at another
    time.
    """
    items = p.items
    beats = [it for it in items if it["kind"] == "line" and not it.get("unmappable")]
    goto = next((it for it in items if it["kind"] == "goto" and not it.get("dead")), None)
    links = [it for it in items if it["kind"] == "option" and not it.get("unmappable")]
    if goto:
        for it in links:
            it["unmappable"] = WHY_OVERRIDDEN_LINK
            unmapped.append({"node": p.title, "lineno": it["lineno"], "construct":
                             f"[[…|{it.get('target')}]]", "text": it["text"],
                             "why": WHY_OVERRIDDEN_LINK})
        links = []
    p.exit = ({"kind": "goto", "target": goto["target"]} if goto else
              {"kind": "choices"} if links else {"kind": "end"})
    last = beats[-1]["index"] if beats else None
    for it in items:
        if it["kind"] != "command" or not it.get("parlance") or it.get("dead"):
            continue
        written = {e.get("flag") or e.get("counter") or e.get("variable")
                   for e in it["parlance"]}
        after = [b for b in beats if b["index"] > it["index"]]
        before = [b for b in beats if b["index"] < it["index"]]
        carrier = None
        if not it["key"]:
            nxt = next((b for b in after if not b["key"]), None)
            between = [b for b in after if nxt and b["index"] < nxt["index"]]
            prev = before[-1] if before else None
            if nxt and not any(_reads(b, written) for b in between):
                carrier = nxt["index"]
            elif prev and not prev["key"] and not any(
                    re.search(r"\$" + re.escape(v) + r"\b", prev["text"], re.I)
                    for v in written if v):
                # Earlier than the source by exactly one beat, whose own text
                # does not interpolate what this writes.
                carrier = prev["index"]
            elif not beats and links:
                carrier = "exit"
        else:
            final_fires = p.exit["kind"] != "goto"
            if after and after[0]["key"] == it["key"] and \
                    not (final_fires and after[0]["index"] == last):
                carrier = after[0]["index"]
            else:
                prev = [b for b in before if b["key"] == it["key"]
                        and not (final_fires and b["index"] == last)]
                if prev and prev[-1] is before[-1]:
                    carrier = prev[-1]["index"]
        if carrier is None:
            unmapped.append({"node": p.title, "lineno": it["lineno"],
                             "construct": f"<<{it.get('macro', 'set')} {it.get('raw', '')}>>",
                             "why": WHY_NO_CARRIER})
            it["parlance"] = []
        it["carrier"] = carrier


# ---------------------------------------------------------------------------

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("source")
    ap.add_argument("--emit", choices=["ir", "manifest"], default="ir")
    a = ap.parse_args()
    text, raw_passages, start = read_source(a.source)

    unmapped, passages, accounted = [], [], []
    for raw in raw_passages:
        title = raw["title"]
        accounted.append((raw["lineno"], title))
        accounted += [(raw["lineno"], t) for t in raw["tags"]]
        if title in METADATA or set(raw["tags"]) & CODE_TAGS:
            # Story metadata, stylesheets and scripts: code and configuration,
            # none of it player-facing prose.
            accounted += [(n, line) for n, line in raw["body"]]
            continue
        p = Passage(title, raw["tags"], raw["lineno"], raw["body"], unmapped)
        scan(p)
        p.special = None
        passages.append(p)
    for p in passages:
        p.special = special_reason(p)
        accounted += p.accounted
    kinds, defaults, engine_written, rewrites = analyse(passages, unmapped)
    story = [p for p in passages if not p.special]
    if not start:
        # SugarCube's own rule when a story names no start: the passage `Start`.
        start = "Start" if any(p.title == "Start" for p in story) else \
            (story[0].title if story else None)

    links = []
    for p in story:
        for it in p.items:
            if it["kind"] == "option" and not it.get("unmappable"):
                links.append({"from": p.title, "to": it["target"], "lineno": it["lineno"]})
        if p.exit["kind"] == "goto":
            links.append({"from": p.title, "to": p.exit["target"], "lineno": None})

    if a.emit == "ir":
        nodes = [{"title": p.title, "tags": p.tags, "items": p.items, "exit": p.exit}
                 for p in story]
        print(json.dumps({"source": a.source, "format": "sugarcube", "nodes": nodes,
                          "start": start, "variables": sorted(kinds),
                          "variableKinds": kinds, "defaults": defaults,
                          "engineWritten": sorted(engine_written),
                          "rewrites": rewrites, "links": links,
                          "unmapped": unmapped}, indent=2, ensure_ascii=False))
        return 0

    units = [{"kind": it["kind"], "node": p.title, "speaker": None, "text": it["text"],
              "lineno": it["lineno"],
              **({"unmappable": it["unmappable"]} if it.get("unmappable") else {}),
              **({"showIf": it["showIf"]} if it.get("showIf") and not it.get("unmappable") else {})}
             for p in passages for it in p.items
             if it["kind"] in ("line", "option") and it.get("text")]
    man = {"source": a.source, "format": "sugarcube", "units": units,
           "variables": sorted(kinds), "variableKinds": kinds,
           "nodes": [p.title for p in story], "unmapped": unmapped,
           # `$name` -> `{name}` for each text variable a line interpolates:
           # sigil swaps, which check.py accepts by SHAPE and nothing wider.
           "rewrites": rewrites}
    man["residue"] = find_residue(text, units, unmapped,
                                  [(n, s) for n, s in accounted if s], fmt="sugarcube")
    print(json.dumps(_manifest.stamp(man), indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
