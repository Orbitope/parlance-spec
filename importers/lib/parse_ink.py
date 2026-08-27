#!/usr/bin/env python3
"""
parse_ink.py — deterministic Ink (inkle) parser.

Emits an intermediate representation for an importer to MAP from, and a
reconciliation manifest for check.py to verify against. The model never
transcribes prose: every string in the output of an import must have come from
here, byte for byte.

Supports the Ink subset that carries story: knot and stitch headers, speaker
lines, choices (`*` once-only and `+` sticky, at any weave level, with the
`front[choice-only]after` bracket form), gathers, diverts, VAR/CONST
declarations, `~` assignments, conditional blocks, tags and glue. Anything it
does not understand is preserved in "unmapped" rather than dropped — a parser
that silently skips a construct is the same defect class as a model that
invents one.

Ink is a programming language rather than a serialization format, so more of it
falls outside Parlance than was the case for Yarn. Everything that does is
named, with its source line, in "unmapped"; the units it costs are marked
"unmappable" so check.py can report them as declared loss without letting the
import loop off the hook for anything else.

Usage:
    python3 parse_ink.py story.ink --emit ir        > ir.json
    python3 parse_ink.py story.ink --emit manifest  > manifest.json
"""
import argparse, json, os, re, sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from residue import find_residue, strip_comment
import conditions
import manifest as _manifest

KNOT       = re.compile(r"^\s*={2,}\s*(function\s+)?([A-Za-z_]\w*)\s*(\([^)]*\))?\s*=*\s*$")
STITCH     = re.compile(r"^\s*=\s*(function\s+)?([A-Za-z_]\w*)\s*(\([^)]*\))?\s*$")
CHOICE     = re.compile(r"^\s*((?:[*+]\s*)+)(.*)$")
# NOT `-+` alone, for two reasons. `-> knot` also starts with a dash, which is
# what the lookahead is for. And Ink writes a nested gather as `- -` as readily
# as `--`, so the marker run has to allow the spaces: `(-+)` read `- - (bunk_opts)`
# as a LEVEL 1 gather whose text began with a dash, which put ten labelled
# gathers out of reach of every divert pointing at them.
GATHER     = re.compile(r"^\s*((?:-\s*)+)(?!>)(.*)$")
VARDECL    = re.compile(r"^\s*(VAR|CONST)\s+([A-Za-z_]\w*)\s*=\s*(.+?)\s*$")
LISTDECL   = re.compile(r"^\s*LIST\s+([A-Za-z_]\w*)\s*=\s*(.+?)\s*$")
EXTERNAL   = re.compile(r"^\s*EXTERNAL\s+([A-Za-z_]\w*)\s*\(([^)]*)\)\s*$")
INCLUDE    = re.compile(r"^\s*INCLUDE\s+(.+?)\s*$")
ASSIGN     = re.compile(r"^\s*~\s*(.+?)\s*$")
THREAD     = re.compile(r"^\s*<-\s*([A-Za-z_][\w.]*)")
TUNNEL_RET = re.compile(r"^\s*->\s*->\s*$")
TUNNEL     = re.compile(r"->\s*([A-Za-z_][\w.]*)\s*->")
DIVERT     = re.compile(r"->\s*([A-Za-z_][\w.]*)")
SPEAKER    = re.compile(r"^([A-Za-z_][\w .'-]*?)\s*:\s*(.*)$")
BRACKET    = re.compile(r"^(.*?)\[(.*?)\](.*)$", re.S)
TAG        = re.compile(r"\s+#\s*(.+?)\s*$")
GATE       = re.compile(r"^\{([^{}:]*)\}\s*(.*)$")
IDENT      = re.compile(r"[A-Za-z_]\w*(?:\.\w+)?")
# `* (lie) [Lie]` / `- (hoopers_hut_3) "…"`. A label names a choice or a gather,
# and Ink lets a divert target one exactly as it targets a knot — 43 of The
# Intercept's divert targets are labels. Unparsed, every one of them looked like
# a dangling reference.
LABEL      = re.compile(r"^\((\w+)\)\s*")

TERMINAL = ("END", "DONE")

# Reasons, spelled once so the manifest and the report agree word for word.
WHY_SWITCH = ("conditional narration: a switch on a value ({ x: - 0: … - 1: … }) whose "
              "branch heads are not literals, so the equality test each branch stands "
              "for cannot be written down without guessing what the head means")
WHY_CHOICE_HOST = (
    "conditional narration immediately before a choice list. The line would have to be "
    "the node that hosts those choices, and a Parlance node may not carry showIf and "
    "choices together (validator rule COND) — a conditional node is interstitial "
    "narration, and there is no text-less node to hang the choices on instead")
WHY_VAR_TEXT = ("variable text: an alternative/sequence/shuffle ({a|b}) has no Parlance "
                "equivalent — a node holds one authored string")
WHY_COND_ALTERNATIVE = (
    "an inline conditional alternative ({cond: a|b}) — two variants of PART of a line. "
    "The condition itself would map, but a Parlance node holds one authored string, so "
    "carrying this needs the sentence split at the brace, and the pieces either side are "
    "sentence fragments rather than beats. Rewriting it in the source as two whole lines "
    "under a `{cond:` block makes it importable")
WHY_READ_COUNT = ("gated on a read count (how many times a knot has been visited); Parlance "
                  "has no read-count condition, and importing the choice ungated would "
                  "change when the player may take it")
WHY_LIST_COND = ("gated on a LIST value; Parlance variables are flags, counters and text "
                 "slots — there is no set-valued type to test")
WHY_ORPHAN_BODY = "body of a choice that is itself unmappable, so it can never be reached"
WHY_NO_HOST = (
    "a choice list with no narration line to host it — the options open a container, or "
    "follow a line that is itself declared loss. A Parlance choice hangs off a node and "
    "every node requires text, so there is nothing for them to attach to. Duplicating "
    "them onto the tail of each preceding branch would read correctly to a player but "
    "put the same string in the data several times, which the content check counts as "
    "invented prose. One line of narration before them makes them importable")
WHY_COND_DIVERT = (
    "a divert inside a conditional block — the story goes somewhere else only when the "
    "condition holds. A Parlance `next` and `goto` are unconditional; `showIf` gates "
    "whether a NODE is shown, not where the conversation goes next")
