#!/usr/bin/env python3
"""
parse_arcweave.py — deterministic parser for an Arcweave JSON export.

Emits an intermediate representation for an importer to MAP from, and a
reconciliation manifest for check.py to verify against. The model never
transcribes prose: every string in the output of an import must have come from
here, byte for byte.

**The input is the project file Arcweave's "Export → JSON" writes**: one object
holding `boards`, `elements`, `connections`, `branches`, `conditions`,
`jumpers`, `components`, `attributes`, `variables`, `notes`, `assets` and
`startingElement`, each collection keyed by id. The shape here was
reconstructed from the published export format and the engine plugins that read
it; it is written to be strict about what it recognises and loud about the rest,
because a field it does not know about is exactly where prose goes missing.

What carries:

- an element's content paragraphs — one node per paragraph, never merged;
- a connection's label — a choice's text;
- a branch's `if` / `elseif` / `else` conditions behind a LABELLED connection —
  one gated choice per arm, each gated by its own test and the NEGATION of every
  arm above it (Arcweave writes neither negation down);
- a jumper — the element it points at;
- Arcscript in content: `x = true`, `x = "text"`, `x += 1`, `x -= 1` as effects,
  and `if`/`elseif`/`else`/`endif` around paragraphs as `node.showIf`;
- variables, with their declared types and defaults — Arcweave TYPES its
  variables, so unlike Yarn or Harlowe nothing about a kind is inferred;
- a component attached to an element as that element's speaker, when it is the
  only one attached.

What does not is named in "unmapped": a branch reached by an UNLABELLED
connection (the engine picks the route; a Parlance `next` names one node), any
Arcscript function (`visits()`, `random()`, `roll()`, `show()`, `reset()` …),
arithmetic, component attributes, board notes, assets, and inline formatting.

HTML IS MARKUP, NOT PROSE. Element content and labels are HTML, and a unit's
text is the concatenation of the text between the tags, entities decoded —
every character of it a character of the source, in order, nothing added. The
same accounting the Twine parser applies to a styling macro: the markup is
declared, the words stay required.

THE RESIDUE TEXT IS A PROJECTION. A JSON export has no lines worth reporting
against (an element's whole content is one line of the file), so residue is
computed over the export's string leaves, one per line, in document order, and
a unit's `lineno` is its leaf's position there — `path` names the leaf. Every
leaf is in the projection; a leaf this parser does not recognise is residue,
which is the point.

Usage:
    python3 parse_arcweave.py project.json --emit ir        > ir.json
    python3 parse_arcweave.py project.json --emit manifest  > manifest.json
"""
import argparse, html, json, os, re, sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from residue import find_residue
import conditions
import manifest as _manifest

WHY_AUTO_ROUTE = (
    "a branch reached by an UNLABELLED connection — the engine evaluates the "
    "conditions and follows one route without the player choosing. A Parlance "
    "`next` and `goto` name one node; `showIf` gates whether a node or choice is "
    "shown, not where the conversation goes. Labelling the connection into the "
    "branch makes it importable, as one gated choice per arm")
WHY_UNLABELLED_BESIDE = (
    "an unlabelled connection beside labelled ones — Arcweave offers it as a bare "
    "option, and a Parlance choice needs text. Nothing is invented to fill it")
WHY_TWO_LABELS = (
    "a labelled connection into a branch whose arm is ALSO labelled — two texts for "
    "one choice, and picking either would drop the other")
WHY_FUNCTION = (
    "an Arcscript function (`visits()`, `random()`, `roll()`, `show()`, `reset()`, "
    "`abs()` …). The Parlance effect and condition vocabularies are closed and "
    "call nothing; a visit count in particular has no equivalent")
WHY_ARITH = (
    "an assignment computed from an expression. Parlance effects write literals "
    "(`set_flag`, `set_text`) or add a literal delta (`adjust_counter`)")
WHY_ABS_COUNTER = (
    "an absolute assignment to a number (`x = 3`). The effect vocabulary has "
    "`adjust_counter` with a delta and no absolute set, which would need the value "
    "at this point in the story")
WHY_FLOAT = ("a float variable — a Parlance counter is an integer, and rounding the "
             "author's value would be a rewrite")
