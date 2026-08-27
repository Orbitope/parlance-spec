#!/usr/bin/env python3
"""
Rebuild the Cyberharcèlement worked import from the vendored source.

    python3 import.py

Writes `project/`. Verify it the way anyone else can:

    python3 ../../lib/parse_yarn.py episode1.yarn --emit manifest > /tmp/m1.json
    python3 ../../lib/check.py --root project --manifest /tmp/m1.json --reset
"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))

import build_yarn_example as B          # noqa: E402
import write_project as W               # noqa: E402

SOURCES = ["episode1.yarn", "episode2.yarn"]


def main():
    irs = [B.ir_of(os.path.join(HERE, s)) for s in SOURCES]
    names = [os.path.splitext(s)[0] for s in SOURCES]
    builders, dialogues, notes = B.build(irs, names)

    # Which character speaks which dialogue, in the order the source presents
    # them. A ladder is required for a character to be reachable at all.
    ladders = {}
    for d in dialogues:
        speakers = []
        for n in d["nodes"]:
            sid = n.get("speakerId")
            if sid and sid not in speakers:
                speakers.append(sid)
        for sid in speakers:
            ladders.setdefault(sid, []).append(d["id"])

    kinds = {}
    for b in builders:
        kinds.update(b.kinds)
    speakers = {}
    for b in builders:
        speakers.update(b.speakers)

    defaults = {}
    for ir in irs:
        for n in ir["nodes"]:
            for it in n["items"]:
                for c in it["commands"]:
                    if c.split()[:1] == ["declare"]:
                        m = B.SET.match(c.strip())
                        if m:
                            raw = m.group(4).strip()
                            name = m.group(1)
                            if raw in ("true", "false"):
                                defaults[name] = raw == "true"
                            elif raw.lstrip("-").isdigit():
                                defaults[name] = int(raw)
                            elif raw.startswith('"'):
                                defaults[name] = raw[1:-1]

    W.write_project(
        os.path.join(HERE, "project"),
        dialogues,
        W.variables_of(kinds, defaults, "Yarn $"),
        W.characters_of(speakers, ladders),
    )
    print(f"{len(dialogues)} dialogues, "
          f"{sum(len(d['nodes']) for d in dialogues)} nodes, "
          f"{len(speakers)} characters")
    for n in notes:
        print("  note:", n)


if __name__ == "__main__":
    main()