WHY_COND_TERMINAL = (
    "conditional narration as the last beat of the conversation. The node would have to "
    "carry showIf and isEnd together, which the validator refuses (rule COND): a "
    "dialogue's termination must not be conditional, or a player who fails the gate has "
    "nowhere to go. A line after it, or a divert onwards, makes it importable")
WHY_THREAD_ONLY = ("reachable only through a thread (<-), which weaves a second flow into "
                   "the current one; a Parlance dialogue has a single point of control")
WHY_TUNNEL_AMBIGUOUS = (
    "a tunnel (-> knot ->) called from places that want DIFFERENT returns. A Parlance "
    "`goto` may point anywhere, backwards included — a hub dialogue loops on purpose — "
    "but it names ONE node, written into the data, and `->->` here has to reach a "
    "different one per caller. With a single return target it is carried as an ordinary "
    "goto; with several it needs the scene duplicated once per target, which would put "
    "the author's prose in the project more than once")


# `strip_comment` is imported from residue.py rather than defined here: the
# accounting has to agree with the parser about where a comment starts, and it did
# not. Cutting at the first `//` excised the rest of any line containing a URL — a
# real prose loss, which residue then reported as a parser gap, correctly.


def split_tags(s):
    """Peel trailing `# tag` markers off a content line.

    Ink starts a tag at any bare `#`, so this is a heuristic on prose that
    contains one; the limitation is declared rather than hidden.
    """
    tags = []
    while True:
        m = TAG.search(s)
        if not m:
            return s.strip(), list(reversed(tags))
        tags.append(m.group(1))
        s = s[: m.start()]


def split_speaker(s):
    m = SPEAKER.match(s)
    return (m.group(1), m.group(2)) if m else (None, s)


def take_divert(s):
    """Pull a divert or tunnel off a fragment. Returns (rest, divert-dict|None)."""
    # A tunnel RETURN. `TUNNEL_RET` only matches a line that is nothing else, so
    # `- ->->` — a gather that returns — got here with `->->` still in it, and
    # neither pattern below has an identifier to match. It became a gather whose
    # TEXT was `->->`: two arrows in the manifest as a line of inkle's dialogue.
    if re.match(r"^->\s*->$", s.strip()):
        return "", {"kind": "tunnel_return"}
    m = TUNNEL.search(s)
    if m:
        rest = (s[: m.start()] + s[m.end():]).strip()
        # `-> a -> b` is a tunnel that hands on to another container when it
        # returns, not a tunnel followed by prose. Taking only the tunnel left
        # `harris_demands_component` sitting in the manifest as a line of the
        # writer's dialogue, which it is not.
        onward = re.match(r"^([A-Za-z_][\w.]*)\s*$", rest)
        return ("" if onward else rest,
                {"kind": "tunnel", "target": m.group(1),
                 **({"onward": onward.group(1)} if onward else {})})
    m = DIVERT.search(s)
    if m:
        t = m.group(1)
        return (s[: m.start()] + s[m.end():]).strip(), {
            "kind": "terminal" if t in TERMINAL else "divert", "target": t}
    return s, None


def parse_assignment(expr):
    """`~ ...` — the Ink form that carries state. Anything else is reported raw."""
    e = expr.strip()
    m = re.match(r"^(?:temp\s+)([A-Za-z_]\w*)\s*=\s*(.+)$", e)
    if m:
        return {"op": "temp", "var": m.group(1), "raw": e}
    m = re.match(r"^([A-Za-z_]\w*)\s*(\+\+|--)$", e)
    if m:
        return {"op": "add", "var": m.group(1), "delta": 1 if m.group(2) == "++" else -1,
                "raw": e}
    m = re.match(r"^([A-Za-z_]\w*)\s*([-+])=\s*(-?\d+)$", e)
    if m:
        d = int(m.group(3)) * (1 if m.group(2) == "+" else -1)
        return {"op": "add", "var": m.group(1), "delta": d, "raw": e}
    m = re.match(r"^([A-Za-z_]\w*)\s*=\s*(.+)$", e)
    if m:
        var, val = m.group(1), m.group(2).strip()
        inc = re.match(r"^" + re.escape(var) + r"\s*([-+])\s*(\d+)$", val)
        if inc:
            d = int(inc.group(2)) * (1 if inc.group(1) == "+" else -1)
            return {"op": "add", "var": var, "delta": d, "raw": e}
        if val in ("true", "false"):
            return {"op": "set", "var": var, "value": val == "true", "raw": e}
        if re.match(r"^-?\d+$", val):
            return {"op": "setnum", "var": var, "value": int(val), "raw": e}
        if re.match(r'^".*"$', val):
            return {"op": "settext", "var": var, "value": val[1:-1], "raw": e}
        return {"op": "expr", "var": var, "raw": e}
    return {"op": "expr", "var": None, "raw": e}


def brace_reason(inner):
    """Which unmappable brace form this is — the two read very differently.

    `{a|b}` is variable text: the author wrote two variants of a beat and Ink
    picks one. `{cond: a|b}` is an if/else INSIDE a sentence, and its condition
    would map perfectly well; what does not map is the sentence being part
    conditional. Reporting both as "variable text" told an author their story
    used a feature it does not, and hid the one rewrite that would let the line
    through.
    """
    return WHY_COND_ALTERNATIVE if ":" in inner.split("|", 1)[0] else WHY_VAR_TEXT


def is_block_opener(s):
    """Does this line OPEN a multiline conditional, rather than contain an inline one?

    `s.startswith("{") and not s.endswith("}")` was the old test, and it is wrong on
    the commonest real construct there is: a line that begins with an inline
    conditional and continues afterwards —

        {gotcomponent:The weight of the component in my jacket|Satisfied}, I return.

    — opens a block that never closes, and every line to the end of the FILE inherits
    a guard it does not have. 230 lines of The Intercept came out conditional on one
    flag this way. A real opener ends the line at its `:`, so that is the test.
    """
    return s.startswith("{") and "}" not in s and (s.strip() == "{" or s.rstrip().endswith(":"))


def new_frame(opener_line):
    """One open `{ … :` conditional block.

    `opener` is the block's own test, if it has one. A block written `{` with the
    tests on its branch lines has none, and the difference matters: with an
    opener, a branch head is a VALUE compared against it; without one, a branch
    head is a condition in its own right.
    """
    opener = opener_line[1:].rstrip(":").strip().rstrip(":")
    # `switch` stays undecided until the first branch head shows which form this
    # is; before then the opener is the first branch's test, which is what a
    # `{ cond:` block with no branch header at all means.
    return {"opener": opener, "prior": [], "current": opener or None,
            "switch": None, "why": None}


