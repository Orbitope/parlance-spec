#!/usr/bin/env python3
"""
parse_yarn.py — deterministic Yarn Spinner parser.

Emits an intermediate representation for an importer to MAP from, and a
reconciliation manifest for check.py to verify against. The model never
transcribes prose: every string in the output of an import must have come from
here, byte for byte.

Supports the Yarn subset that carries story: node headers, speaker lines,
options (including nested/indented bodies), <<jump>>, <<set>>, <<if/elseif/
else/endif>>, and line tags. Anything it does not understand is preserved in
"unmapped" rather than dropped — a parser that silently skips a construct is
the same defect class as a model that invents one.

Usage:
    python3 parse_yarn.py story.yarn --emit ir        > ir.json
    python3 parse_yarn.py story.yarn --emit manifest  > manifest.json
"""
import argparse, json, os, re, sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from residue import find_residue
import conditions
import manifest as _manifest
import source as _source

CMD = re.compile(r"<<\s*(.*?)\s*>>")
OPTION = re.compile(r"^(\s*)->\s*(.*)$")
SPEAKER = re.compile(r"^([A-Za-z_][\w .'-]*?)\s*:\s*(.*)$")
TAG = re.compile(r"\s+(#[\w:.-]+)+\s*$")


def parse(text):
    nodes, cur, in_body = [], None, False
    for lineno, raw in enumerate(text.splitlines(), 1):
        line = raw.rstrip("\n")
        stripped = line.strip()

        if not in_body:
            if stripped == "---":
                in_body = True
                continue
            if ":" in stripped and cur is not None:
                k, v = stripped.split(":", 1)
                cur["headers"][k.strip()] = v.strip()
                continue
            if stripped and cur is None:
                cur = {"title": None, "headers": {}, "items": []}
                k, v = (stripped.split(":", 1) + [""])[:2]
                cur["headers"][k.strip()] = v.strip()
                continue
            continue

        if stripped == "===":
            if cur:
                cur["title"] = cur["headers"].get("title")
                nodes.append(cur)
            cur, in_body = None, False
            continue
        if cur is None:
            cur = {"title": None, "headers": {}, "items": []}
        if not stripped or stripped.startswith("//"):
            continue

        indent = len(line) - len(line.lstrip())
        cmds = CMD.findall(line)
        body = CMD.sub("", line).strip()
        tags = []
        m = TAG.search(body)
        if m:
            tags = m.group(0).split()
            body = TAG.sub("", body).strip()

        om = OPTION.match(line)
        if om:
            otext = CMD.sub("", om.group(2)).strip()
            otext = TAG.sub("", otext).strip()
            sp = SPEAKER.match(otext)
            cur["items"].append({
                "kind": "option", "lineno": lineno, "indent": indent,
                "speaker": sp.group(1) if sp else None,
                "text": sp.group(2) if sp else otext,
                "commands": cmds, "tags": tags,
            })
            continue

        if body:
            sp = SPEAKER.match(body)
            cur["items"].append({
                "kind": "line", "lineno": lineno, "indent": indent,
                "speaker": sp.group(1) if sp else None,
                "text": sp.group(2) if sp else body,
                "commands": cmds, "tags": tags,
            })
        elif cmds:
            cur["items"].append({
                "kind": "command", "lineno": lineno, "indent": indent,
                "speaker": None, "text": None, "commands": cmds, "tags": tags,
            })
    if cur and cur["items"]:
        cur["title"] = cur["headers"].get("title")
        nodes.append(cur)
    return nodes


KNOWN = ("jump", "set", "if", "elseif", "else", "endif", "declare", "stop")

ASSIGN = re.compile(r"^(?:set|declare)\s+\$(\w+)\s*(?:to|=|(\+=)|(-=))\s*(.+)$")
COMPARE = re.compile(r"\$(\w+)\s*(?:==|!=|>=|<=|>|<)\s*([^\s()&|]+)")

# Until the 0.15 contract three POSITIONS were declared loss here — a guarded
# line before a choice list, a guarded line as the conversation's last beat, and
# a choice list with no narration line to host it. All three are expressible
# now: `showIf` on a node with `choices` or `isEnd` hides only the line, and a
# node may carry choices with no `text` at all. The importer emits those shapes
# (see build_yarn_example.py), so nothing positional is declared any more.


def literal_kind(val):
    """The Parlance variable kind a Yarn right-hand side implies, if any."""
    v = val.strip()
    if v in ("true", "false"):
        return "flag"
    if re.match(r"^-?\d+$", v):
        return "counter"
    if re.match(r'^".*"$', v):
        return "text"
    return "unknown"


