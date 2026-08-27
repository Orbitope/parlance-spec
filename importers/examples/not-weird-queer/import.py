#!/usr/bin/env python3
"""
Rebuild the Not Weird. Queer worked import from the vendored source.

    python3 import.py

Writes `project/`. Verify it the way anyone else can:

    python3 ../../lib/parse_twine.py Not-Weird-Queer-0-0-008.html --emit manifest > /tmp/m.json
    python3 ../../lib/check.py --root project --manifest /tmp/m.json --reset
"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))

import build_twine_example as B          # noqa: E402
import write_project as W                # noqa: E402

SOURCE = "Not-Weird-Queer-0-0-008.html"


def main():
    ir = B.ir_of(os.path.join(HERE, SOURCE))
    builder, dialogues = B.build(ir, "nwq")

    W.write_project(
        os.path.join(HERE, "project"),
        dialogues,
        W.variables_of(builder.kinds, {}, "Harlowe $"),
        {},          # Harlowe names no speakers: the story is unattributed narration
    )
    print(f"{len(dialogues)} dialogues, "
          f"{sum(len(d['nodes']) for d in dialogues)} nodes")
    for n in builder.notes[:8]:
        print("  note:", n)
    if len(builder.notes) > 8:
        print(f"  ... and {len(builder.notes) - 8} more notes")


if __name__ == "__main__":
    main()