def snapshot(frame):
    """The guard a line inside `frame` is under, at the moment it is read."""
    return {"current": frame["current"], "prior": list(frame["prior"]),
            "why": frame["why"]}


def describe_frame(frame):
    """The frame's branch in source terms, for the IR a human reads."""
    if frame["current"] is not None:
        return frame["current"]
    return "else of " + " / ".join(frame["prior"]) if frame["prior"] else frame["opener"]


def prescan(lines):
    """Container and declaration names, needed before conditions can be classified.

    A `{bench > 1}` gate is a read count if `bench` is a knot and a variable test
    if it is a VAR, and the two map very differently — one to showIf, one to
    nothing at all. That distinction cannot be made in one pass.
    """
    containers, variables, consts, lists_ = [], set(), {}, set()
    knot = None
    for raw in lines:
        s = strip_comment(raw).strip()
        # A labelled choice or gather — `* (lift_up_cup) [Take it]` — is testable
        # by READ COUNT exactly like a knot. Without them here, a guard on one
        # reported "the source never declares this name", which sent the reader
        # looking for a missing VAR instead of at a construct Parlance has no
        # equivalent for.
        m = re.match(r"^\s*(?:[*+-]\s*)+\((\w+)\)", s)
        if m:
            containers.append(m.group(1))
        m = KNOT.match(s)
        if m:
            knot = m.group(2)
            containers.append(knot)
            continue
        m = STITCH.match(s)
        if m and knot:
            containers.append(f"{knot}.{m.group(2)}")
            continue
        m = VARDECL.match(s)
        if m:
            if m.group(1) == "VAR":
                variables.add(m.group(2))
            else:
                consts[m.group(2)] = m.group(3).strip()
            continue
        m = LISTDECL.match(s)
        if m:
            lists_.add(m.group(1))
    return containers, variables, consts, lists_


def classify_condition(cond, containers, variables, lists_):
    """Why a condition cannot be carried, or None if it can.

    `containers` must include LABELLED choices and gathers, not only knots and
    stitches. Ink lets a story test `(shouted)` or `(bunk_opts)` by read count
    exactly as it tests a knot, and without the labels those guards fell through
    to the generic translator, which reported them as names the source never
    declares — true of a variable, and misleading about a construct that is
    right there in the file.
    """
    names = {n for n in IDENT.findall(cond)
             if n not in ("true", "false", "not", "and", "or", "has", "hasnt")}
    short = {c.split(".")[-1] for c in containers}
    for n in sorted(names):
        if n in lists_:
            return WHY_LIST_COND
        if n in variables:
            continue
        # `knot.label` addresses a label from outside its container, so the last
        # segment is what has to be recognised — the dotted whole never appears
        # in either list.
        if n in containers or n in short or n.split(".")[-1] in short:
            return WHY_READ_COUNT
    return None


