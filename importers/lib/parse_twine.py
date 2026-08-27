#!/usr/bin/env python3
"""
parse_twine.py — deterministic Twine (Harlowe) parser, reading a published story.

Emits an intermediate representation for an importer to MAP from, and a
reconciliation manifest for check.py to verify against. The model never
transcribes prose: every string in the output of an import must have come from
here, byte for byte.

**The published `.html` is the expected input**, and Twee is accepted where it
exists. That is the right way round: the compiled file is the artefact a Twine
story always has, since it is what the tool produces and what people distribute,
while Twee only exists if the author happens to use `tweego` or exports it. This
parser was Twee-only at first and that excluded almost the entire corpus — a
search for a second Harlowe story turned up templates, parser fixtures and course
exercises, because the real stories ship compiled.

The reason for refusing HTML was that the prose is escaped and un-escaping would
be a rewrite. It is not. Escaping is an encoding Twine applies on the way out, and
decoding recovers the author's bytes exactly — the five entities that appear in a
passage body (`&amp; &lt; &gt; &quot; &#39;`) are each at most six characters,
well inside the rewrite budget `check.py` already polices for real format
differences. The decode happens on read, so units and residue see one text.
`&amp;` decodes LAST: an author who literally types `&amp;` has it escaped to
`&amp;amp;`, and decoding the ampersand first would hand them a bare `&`.

Reading the compiled file buys one thing Twee cannot: the story DECLARES its
format, so a SugarCube story is refused instead of being parsed into a project
full of unparsed macros.

Everything outside `<tw-storydata>` is blanked before parsing — the compiled file
carries the whole Harlowe engine inline, and none of it is story. Blanked rather
than stripped, so line numbers still point into the file a reader can open.

Harlowe is a macro language rather than a serialization format, so a good deal of
it falls outside Parlance — audio, styling, input widgets, anything computed.
Everything that does is named, with its source line, in "unmapped".

The one structural difference from the Yarn and Ink parsers: Harlowe's
conditional is a HOOK, `(if: $x)[ … ]`, whose brackets nest and span lines and
whose `(else:)` is written `](else:)[` — closing and opening in one gesture. So
this scans characters rather than lines, tracking a hook stack, and reconstructs
line numbers as it goes.

Usage:
    python3 parse_twine.py story.html --emit ir        > ir.json
    python3 parse_twine.py story.html --emit manifest  > manifest.json

`.twee` is accepted at the same commands where the author has it.
"""
import argparse, json, os, re, sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from residue import find_residue
import conditions
import manifest as _manifest

# `:: Name [tag tag] {"position":"…"}` — tags and metadata both optional.
PASSAGE = re.compile(r"^::\s*(?P<name>[^\[\{\n]+?)"
                     r"(?:\s*\[(?P<tags>[^\]]*)\])?"
                     r"(?:\s*(?P<meta>\{.*\}))?\s*$")
MACRO_HEAD = re.compile(r"\(\s*([A-Za-z][\w-]*)\s*:")
# `(input-box: bind $nome, …)`. A bind DECLARES the variable — the widget writes
# into it — so a story can use `$nome` without ever `(set:)`ing it. Unrecognised,
# a guard on one was reported as "gated on a name the source never declares",
# which is wrong and sends the reader looking for a missing `(set:)`.
BIND = re.compile(r"\b2?bind\s+_?\$(\w+)")
# WHICH KIND a bind implies depends on the macro, and guessing costs more than
# not knowing. `(icon-counter: bind $self, …)` displays a NUMBER; reading every
# bind as text made four of this corpus's counters conflict with themselves and
# resolve to unknown, which turned every guard on them into declared loss. A
# macro not listed here contributes no kind at all and lets the assignments
# decide.
BIND_KIND = {"input-box": "text", "force-input-box": "text", "dropdown": "text",
             "cycling-link": "text", "seq-link": "text",
             "icon-counter": "counter", "meter": "counter"}
SET = re.compile(r"^\$?(\w+)\s+to\s+(.+)$", re.S)

# Harlowe macros that carry state or flow. Everything else is reported.
KNOWN = ("if", "else", "else-if", "elseif", "unless", "set", "put", "display", "goto")

