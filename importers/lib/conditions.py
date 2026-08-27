"""
conditions.py — source guard expressions to Parlance conditions.

Yarn writes `<<if $paid and $coins >= 2>>`, Ink writes `{paid && coins >= 2:}`.
Both are guarding a line, and since 0.11.0 Parlance has somewhere to put that:
`DialogueNode.showIf`. This module is the translation, and it lives in one file
because both parsers need it to agree — a guard that maps one way in Yarn and
another in Ink would make the two importers disagree about the same story.

Two things it is deliberately strict about.

**It refuses more than it approximates.** Parlance's condition vocabulary is
closed (flag, counter, reputation, relationship, skill, item, quest,
questOutcome, composed with all/any/not). A guard it cannot express exactly
returns a REASON, and the caller declares the loss. Widening a guard — dropping
a conjunct that will not map, say — shows the player a line the author gated,
and no content check can see it: nothing is missing and nothing is invented.

**Negation is exact, not restated.** `negate()` exists because an `else` branch
in both formats is written without repeating its condition. Handing the else
branch the same guard as its `if` shows both lines together whenever the guard
holds. That is the single most dangerous defect this module can produce, for the
same reason: string accounting is blind to it.

There is no text-valued condition in the vocabulary, so a test against a text
variable cannot be carried at all. That is a fact about the format, not a gap
here.
"""
import re

# --- what the caller gets back when a guard will not map ---------------------
# Spelled once so the manifest, the report and the tests agree word for word.
WHY_UNKNOWN_VAR = ("gated on a name the source never declares, so its Parlance kind "
                   "(flag / counter / text) cannot be derived and the test has no "
                   "condition type to become")
WHY_TEXT_VAR = ("gated on a text variable; the Parlance condition vocabulary tests flags, "
                "counters, reputation, relationships, skills, items and quests — there is "
                "no comparison against a text slot")
WHY_VAR_TO_VAR = ("gated on a comparison between two variables; a Parlance condition "
                  "compares one registered variable against a literal")
WHY_ARITHMETIC = ("gated on an arithmetic expression; the Parlance condition vocabulary "
                  "has no expression language, only a variable, an operator and a literal")
WHY_UNPARSEABLE = ("the guard expression is outside the boolean subset this importer "
                   "translates (variable tests, comparisons against literals, and "
                   "and/or/not over them)")
WHY_BAD_ID = ("the variable's name does not reduce to a Parlance id (lowercase, starting "
              "with a letter), and renaming it would be inventing an id the source "
              "never gave")
WHY_FUNCTION_CALL = (
    "gated on a function call — `visited(...)`, `hasMessage(...)`, or a custom one. A "
    "Parlance condition compares registered state against a literal and calls nothing, "
    "and a visit test in particular has no equivalent: there is no read-count condition")

ID_RE = re.compile(r"^[a-z][a-z0-9_]*$")


def var_id(name):
    """The Parlance id for a source variable name, or None if there is not one.

    Lowercasing and nothing else. `parse_ink.py` already derived registry ids
    this way, and the id in a condition has to be the same string as the id in
    `variables.json` or the import produces a dangling reference — so the
    derivation is shared rather than written twice. Anything cleverer (camelCase
    to snake_case) would be inventing a name the source never used, which is the
    one thing the importers do not do.
    """
    ident = (name or "").lower()
    return ident if ID_RE.match(ident) else None


# --- tokenizer ---------------------------------------------------------------

# Arithmetic operators are tokenized rather than rejected as unknown characters,
# so that `coins > base + 1` can be declined with the reason that actually
# applies instead of the catch-all. Numbers are unsigned here and a leading `-`
# is read where an operand is expected — otherwise `x > -1` and `x - 1` would
# have to be told apart by the tokenizer, which cannot see which one it is in.
TOKEN = re.compile(r"""
      \s+
    | (?P<op>==|!=|>=|<=|&&|\|\||[<>()!+*/-])
    | (?P<num>\d+)
    | (?P<str>"[^"\n]*")
    | (?P<ident>\$?[A-Za-z_]\w*)
""", re.X)

ARITH = ("+", "-", "*", "/")

# Yarn Spinner spells its operators as words as well as symbols, and `is` for
# equality is the one that actually turns up in real scripts.
WORD_OPS = {"and": "&&", "or": "||", "not": "!",
            "is": "==", "eq": "==", "neq": "!=",
            "gt": ">", "lt": "<", "gte": ">=", "lte": "<="}