def parse(text):
    lines = text.splitlines()
    containers_seen, variables, consts, lists_ = prescan(lines)

    containers, decls, unmapped = [], [], []
    cur = None
    knot = None
    file_tags = []
    in_block_comment = False
    cond_stack = []            # open multiline conditionals, innermost last
    last_marker = None         # index of the enclosing choice/gather in cur["items"]

    def new_container(title, kind, name, lineno):
        nonlocal cur, last_marker
        cur = {"title": title, "kind": kind, "name": name, "knot": knot,
               "lineno": lineno, "tags": [], "items": []}
        containers.append(cur)
        last_marker = None

    def add(item):
        nonlocal last_marker
        if cur is None:
            new_container("_prologue", "knot", "_prologue", item["lineno"])
        item["index"] = len(cur["items"])
        item["parent"] = last_marker
        item.setdefault("level", 0)
        cur["items"].append(item)
        if item["kind"] in ("option", "gather"):
            last_marker = item["index"]
        return item

    def note_callable(s, lineno, is_function, params):
        if is_function:
            report(lineno, s.strip(), "function: Parlance data has no call/return and no "
                                      "expression language to call one from")
        elif params:
            report(lineno, s.strip(), "parameterised knot: a Parlance goto carries no "
                                      "arguments, so the parameters have nowhere to go")

    def report(lineno, construct, why, text_=None):
        e = {"node": cur["title"] if cur else None, "lineno": lineno,
             "construct": construct, "why": why}
        if text_ is not None:
            e["text"] = text_
        unmapped.append(e)
        return e

    for lineno, raw in enumerate(lines, 1):
        s = strip_comment(raw).strip()

        if in_block_comment:
            if "*/" in s:
                in_block_comment = False
                s = s.split("*/", 1)[1].strip()
            else:
                continue
        while s.startswith("/*"):
            if "*/" in s:
                s = (s.split("*/", 1)[1]).strip()
            else:
                in_block_comment = True
                s = ""
        if not s or s.startswith("TODO:"):
            continue

        if "<>" in s:
            s = s.replace("<>", " ").strip()
            report(lineno, "<>", "glue joins this line to its neighbour in one printed "
                                 "run; a Parlance node is a discrete beat, so the join "
                                 "is dropped and both lines survive as separate nodes",
                   s)

        # ---- inside a multiline conditional block -------------------------
        #
        # The branch headers are the whole difficulty. Ink writes an `else`
        # without restating what it is the alternative to, so a line under
        # `- else:` carries the NEGATION of every branch above it — computed
        # here, from the frame, rather than left for the importer to remember.
        # Handing the else branch its `if`'s guard shows both lines together
        # whenever the guard holds, and no downstream check can see that:
        # nothing is missing and nothing is invented.
        if cond_stack:
            if s == "}":
                cond_stack.pop()
                continue
            # A gather line can OPEN a nested block (`- { teacup:`), and inside a
            # block that reads as a branch header whose test is `{ teacup`. Checked
            # first, because the wrong reading leaves the nested block unopened and
            # its `}` closing the OUTER one.
            if s.startswith("-") and is_block_opener(s[1:].strip()):
                cond_stack.append(new_frame(s[1:].strip()))
                continue
            m = re.match(r"^-\s*(?:(else|otherwise)\s*:|([^:\n]*?)\s*:)\s*$", s)
            if m:
                frame, head = cond_stack[-1], m.group(2)
                is_else = bool(m.group(1)) or head in (None, "")
                literal = bool(head) and re.match(r"^(?:-?\d+|true|false)$", head)
                # `{ x:` with `- 0:` under it is a SWITCH: each branch head is a
                # value the opener is compared against, not a condition of its
                # own, and the opener is not a test at all. Written out as that
                # equality when the head is a literal, and declined when it is
                # anything else rather than guessed at.
                if frame["switch"] is None and frame["opener"] and not is_else:
                    frame["switch"] = bool(literal)
                    if frame["switch"] and not frame["prior"]:
                        frame["current"] = None
                if frame["current"] is not None:
                    frame["prior"].append(frame["current"])
                if is_else:
                    frame["current"] = None
                elif frame["switch"]:
                    if literal:
                        frame["current"] = f"{frame['opener']} == {head}"
                    else:
                        frame["why"] = WHY_SWITCH
                        frame["current"] = head
                else:
                    frame["current"] = head
                continue
            if is_block_opener(s):
                cond_stack.append(new_frame(s))
                continue
            body, tags = split_tags(s)
            # Glue is stripped here too. It was handled only on the ordinary
            # content path, so a glued line inside a conditional block reached
            # the manifest with its `<>` and the project without it — the same
            # line, differing by the one declared rewrite, which the content
            # check reads as a line invented and a line lost.
            body, div = take_divert(body)
            if body:
                sp, txt = split_speaker(body)
                add({"kind": "line", "lineno": lineno, "level": 0, "speaker": sp,
                     "text": txt, "tags": tags, "divert": div, "effects": [],
                     "condition": " and ".join(describe_frame(f) for f in cond_stack),
                     "guard": [snapshot(f) for f in cond_stack]})
            continue

        # ---- file-level declarations --------------------------------------
        m = VARDECL.match(s)
        if m:
            kw, name, val = m.group(1), m.group(2), m.group(3).strip()
            # `VAR hooperClueType = NONE` where `CONST NONE = 0`. Resolved rather
            # than left unknown: a CONST is a literal with a name, and leaving it
            # unresolved made every guard on the variable declared loss with a
            # reason ("the source never declares it") that was not even true.
            val = consts.get(val, val)
            kind = ("flag" if val in ("true", "false")
                    else "counter" if re.match(r"^-?\d+$", val)
                    else "text" if re.match(r'^".*"$', val) else "unknown")
            default = (val == "true" if kind == "flag"
                       else int(val) if kind == "counter"
                       else val[1:-1] if kind == "text" else val)
            decls.append({"decl": kw, "name": name, "id": name.lower(), "kind": kind,
                          "default": default, "lineno": lineno, "raw": s})
            if kw == "CONST":
                report(lineno, s,
                       "CONST is a compile-time constant; Parlance registers mutable state "
                       "only, so inline its value at the use sites rather than declaring a "
                       "counter the story never writes")
            elif kind == "unknown":
                report(lineno, s, "VAR initialised from an expression; its Parlance kind "
                                  "(flag / counter / text) cannot be derived from the source")
            continue
        m = LISTDECL.match(s)
        if m:
            decls.append({"decl": "LIST", "name": m.group(1), "lineno": lineno, "raw": s})
            report(lineno, s, "LIST is a set-valued type; Parlance variables are flags, "
                              "counters and text slots, with no set to hold or test")
            continue
        m = EXTERNAL.match(s)
        if m:
            decls.append({"decl": "EXTERNAL", "name": m.group(1), "lineno": lineno, "raw": s})
            report(lineno, s, "EXTERNAL binds a game-code function; Parlance data calls "
                              "nothing — its effect vocabulary is closed")
            continue
        m = INCLUDE.match(s)
        if m:
            decls.append({"decl": "INCLUDE", "name": m.group(1), "lineno": lineno, "raw": s})
            report(lineno, s, "INCLUDE pulls in another file; parse and import each file, "
                              "then reconcile the manifests")
            continue

        # ---- headers -------------------------------------------------------
        m = KNOT.match(s)
        if m:
            knot = m.group(2)
            new_container(knot, "knot", knot, lineno)
            note_callable(s, lineno, m.group(1), m.group(3))
            continue
        m = STITCH.match(s)
        if m:
            name = m.group(2)
            new_container(f"{knot}.{name}" if knot else name, "stitch", name, lineno)
            note_callable(s, lineno, m.group(1), m.group(3))
            continue

        # ---- tag-only line --------------------------------------------------
        if s.startswith("#"):
            tag = s[1:].strip()
            if cur is None:
                file_tags.append(tag)
            else:
                cur["tags"].append(tag)
            continue

        # ---- threads and tunnel returns -------------------------------------
        m = THREAD.match(s)
        if m:
            add({"kind": "thread", "lineno": lineno, "level": 0, "speaker": None,
                 "text": None, "tags": [], "divert": {"kind": "thread", "target": m.group(1)},
                 "effects": []})
            report(lineno, s, WHY_THREAD_ONLY)
            continue
        if TUNNEL_RET.match(s):
            # Carried as a DIVERT of kind tunnel_return, the same shape the gather
            # form produces (`- ->->`), so the importer has one case rather than
            # two. Whether it can be resolved is decided in analyse(): a tunnel
            # with one call site returns to one place, and a `goto` expresses that
            # exactly. Only an ambiguous one is reported.
            add({"kind": "tunnel_return", "lineno": lineno, "level": 0, "speaker": None,
                 "text": None, "tags": [], "divert": {"kind": "tunnel_return"},
                 "effects": []})
            continue

        # ---- assignments -----------------------------------------------------
        m = ASSIGN.match(s)
        if m:
            eff = parse_assignment(m.group(1))
            add({"kind": "command", "lineno": lineno, "level": 0, "speaker": None,
                 "text": None, "tags": [], "divert": None, "effects": [eff]})
            if eff["op"] == "temp":
                report(lineno, s, "temp variable: scoped to the knot call, with no registry "
                                  "entry it could map to")
            elif eff["op"] == "expr":
                report(lineno, s, "expression assignment; the Parlance effect vocabulary is "
                                  "set_flag / adjust_counter / set_text, with no arithmetic")
            continue

        # ---- choices ----------------------------------------------------------
        m = CHOICE.match(s)
        if m and re.match(r"^\s*[*+]", s):
            markers = m.group(1)
            level = sum(1 for ch in markers if ch in "*+")
            sticky = [ch for ch in markers if ch in "*+"][-1] == "+"
            body, tags = split_tags(m.group(2))
            label = None
            lm = LABEL.match(body)
            if lm:
                label, body = lm.group(1), body[lm.end():]
            gate = None
            g = GATE.match(body)
            if g:
                gate, body = g.group(1).strip(), g.group(2).strip()
            body, div = take_divert(body)
            b = BRACKET.match(body)
            if b:
                front, only, after = b.group(1), b.group(2), b.group(3)
                otext = re.sub(r"\s+", " ", front + only).strip()
                printed = re.sub(r"\s+", " ", front + after).strip()
            else:
                otext, printed = body.strip(), None
            opt = add({"kind": "option", "lineno": lineno, "level": level,
                       "sticky": sticky, "tags": tags, "divert": div, "effects": [],
                       "label": label,
                       "condition": gate, "echoes": b is None,
                       **({"guard": [{"current": gate, "prior": [], "why": None}]}
                          if gate else {}),
                       **dict(zip(("speaker", "text"), split_speaker(otext)))})
            if printed:
                sp, txt = split_speaker(printed)
                add({"kind": "line", "lineno": lineno, "level": level, "speaker": sp,
                     "text": txt, "tags": tags, "divert": None, "effects": [],
                     "condition": None, "printed_by": opt["index"]})
            continue

        # ---- gathers -----------------------------------------------------------
        m = GATHER.match(s)
        if m:
            level = m.group(1).count("-")
            body, tags = split_tags(m.group(2))
            label = None
            lm = LABEL.match(body)
            if lm:
                label, body = lm.group(1), body[lm.end():].strip()
            body, div = take_divert(body)
            opens = is_block_opener(body)
            sp, txt = split_speaker(body) if body and not opens else (None, None)
            add({"kind": "gather", "lineno": lineno, "level": level, "speaker": sp,
                 "text": txt or None, "tags": tags, "divert": div, "effects": [],
                 "label": label, "condition": None})
            if opens:
                cond_stack.append(new_frame(body))
            continue

        # ---- standalone divert / tunnel ------------------------------------------
        if s.startswith("->"):
            body, tags = split_tags(s)
            _, div = take_divert(body)
            add({"kind": "divert", "lineno": lineno, "level": 0, "speaker": None,
                 "text": None, "tags": tags, "divert": div, "effects": []})
            continue

        # ---- conditional block opener ---------------------------------------------
        if is_block_opener(s):
            cond_stack.append(new_frame(s))
            continue

        # ---- ordinary content line --------------------------------------------------
        body, tags = split_tags(s)
        body, div = take_divert(body)
        unmappable, condition, guard = None, None, None
        if body.startswith("{") and body.endswith("}") and body.count("{") == 1:
            inner = body[1:-1]
            if "|" in inner:
                unmappable = brace_reason(inner)
                report(lineno, body, unmappable, body)
            elif ":" in inner:
                condition, rest = inner.split(":", 1)
                condition, body = condition.strip(), rest.strip()
                # The one-line form of the same thing the block above handles.
                # It has no branches, so its guard is a single frame with no
                # negations to work out.
                guard = [{"current": condition, "prior": [], "why": None}]
        else:
            m_alt = re.search(r"\{([^{}]*\|[^{}]*)\}", body)
            if m_alt:
                unmappable = brace_reason(m_alt.group(1))
                report(lineno, body, unmappable, body)
        if body:
            sp, txt = split_speaker(body)
            it = {"kind": "line", "lineno": lineno, "level": 0, "speaker": sp, "text": txt,
                  "tags": tags, "divert": div, "effects": [], "condition": condition,
                  **({"guard": guard} if guard else {})}
            if unmappable:
                it["unmappable"] = unmappable
            add(it)
            if tags:
                report(lineno, " ".join("#" + t for t in tags),
                       "line tag: a Parlance dialogue carries tags, a node does not, so a "
                       "per-line tag has nowhere to land")
        elif div:
            add({"kind": "divert", "lineno": lineno, "level": 0, "speaker": None,
                 "text": None, "tags": tags, "divert": div, "effects": []})

    return {"containers": containers, "declarations": decls, "file_tags": file_tags,
            "unmapped": unmapped, "prescan": {"containers": containers_seen,
                                              "variables": sorted(variables),
                                              "consts": sorted(consts),
                                              "constValues": consts,
                                              "lists": sorted(lists_)}}