WHY_MACRO = ("a Harlowe macro with no Parlance equivalent — the effect vocabulary is "
             "closed (set_flag / adjust_counter / set_text and the rest) and calls "
             "nothing, so audio, styling, input widgets and anything computed have "
             "nowhere to go")
WHY_COMPUTED_TEXT = ("text computed at runtime — `(print:)`, `(display:)` and the "
                     "variable interpolations they build. A Parlance node holds one "
                     "authored string, decided by the author rather than at play time")
WHY_READ_COUNT = (
    "gated on a Harlowe keyword rather than a variable — `visits` (how many times this "
    "passage has been seen), `turns`, `time`, `history`. Parlance has no read-count or "
    "clock condition, and importing the line ungated would change when it appears")
WHY_CHOICE_HOST = (
    "conditional narration immediately before a link. The line would have to be the "
    "node that hosts those choices, and a Parlance node may not carry showIf and "
    "choices together (validator rule COND) — a conditional node is interstitial "
    "narration, and there is no text-less node to hang the choices on instead")
WHY_NO_HOST = (
    "a link with no narration line to host it — the passage opens with it, or the "
    "line before it is itself declared loss. A Parlance choice hangs off a node and "
    "every node requires text, so there is nothing for it to attach to. One line of "
    "narration before it makes it importable")
WHY_COND_TERMINAL = (
    "conditional narration as the last beat of the conversation. The node would have "
    "to carry showIf and isEnd together, which the validator refuses (rule COND): a "
    "dialogue's termination must not be conditional, or a player who fails the gate "
    "has nowhere to go. A line after it, or a link onwards, makes it importable")
WHY_LINKED_HOOK = ("a link inside a conditional hook — the choice is offered only when "
                   "the condition holds, which maps, but it sits where this importer "
                   "cannot tell which line hosts it")


PASSAGEDATA = re.compile(
    r'<tw-passagedata\b(?P<attrs>[^>]*)>(?P<body>.*?)</tw-passagedata>', re.S)
ATTR = re.compile(r'(\w[\w-]*)\s*=\s*"([^"]*)"')
ENTITIES = (("&lt;", "<"), ("&gt;", ">"), ("&quot;", '"'),
            ("&#39;", "'"), ("&apos;", "'"), ("&amp;", "&"))


def unescape(s):
    """The inverse of the escaping Twine applies when it compiles a story.

    `&amp;` LAST, and that ordering is the whole correctness of this function: an
    author who wrote `&amp;` gets `&amp;` escaped to `&amp;amp;`, and decoding the
    outer one first would turn their literal into an ampersand.
    """
    for ent, ch in ENTITIES:
        s = s.replace(ent, ch)
    return s


def wrong_format(declared):
    """The message for a story this parser has no business reading.

    Twine is a tool, not a language: a story picks a FORMAT, and the formats do
    not share a syntax. SugarCube writes `<<set $x to 1>>`, Harlowe writes
    `(set: $x to 1)`, and reading one with the other's parser does not fail — it
    quietly produces a project whose prose is full of macro text. That is the
    worst possible outcome for an importer, so it is refused rather than warned
    about, and the format is right there in the file to check.
    """
    return (f"WRONG STORY FORMAT — this story declares '{declared}', and "
            f"twine-import reads Harlowe.\n"
            f"SugarCube, Chapbook and Snowman are different macro languages, not "
            f"dialects: their\nsyntax overlaps Harlowe's nowhere. Parsing one with "
            f"this parser yields a project whose\nprose is full of unparsed macros, "
            f"which no downstream check would flag as wrong.\n"
            f"See IMPORTERS.md — SugarCube is listed as not started.")


def declared_format(raw):
    """The story format a compiled file declares, or None."""
    m = re.search(r"<tw-storydata\b([^>]*)>", raw)
    return dict(ATTR.findall(m.group(1))).get("format") if m else None