def infer_kinds(nodes):
    """flag / counter / text per variable, derived from what the story does with it.

    Only from evidence that admits one reading: an assignment of a literal, an
    increment, or a comparison against a literal. A bare `<<if $v>>` deliberately
    contributes NOTHING — a number is truthy in Yarn too, so reading it as a flag
    is a guess, and a guess here silently changes when a line appears. A variable
    left unknown makes its guards declared loss, which is the honest outcome.

    Conflicting evidence also resolves to unknown rather than to a majority: a
    variable the story treats as both is one this importer cannot register.
    """
    seen = {}
    for n in nodes:
        for it in n["items"]:
            for c in it["commands"]:
                m = ASSIGN.match(c.strip())
                if m:
                    name, plus, minus, val = m.group(1), m.group(2), m.group(3), m.group(4)
                    if plus or minus:
                        kind = "counter" if re.match(r"^-?\d+$", val.strip()) else "unknown"
                    else:
                        kind = literal_kind(val)
                        # `<<set $coins to $coins + 1>>` — arithmetic on itself is
                        # only meaningful for a number.
                        if kind == "unknown" and re.match(
                                r"^\$" + re.escape(name) + r"\s*[-+]\s*\d+$", val.strip()):
                            kind = "counter"
                    seen.setdefault(name, set()).add(kind)
                    continue
                head = c.split()[0] if c.split() else ""
                if head in ("if", "elseif"):
                    for name, lit in COMPARE.findall(c):
                        kind = literal_kind(lit)
                        if kind != "unknown":
                            seen.setdefault(name, set()).add(kind)
    out = {}
    for name, kinds in seen.items():
        determinate = kinds - {"unknown"}
        out[name] = determinate.pop() if len(determinate) == 1 else "unknown"
    return out


def head_of(command):
    parts = command.split()
    return parts[0] if parts else ""


def declare(node, item, why, unmapped, construct):
    if not item.get("text") or item.get("unmappable"):
        return
    item["unmappable"] = why
    item.pop("showIf", None)
    unmapped.append({"node": node["title"], "lineno": item["lineno"],
                     "command": construct, "text": item["text"], "why": why})


def analyse(nodes):
    """Collect variables and jumps, and mark what Yarn can express and Parlance cannot.

    Conditional narration is the case that used to dominate this function. Yarn
    guards any line with `<<if>>`, and until 0.11.0 Parlance had nowhere to put
    that, so every guarded line was declared loss. `DialogueNode.showIf` is that
    place, and a guard whose expression fits the Parlance condition vocabulary is
    now carried rather than reported.

    What is left is narrower and each case says which: a guard on a variable
    whose kind the source never reveals, a guard the condition vocabulary cannot
    express, and a guarded line that would have to host a choice list. Loss that
    is declared here is loss the author gets told about; that is the whole
    contract, and it did not change — only how much of it there is.
    """
    kinds = infer_kinds(nodes)
    variables, jumps, unmapped = set(kinds), [], []
    for n in nodes:
        stack = []
        for index, it in enumerate(n["items"]):
            heads = [c.split()[0] if c.split() else "" for c in it["commands"]]

            # Openers apply BEFORE this item's own text is judged and `endif`
            # applies after, so a line carrying its own guard —
            # `<<if $paid>>Keeper: Go on.<<endif>>` — is read as guarded. Reading
            # a depth counter instead missed those entirely and imported them as
            # unconditional narration: the silent-loss case this file exists to
            # prevent.
            for c in it["commands"]:
                head = c.split()[0] if c.split() else ""
                rest = c[len(head):].strip()
                if head == "if":
                    stack.append({"prior": [], "current": rest, "expr": rest})
                elif head == "elseif" and stack:
                    top = stack[-1]
                    if top["current"] is not None:
                        top["prior"].append(top["current"])
                    top["current"] = rest
                elif head == "else" and stack:
                    top = stack[-1]
                    if top["current"] is not None:
                        top["prior"].append(top["current"])
                    top["current"] = None

            if it["kind"] == "line" and stack:
                why, show_if = None, None
                parts, reasons = [], []
                for frame in stack:
                    cond, reason = frame_condition(frame, kinds)
                    if reason:
                        reasons.append(reason)
                    else:
                        parts.append(cond)
                if reasons:
                    why = reasons[0]
                else:
                    show_if = parts[0] if len(parts) == 1 else {"type": "all", "of": parts}
                if why:
                    it["unmappable"] = why
                    unmapped.append({"node": n["title"], "lineno": it["lineno"],
                                     "command": "if-guarded line", "text": it["text"],
                                     "why": why})
                else:
                    it["showIf"] = show_if

            if "endif" in heads and stack:
                stack.pop()

            for c in it["commands"]:
                head = c.split()[0] if c.split() else ""
                if head == "set" or head == "declare":
                    m = re.search(r"\$(\w+)", c)
                    if m:
                        variables.add(m.group(1))
                elif head == "jump":
                    jumps.append({"from": n["title"], "to": c.split()[-1],
                                  "lineno": it["lineno"]})
                elif head == "if" or head == "elseif":
                    for m in re.finditer(r"\$(\w+)", c):
                        variables.add(m.group(1))
                if head not in KNOWN and it["kind"] == "line":
                    # A custom command on its own line or on an option is
                    # carried as an `engine` effect (0.15) — the engine decides
                    # what `<<shake 0.5>>` means. One sitting INLINE on a
                    # narration line has no effect list to ride in the
                    # mapping, so it is still declared.
                    unmapped.append({"node": n["title"], "lineno": it["lineno"],
                                     "command": c,
                                     "why": "Yarn command inline on a narration line — carried "
                                            "as an engine effect only on its own line or an option"})
    # No structural pass any more: a guarded line may host a choice list or end
    # the conversation (the gate hides only its line), and a choice list with no
    # line to hang off gets a text-less node — all 0.15 shapes.
    return sorted(variables), jumps, unmapped, kinds