def label_index(containers):
    """Every label, under each name a divert may reach it by.

    A label is scoped to its container but addressable from outside as
    `knot.label` or `knot.stitch.label`, and from inside by the bare name.
    Collisions keep the FIRST — the same reading Ink gives a bare name from
    outside its own knot, and never a silent overwrite.
    """
    out = {}
    for c in containers:
        for it in c["items"]:
            if not it.get("label"):
                continue
            for name in (it["label"], f"{c['title']}.{it['label']}",
                         f"{c['knot']}.{it['label']}" if c.get("knot") else None):
                if name and name not in out:
                    out[name] = (c["title"], it["index"])
    return out


def resolve(target, knot, titles, labels=()):
    """A divert may name a knot, `knot.stitch`, a bare stitch in the same knot —
    or a LABELLED choice or gather, which is a container-relative address rather
    than a container of its own."""
    if target in titles:
        return target
    if knot and f"{knot}.{target}" in titles:
        return f"{knot}.{target}"
    if labels:
        for name in (f"{knot}.{target}" if knot else None, target):
            if name and name in labels:
                return labels[name][0]
    return None


def weave(container):
    """Wire the weave: which gather each choice and gather falls into.

    Ink's indentation is cosmetic — nesting is the number of `*`/`+`/`-` markers
    — so this is computed from marker depth, never from whitespace.
    """
    items = container["items"]
    for it in items:
        if it["kind"] not in ("option", "gather"):
            continue
        lvl = it["level"]
        target = None
        for j in range(it["index"] + 1, len(items)):
            o = items[j]
            if o["kind"] != "gather":
                continue
            if (o["level"] <= lvl and it["kind"] == "option") or \
               (o["level"] < lvl and it["kind"] == "gather"):
                target = j
                break
        it["gathersTo"] = target