def read_source(path):
    """(text as the parser and residue should see it, passages).

    Twee is returned as-is. Compiled HTML is reduced to just its passage bodies —
    everything else blanked to spaces, newlines kept — and those bodies decoded,
    so a line number still points at the line a reader would find in the file.
    """
    raw = open(path, encoding="utf-8-sig").read()
    if "<tw-passagedata" not in raw:
        return raw, split_passages(raw)

    fmt = declared_format(raw)
    if fmt and fmt.lower() != "harlowe":
        sys.exit(wrong_format(fmt))

    out = list(" " * len(raw))
    for i, ch in enumerate(raw):
        if ch == "\n":
            out[i] = "\n"
    passages, start_pid, start_name = [], None, None
    m = re.search(r"<tw-storydata\b([^>]*)>", raw)
    if m:
        start_pid = dict(ATTR.findall(m.group(1))).get("startnode")

    for pm in PASSAGEDATA.finditer(raw):
        attrs = dict(ATTR.findall(pm.group("attrs")))
        body = pm.group("body")
        # Decode line by line: an entity never spans a newline, so the line
        # numbering survives even though the text gets shorter.
        lines = [unescape(line) for line in body.split("\n")]
        offset = pm.start("body")
        for line in body.split("\n"):
            for j, ch in enumerate(unescape(line)):
                out[offset + j] = ch
            offset += len(line) + 1
        first = raw.count("\n", 0, pm.start("body")) + 1
        passages.append({"title": attrs.get("name", ""),
                         "tags": (attrs.get("tags") or "").split(),
                         "lineno": first,
                         "body": list(enumerate(lines, first))})
        if start_pid and attrs.get("pid") == start_pid:
            start_name = attrs.get("name")
    return "".join(out), (passages, start_name)


def split_passages(text):
    """(title, tags, header lineno, body lines with their line numbers)."""
    out, cur = [], None
    for lineno, raw in enumerate(text.splitlines(), 1):
        m = PASSAGE.match(raw) if raw.startswith("::") else None
        if m:
            if cur:
                out.append(cur)
            cur = {"title": m.group("name").strip(),
                   "tags": (m.group("tags") or "").split(),
                   "lineno": lineno, "body": []}
            continue
        if cur is not None:
            cur["body"].append((lineno, raw))
    if cur:
        out.append(cur)
    return out


def find_close(s, i, open_ch, close_ch):
    """Index just past the `close_ch` matching the `open_ch` at `i`, or len(s).

    Depth-counted, and it skips quoted runs — a Harlowe macro argument may hold a
    bracket inside a string (`(track: 'a]b', 'play')`) and counting that would
    close the wrong thing.
    """
    depth, j, quote = 0, i, None
    while j < len(s):
        c = s[j]
        if quote:
            if c == quote:
                quote = None
        elif c in "'\"":
            quote = c
        elif c == open_ch:
            depth += 1
        elif c == close_ch:
            depth -= 1
            if depth == 0:
                return j + 1
        j += 1
    return len(s)


class Passage:
    """One passage, scanned into ordered items."""

    def __init__(self, title, body, unmapped):
        self.title = title
        self.items = []
        self.unmapped = unmapped
        self.text = "\n".join(line for _n, line in body)
        self.first_line = body[0][0] if body else 0
        self.hooks = []          # open `(if:)[` frames, innermost last
        self.last_hook = None    # the frame just closed, for `](else:)[`
        self.pending = []        # effects seen since the last line
        # Every macro argument, with its line. A hook opener like `(if: $n <= 2)`
        # produces no item of its own, so without this its literals counted as
        # prose the parser had lost.
        self.macro_args = []
        self.binds = []          # (macro name, variable) for every `bind $x`

    # -- line numbers ------------------------------------------------------
    def lineno_at(self, pos):
        return self.first_line + self.text.count("\n", 0, pos)

    # -- guard state -------------------------------------------------------
    def guard(self):
        # Plain hooks carry no condition: `(text-style:"underline")[TEXT]` styles
        # its contents rather than gating them.
        return [{"current": f["current"], "prior": list(f["prior"])}
                for f in self.hooks if not f.get("plain")]

    def open_hook(self, macro, arg, plain=False):
        if plain:
            # ANY Harlowe macro may take a hook, not only the conditionals —
            # `(text-style:)`, `(link:)`, `(box:)`, `(align:)`. Unrecognised, the
            # `[` stayed in the text and a styled run came out as a line of prose
            # beginning with a bracket. The macro is declared; its CONTENTS are
            # the author's words and stay required.
            self.hooks.append({"current": None, "prior": [], "plain": True})
            return
        if macro in ("else", "else-if", "elseif") and self.last_hook:
            prior = list(self.last_hook["prior"])
            if self.last_hook["current"] is not None:
                prior.append(self.last_hook["current"])
            current = None if macro == "else" else arg
        elif macro == "unless":
            prior, current = [arg], None
        else:
            prior, current = [], arg
        self.hooks.append({"current": current, "prior": prior})

    def close_hook(self):
        if self.hooks:
            closed = self.hooks.pop()
            # Only a CONDITIONAL hook can be the `if` an `](else:)[` refers to.
            if not closed.get("plain"):
                self.last_hook = closed

    # -- emitting ----------------------------------------------------------
    def add(self, item):
        item["index"] = len(self.items)
        self.items.append(item)
        return item

    def flush(self, buf, start):
        """A run of plain text becomes one item per non-empty line."""
        pos = start
        for chunk in buf.split("\n"):
            stripped = chunk.strip()
            if stripped:
                item = {"kind": "line", "lineno": self.lineno_at(pos),
                        "speaker": None, "text": stripped,
                        "effects": self.pending, "guard": self.guard() or None}
                self.pending = []
                self.add(item)
            pos += len(chunk) + 1


