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
TRUSTED_FIELDS = ("units", "rewrites", "residue")


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
