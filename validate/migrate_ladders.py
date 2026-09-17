#!/usr/bin/env python3
"""Migrate a Parlance project from character dialogue LADDERS to dialogue OFFERS (ws 17).

The ladder (`character.dialogues`: an ordered, first-match-wins list) is replaced by
self-declaring `offer` objects on the dialogues themselves. Resolution becomes
priority-tier -> specificity -> ordinal id (see RUNTIME_CONTRACT / ws 17), which is
order-independent. This script rewrites a project in place so the winner in every game
state is preserved, and REPORTS the judgement calls it made (priority inversions, shadowed
dead rungs, dropped availableWhen) for a human to review.

Usage:
    python3 tooling/scripts/migrate_ladders.py [--root <project>] [--check]

    --root    project directory (default: cwd). Honors parlance.config.json's `data`.
    --check   do not write; exit 1 if any file WOULD change (for CI / idempotence).

Algorithm (per character C with rungs r[0..n], top = highest priority):
  1. Each rung's dialogue d gets offer = {}; rung.showIf -> offer.when; if d.speakerId != C
     -> offer.character = C. A laddered dialogue's own availableWhen was never read by
     ladder resolution, so it is dropped (reported).
  2. A dialogue with availableWhen in NO rung keeps it as offer.when (it was discovery-only).
  3. Priorities preserve order: for each pair (i above j) that can both be eligible (not
     provably exclusive), if (spec_i, id_i) does not already beat (spec_j, id_j) under the
     runtime tiebreak, i needs a higher tier. Computed bottom-up; every non-zero tier is an
     INVERSION report.
  4. An unconditional rung that is not last shadows every rung below it. Step 3 keeps
     that shadowing (the rung gets a priority tier, so the ladder's winner is preserved),
     which leaves a PRIORITIZED FALLBACK the validator warns about — reported as SHADOWED,
     so the author can decide whether to drop the tier and let the lower rungs play.
  5. character.dialogues is deleted.

The exclusivity oracle and condition_specificity are imported from validate.py so the
migration and the editor's tie warning never disagree.
"""
from __future__ import annotations

import argparse
import glob
import json
import os
import sys

# validate.py sits one directory up in this repo (tooling/scripts/ beside
# tooling/validate.py) and in the SAME directory in the published spec repo
# (validate/migrate_ladders.py beside validate/validate.py); try both.
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.dirname(__file__))
from validate import condition_specificity, offers_exclusive  # noqa: E402


def data_dir(root: str) -> str:
    cfg = os.path.join(root, "parlance.config.json")
    try:
        return os.path.join(root, json.load(open(cfg, encoding="utf-8")).get("data") or "data")
    except Exception:
        return os.path.join(root, "data")


def canonical(obj) -> str:
    # Matches editor/core/src/serializer.ts: sorted keys, 2-space indent, LF, raw unicode.
    return json.dumps(obj, sort_keys=True, ensure_ascii=False, indent=2) + "\n"


def load_kind(data: str, kind: str) -> dict:
    """id -> (obj, path), recursively (dir-mode entities may be nested)."""
    out = {}
    for p in sorted(glob.glob(os.path.join(data, kind, "**", "*.json"), recursive=True)):
        try:
            obj = json.load(open(p, encoding="utf-8"))
        except Exception:
            continue
        if isinstance(obj, dict) and "id" in obj:
            out[obj["id"]] = (obj, p)
    return out


def tiebreak_beats(spec_i: int, id_i: str, spec_j: int, id_j: str) -> bool:
    """Does offer i beat offer j at EQUAL priority — higher specificity, then lower
    ordinal id (matches betterOffer in runtime.ts)."""
    if spec_i != spec_j:
        return spec_i > spec_j
    return id_i < id_j


def assign_priorities(rungs: list, dialogues: dict) -> tuple[list, list]:
    """Return (priorities, inversions). priorities[i] is the tier for rung i;
    inversions is a list of (i, j, prio) the caller reports."""
    n = len(rungs)
    specs = [condition_specificity(r.get("showIf")) for r in rungs]
    ids = [r["dialogue"] for r in rungs]
    whens = [r.get("showIf") for r in rungs]
    prio = [0] * n
    inversions = []
    for i in range(n - 1, -1, -1):
        best = 0
        for j in range(i + 1, n):
            if offers_exclusive(whens[i], whens[j]):
                continue  # can never both apply — order between them is moot
            if tiebreak_beats(specs[i], ids[i], specs[j], ids[j]):
                need = prio[j]
            else:
                need = prio[j] + 1
            best = max(best, need)
        prio[i] = best
        if best > 0:
            inversions.append((i, ids[i], best))
    return prio, inversions


def is_subtree(needle, haystack) -> bool:
    """True if condition `needle` appears verbatim somewhere inside `haystack`."""
    if needle == haystack:
        return True
    if not isinstance(haystack, dict):
        return False
    t = haystack.get("type")
    if t in ("all", "any"):
        return any(is_subtree(needle, m) for m in haystack.get("of", []))
    if t == "not":
        return is_subtree(needle, haystack.get("of"))
    return False