def parse_link(raw):
    """`[[Text|Target]]`, `[[Text->Target]]`, `[[Target<-Text]]`, `[[Target]]`."""
    inner = raw[2:-2]
    for sep, text_first in (("|", True), ("->", True), ("<-", False)):
        if sep in inner:
            a, b = inner.split(sep, 1)
            return (a.strip(), b.strip()) if text_first else (b.strip(), a.strip())
    return inner.strip(), inner.strip()


def split_top_level(arg):
    """Split a macro argument on commas that are not inside quotes or brackets.

    `(set:)` takes SEVERAL assignments at once — `(set: $gender to "male", $noun
    to "boy", $sbj to "he")` — and reading only the first left the rest of a
    story's variables undeclared, which made every guard on one of them declared
    loss for a reason ("the source never declares it") that was not true.
    """
    out, depth, quote, cur = [], 0, None, []
    for ch in arg:
        if quote:
            if ch == quote:
                quote = None
        elif ch in "'\"":
            quote = ch
        elif ch in "([":
            depth += 1
        elif ch in ")]":
            depth -= 1
        elif ch == "," and depth == 0:
            out.append("".join(cur))
            cur = []
            continue
        cur.append(ch)
    if "".join(cur).strip():
        out.append("".join(cur))
    return out


def parse_macro(name, arg):
    """A Harlowe macro as a list of effects; empty where there is no equivalent."""
    if name not in ("set", "put"):
        return []
    return [e for e in (parse_assignment(one) for one in split_top_level(arg)) if e]


def parse_assignment(arg):
    m = SET.match(arg.strip())
    if not m:
        return None
    var, val = m.group(1), m.group(2).strip()
    # `it` is the variable's own current value: `(set: $n to it - 1)`.
    inc = re.match(r"^(?:it|\$" + re.escape(var) + r")\s*([-+])\s*(\d+)$", val)
    if inc:
        return {"op": "add", "var": var,
                "delta": int(inc.group(2)) * (1 if inc.group(1) == "+" else -1)}
    if val in ("true", "false"):
        return {"op": "set", "var": var, "value": val == "true"}
    if re.match(r"^-?\d+$", val):
        return {"op": "setnum", "var": var, "value": int(val)}
    if re.match(r'^".*"$|^\'.*\'$', val):
        return {"op": "settext", "var": var, "value": val[1:-1]}
    return {"op": "expr", "var": var, "raw": val}


