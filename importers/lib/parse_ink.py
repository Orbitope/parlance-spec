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
from residue import find_residue
import manifest as _manifest

KNOT       = re.compile(r"^\s*={2,}\s*(function\s+)?([A-Za-z_]\w*)\s*(\([^)]*\))?\s*=*\s*$")
STITCH     = re.compile(r"^\s*=\s*(function\s+)?([A-Za-z_]\w*)\s*(\([^)]*\))?\s*$")
CHOICE     = re.compile(r"^\s*((?:[*+]\s*)+)(.*)$")
# NOT `-+` alone: `-> knot` also starts with a dash. The lookahead is what keeps
# a divert from being read as a gather.
GATHER     = re.compile(r"^\s*(-+)(?!>)\s*(.*)$")
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

TERMINAL = ("END", "DONE")

# Reasons, spelled once so the manifest and the report agree word for word.
WHY_COND_LINE = ("conditional narration: the line is guarded by a condition. Parlance "
                 "0.11.0 added DialogueNode.showIf, but this importer does not map "
                 "guards to it yet (see IMPORTERS.md)")
WHY_VAR_TEXT = ("variable text: an alternative/sequence/shuffle ({a|b}) has no Parlance "
                "equivalent — a node holds one authored string")
WHY_READ_COUNT = ("gated on a read count (how many times a knot has been visited); Parlance "
                  "has no read-count condition, and importing the choice ungated would "
                  "change when the player may take it")
WHY_LIST_COND = ("gated on a LIST value; Parlance variables are flags, counters and text "
                 "slots — there is no set-valued type to test")
WHY_ORPHAN_BODY = "body of a choice that is itself unmappable, so it can never be reached"
WHY_THREAD_ONLY = ("reachable only through a thread (<-), which weaves a second flow into "
                   "the current one; a Parlance dialogue has a single point of control")


def strip_comment(s):
    i = s.find("//")
    return s[:i] if i >= 0 else s


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
    m = TUNNEL.search(s)
    if m:
        return (s[: m.start()] + s[m.end():]).strip(), {"kind": "tunnel", "target": m.group(1)}
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


def prescan(lines):
    """Container and declaration names, needed before conditions can be classified.

    A `{bench > 1}` gate is a read count if `bench` is a knot and a variable test
    if it is a VAR, and the two map very differently — one to showIf, one to
    nothing at all. That distinction cannot be made in one pass.
    """
    containers, variables, consts, lists_ = [], set(), set(), set()
    knot = None
    for raw in lines:
        s = strip_comment(raw).strip()
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
            (variables if m.group(1) == "VAR" else consts).add(m.group(2))
            continue
        m = LISTDECL.match(s)
        if m:
            lists_.add(m.group(1))
    return containers, variables, consts, lists_


def classify_condition(cond, containers, variables, lists_):
    """Why a condition cannot be carried, or None if it can."""
    names = {n for n in IDENT.findall(cond)
             if n not in ("true", "false", "not", "and", "or", "has", "hasnt")}
    short = {c.split(".")[-1] for c in containers}
    for n in sorted(names):
        if n in lists_:
            return WHY_LIST_COND
        if n in variables:
            continue
        if n in containers or n in short:
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
    cond_block = None          # open multiline conditional { cond: ... }
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

        # ---- inside a multiline conditional block -------------------------
        if cond_block is not None:
            if s == "}":
                cond_block = None
                continue
            if re.match(r"^-\s*(else|otherwise)?\s*.*:\s*$", s):
                continue        # a branch header, not a gather
            body, tags = split_tags(s)
            body, div = take_divert(body)
            if body:
                sp, txt = split_speaker(body)
                add({"kind": "line", "lineno": lineno, "level": 0, "speaker": sp,
                     "text": txt, "tags": tags, "divert": div, "effects": [],
                     "condition": cond_block, "unmappable": WHY_COND_LINE})
                report(lineno, "conditional block line", WHY_COND_LINE, txt)
            continue

        # ---- file-level declarations --------------------------------------
        m = VARDECL.match(s)
        if m:
            kw, name, val = m.group(1), m.group(2), m.group(3).strip()
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
            add({"kind": "tunnel_return", "lineno": lineno, "level": 0, "speaker": None,
                 "text": None, "tags": [], "divert": None, "effects": []})
            report(lineno, s, "tunnel return (->->): control goes back to whichever knot "
                              "called in; a Parlance goto does not return")
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
                       "condition": gate, "echoes": b is None,
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
            level = len(m.group(1))
            body, tags = split_tags(m.group(2))
            body, div = take_divert(body)
            sp, txt = split_speaker(body) if body else (None, None)
            add({"kind": "gather", "lineno": lineno, "level": level, "speaker": sp,
                 "text": txt or None, "tags": tags, "divert": div, "effects": [],
                 "condition": None})
            continue

        # ---- standalone divert / tunnel ------------------------------------------
        if s.startswith("->"):
            body, tags = split_tags(s)
            _, div = take_divert(body)
            add({"kind": "divert", "lineno": lineno, "level": 0, "speaker": None,
                 "text": None, "tags": tags, "divert": div, "effects": []})
            if div and div["kind"] == "tunnel":
                report(lineno, s, "tunnel (-> knot ->): diverts and returns. Parlance goto "
                                  "does not return, so this is faithful only where the knot "
                                  "has a single call site and can be inlined")
            continue

        # ---- conditional block opener ---------------------------------------------
        if s.startswith("{") and not s.endswith("}"):
            cond_block = s[1:].rstrip(":").strip().rstrip(":")
            report(lineno, s, WHY_COND_LINE)
            continue

        # ---- ordinary content line --------------------------------------------------
        body, tags = split_tags(s)
        glue = "<>" in body
        if glue:
            body = body.replace("<>", " ").strip()
            report(lineno, "<>", "glue joins this line to its neighbour in one printed run; "
                                 "a Parlance node is a discrete beat, so the join is dropped "
                                 "and both lines survive as separate nodes", body)
        body, div = take_divert(body)
        unmappable, condition = None, None
        if body.startswith("{") and body.endswith("}") and body.count("{") == 1:
            inner = body[1:-1]
            if "|" in inner:
                unmappable = WHY_VAR_TEXT
                report(lineno, body, WHY_VAR_TEXT, body)
            elif ":" in inner:
                condition, rest = inner.split(":", 1)
                condition, body = condition.strip(), rest.strip()
                unmappable = WHY_COND_LINE
        elif re.search(r"\{[^{}]*\|[^{}]*\}", body):
            unmappable = WHY_VAR_TEXT
            report(lineno, body, WHY_VAR_TEXT, body)
        if body:
            sp, txt = split_speaker(body)
            it = {"kind": "line", "lineno": lineno, "level": 0, "speaker": sp, "text": txt,
                  "tags": tags, "divert": div, "effects": [], "condition": condition}
            if unmappable:
                it["unmappable"] = unmappable
                if unmappable == WHY_COND_LINE:
                    report(lineno, s, WHY_COND_LINE, txt)
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
                                              "lists": sorted(lists_)}}