def migrate(root: str):
    """Return (changed_files: {path: new_text}, report: list[str])."""
    data = data_dir(root)
    characters = load_kind(data, "characters")
    dialogues = load_kind(data, "dialogues")
    report: list[str] = []
    dirty_paths: set[str] = set()

    # Which dialogue each character's rungs claim (for step-2 discovery detection).
    claimed: dict[str, str] = {}  # dialogue id -> character id that offered it

    for cid in sorted(characters):
        char, cpath = characters[cid]
        rungs = char.get("dialogues")
        if not rungs:
            continue

        prio, inversions = assign_priorities(rungs, dialogues)

        # Step 4 — dead rungs (unconditional, not last). Step 3 has given [i] a
        # tier, so the rungs below stay shadowed exactly as they were; say so,
        # and name the lever, rather than claiming they were revived.
        for i, rung in enumerate(rungs):
            if "showIf" not in rung and i < len(rungs) - 1:
                for j in range(i + 1, len(rungs)):
                    report.append(
                        f"SHADOWED: {cid} rung [{j}] '{rungs[j]['dialogue']}' stays unreachable "
                        f"below unconditional [{i}] '{rung['dialogue']}' — [{i}] keeps priority "
                        f"{prio[i]} so the ladder's winner is preserved, and the validator's OFFER "
                        f"prioritized-fallback warning will point at it; drop that priority to let "
                        f"[{j}] play when its condition holds"
                    )

        for i, rung in enumerate(rungs):
            did = rung["dialogue"]
            if did not in dialogues:
                report.append(f"SKIP: {cid} rung [{i}] names unknown dialogue '{did}' — left for the validator")
                continue
            dlg, dpath = dialogues[did]
            if did in claimed and claimed[did] != cid:
                report.append(
                    f"CONFLICT: dialogue '{did}' is offered by both '{claimed[did]}' and '{cid}' — "
                    f"the offer model has one offering character; kept '{claimed[did]}', skipped '{cid}'"
                )
                continue
            claimed[did] = cid

            offer: dict = {}
            if "showIf" in rung:
                offer["when"] = rung["showIf"]
            if dlg.get("speakerId") != cid:
                offer["character"] = cid
            if prio[i] > 0:
                offer["priority"] = prio[i]

            # A laddered dialogue's own availableWhen was never consulted by
            # resolveCharacterDialogue — the rung's showIf is the real gate. Drop it.
            if "availableWhen" in dlg:
                aw = dlg["availableWhen"]
                if "showIf" in rung and not is_subtree(aw, rung["showIf"]):
                    report.append(
                        f"DROPPED availableWhen: dialogue '{did}' had an availableWhen that is not a "
                        f"sub-tree of its ladder rung showIf on '{cid}' — the rung gate wins; verify"
                    )
                else:
                    report.append(f"dropped dead availableWhen on laddered dialogue '{did}'")
                del dlg["availableWhen"]
                dirty_paths.add(dpath)

            dlg["offer"] = offer
            dirty_paths.add(dpath)

        for i, _did, tier in inversions:
            report.append(
                f"INVERSION: {cid} rung [{i}] '{rungs[i]['dialogue']}' sits above a rung it does "
                f"not out-specify — assigned priority {tier}; consider making its condition more "
                f"specific instead"
            )

        del char["dialogues"]
        dirty_paths.add(cpath)

    # Step 2 — a dialogue with availableWhen that no rung claimed keeps it as offer.when.
    for did in sorted(dialogues):
        dlg, dpath = dialogues[did]
        if did in claimed:
            continue
        if "offer" in dlg:
            continue  # already migrated (idempotence)
        if "availableWhen" in dlg:
            dlg["offer"] = {"when": dlg["availableWhen"]}
            del dlg["availableWhen"]
            dirty_paths.add(dpath)
            if dlg.get("speakerId"):
                report.append(f"discovery-only dialogue '{did}': availableWhen -> offer.when (speaker owns it)")
            else:
                # The old runtime indexed discovery by speakerId, so this gate was
                # dead: nothing ever discovered a speakerless dialogue. The offer
                # is written so the validator's "names no character" warning
                # points at it, but the author has to say who offers it.
                report.append(
                    f"NO SPEAKER: dialogue '{did}' had availableWhen but no speakerId — the old "
                    f"runtime never discovered it; its offer now names no character. Set "
                    f"offer.character to whoever should present it, or drop the offer"
                )

    changed = {}
    for path in sorted(dirty_paths):
        obj = None
        for src in (characters, dialogues):
            for o, p in src.values():
                if p == path:
                    obj = o
        if obj is not None:
            changed[path] = canonical(obj)
    return changed, report


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", default=".")
    ap.add_argument("--check", action="store_true")
    args = ap.parse_args()

    changed, report = migrate(args.root)

    would_change = []
    for path, text in changed.items():
        current = open(path, encoding="utf-8").read() if os.path.exists(path) else None
        if current == text:
            continue
        would_change.append(path)
        if not args.check:
            open(path, "w", encoding="utf-8").write(text)

    for line in report:
        print(line)
    rel = [os.path.relpath(p, args.root) for p in would_change]
    if args.check:
        if would_change:
            print(f"\n{len(would_change)} file(s) NOT migrated: {', '.join(rel)}")
            return 1
        print("\nalready migrated — no changes needed")
        return 0
    if would_change:
        print(f"\nmigrated {len(would_change)} file(s): {', '.join(rel)}")
    else:
        print("\nno ladders to migrate")
    return 0


if __name__ == "__main__":
    sys.exit(main())
