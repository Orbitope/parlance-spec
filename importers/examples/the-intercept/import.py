#!/usr/bin/env python3
"""
Rebuild The Intercept worked import from the vendored source.

    python3 import.py

Writes `project/`. Verify it the way anyone else can:

    python3 ../../lib/parse_ink.py TheIntercept.ink --emit manifest > /tmp/m.json
    python3 ../../lib/check.py --root project --manifest /tmp/m.json --reset
"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))

import build_ink_example as B          # noqa: E402
import write_project as W              # noqa: E402

SOURCE = "TheIntercept.ink"


def main():
    ir = B.ir_of(os.path.join(HERE, SOURCE))
    builder, dialogues = B.build(ir, "intercept")

    ladders = {}
    for d in dialogues:
        seen = []
        for n in d["nodes"]:
            sid = n.get("speakerId")
            if sid and sid not in seen:
                seen.append(sid)
        for sid in seen:
            ladders.setdefault(sid, []).append(d["id"])

    defaults = {d["name"]: d["default"] for d in builder.decls
                if d.get("decl") == "VAR" and "default" in d}

    W.write_project(
        os.path.join(HERE, "project"),
        dialogues,
        W.variables_of(builder.kinds, defaults, "Ink VAR"),
        W.characters_of(builder.speakers, ladders),
    )
    print(f"{len(dialogues)} dialogues, "
          f"{sum(len(d['nodes']) for d in dialogues)} nodes, "
          f"{len(builder.speakers)} characters")
    for n in builder.notes[:12]:
        print("  note:", n)
    if len(builder.notes) > 12:
        print(f"  ... and {len(builder.notes) - 12} more notes")


if __name__ == "__main__":
    main()