def scan(passage):
    """Characters, not lines: a Harlowe hook nests and spans them."""
    s, i = passage.text, 0
    buf, buf_start = "", 0
    while i < len(s):
        # ---- a link ------------------------------------------------------
        if s.startswith("[[", i):
            end = s.find("]]", i)
            end = len(s) if end < 0 else end + 2
            passage.flush(buf, buf_start)
            buf = ""
            text, target = parse_link(s[i:end])
            passage.add({"kind": "option", "lineno": passage.lineno_at(i),
                         "speaker": None, "text": text, "target": target,
                         "effects": [], "guard": passage.guard() or None})
            i = buf_start = end
            continue

        # ---- a macro, and the hook it may open -----------------------------
        m = MACRO_HEAD.match(s, i)
        if m:
            end = find_close(s, i, "(", ")")
            name = m.group(1).lower()
            raw_arg = s[m.end():end - 1]
            arg = raw_arg.strip()
            passage.flush(buf, buf_start)
            buf = ""
            j = end
            while j < len(s) and s[j] in " \t":
                j += 1
            # Harlowe COMPOSES changers with `+`: `(align:"=><=")+(box:"=XXX=")[…]`.
            # The `+` joins two macros and belongs to neither; left in the buffer
            # it flushed as a line of prose reading `+`.
            if j < len(s) and s[j] == "+":
                k = j + 1
                while k < len(s) and s[k] in " \t":
                    k += 1
                if k < len(s) and s[k] == "(":
                    j = k
            opens = j < len(s) and s[j] == "["
            # Per LINE: a `(set:)` may list a dozen assignments down as many
            # lines, and recording the whole argument against the macro's first
            # line left every later line's words looking like lost prose.
            #
            # From the UNSTRIPPED argument. Stripping first swallows the newline
            # that ends the macro's own line, so every following line was
            # credited to the one above it — right count, wrong lines, and
            # residue reported the lot.
            for k, chunk in enumerate(raw_arg.split("\n")):
                passage.macro_args.append((passage.lineno_at(i) + k, chunk))
            for bound in BIND.findall(arg):
                passage.binds.append((name, bound))
            if name in ("if", "unless", "else", "else-if", "elseif") and opens:
                passage.open_hook(name, arg)
                i = buf_start = j + 1
                continue
            effs = parse_macro(name, arg)
            if opens and not effs:
                passage.open_hook(name, arg, plain=True)
                passage.unmapped.append({"node": passage.title,
                                         "lineno": passage.lineno_at(i),
                                         "construct": f"({name}: {arg})",
                                         "why": WHY_MACRO})
                i = buf_start = j + 1
                continue
            passage.add({"kind": "command", "lineno": passage.lineno_at(i),
                         "speaker": None, "text": None, "macro": name, "arg": arg,
                         "effects": effs, "guard": passage.guard() or None})
            usable = [e for e in effs if e["op"] != "expr"]
            passage.pending.extend(usable)
            if not usable:
                why = WHY_COMPUTED_TEXT if name in ("print", "display") else WHY_MACRO
                passage.unmapped.append({"node": passage.title,
                                         "lineno": passage.lineno_at(i),
                                         "construct": f"({name}:)", "why": why})
            i = buf_start = j if (j > end and s[j:j + 1] == "(") else end
            continue

        # ---- a hook closing ------------------------------------------------
        if s[i] == "]" and passage.hooks:
            passage.flush(buf, buf_start)
            buf = ""
            passage.close_hook()
            i = buf_start = i + 1
            continue

        buf += s[i]
        i += 1
    passage.flush(buf, buf_start)


def infer_kinds(passages):
    """flag / counter / text per variable, from what the story ASSIGNS.

    Only from evidence that admits one reading. A bare `(if: $v)` contributes
    nothing: a number is truthy in Harlowe too, so reading an untyped name as a
    flag is a guess, and a guess here silently changes when a line appears.
    """
    seen = {}
    for p in passages:
        # A widget's bind declares its variable. What KIND depends on the macro,
        # and an unrecognised one contributes nothing rather than a guess.
        for macro, bound in p.binds:
            kind = BIND_KIND.get(macro)
            if kind:
                seen.setdefault(bound, set()).add(kind)
            else:
                seen.setdefault(bound, set())
        for it in p.items:
            for eff in it.get("effects") or []:
                kind = {"set": "flag", "setnum": "counter", "add": "counter",
                        "settext": "text"}.get(eff.get("op"))
                if eff.get("var"):
                    seen.setdefault(eff["var"], set()).add(kind or "unknown")
    out = {}
    for name, kinds in seen.items():
        determinate = kinds - {"unknown"}
        out[name] = determinate.pop() if len(determinate) == 1 else "unknown"
    return out