def variable_kinds(parsed):
    """flag / counter / text per declared variable.

    A `VAR` line states the kind by what it initialises to, and that is
    authoritative. `~ x = …` assignments fill in the rest, because Ink lets a
    story write a variable it declared from an expression. Conflicting evidence
    resolves to unknown rather than to a majority: a variable the story treats as
    both is one this importer will not register, and its guards are declared loss.

    A bare `{x: …}` deliberately contributes nothing. A number is truthy in Ink
    too, so reading an untyped name as a flag is a guess, and a guess here
    silently changes when a line appears.
    """
    seen = {}
    for d in parsed["declarations"]:
        if d.get("decl") in ("VAR", "CONST") and d.get("kind"):
            seen.setdefault(d["name"], set()).add(d["kind"])
    for c in parsed["containers"]:
        for it in c["items"]:
            for eff in it.get("effects") or []:
                kind = {"set": "flag", "setnum": "counter", "add": "counter",
                        "settext": "text"}.get(eff.get("op"))
                if kind and eff.get("var"):
                    seen.setdefault(eff["var"], set()).add(kind)
    out = {}
    for name, kinds in seen.items():
        determinate = kinds - {"unknown"}
        out[name] = determinate.pop() if len(determinate) == 1 else "unknown"
    return out


def guard_condition(guard, titles, variables, lists_, kinds, consts=None):
    """A line's stack of enclosing conditional frames as one Parlance condition.

    `(condition, None)` or `(None, why)`. Each frame contributes its own branch
    test AND the negation of every branch above it in the same block — the part
    neither format writes down, and the part that duplicates narration if it is
    forgotten.

    `classify_condition` runs first on every expression because its two answers
    (a read count, a LIST) are Ink facts that name the construct, where the
    generic translator could only say the name was undeclared.
    """
    parts = []
    for frame in guard:
        if frame.get("why"):
            return None, frame["why"]
        for expr, invert in ([(p, True) for p in frame["prior"]] +
                             ([(frame["current"], False)]
                              if frame["current"] is not None else [])):
            why = classify_condition(expr, titles, variables, lists_)
            if why:
                return None, why
            cond, why = conditions.translate(expr, kinds, consts)
            if why:
                return None, why
            parts.append(conditions.negate(cond) if invert else cond)
    if not parts:
        return None, conditions.WHY_UNPARSEABLE
    return (parts[0] if len(parts) == 1 else {"type": "all", "of": parts}), None


def declare(container, item, why, unmapped, construct):
    if not item.get("text") or item.get("unmappable"):
        return
    item["unmappable"] = why
    item.pop("showIf", None)
    unmapped.append({"node": container["title"], "lineno": item["lineno"],
                     "construct": construct, "text": item["text"], "why": why})


def mark_structural_losses(container, unmapped, lo=0, hi=None, terminal=True, empty=()):
    """Everything a guard or a choice list cannot be carried INTO, structurally.

    The Ink counterpart of the pass in `parse_yarn.py`, and the same three cases:
    a choice list with no narration line to host it, a guarded line that would end
    up hosting one, and a guarded line that would end up as the conversation's
    last beat. `showIf` is mutually exclusive with both `choices` and `isEnd`.

    It runs AFTER the guard pass and looks PAST declared-loss lines, because those
    are never emitted — adjacency in the source is not adjacency in the output.
    The Intercept opens a choice set right under `{|I rattle my fingers…|}`, which
    is variable text and therefore not carried; the choices have no host at all.
    """
    items = container["items"]
    hi = len(items) if hi is None else hi
    host = None
    guarded = []
    i = lo
    while i < hi:
        it = items[i]

        if it["kind"] in ("line", "gather") and it.get("text") \
                and not it.get("unmappable"):
            if it.get("showIf"):
                guarded.append(it)
            else:
                host, guarded = it, []
            i += 1
            continue

        if it["kind"] != "option":
            i += 1
            continue

        level = it["level"]
        run, j = [], i
        while j < hi and items[j]["kind"] == "option" and items[j]["level"] == level:
            b0 = j + 1
            b1 = hi
            for k in range(b0, hi):
                if items[k]["kind"] in ("option", "gather") and items[k]["level"] <= level:
                    b1 = k
                    break
            run.append((j, b0, b1))
            j = b1

        for g in guarded:
            declare(container, g, WHY_CHOICE_HOST, unmapped,
                    "guarded line before a choice list")
        before_run = host
        if host is None:
            for k in range(i, j):
                dead = items[k]
                why = (WHY_NO_HOST if dead["kind"] == "option" and dead["level"] == level
                       else WHY_ORPHAN_BODY)
                declare(container, dead, why, unmapped, "choice list with no host")
        else:
            after_lives = any(
                items[k].get("text") and not items[k].get("unmappable")
                for k in range(j, hi)) or any(
                not items[k].get("conditionalDivert")
                and _goes_somewhere(items[k].get("divert"), empty)
                for k in range(j, hi))
            for oi, b0, b1 in run:
                # An option that diverts sends the story on, so its body does not
                # end the conversation — but only then. Skipping the body wholesale
                # left a guarded last line in it undeclared.
                onward = _goes_somewhere(items[oi].get("divert"), empty)
                mark_structural_losses(container, unmapped, b0, b1,
                                       terminal and not after_lives and not onward,
                                       empty)
        host, guarded = single_branch_host(items, run, j, before_run), []
        i = j

    if terminal and guarded and not any(
            not items[k].get("conditionalDivert")
            and _goes_somewhere(items[k].get("divert"), empty)
            for k in range(lo, hi)):
        for g in guarded:
            declare(container, g, WHY_COND_TERMINAL, unmapped,
                    "guarded line ending the container")


def single_branch_host(items, run, after, before_run):
    """What can host a choice list that comes straight after this option run.

    A bare Ink gather is a join with no text, and Parlance has no text-less node —
    so a choice set arriving right after one has nothing to hang off unless the
    join has exactly ONE live branch, in which case that branch's last beat is
    unambiguously the line the player just read. With several branches the beat
    differs per path, and the only ways to express it would be duplicating the
    choices onto each tail (which the content check counts as invented prose) or
    inventing a line. So: one branch, reuse it; more, declare.

    It matters more than the count suggests. In The Intercept a single variable-
    text line sits between a gather and the story's main choice set; without this,
    that set is dropped and 535 of 539 nodes become unreachable — the whole story
    after the first four lines.
    """
    live = [(oi, b0, b1) for oi, b0, b1 in run if not items[oi].get("unmappable")]
    if len(live) != 1:
        return None
    _oi, b0, b1 = live[0]
    for k in range(b1 - 1, b0 - 1, -1):
        it = items[k]
        if it["kind"] == "option":
            return None         # the branch ends in a nested choice set of its own
        if it["kind"] in ("line", "gather") and it.get("text") and not it.get("unmappable"):
            return it
    return before_run