# `and (`, `not (` and friends are grouping, not calls. Everything else that puts
# an identifier straight before a `(` is a call.
CALL = re.compile(r"\b(?!(?:" + "|".join(WORD_OPS) + r")\b)[A-Za-z_]\w*\s*\(")


def _tokens(expr):
    """Tokens, or None if the expression contains something unrecognised.

    Returning None rather than skipping is the point: a character this does not
    understand may be an operator that changes the meaning of the guard, and a
    guard translated from a partial reading is worse than one declared as loss.
    """
    out, i = [], 0
    while i < len(expr):
        m = TOKEN.match(expr, i)
        if not m or m.end() == i:
            return None
        i = m.end()
        if m.group("op"):
            out.append(("op", m.group("op")))
        elif m.group("num"):
            out.append(("num", int(m.group("num"))))
        elif m.group("str"):
            out.append(("str", m.group("str")[1:-1]))
        elif m.group("ident"):
            raw = m.group("ident").lstrip("$")
            low = raw.lower()
            if low in WORD_OPS:
                out.append(("op", WORD_OPS[low]))
            elif low in ("true", "false"):
                out.append(("bool", low == "true"))
            else:
                out.append(("ident", raw))
    return out


class _Fail(Exception):
    def __init__(self, why):
        super().__init__(why)
        self.why = why


# --- recursive descent over the boolean subset -------------------------------

class _Parser:
    def __init__(self, toks, kinds):
        self.toks, self.i, self.kinds = toks, 0, kinds

    def peek(self):
        return self.toks[self.i] if self.i < len(self.toks) else (None, None)

    def eat(self, kind, value=None):
        k, v = self.peek()
        if k == kind and (value is None or v == value):
            self.i += 1
            return v
        return None

    def parse(self):
        node = self.or_expr()
        if self.i != len(self.toks):
            raise _Fail(WHY_UNPARSEABLE)
        return node

    def or_expr(self):
        parts = [self.and_expr()]
        while self.eat("op", "||"):
            parts.append(self.and_expr())
        return parts[0] if len(parts) == 1 else _join("any", parts)

    def and_expr(self):
        parts = [self.unary()]
        while self.eat("op", "&&"):
            parts.append(self.unary())
        return parts[0] if len(parts) == 1 else _join("all", parts)

    def unary(self):
        if self.eat("op", "!"):
            return negate(self.unary())
        return self.atom()

    def atom(self):
        if self.eat("op", "("):
            node = self.or_expr()
            if not self.eat("op", ")"):
                raise _Fail(WHY_UNPARSEABLE)
            return node
        k, v = self.peek()
        if k == "bool":
            # `{true: ...}` is a guard that always holds. Translating it to a
            # condition would put a tautology in the data; the caller is told to
            # drop the gate instead, which is a mapping decision, not a loss.
            raise _Fail(WHY_UNPARSEABLE)
        if k != "ident":
            raise _Fail(WHY_UNPARSEABLE)
        self.i += 1
        return self.after_ident(v)

    def after_ident(self, name):
        k, op = self.peek()
        if k == "op" and op in ("==", "!=", ">=", "<=", ">", "<"):
            self.i += 1
            return self.comparison(name, op)
        if k == "op" and op in ARITH:
            raise _Fail(WHY_ARITHMETIC)
        return self.truthy(name)

    # -- the two leaf forms ---------------------------------------------------

    def kind_of(self, name):
        kind = self.kinds.get(name) or self.kinds.get(name.lower())
        if kind in (None, "unknown"):
            raise _Fail(WHY_UNKNOWN_VAR)
        if kind == "text":
            raise _Fail(WHY_TEXT_VAR)
        return kind

    def ident_of(self, name):
        ident = var_id(name)
        if not ident:
            raise _Fail(WHY_BAD_ID)
        return ident

    def truthy(self, name):
        """A bare `$v` / `{v: ...}` — the commonest guard there is."""
        kind, ident = self.kind_of(name), self.ident_of(name)
        if kind == "flag":
            return {"type": "flag", "flag": ident, "value": True}
        # A counter is truthy when it is not zero. Parlance has no `!=`, and
        # `not (v == 0)` is exactly that test over integers.
        return {"type": "not", "of": {"type": "counter", "counter": ident,
                                      "op": "==", "value": 0}}

    def comparison(self, name, op):
        kind, ident = self.kind_of(name), self.ident_of(name)
        sign = -1 if self.eat("op", "-") else 1
        k, v = self.peek()
        if k == "ident":
            raise _Fail(WHY_VAR_TO_VAR)
        if k is None:
            raise _Fail(WHY_UNPARSEABLE)
        self.i += 1
        if k == "num":
            v *= sign
        elif sign == -1:
            raise _Fail(WHY_UNPARSEABLE)
        # An operand followed by arithmetic (`coins > base + 1`) is an
        # expression, not a literal, and there is nothing to compare against.
        nk, nv = self.peek()
        if nk == "op" and nv in ARITH:
            raise _Fail(WHY_ARITHMETIC)

        if k == "str":
            raise _Fail(WHY_TEXT_VAR)
        if k == "bool":
            if kind != "flag" or op not in ("==", "!="):
                raise _Fail(WHY_UNPARSEABLE)
            value = v if op == "==" else not v
            return {"type": "flag", "flag": ident, "value": value}
        if k == "num":
            if kind == "flag":
                # A flag compared to a number is not a flag. Rather than guess
                # which of the two readings the source meant, decline.
                raise _Fail(WHY_UNPARSEABLE)
            if op == "!=":
                return negate({"type": "counter", "counter": ident,
                               "op": "==", "value": v})
            return {"type": "counter", "counter": ident, "op": op, "value": v}
        raise _Fail(WHY_UNPARSEABLE)