WHY_STATEMENT = "an Arcscript statement this parser does not map"
WHY_UNHOSTED = (
    "an effect inside a conditional with no paragraph after it in the same branch to "
    "carry it — a Parlance effect rides on a node, and moving it would change when "
    "it fires")
WHY_ATTRIBUTE = (
    "a component attribute — per-entity data with no Parlance field to hold it "
    "verbatim. The text is here so the author can see what was not carried")
WHY_NOTE = "a board note — an author's annotation on the canvas, not attached to any line"
WHY_ASSET = "an asset (image, audio, cover) — media, not data"
WHY_FORMAT = ("inline formatting or a mention link (`<em>`, `<strong>`, a component "
              "mention). Parlance text is plain; the words are carried, the markup is not")
WHY_COND_NO_ARMS = "a branch with no conditions to follow"
WHY_NO_TARGET = "a connection whose target this export does not define"
WHY_SPEAKERS = ("several components attached to one element — which of them speaks is "
                "not in the data, so the lines are carried as narration")

KIND_OF_TYPE = {"boolean": "flag", "integer": "counter", "string": "text"}
BLOCK_TAGS = ("p", "h1", "h2", "h3", "h4", "h5", "h6", "li", "blockquote", "div")
TAG = re.compile(r"<(/?)([A-Za-z][\w-]*)([^<>]*)>")
IDENT = r"[A-Za-z_]\w*"
ASSIGN = re.compile(r"^(" + IDENT + r")\s*(=|\+=|-=|\*=|/=)\s*(.+)$")
CALL = re.compile(r"\b" + IDENT + r"\s*\(")

# Keys whose string values are structure, never prose: enum-like settings and
# references. Every other leaf must be accounted for by a unit, a declared loss,
# or something the parser recognised.
STRUCTURAL_KEYS = ("theme", "type", "sourceType", "targetType", "cType", "color",
                   "mediaType")


# --- the projection ---------------------------------------------------------

def leaves(obj, path=()):
    """Every string leaf, in document order, with its path."""
    if isinstance(obj, dict):
        for k, v in obj.items():
            yield from leaves(v, path + (k,))
    elif isinstance(obj, list):
        for i, v in enumerate(obj):
            yield from leaves(v, path + (i,))
    elif isinstance(obj, str):
        yield path, obj


def projection(data):
    """(text, {path: lineno}) — one string leaf per line.

    A newline inside a leaf (Arcscript code holds several statements) is kept
    as a space: the leaf is one line of the projection, as it is one field of
    the export.
    """
    lines, where = [], {}
    for path, value in leaves(data):
        lines.append(value.replace("\r", " ").replace("\n", " "))
        where[path] = len(lines)
    return "\n".join(lines) + "\n", where


# --- HTML --------------------------------------------------------------------

CODE_BLOCK = re.compile(r"<pre\b[^>]*>(.*?)</pre>", re.S | re.I)


def html_blocks(s):
    """Content HTML as ordered blocks: ("text", str, [inline tags]) or ("code", str).

    `<pre>` is Arcscript. Outside it, a paragraph-level element is one block and
    `<br>` splits a paragraph in two (one line, one node — never merged). Inline
    tags are dropped from the text and returned, so the caller can declare them.
    """
    out, pos = [], 0
    for m in CODE_BLOCK.finditer(s or ""):
        out += text_blocks(s[pos:m.start()])
        inner = re.sub(r"<br\s*/?>", "\n", m.group(1), flags=re.I)
        inner = re.sub(r"</p>\s*<p\b[^>]*>", "\n", inner, flags=re.I)
        out.append(("code", html.unescape(re.sub(r"<[^<>]*>", "", inner))))
        pos = m.end()
    out += text_blocks((s or "")[pos:])
    return out


def text_blocks(s):
    out, buf, tags, pos = [], [], [], 0

    def flush():
        text = "".join(buf).strip()
        if text:
            out.append(("text", text, list(dict.fromkeys(tags))))
        buf.clear()
        tags.clear()

    for m in TAG.finditer(s):
        buf.append(html.unescape(s[pos:m.start()]))
        pos = m.end()
        closing, name, attrs = m.group(1), m.group(2).lower(), m.group(3)
        if name in BLOCK_TAGS or name == "br":
            flush()
        elif not closing:
            tags.append("<" + name + (" mention" if "mention" in attrs else "") + ">")
    buf.append(html.unescape(s[pos:]))
    flush()
    return out