def _goes_somewhere(div, empty):
    """A divert that leads to prose. `-> END` does not, nor does one whose target
    is a container every line of which is declared loss."""
    if not div or div["kind"] == "terminal":
        return False
    target = div.get("resolved") or (div.get("resolvedLabel") or [None])[0]
    return bool(target) and target not in empty


def analyse(parsed):
    containers = parsed["containers"]
    titles = [c["title"] for c in containers]
    pre = parsed["prescan"]
    # Everything addressable by read count: knots, stitches, and the labelled
    # choices and gathers prescan collected.
    countable = list(titles) + list(pre["containers"])
    variables = set(pre["variables"])
    lists_ = set(pre["lists"])
    unmapped = parsed["unmapped"]

    labels = label_index(containers)
    divert_targets, thread_targets, edges = set(), set(), []
    for c in containers:
        weave(c)
        for it in c["items"]:
            d = it.get("divert")
            if not d:
                continue
            if d["kind"] == "thread":
                r = resolve(d["target"], c["knot"], titles, labels)
                d["resolved"] = r
                thread_targets.add(r or d["target"])
                continue
            if d["kind"] in ("terminal", "tunnel_return"):
                # A tunnel return names no target: it goes back to whichever
                # container called in, which is a runtime fact.
                d["resolved"] = None
                continue
            r = resolve(d["target"], c["knot"], titles, labels)
            d["resolved"] = r
            # Where inside that container, when the target was a label.
            for name in (f"{c['knot']}.{d['target']}" if c.get("knot") else None,
                         d["target"]):
                if name and name in labels:
                    d["resolvedLabel"] = labels[name]
                    break
            divert_targets.add(r or d["target"])
            edges.append({"from": c["title"], "to": r or d["target"],
                          "kind": d["kind"], "lineno": it["lineno"]})

    # Guards, on a choice and on narration alike. A variable test becomes a
    # `showIf`; a read count, a LIST or anything outside the condition vocabulary
    # is declared loss, and says which of those it was.
    kinds = variable_kinds(parsed)
    consts = parsed["prescan"].get("constValues") or {}
    for c in containers:
        for index, it in enumerate(c["items"]):
            if it.get("unmappable") or not it.get("guard"):
                continue
            cond, why = guard_condition(it["guard"], countable, variables, lists_,
                                        kinds, consts)
            if why:
                it["unmappable"] = why
                unmapped.append({"node": c["title"], "lineno": it["lineno"],
                                 "construct": "{%s}" % (it.get("condition") or ""),
                                 "text": it["text"], "why": why})
            else:
                it["showIf"] = cond

    # A knot reached only by a thread cannot be entered at all in Parlance, so its
    # prose is declared loss rather than a line the importer merely forgot.
    for c in containers:
        if c["title"] in thread_targets and c["title"] not in divert_targets \
                and c is not containers[0]:
            for it in c["items"]:
                if it.get("text") and not it.get("unmappable"):
                    it["unmappable"] = WHY_THREAD_ONLY
                    unmapped.append({"node": c["title"], "lineno": it["lineno"],
                                     "construct": "<- %s" % c["title"], "text": it["text"],
                                     "why": WHY_THREAD_ONLY})

    # Anything hanging off an unmappable choice is unreachable with it gone.
    #
    # By LEVEL, not by `parent`. `parent` records the previous marker, so the
    # option after an unmappable one is its "child" in that link — and three of
    # The Intercept's choices were killed as orphans for standing next to a
    # read-count gate, taking their bodies with them. A body is the items after
    # an option, up to the next option or gather at its own level or shallower.
    for c in containers:
        items = c["items"]
        for oi, it in enumerate(items):
            if it["kind"] != "option" or not it.get("unmappable"):
                continue
            level = it["level"]
            end = len(items)
            for k in range(oi + 1, len(items)):
                if items[k]["kind"] in ("option", "gather") and items[k]["level"] <= level:
                    end = k
                    break
            for k in range(oi + 1, end):
                dead = items[k]
                if dead.get("text") and not dead.get("unmappable"):
                    dead["unmappable"] = WHY_ORPHAN_BODY
                    dead.pop("showIf", None)
                    unmapped.append({"node": c["title"], "lineno": dead["lineno"],
                                     "construct": "choice body", "text": dead["text"],
                                     "why": WHY_ORPHAN_BODY})

    # Once-only (`*`) choices, reported once rather than per occurrence: the loss is
    # one property of the format, and a line-by-line list of it would drown the
    # report that has to be read.
    once = [it["lineno"] for c in containers for it in c["items"]
            if it["kind"] == "option" and not it.get("sticky")]
    if once:
        unmapped.append({"node": None, "lineno": once[0], "construct": "* (once-only choice)",
                         "count": len(once), "linenos": once,
                         "why": "a `*` choice disappears once taken; a Parlance choice does "
                                "not, and reproducing it needs an author-added flag plus a "
                                "showIf — a variable the source never declared, so the "
                                "importer will not invent one"})

    # Bracket-less choices ECHO in Ink and do not in Parlance. `* Text` prints
    # "Text" into the story flow after selection — that is precisely why the
    # `[]` bracket form exists, to suppress it. Parlance's chooseChoice
    # "carries no player-facing strings" (tooling/RUNTIME_CONTRACT.md), so the
    # chosen text never becomes a story beat.
    #
    # The string check cannot see this: the text IS present in the project, as
    # choice.text, so nothing is missing and nothing is invented. What differs
    # is what the player reads. Reporting it is the only honest option —
    # duplicating each one as a narration node would put the same string in the
    # data twice and read as an importer artefact to a Parlance author.
    echoing = [it["lineno"] for c in containers for it in c["items"]
               if it["kind"] == "option" and it.get("echoes")]
    if echoing:
        unmapped.append({"node": None, "lineno": echoing[0],
                         "construct": "bracket-less choice (echoes in Ink)",
                         "count": len(echoing), "linenos": echoing,
                         "why": "in Ink a `* Text` choice prints its own text into the "
                                "story after selection; a Parlance choice does not echo. "
                                "The words are preserved as choice.text, so this is a "
                                "READING difference, not lost text — the player sees one "
                                "fewer beat per choice. Author decision: accept it, or "
                                "rewrite those choices in Ink's `front[choice-only]after` "
                                "form so the printed remainder becomes a real line"})

    # A divert that only fires when a condition holds. Reported rather than taken
    # unconditionally, which sent one branch of The Intercept off to a knot the
    # player had not earned.
    #
    # LINES only. An OPTION's guard is its own gate — `* {drugged} [Lie] -> knot`
    # is a choice with a `showIf` and a `goto`, and Parlance expresses both
    # exactly. Flagging those too declared 18 losses that were not losses, and
    # the report built on that number said Ink's conditional flow control was
    # three times the problem it actually is.
    for c in containers:
        for it in c["items"]:
            d = it.get("divert")
            if d and it.get("guard") and it["kind"] != "option" \
                    and d["kind"] != "terminal":
                unmapped.append({"node": c["title"], "lineno": it["lineno"],
                                 "construct": "-> %s" % d["target"],
                                 "why": WHY_COND_DIVERT})
                it["conditionalDivert"] = True

    def yields_nothing(c):
        return not any(it.get("text") and not it.get("unmappable") for it in c["items"])

    # To a fixpoint: declaring one container's lines can empty it, which turns a
    # divert into a dead end, which makes another container's tail terminal.
    while True:
        before = len(unmapped)
        empty = {c["title"] for c in containers if yields_nothing(c)}
        for c in containers:
            mark_structural_losses(c, unmapped, empty=empty)
        if len(unmapped) == before:
            break

    # --- tunnels -------------------------------------------------------------
    # `-> knot -> onward` is a call. Where every call site agrees on where the
    # return goes, it IS a plain goto: into the knot, and out of its `->->` to
    # that one place. Backward gotos are legal (the validator keeps hub cycles on
    # purpose), so nothing exotic is needed and nothing is declared.
    #
    # Only a knot called from places wanting DIFFERENT returns is loss, and even
    # then it is loss the author can fix by duplicating the scene — the format
    # allows that; this importer will not, because a copy puts their prose in
    # twice and the content check counts the second one as invented.
    tunnel_calls = {}
    for c in containers:
        for it in c["items"]:
            d = it.get("divert") or {}
            if d.get("kind") == "tunnel" and not it.get("conditionalDivert"):
                tunnel_calls.setdefault(d["target"], set()).add(d.get("onward"))
    tunnel_returns, ambiguous = {}, {}
    for target, onwards in tunnel_calls.items():
        if len(onwards) == 1:
            tunnel_returns[target] = next(iter(onwards))
        else:
            ambiguous[target] = sorted(o or "(its caller)" for o in onwards)

    for c in containers:
        for it in c["items"]:
            d = it.get("divert") or {}
            if d.get("kind") == "tunnel" and d["target"] in ambiguous:
                unmapped.append({"node": c["title"], "lineno": it["lineno"],
                                 "construct": "-> %s ->" % d["target"],
                                 "why": WHY_TUNNEL_AMBIGUOUS})
        if c["title"] in ambiguous:
            for it in c["items"]:
                if it.get("text") and not it.get("unmappable"):
                    it["unmappable"] = WHY_TUNNEL_AMBIGUOUS
                    it.pop("showIf", None)
                    unmapped.append({"node": c["title"], "lineno": it["lineno"],
                                     "construct": "tunnelled scene", "text": it["text"],
                                     "why": WHY_TUNNEL_AMBIGUOUS})

    orphans = sorted(t for t in (divert_targets | thread_targets)
                     if t and t not in titles and t not in TERMINAL)
    return {"titles": titles, "edges": edges, "orphan_targets": orphans,
            "variables": sorted(variables), "lists": sorted(lists_),
            "variableKinds": kinds, "tunnelReturns": tunnel_returns}


