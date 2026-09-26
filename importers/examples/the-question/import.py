#!/usr/bin/env python3
"""
Rebuild The Question worked import from the vendored source.

    python3 import.py

Writes `project/`. Verify it the way anyone else can:

    python3 ../../lib/parse_renpy.py script.rpy --emit manifest > /tmp/m.json
    python3 ../../lib/check.py --root project --manifest /tmp/m.json --reset
"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))

import build_renpy_example as B          # noqa: E402

SOURCE = "script.rpy"


def main():
    ir = B.ir_of(os.path.join(HERE, SOURCE))
    builder, dialogues = B.write(os.path.join(HERE, "project"), ir, "tq")
    print(f"{len(dialogues)} dialogues, "
          f"{sum(len(d['nodes']) for d in dialogues)} nodes")
    for n in builder.notes:
        print("  note:", n)


if __name__ == "__main__":
    main()