def plain(s):
    """A label's text: the text between its tags, entities decoded, trimmed."""
    parts = [b[1] for b in html_blocks(s) if b[0] == "text"]
    return " ".join(parts) if parts else None


def code_of(script):
    """A condition's script: the Arcscript inside its code block, or the bare string."""
    if script is None:
        return None
    blocks = html_blocks(script)
    code = [b[1] for b in blocks if b[0] == "code"]
    if code:
        return "\n".join(code).strip()
    return html.unescape(re.sub(r"<[^<>]*>", "", script)).strip()


# --- the parser ----------------------------------------------------------------

class Parser:
    def __init__(self, data):
        self.d = data
        self.text, self.where = projection(data)
        self.unmapped, self.accounted, self.units = [], [], []
        self.all_ids = set()
        for coll in data.values():
            if isinstance(coll, dict):
                self.all_ids.update(k for k in coll if isinstance(k, str))
        self.kinds, self.defaults, self.var_names = {}, {}, {}
        self.characters = {}
        self.frame_seq = 0

    def line(self, *path):
        return self.where.get(tuple(path))

    def account(self, path, text):
        n = self.where.get(tuple(path))
        if n and text:
            self.accounted.append((n, text))

    def declare(self, path, why, construct, text=None, node=None):
        entry = {"node": node, "lineno": self.where.get(tuple(path)),
                 "path": "/".join(map(str, path)), "construct": construct, "why": why}
        if text:
            entry["text"] = text
        self.unmapped.append(entry)

    # -- structure every leaf the parser understands without mapping ------------
    def account_structure(self):
        for path, value in leaves(self.d):
            key = next((p for p in reversed(path) if isinstance(p, str)), None)
            if value in self.all_ids or key in STRUCTURAL_KEYS:
                self.account(path, value)

    def variables(self):
        for vid, v in (self.d.get("variables") or {}).items():
            if not isinstance(v, dict):
                continue
            name = v.get("name")
            self.account(("variables", vid, "name"), name)
            if v.get("children") is not None or v.get("root"):
                continue            # a folder
            kind = KIND_OF_TYPE.get(v.get("type"))
            if v.get("type") == "float":
                self.declare(("variables", vid, "name"), WHY_FLOAT, f"variable {name}")
                kind = "unknown"
            self.kinds[name] = kind or "unknown"
            self.var_names[vid] = name
            if kind and "value" in v:
                self.defaults[name] = v["value"]
                if isinstance(v["value"], str):
                    self.account(("variables", vid, "value"), v["value"])

    def components(self):
        for cid, c in (self.d.get("components") or {}).items():
            if not isinstance(c, dict):
                continue
            self.account(("components", cid, "name"), c.get("name"))
            self.assets(("components", cid), c.get("assets"))
        for aid, a in (self.d.get("attributes") or {}).items():
            if not isinstance(a, dict):
                continue
            val = a.get("value") or {}
            data = val.get("data")
            text = plain(data) if isinstance(data, str) else None
            self.account(("attributes", aid, "name"), a.get("name"))
            where = ("attributes", aid, "value", "data") if isinstance(data, str) else (
                "attributes", aid, "name")
            self.declare(where, WHY_ATTRIBUTE, f"attribute {a.get('name')}", text)

    def assets(self, path, assets):
        for path2, value in leaves(assets or {}, tuple(path) + ("assets",)):
            if value not in self.all_ids:
                self.declare(path2, WHY_ASSET, value)

    def notes(self):
        for nid, n in (self.d.get("notes") or {}).items():
            if isinstance(n, dict) and isinstance(n.get("content"), str):
                self.declare(("notes", nid, "content"), WHY_NOTE, "note",
                             plain(n["content"]))

    def boards(self):
        for bid, b in (self.d.get("boards") or {}).items():
            if isinstance(b, dict):
                self.account(("boards", bid, "name"), b.get("name"))

    # -- Arcscript -------------------------------------------------------------
    def translate(self, expr):
        expr = re.sub(r"\bis\s+not\b", "!=", expr)
        return conditions.translate(expr, self.kinds)

    def statement(self, stmt, path, element):
        """One Arcscript statement: ("if"|"elseif"|"else"|"endif", expr) or an effect."""
        s = stmt.strip()
        head = s.split()[0] if s.split() else ""
        if head in ("if", "elseif"):
            return (head, s[len(head):].strip()), None
        if s in ("else", "endif"):
            return (s, None), None
        am = ASSIGN.match(s)
        if am and not CALL.search(s):
            name, op, val = am.groups()
            kind, ident = self.kinds.get(name), conditions.var_id(name)
            val = val.strip()
            if not ident or kind not in ("flag", "counter", "text"):
                return None, (conditions.WHY_UNKNOWN_VAR if ident else conditions.WHY_BAD_ID)
            if kind == "flag" and op == "=" and val in ("true", "false"):
                return {"type": "set_flag", "flag": ident, "value": val == "true"}, None
            if kind == "text" and op == "=" and re.match(r'^"[^"]*"$|^\'[^\']*\'$', val):
                return {"type": "set_text", "variable": ident, "value": val[1:-1]}, None
            if kind == "counter" and op in ("+=", "-=") and re.match(r"^\d+$", val):
                n = int(val)
                return {"type": "adjust_counter", "counter": ident,
                        "delta": n if op == "+=" else -n}, None
            if kind == "counter" and op == "=" and re.match(r"^-?\d+$", val):
                return None, WHY_ABS_COUNTER
            return None, WHY_ARITH
        if CALL.search(s):
            return None, WHY_FUNCTION
        return None, WHY_STATEMENT

    def guard_of(self, stack):
        parts = []
        for frame in stack:
            for expr, invert in ([(p, True) for p in frame["prior"]] +
                                 ([(frame["current"], False)]
                                  if frame["current"] is not None else [])):
                cond, why = self.translate(expr)
                if why:
                    return None, why
                parts.append(conditions.negate(cond) if invert else cond)
        if not parts:
            return None, None
        return (parts[0] if len(parts) == 1 else {"type": "all", "of": parts}), None

    # -- elements ----------------------------------------------------------------
    def element(self, eid, e):
        path = ("elements", eid, "content")
        title = plain(e.get("title")) if isinstance(e.get("title"), str) else None
        # A title names the element on the canvas; the importer uses it for ids,
        # as the Twine importer uses a passage name. It is not displayed.
        self.account(("elements", eid, "title"), title)
        self.assets(("elements", eid), e.get("assets"))
        comps = [c for c in (e.get("components") or []) if c in (self.d.get("components") or {})]
        speaker = None
        if len(comps) == 1:
            speaker = comps[0]
            name = self.d["components"][speaker].get("name")
            self.characters[speaker] = name
        elif len(comps) > 1:
            self.declare(("elements", eid, "components"), WHY_SPEAKERS,
                         f"{len(comps)} components")
        items, stack, pending = [], [], []
        content = e.get("content") if isinstance(e.get("content"), str) else ""
        formatted = []
        for block in html_blocks(content):
            if block[0] == "code":
                for stmt in re.split(r"\n", block[1]):
                    if not stmt.strip():
                        continue
                    res, why = self.statement(stmt, path, eid)
                    if why:
                        self.declare(path, why, stmt.strip(), node=eid)
                        continue
                    self.account(path, stmt)
                    if isinstance(res, tuple):
                        head, expr = res
                        if head == "if":
                            self.frame_seq += 1
                            stack.append({"id": self.frame_seq, "prior": [],
                                          "current": expr})
                        elif head in ("elseif", "else") and stack:
                            top = stack[-1]
                            if top["current"] is not None:
                                top["prior"].append(top["current"])
                            top["current"] = expr
                            self.frame_seq += 1
                            top["id"] = self.frame_seq
                        elif head == "endif" and stack:
                            stack.pop()
                        continue
                    pending.append({"effect": res,
                                    "guard": tuple(f["id"] for f in stack)})
                continue
            text, tags = block[1], block[2]
            formatted += tags
            gkey = tuple(f["id"] for f in stack)
            item = {"kind": "line", "lineno": self.line(*path), "path": "/".join(path),
                    "speaker": speaker, "text": text, "effects": [], "guard": gkey}
            cond, why = self.guard_of(stack)
            if why:
                item["unmappable"] = why
                self.declare(path, why, "if", text, node=eid)
            elif cond:
                item["showIf"] = cond
            # Effects ride on the next paragraph in the SAME guard; anything
            # else would change when they fire.
            if pending and not item.get("unmappable") and all(
                    p["guard"] == gkey for p in pending):
                item["effects"] = [p["effect"] for p in pending]
                pending = []
            elif pending and any(p["guard"] for p in pending):
                for p in pending:
                    self.declare(path, WHY_UNHOSTED, p["effect"]["type"], node=eid)
                pending = []
            items.append(item)
        # Unguarded effects left at the end fire on entering the element in
        # Arcweave, before its outputs are offered; they ride on the element's
        # last node. Guarded ones have nothing in their branch to ride on.
        trailing = []
        for p in pending:
            if p["guard"]:
                self.declare(path, WHY_UNHOSTED, p["effect"]["type"], node=eid)
            else:
                trailing.append(p["effect"])
        for t in dict.fromkeys(formatted):
            self.declare(path, WHY_FORMAT, t, node=eid)
        return {"id": eid, "title": title, "speaker": speaker, "items": items,
                "trailingEffects": trailing, "routes": []}

    # -- connections, branches, jumpers ------------------------------------------
    def conn_label(self, cid):
        c = (self.d.get("connections") or {}).get(cid) or {}
        lab = c.get("label")
        return plain(lab) if isinstance(lab, str) else None

    def expand(self, cid, label, label_path, arms, seen=()):
        """The routes one connection leads to, through branches and jumpers.

        A route is (label, where the label came from, arm conditions, target
        element or None, why it cannot be carried or None).
        """
        conns = self.d.get("connections") or {}
        c = conns.get(cid)
        if not isinstance(c, dict) or cid in seen:
            return [{"label": label, "labelPath": label_path, "arms": arms,
                     "target": None, "why": WHY_NO_TARGET}]
        seen = seen + (cid,)
        mine = self.conn_label(cid)
        if mine:
            self.account(("connections", cid, "label"), mine)
            if label:
                return [{"label": label, "labelPath": label_path, "arms": arms,
                         "target": None, "why": WHY_TWO_LABELS,
                         "extraLabel": (mine, ("connections", cid, "label"))}]
            label, label_path = mine, ("connections", cid, "label")
        tt, tid = c.get("targetType"), c.get("targetid")
        if tt == "jumpers":
            j = (self.d.get("jumpers") or {}).get(tid) or {}
            tt, tid = "elements", j.get("elementId")
        if tt == "elements" and tid in (self.d.get("elements") or {}):
            return [{"label": label, "labelPath": label_path, "arms": arms,
                     "target": tid, "why": None}]
        if tt == "branches":
            b = (self.d.get("branches") or {}).get(tid) or {}
            spec = b.get("conditions") or {}
            order = ([spec.get("ifCondition")] + list(spec.get("elseIfConditions") or [])
                     + [spec.get("elseCondition")])
            order = [x for x in order if x]
            if not order:
                return [{"label": label, "labelPath": label_path, "arms": arms,
                         "target": None, "why": WHY_COND_NO_ARMS}]
            out, prior = [], []
            for cond_id in order:
                cd = (self.d.get("conditions") or {}).get(cond_id) or {}
                script = code_of(cd.get("script"))
                if script:
                    self.account(("conditions", cond_id, "script"), script)
                arm = {"prior": list(prior), "current": script or None}
                if script:
                    prior.append(script)
                if cd.get("output"):
                    out += self.expand(cd["output"], label, label_path, arms + [arm], seen)
            return out
        return [{"label": label, "labelPath": label_path, "arms": arms,
                 "target": None, "why": WHY_NO_TARGET}]

    def routes(self, el, e):
        routes = []
        for cid in e.get("outputs") or []:
            for r in self.expand(cid, None, None, []):
                r["conn"] = cid
                routes.append(r)
        out = []
        for r in routes:
            cond, why = (None, r["why"])
            if not why and r["arms"]:
                cond, why = self.guard_of(r["arms"])
            if not r["label"]:
                if len(routes) == 1 and not r["arms"] and not why:
                    out.append({"kind": "next", "target": r["target"]})
                    continue
                # The structural reason leads: an unlabelled route through a
                # branch could not be carried even if its test translated.
                if r["arms"]:
                    why = WHY_AUTO_ROUTE
                why = why or WHY_UNLABELLED_BESIDE
                self.declare(("connections", r["conn"], "targetid"), why,
                             f"connection {r['conn']}", node=el["id"])
                continue
            opt = {"kind": "option", "text": r["label"], "target": r["target"],
                   "lineno": self.line(*r["labelPath"]),
                   "path": "/".join(map(str, r["labelPath"])),
                   "speaker": None}
            if why:
                opt["unmappable"] = why
                self.declare(r["labelPath"], why, "connection", r["label"], node=el["id"])
                if r.get("extraLabel"):
                    self.declare(r["extraLabel"][1], why, "connection",
                                 r["extraLabel"][0], node=el["id"])
            elif cond:
                opt["showIf"] = cond
            out.append(opt)
        return out

    def run(self):
        self.account_structure()
        self.account(("name",), self.d.get("name"))
        self.boards()
        self.variables()
        self.components()
        self.notes()
        for aid, a in (self.d.get("assets") or {}).items():
            if isinstance(a, dict):
                for path, value in leaves(a, ("assets", aid)):
                    if value not in self.all_ids:
                        self.declare(path, WHY_ASSET, value)
        self.elements = []
        for eid, e in (self.d.get("elements") or {}).items():
            if not isinstance(e, dict):
                continue
            el = self.element(eid, e)
            el["routes"] = self.routes(el, e)
            carried = [i for i in el["items"] if not i.get("unmappable")]
            options = [r for r in el["routes"] if r["kind"] == "option"
                       and not r.get("unmappable")]
            if el["trailingEffects"] and not carried and not options:
                # No line and no choice: nothing in the element can carry them.
                for eff in el["trailingEffects"]:
                    self.declare(("elements", eid, "content"), WHY_UNHOSTED,
                                 eff["type"], node=eid)
                el["trailingEffects"] = []
            self.elements.append(el)
        return self