def units_of(parsed):
    for c in parsed["containers"]:
        for it in c["items"]:
            if it["kind"] in ("line", "option", "gather") and it.get("text"):
                yield c, it, ("option" if it["kind"] == "option" else "line")


# The stamp lives in manifest.py so that it is computed exactly as check.py
# verifies it. It was a copy here, a copy in the other parser and a third in
# check.py — three implementations of one function, which is how the trusted
# field list drifts apart.
_stamp = _manifest.stamp


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("source")
    ap.add_argument("--emit", choices=["ir", "manifest"], default="ir")
    a = ap.parse_args()
    # utf-8-sig, not utf-8: a BOM is invisible in an editor but makes the
    # first line unrecognisable to every line-anchored pattern here — a
    # BOM'd file parsed to a single node titled None before this.
    text = open(a.source, encoding="utf-8-sig").read()
    parsed = parse(text)
    info = analyse(parsed)

    if a.emit == "ir":
        print(json.dumps(_stamp({
            "source": a.source, "format": "ink",
            "fileTags": parsed["file_tags"],
            "containers": parsed["containers"],
            "declarations": parsed["declarations"],
            "edges": info["edges"],
            "orphanTargets": info["orphan_targets"],
            "variables": info["variables"],
            "variableKinds": info["variableKinds"],
            "tunnelReturns": info["tunnelReturns"],
            "unmapped": parsed["unmapped"],
        }), indent=2, ensure_ascii=False))
        return 0

    units = [{"kind": kind, "node": c["title"], "speaker": it["speaker"],
              "text": it["text"], "lineno": it["lineno"],
              **({"unmappable": it["unmappable"]} if it.get("unmappable") else {}),
              **({"showIf": it["showIf"]} if it.get("showIf") else {})}
             for c, it, kind in units_of(parsed)]
    man = {
        "source": a.source, "format": "ink", "units": units,
        "variables": info["variables"],
        "variableKinds": info["variableKinds"],
        "nodes": info["titles"],
        "unmapped": parsed["unmapped"],
        # Declared, auditable transformations. Ink's glue marker `<>` is a
        # rendering directive inside a player-facing line, so it is removed and
        # the removal is named here. Interpolation needs none: Ink writes {var}
        # and so does Parlance. Anything NOT listed here must survive the import
        # byte for byte.
        "rewrites": [["<>", ""]],
    }
    # Words in the source that appear in no unit, no declared-unmappable
    # construct and no recognised command. check.py refuses to converge while
    # this is non-empty: prose dropped BEFORE the manifest is written is
    # invisible to the manifest comparison, so it is caught here or not at all.
    man["residue"] = find_residue(text, man["units"], man["unmapped"], fmt="ink")
    print(json.dumps(_stamp(man), indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