def resolve(target, knot, titles):
    """A divert may name a knot, `knot.stitch`, or a bare stitch in the same knot."""
    if target in titles:
        return target
    if knot and f"{knot}.{target}" in titles:
        return f"{knot}.{target}"
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


def analyse(parsed):
    containers = parsed["containers"]
    titles = [c["title"] for c in containers]
    pre = parsed["prescan"]
    variables = set(pre["variables"])
    lists_ = set(pre["lists"])
    unmapped = parsed["unmapped"]

    divert_targets, thread_targets, edges = set(), set(), []
    for c in containers:
        weave(c)
        for it in c["items"]:
            d = it.get("divert")
            if not d:
                continue
            if d["kind"] == "thread":
                r = resolve(d["target"], c["knot"], titles)
                d["resolved"] = r
                thread_targets.add(r or d["target"])
                continue
            if d["kind"] == "terminal":
                d["resolved"] = None
                continue
            r = resolve(d["target"], c["knot"], titles)
            d["resolved"] = r
            divert_targets.add(r or d["target"])
            edges.append({"from": c["title"], "to": r or d["target"],
                          "kind": d["kind"], "lineno": it["lineno"]})

    # Conditions on choices: a variable test maps to showIf, a read count does not.
    for c in containers:
        for it in c["items"]:
            if it["kind"] == "option" and it.get("condition"):
                why = classify_condition(it["condition"], titles, variables, lists_)
                if why:
                    it["unmappable"] = why
                    unmapped.append({"node": c["title"], "lineno": it["lineno"],
                                     "construct": "{%s}" % it["condition"],
                                     "text": it["text"], "why": why})

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
    for c in containers:
        dead = set()
        for it in c["items"]:
            if it["kind"] == "option" and it.get("unmappable"):
                dead.add(it["index"])
            elif it.get("parent") in dead or it.get("printed_by") in dead:
                if it.get("text") and not it.get("unmappable"):
                    it["unmappable"] = WHY_ORPHAN_BODY
                    unmapped.append({"node": c["title"], "lineno": it["lineno"],
                                     "construct": "choice body", "text": it["text"],
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

    orphans = sorted(t for t in (divert_targets | thread_targets)
                     if t and t not in titles and t not in TERMINAL)
    return {"titles": titles, "edges": edges, "orphan_targets": orphans,
            "variables": sorted(variables), "lists": sorted(lists_)}


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
            "unmapped": parsed["unmapped"],
        }), indent=2, ensure_ascii=False))
        return 0

    units = [{"kind": kind, "node": c["title"], "speaker": it["speaker"],
              "text": it["text"], "lineno": it["lineno"],
              **({"unmappable": it["unmappable"]} if it.get("unmappable") else {})}
             for c, it, kind in units_of(parsed)]
    man = {
        "source": a.source, "format": "ink", "units": units,
        "variables": info["variables"],
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
