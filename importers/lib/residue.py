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

# A `//` comment — but NOT the `//` in `https://example.com`. Both parsers used to
# cut at the first `//` unconditionally, which excised the rest of any line
# containing a URL. Residue caught that, loudly, which is how it was found; the
# rule is shared from here so the parsers and the accounting cannot disagree about
# where a comment starts.
LINE_COMMENT = re.compile(r"(?<!:)//[^\n]*")
BLOCK_COMMENT = re.compile(r"/\*.*?\*/", re.S)


def strip_comment(line):
    """One line, with any trailing `//` comment removed. Shared with the parsers."""
    return LINE_COMMENT.sub("", line)


def blank_comments(text):
    """Comment text replaced by spaces, with every newline kept.

    Line numbering has to survive, because residue reports by line — so this
    blanks rather than deletes. Block comments are the reason it exists at all:
    they are not player-facing prose, the parsers already skip them, and residue
    counted every word inside one as a line the parser had lost.
    """
    def blank(m):
        return "".join(c if c == "\n" else " " for c in m.group(0))
    return LINE_COMMENT.sub(blank, BLOCK_COMMENT.sub(blank, text))


def blank_yarn_headers(text):
    """Yarn node headers blanked, with newlines kept.

    A header runs from the start of a node to its `---`, and may hold ANY key —
    `title`, `tags`, and whatever else the game's tooling reads. The only way to
    tell a header's `to: M Douraud` from a body line's `Keeper: Two coins.` is
    WHERE it is, which is why this tracks the region instead of listing keys.
    """
    out, in_body = [], False
    for raw in text.splitlines():
        s = raw.strip()
        if s == "---":
            in_body = True
        elif s == "===":
            in_body = False
        elif not in_body and s:
            raw = " " * len(raw)
        out.append(raw)
    return "\n".join(out)


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
        # NOT `<<[^>\n]*>>`: that excludes `>` from the body, so every command
        # containing a comparison — `<<if $coins >= 2>>`, `<<elseif $n > 0>>` —
        # matched nothing at all and was counted as prose. The whole line then
        # showed up as residue and refused to converge, on a story that had
        # nothing wrong with it. Non-greedy to the first `>>` instead, which
        # still stops at the end of the command and still cannot cross a line.
        r"<<[^\n]*?>>",               # commands
        # Node headers are blanked STRUCTURALLY, by `blank_yarn_headers` below,
        # not matched here. They used to be an allowlist of key names — and a
        # Yarn header may carry any key at all, so a real script using `to:`,
        # `name:`, `icon:` or `image:` reported every one of them as lost prose.
        # A general `^\s*\w+\s*:.*$` cannot replace the list either: it would eat
        # `Keeper: Two coins.` and hide a whole speaker line, which is the very
        # thing this file exists to make impossible.
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
        # Diverts and threads BEFORE the choice/gather markers, so that the `-`
        # of `->` is not consumed as a gather first. Three shapes are recognised:
        # `-> a`, `-> a ->`, and `-> a -> b` (a tunnel that hands on to another
        # container). Only the LAST may be followed by end-of-line or a brace: in
        # Ink, text after a divert is unreachable, so a `->` mid-sentence is prose
        # the parser mis-read rather than syntax, and stripping those would hide
        # exactly that defect. The optional `}` is for a conditional whose whole
        # body is a divert: `{ flag: -> knot }`.
        r"(?:->\s*(?:[A-Za-z_][\w.]*|END|DONE)\s*)+(?:->\s*)?\}?\s*$",
        r"<-\s*[A-Za-z_][\w.]*\s*$",
        # Conditional-block branch markers: `- else:`, `- cond:`.
        r"^\s*-\s*(?:else|otherwise)?\s*[^:\n]*:\s*$",
        # Choice and gather markers, with the label that may follow one. The
        # markers may be spaced (`- - (bunk_opts)`) as readily as run together,
        # and a label is an address rather than prose.
        r"^\s*(?:[*+\-]\s*)+(?:\(\w+\)\s*)?",
        r"#[\w:.\-]+",                 # inline tags
        # ONLY the head of a brace group: `{cond}`, `{ cond:`, `{var:`. A group
        # holding an alternative (`{a|b}`) has no head to match and is left
        # entirely to the accounting, as is every word after a `:`.
        r"\{[^{}|:\n]*[:}]",
        r"^\s*\}\s*$",                # a brace group's closing line
        r"[|}]",                      # the alternative separator and closer
        r"<>",                        # glue
    ],
    "twine": [
        r"^\s*::.*$",                          # passage headers
        # ONLY the macro head. A macro's arguments can hold prose — `(print: "…")`
        # is the case that proves it — so they are accounted for by the parser
        # instead, which records every macro's argument text with its line. The
        # same rule as the Ink brace head, and for the same reason.
        r"\(\s*[A-Za-z][\w-]*\s*:",
        # A link's TARGET is an address, not prose; the text beside it is prose
        # and stays required. Both orders: `[[Text|Target]]`, `[[Text->Target]]`
        # and `[[Target<-Text]]`.
        r"(?:\||->)[^\]\n]*(?=\]\])",
        r"\[\[[^\]\n]*?<-",
        r"\[\[|\]\]",
        # Variable interpolation, WITH any possessive or contraction hanging off
        # it. `$name's` strips to a bare `'s`, whose `s` the word pattern then
        # counts as a word of prose nobody wrote — 64 lines of a real story
        # reported lost on the strength of one apostrophe.
        r"\$\w+(?:['’]\w+)?",
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
    # Comments are not player-facing prose and the parsers already skip them, so
    # counting their words reported the parser as having lost lines nobody wrote
    # for a player. Blanked rather than deleted: residue reports by line number.
    blanked = blank_comments(source_text)
    if fmt == "yarn":
        blanked = blank_yarn_headers(blanked)
    for i, raw in enumerate(blanked.splitlines(), 1):
        if not raw.strip():
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
