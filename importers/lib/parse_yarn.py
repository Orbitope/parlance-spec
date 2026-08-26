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
import manifest as _manifest

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


def analyse(nodes):
    """Collect variables and jumps, and mark what Yarn can express and Parlance cannot.

    The important case is a CONDITIONAL NARRATION LINE. Yarn guards any line with
    <<if>>. A faithful target now EXISTS — `DialogueNode.showIf`, added in 0.11.0 —
    but this importer does not map guards onto it yet, and marking these mappable
    before it can do so safely would be worse than the loss. The blocker is the
    else-branch negation in IMPORTERS.md: an `else` written without restating its
    condition, mapped to the same guard as its `if`, shows both lines together
    whenever the guard holds. Nothing is lost and nothing is invented, so no
    content check can see it.

    Until that lands, a guarded line stays declared loss: reported to the author,
    never silently dropped, and never wrapped in a choice — which would fabricate
    a decision the player never made. Loss that is declared here is loss the
    author gets told about; that is the whole contract.
    """
    variables, jumps, unmapped = set(), [], []
    for n in nodes:
        depth = 0
        for it in n["items"]:
            heads = [c.split()[0] if c.split() else "" for c in it["commands"]]
            # A line can carry its own guard: `<<if $paid>>Keeper: Go on.<<endif>>`
            # is one `line` item whose commands include `if`, and the enclosing
            # depth is still 0 when it is tested. Reading depth alone therefore
            # missed inline guards entirely and imported them as unconditional
            # narration — the silent-loss case this whole file exists to prevent.
            # An `endif` that leaves prose after it on the same line is counted
            # guarded too: over-reporting is a declared loss the author reads,
            # under-reporting is a guard that vanishes without trace.
            own_guard = any(h in ("if", "elseif", "else") for h in heads)
            if it["kind"] == "line" and (depth > 0 or own_guard):
                it["unmappable"] = ("conditional narration: guarded by <<if>>. Parlance "
                                    "0.11.0 added DialogueNode.showIf, but this importer "
                                    "does not map guards to it yet (see IMPORTERS.md)")
                unmapped.append({"node": n["title"], "lineno": it["lineno"],
                                 "command": "if-guarded line", "text": it["text"],
                                 "why": it["unmappable"]})
            if "if" in heads:
                depth += 1
            if "endif" in heads:
                depth = max(0, depth - 1)
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
                if head not in KNOWN:
                    unmapped.append({"node": n["title"], "lineno": it["lineno"],
                                     "command": c,
                                     "why": "Yarn command with no Parlance equivalent"})
    return sorted(variables), jumps, unmapped


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
    nodes = parse(text)
    variables, jumps, unmapped = analyse(nodes)

    if a.emit == "ir":
        print(json.dumps({"source": a.source, "format": "yarn", "nodes": nodes,
                          "variables": variables, "jumps": jumps,
                          "unmapped": unmapped}, indent=2, ensure_ascii=False))
        return 0

    units = [{"kind": it["kind"], "node": n["title"], "speaker": it["speaker"],
              "text": it["text"], "lineno": it["lineno"],
              **({"unmappable": it["unmappable"]} if it.get("unmappable") else {})}
             for n in nodes for it in n["items"]
             if it["kind"] in ("line", "option") and it["text"]]
    man = {
        "source": a.source, "format": "yarn", "units": units,
        "variables": variables, "nodes": [n["title"] for n in nodes],
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