def units_of(p):
    out = []
    for el in p.elements:
        for it in el["items"]:
            out.append((el["id"], it))
        for r in el["routes"]:
            if r["kind"] == "option":
                out.append((el["id"], r))
    return out


_stamp = _manifest.stamp


def parse_file(path):
    data = json.load(open(path, encoding="utf-8-sig"))
    return Parser(data).run()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("source")
    ap.add_argument("--emit", choices=["ir", "manifest"], default="ir")
    a = ap.parse_args()
    p = parse_file(a.source)

    if a.emit == "ir":
        print(json.dumps({"source": a.source, "format": "arcweave",
                          "name": p.d.get("name"),
                          "start": p.d.get("startingElement"),
                          "elements": p.elements,
                          "characters": p.characters,
                          "variables": sorted(p.kinds), "variableKinds": p.kinds,
                          "defaults": p.defaults,
                          "unmapped": p.unmapped}, indent=2, ensure_ascii=False))
        return 0

    units = [{"kind": it["kind"], "node": owner, "speaker": it.get("speaker"),
              "text": it["text"], "lineno": it["lineno"], "path": it["path"],
              **({"unmappable": it["unmappable"]} if it.get("unmappable") else {}),
              **({"showIf": it["showIf"]} if it.get("showIf") else {})}
             for owner, it in units_of(p) if it.get("text")]
    man = {
        "source": a.source, "format": "arcweave", "units": units,
        "variables": sorted(p.kinds), "variableKinds": p.kinds,
        "nodes": [el["id"] for el in p.elements],
        "unmapped": p.unmapped,
        # No rewrites: Arcweave has no interpolation syntax to translate, and
        # the markup is removed when the unit is read, not after.
        "rewrites": [],
    }
    man["residue"] = find_residue(p.text, man["units"], man["unmapped"],
                                  p.accounted, fmt="arcweave")
    print(json.dumps(_stamp(man), indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