# Harlowe's own read-count and clock keywords. They look like bare variables in a
# condition and are not: reporting them as "a name the source never declares" sent
# the reader looking for a missing `(set:)` for something the language provides.
KEYWORDS = ("visits", "visit", "turns", "time", "exits", "history", "exit")
KEYWORD_RE = re.compile(r"(?<![$\w])(?:" + "|".join(KEYWORDS) + r")(?![\w])")


def guard_condition(guard, kinds):
    """A line's stack of enclosing hooks as one Parlance condition.

    Each frame contributes its own branch test AND the negation of every branch
    above it in the same chain — the part Harlowe does not write down, since
    `](else:)[` restates nothing. Getting it wrong shows both branches together
    whenever the guard holds, which no content check can see.
    """
    parts = []
    for frame in guard or []:
        for expr, invert in ([(p, True) for p in frame["prior"]] +
                             ([(frame["current"], False)]
                              if frame["current"] is not None else [])):
            if KEYWORD_RE.search(expr or ""):
                return None, WHY_READ_COUNT
            cond, why = conditions.translate(expr, kinds)
            if why:
                return None, why
            parts.append(conditions.negate(cond) if invert else cond)
    if not parts:
        return None, conditions.WHY_UNPARSEABLE
    return (parts[0] if len(parts) == 1 else {"type": "all", "of": parts}), None


def declare(passage, item, why, unmapped, construct):
    if not item.get("text") or item.get("unmappable"):
        return
    item["unmappable"] = why
    item.pop("showIf", None)
    unmapped.append({"node": passage.title, "lineno": item["lineno"],
                     "construct": construct, "text": item["text"], "why": why})


def mark_structural_losses(passage, unmapped, links_out):
    """What a guard cannot be carried onto, given where the links actually land.

    This has to model the IMPORTER's shape, not the source's. Harlowe renders a
    whole passage at once and shows every link in it together, so all of a
    passage's links hang off its LAST line — not off whichever line each one
    happens to follow. Checking per-link adjacency instead let a guarded line
    host a choice list anyway, which the validator rejects (rule COND) after the
    content check had already converged.

    Three cases fall out of that:

    * links, and no mappable line at all — nothing to hang them on (WHY_NO_HOST);
    * links, and the last mappable line is guarded — that line would carry showIf
      and choices together, so it is declared and the line before it becomes the
      host, repeatedly (WHY_CHOICE_HOST);
    * no links out — the last mappable line ends the conversation, so a guard on
      it would be showIf with isEnd (WHY_COND_TERMINAL).
    """
    def mappable_lines():
        return [it for it in passage.items
                if it["kind"] == "line" and it.get("text") and not it.get("unmappable")]

    if links_out:
        while True:
            lines = mappable_lines()
            if not lines:
                for it in passage.items:
                    if it["kind"] == "option" and not it.get("unmappable"):
                        declare(passage, it, WHY_NO_HOST, unmapped, "link with no host")
                return
            if not lines[-1].get("showIf"):
                return
            declare(passage, lines[-1], WHY_CHOICE_HOST, unmapped,
                    "guarded line hosting the passage's links")
    else:
        while True:
            lines = mappable_lines()
            if not lines or not lines[-1].get("showIf"):
                return
            declare(passage, lines[-1], WHY_COND_TERMINAL, unmapped,
                    "guarded line ending the passage")


def analyse(passages, unmapped):
    kinds = infer_kinds(passages)
    for p in passages:
        for it in p.items:
            if it["kind"] not in ("line", "option") or not it.get("guard"):
                continue
            cond, why = guard_condition(it["guard"], kinds)
            if why:
                it["unmappable"] = why
                unmapped.append({"node": p.title, "lineno": it["lineno"],
                                 "construct": "(if: …)", "text": it.get("text"),
                                 "why": why})
            else:
                it["showIf"] = cond

    # To a fixpoint, for the same reason as the other two parsers: declaring one
    # passage's lines can empty it, which turns a link into a dead end, which
    # makes another passage's tail terminal.
    while True:
        before = len(unmapped)
        empty = {p.title for p in passages
                 if not any(it.get("text") and not it.get("unmappable")
                            for it in p.items)}
        for p in passages:
            live = [it for it in p.items
                    if it["kind"] == "option" and not it.get("unmappable")
                    and it.get("target") not in empty]
            mark_structural_losses(p, unmapped, live)
        if len(unmapped) == before:
            break

    links = [{"from": p.title, "to": it["target"], "lineno": it["lineno"]}
             for p in passages for it in p.items if it["kind"] == "option"]
    titles = {p.title for p in passages}
    for link in links:
        if link["to"] not in titles:
            unmapped.append({"node": link["from"], "lineno": link["lineno"],
                             "construct": f"[[…|{link['to']}]]",
                             "why": "a link to a passage this story does not define"})
    return sorted(kinds), kinds, links