def _join(kind, parts):
    """Flatten `a and (b and c)` into one `all`, which is the same condition and
    a great deal easier for an author to read in the imported project."""
    flat = []
    for p in parts:
        if p.get("type") == kind:
            flat.extend(p["of"])
        else:
            flat.append(p)
    return {"type": kind, "of": flat}


def _inline_const(tok, consts):
    """One token, with a compile-time constant replaced by the literal it names."""
    kind, value = tok
    if kind != "ident":
        return tok
    lit = consts.get(value)
    if lit is None:
        return tok
    lit = str(lit).strip()
    if re.match(r"^-?\d+$", lit):
        return ("num", int(lit))
    if lit in ("true", "false"):
        return ("bool", lit == "true")
    if re.match(r'^".*"$', lit):
        return ("str", lit[1:-1])
    return tok


def negate(cond):
    """The logical negation of a condition.

    Exact, never approximate — this is what an `else` branch gets, and getting it
    wrong duplicates narration in a way no string comparison can detect. A flag
    is boolean, so flipping its value IS its negation and reads far better in the
    data than a wrapper; everything else is wrapped, with a double negation
    collapsed rather than left to accumulate.
    """
    if cond.get("type") == "flag":
        return {**cond, "value": not cond["value"]}
    if cond.get("type") == "not":
        return cond["of"]
    return {"type": "not", "of": cond}


def translate(expr, kinds, consts=None):
    """`(condition, None)` if the guard maps, `(None, why)` if it does not.

    `kinds` maps a source variable name to "flag", "counter", "text" or
    "unknown". An unknown kind is a refusal, not a guess: importing `{stage: …}`
    as a flag when `stage` holds a number silently changes when the line shows.

    `consts` maps a compile-time constant to its literal, and those are
    substituted before parsing. Ink's `{hooperClueType == NONE}` compares against
    `CONST NONE = 0`; without the substitution that reads as a comparison between
    two variables and is declined, which is both a refusal and a wrong reason. It
    is not a guess — a CONST *is* a literal, and the importers' own guidance is
    already to inline one at its use sites.
    """
    if not expr or not expr.strip():
        return None, WHY_UNPARSEABLE
    # Checked before tokenizing so the reason names the construct. Without it a
    # call came back as "the source never declares this name", which sends the
    # reader looking for a missing variable instead of at a function.
    if CALL.search(expr):
        return None, WHY_FUNCTION_CALL
    toks = _tokens(expr.strip())
    if toks is None:
        return None, WHY_UNPARSEABLE
    if consts:
        toks = [_inline_const(t, consts) for t in toks]
    try:
        return _Parser(toks, kinds).parse(), None
    except _Fail as e:
        return None, e.why
