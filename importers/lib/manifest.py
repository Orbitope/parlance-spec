"""
manifest.py — the integrity stamp, in one place.

The gate compares the imported project against the manifest, and the manifest
is a plain file written by the parser, inside the very loop the gate polices.
So the stamp is what lets check.py tell a parser's own output apart from one a
repair pass rewrote to suit itself.

It lives here rather than being copied into each parser and into check.py
because it was copied into each parser and into check.py — three
implementations of one function, which is how the fields drift apart. A stamp
computed differently from how it is verified is not a stamp.

ABSENT IS NOT EMPTY. The digest used to read every field with a default:
`man.get("residue", [])`. That made a manifest with no `residue` key hash
identically to one with an empty list, so deleting the key from a stamped
manifest left the stamp VALID and skipped the residue gate entirely — the
cheapest possible edit, and the check that exists to catch cheap edits waved it
through. A parser at a pre-residue version did the same thing by accident. The
digest now covers WHICH fields are present as well as what is in them, and
check.py requires all of them.
"""
import hashlib
import json

#: Every manifest field check.py's verdict depends on. Adding a field here
#: without adding it to the parsers' output is a hard failure, by design: an
#: unstamped-for field is a field a repair pass may edit unnoticed.
TRUSTED_FIELDS = ("units", "rewrites", "residue", "literals")


def literals_of(*roots, extra=()):
    """Every string the source WRITES rather than speaks, for check.py's
    invention check: the values `set`-style commands assign to text variables
    (they reach the project as `set_text` effects and are interpolated into
    player-facing lines), plus whatever the parser passes as `extra` — speaker
    display names a `define` gave, say. Collected by walking the parser's own
    structures for the two shapes an assignment takes on its way to a project
    (`{"op": "settext", "value": …}` in an IR, `{"type": "set_text", "value":
    …}` as an effect), so a parser cannot forget to list one it mapped.

    A literal vouches only for a `set_text` value or a character name in the
    output. It never vouches for a line or an option: those are compared
    against `units`, so a string the source assigned to a variable cannot be
    laundered into narration."""
    out = set(s for s in extra if isinstance(s, str) and s)

    def walk(o):
        if isinstance(o, dict):
            v = o.get("value")
            if isinstance(v, str) and (o.get("op") == "settext" or o.get("type") == "set_text"):
                out.add(v)
            for x in o.values():
                walk(x)
        elif isinstance(o, (list, tuple)):
            for x in o:
                walk(x)

    for r in roots:
        walk(r)
    return sorted(out)


def digest(man):
    """Hash exactly the fields the comparison trusts, presence included."""
    payload = {
        "fields": [k for k in TRUSTED_FIELDS if k in man],
        **{k: man[k] for k in TRUSTED_FIELDS if k in man},
    }
    blob = json.dumps(payload, sort_keys=True, ensure_ascii=False,
                      separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(blob).hexdigest()


def stamp(man):
    """Attach the digest. Parsers call this immediately before emitting."""
    man["integrity"] = {"algo": "sha256", "sha256": digest(man)}
    return man


def missing_fields(man):
    """Trusted fields this manifest does not carry at all."""
    return [k for k in TRUSTED_FIELDS if k not in man]