_stamp = _manifest.stamp


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("source")
    ap.add_argument("--emit", choices=["ir", "manifest"], default="ir")
    a = ap.parse_args()
    # utf-8-sig for the same reason the other two parsers use it: a BOM is
    # invisible in an editor and makes the first line unrecognisable.
    text, raw_passages = read_source(a.source)
    html_start = None
    if isinstance(raw_passages, tuple):
        raw_passages, html_start = raw_passages

    unmapped = []
    passages = []
    # The story's entry point is NOT the first passage in the file: egg.exe opens
    # on `Disclaimer` and defines `Confirmacao` first. Twee records it in
    # StoryData; compiled HTML records it as `startnode`, a pid, which read_source
    # has already resolved to a name. Taken from file order, 37 nodes came out
    # unreachable — the story's own opening scene among them.
    start = html_start
    # Words the parser accounted for that are not a unit's text: a macro's
    # arguments, and Twee's own metadata passages. Recorded rather than stripped
    # by a pattern, because a macro argument CAN hold prose and a pattern wide
    # enough to strip one is wide enough to swallow the other.
    accounted = []
    for raw in raw_passages:
        if raw["title"] in ("StoryTitle", "StoryData", "StoryStylesheet", "StoryScript"):
            # Twee's own metadata passages carry no story — an IFID, a format
            # version, tag colours, the stylesheet.
            accounted += [(n, line) for n, line in raw["body"]]
            accounted.append((raw["lineno"], raw["title"]))
            if raw["title"] == "StoryData":
                try:
                    data = json.loads("\n".join(l for _n, l in raw["body"]))
                except (ValueError, TypeError):
                    data = {}
                fmt = data.get("format")
                if fmt and fmt.lower() != "harlowe":
                    sys.exit(wrong_format(fmt))
                start = data.get("start") or start
            continue
        p = Passage(raw["title"], raw["body"], unmapped)
        p.tags = raw["tags"]
        scan(p)
        accounted += p.macro_args
        accounted.append((raw["lineno"], raw["title"]))
        accounted += [(raw["lineno"], tag) for tag in p.tags]
        accounted += [(it["lineno"], it.get("target")) for it in p.items
                      if it["kind"] == "option"]
        passages.append(p)
    variables, kinds, links = analyse(passages, unmapped)

    nodes = [{"title": p.title, "tags": p.tags, "items": p.items} for p in passages]
    if a.emit == "ir":
        print(json.dumps({"source": a.source, "format": "twine", "nodes": nodes,
                          "start": start,
                          "variables": variables, "variableKinds": kinds,
                          "links": links, "unmapped": unmapped},
                         indent=2, ensure_ascii=False))
        return 0

    units = [{"kind": it["kind"], "node": p.title, "speaker": None,
              "text": it["text"], "lineno": it["lineno"],
              **({"unmappable": it["unmappable"]} if it.get("unmappable") else {}),
              **({"showIf": it["showIf"]} if it.get("showIf") else {})}
             for p in passages for it in p.items
             if it["kind"] in ("line", "option") and it.get("text")]
    man = {
        "source": a.source, "format": "twine", "units": units,
        "variables": variables, "variableKinds": kinds,
        "nodes": [p.title for p in passages],
        "unmapped": unmapped,
        # Harlowe interpolates `$var` and Parlance interpolates `{var}`, which is
        # not a token-for-token swap, so it is NOT declared as a rewrite — a
        # variable named in a line stays exactly as the author wrote it and the
        # report says so. Nothing else differs between source and output.
        "rewrites": [],
    }
    man["residue"] = find_residue(text, man["units"], man["unmapped"],
                                  [(n, s) for n, s in accounted if s], fmt="twine")
    print(json.dumps(_stamp(man), indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
