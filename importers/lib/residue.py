"""
residue.py — prove the parser did not quietly drop prose.

check.py compares the imported project against the manifest. That catches
everything the manifest knows about, and nothing it does not: prose a parser
drops BEFORE writing the manifest is invisible to the comparison by
construction. An audit found six live instances — a `->` inside a sentence
excising the rest of it, a URL swallowed whole, a `#` in prose truncating the
line, a stray `{` marking the rest of a file unmappable so that an entirely
EMPTY project converged.

The defence is accounting rather than more regexes: every word in the source
must show up somewhere the parser can name — a unit's text, a speaker, a
declared-unmappable construct, or a command it recognised. Words that appear
nowhere are residue, and residue is reported loudly instead of being lost.

Deliberately word-level, not byte-level. Format punctuation legitimately
disappears (`<<`, `->`, `{$`), so demanding byte coverage would be pure noise;
losing a WORD of a writer's prose never has an innocent explanation.
"""
import re
from collections import Counter

WORD = re.compile(r"[^\W_]+(?:['’][^\W_]+)*", re.UNICODE)


def _words(s):
    return WORD.findall(s or "")


# Format syntax, stripped before words are counted. Losing a `<<jump>>` or a
# knot header costs nothing; losing a word of a writer's prose never has an
# innocent explanation, and that is the only thing this is looking for.
#
# THE GOVERNING RULE: never strip a construct that can CARRY prose. Every
# pattern here is a hole in the accounting, and a pattern that swallows
# narration rebuilds, inside the fix, the exact blind spot the fix exists to
# close. Ink braces are the case that proves it — `{a|b}` alternatives and
# `{cond: line}` conditionals are player-facing text, and a blanket
# `\{[^{}]*\}` reported an entire dropped line as fully accounted for. Only the
# non-prose HEAD of a brace group is stripped now; anything past a `:` or a `|`
# stays required, so the parser has to name it in a unit or in `unmapped`.
#
# Two further rules the ink set learned the hard way:
#
# ORDER MATTERS — patterns apply in sequence, so a broad marker pattern placed
# first eats the prefix of a construct the next pattern needs to see. `-> END`
# is the live example: the choice/gather marker `^\s*[*+-]+` consumed the `-`,
# leaving `> END` that the divert pattern no longer matched.
#
# NEGATED CLASSES MUST EXCLUDE THE NEWLINE. `[^:]*` happily crosses lines, and
# the else-branch pattern below once matched four lines at a stretch — a divert,
# a blank line, a knot header and the opening of the next conditional — hiding
# all of them from the count.
MARKUP = {
    "yarn": [
        r"<<[^>\n]*>>",               # commands
        r"^\s*(?:title|tags|position|colorID|bg|time|type|from|allowIcons)\s*:.*$",
        r"^\s*(?:---|===)\s*$",       # node delimiters
        r"^\s*->",                    # option marker (its text is a unit)
        r"#[\w:.\-]+",                # line tags
        r"\{\$?[\w.]+\}",             # interpolation
    ],
    "ink": [
        # Whole-line structure first.
        r"^\s*#.*$",                  # file / knot tag lines (`# story: ...`)
        r"^\s*={2,}.*={0,}\s*$",       # knot headers
        r"^\s*=\s*[A-Za-z_]\w*.*$",   # stitch headers
        r"^\s*(?:VAR|CONST|LIST|EXTERNAL|INCLUDE)\b.*$",
        r"^\s*~.*$",                  # logic lines
        # Diverts and threads BEFORE the choice/gather markers, so that the
        # `-` of `->` is not consumed as a gather first. Anchored to
        # end-of-line: in Ink, text after a divert is unreachable, so a `->`
        # mid-sentence is prose the parser mis-read, not syntax, and stripping
        # those would hide exactly that defect.
        r"->\s*(?:[A-Za-z_][\w.]*|END|DONE)\s*(?:->)?\s*$",
        r"<-\s*[A-Za-z_][\w.]*\s*$",
        # Conditional-block branch markers: `- else:`, `- cond:`.
        r"^\s*-\s*(?:else|otherwise)?\s*[^:\n]*:\s*$",
        r"^\s*[*+\-]+",                # choice / gather markers
        r"#[\w:.\-]+",                 # inline tags
        # ONLY the head of a brace group: `{cond}`, `{ cond:`, `{var:`. A group
        # holding an alternative (`{a|b}`) has no head to match and is left
        # entirely to the accounting, as is every word after a `:`.
        r"\{[^{}|:\n]*[:}]",
        r"^\s*\}\s*$",                # a brace group's closing line
        r"[|}]",                      # the alternative separator and closer
        r"<>",                        # glue
    ],
}


def find_residue(source_text, units, unmapped=(), extra_accounted=(), fmt=None):
    """Words present in the source but in nothing the parser recorded.

    `units` and `unmapped` are the manifest's own structures, so this checks the
    artefact that will actually be used as the yardstick — not a parallel parse
    that could drift from it.

    Counted as a MULTISET, not a set. A parser that eats one occurrence of a
    repeated word corrupts the sentence just as surely as one that eats a rare
    word, and set accounting cannot see it: `The rope -> the cleat, then around
    the post.` loses a `the` to a phantom divert and still contains two more.
    """
    accounted = {}

    def add(lineno, text):
        if lineno and text:
            accounted.setdefault(int(lineno), Counter())\
                .update(w.lower() for w in _words(text))

    for u in units:
        add(u.get("lineno"), u.get("text"))
        add(u.get("lineno"), u.get("speaker"))
        add(u.get("lineno"), u.get("node"))
    for e in unmapped:
        add(e.get("lineno"), e.get("text"))
        add(e.get("lineno"), e.get("command"))
        add(e.get("lineno"), e.get("construct"))
    for lineno, text in extra_accounted:
        add(lineno, text)

    out = []
    for i, raw in enumerate(source_text.splitlines(), 1):
        if not raw.strip() or raw.lstrip().startswith("//"):
            continue
        stripped = raw
        for pat in MARKUP.get(fmt or "", []):
            stripped = re.sub(pat, " ", stripped, flags=re.M)
        want = Counter(w.lower() for w in _words(stripped))
        missing = want - accounted.get(i, Counter())
        if missing:
            out.append({"lineno": i, "line": raw.strip()[:160],
                        "words": sorted(missing.elements())})
    return out