def frame_condition(frame, kinds):
    """One if/elseif/else frame as a Parlance condition, or the reason it is not.

    An `elseif` runs only when its own test holds and every earlier test in the
    chain did not; an `else` runs when none of them did. Yarn writes neither of
    those negations down, which is exactly why they are computed here rather
    than left to the importer to remember — a branch handed the same guard as
    its `if` shows both lines together whenever the guard holds, and nothing
    downstream can see that: no line is missing and none is invented.
    """
    negated = []
    for prior in frame["prior"]:
        cond, why = conditions.translate(prior, kinds)
        if why:
            return None, why
        negated.append(conditions.negate(cond))
    parts = list(negated)
    if frame["current"] is not None:
        cond, why = conditions.translate(frame["current"], kinds)
        if why:
            return None, why
        parts.insert(0, cond)
    if not parts:
        return None, conditions.WHY_UNPARSEABLE
    return (parts[0] if len(parts) == 1 else {"type": "all", "of": parts}), None


# The stamp lives in manifest.py so that it is computed exactly as check.py
# verifies it. It was a copy here, a copy in the other parser and a third in
# check.py — three implementations of one function, which is how the trusted
# field list drifts apart.
_stamp = _manifest.stamp


# `<<set $name to "…">>` / `<<declare $name = "…">>` — the quoted value is a
# string the source writes into a variable, which an importer carries as a
# `set_text` effect. Same shape the example builder maps (its SET pattern),
# so the manifest vouches for exactly the string the project will hold.
SET_STRING = re.compile(r'^(?:set|declare)\s+\$\w+\s*(?:to|=)\s*"(.*)"$', re.S)


def set_literals(nodes):
    """Every quoted string a set/declare command assigns, for the manifest."""
    out = []
    for n in nodes:
        for it in n["items"]:
            for cmd in it.get("commands") or []:
                m = SET_STRING.match(cmd.strip())
                if m:
                    out.append(m.group(1))
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("source")
    ap.add_argument("--emit", choices=["ir", "manifest"], default="ir")
    a = ap.parse_args()
    # utf-8-sig, not utf-8: a BOM is invisible in an editor but makes the
    # first line unrecognisable to every line-anchored pattern here — a
    # BOM'd file parsed to a single node titled None before this.
    text = _source.read_text(a.source)
    nodes = parse(text)
    variables, jumps, unmapped, kinds = analyse(nodes)

    if a.emit == "ir":
        print(json.dumps({"source": a.source, "format": "yarn", "nodes": nodes,
                          "variables": variables, "variableKinds": kinds,
                          "jumps": jumps,
                          "unmapped": unmapped}, indent=2, ensure_ascii=False))
        return 0

    units = [{"kind": it["kind"], "node": n["title"], "speaker": it["speaker"],
              "text": it["text"], "lineno": it["lineno"],
              **({"unmappable": it["unmappable"]} if it.get("unmappable") else {}),
              **({"showIf": it["showIf"]} if it.get("showIf") else {})}
             for n in nodes for it in n["items"]
             if it["kind"] in ("line", "option") and it["text"]]
    man = {
        "source": a.source, "format": "yarn", "units": units,
        "literals": _manifest.literals_of(extra=set_literals(nodes)),
        "variables": variables, "variableKinds": kinds,
        "nodes": [n["title"] for n in nodes],
        "unmapped": unmapped,
        # Declared, auditable transformations. Yarn interpolates {$var};
        # Parlance interpolates {var}. Anything NOT listed here must survive
        # the import byte for byte.
        "rewrites": [["{$", "{"]],
    }
    # Words in the source that appear in no unit, no declared-unmappable
    # construct, and no recognised command. check.py refuses to converge
    # while this is non-empty: prose dropped before the manifest is written
    # is invisible to the comparison, so it has to be caught here or not at all.
    man["residue"] = find_residue(text, man["units"], man["unmapped"], fmt="yarn")
    print(json.dumps(_stamp(man), indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
