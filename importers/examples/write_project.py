#!/usr/bin/env python3
"""
write_project.py — the registries and files a built dialogue set needs on disk.

Shared by the worked examples so that the mapping scripts stay about mapping.
Everything written here is either derived from the source or left empty: the
skills' rule is that an optional field the author did not write stays absent, and
that applies to a script as much as to a model.

`progression.json` is the one file with no source to derive from. Parlance
requires it and a Yarn or Ink story says nothing about skill progression, so it
is written at the schema's own defaults and the report says so.
"""
import json
import os
import shutil


def canonical(obj):
    """Sorted keys, 2-space indent, literal UTF-8, trailing newline.

    The same shape `editor/core/src/serializer.ts` writes, so opening one of
    these projects in the editor and saving produces no diff — and
    `npm run normalize -- --check` stays green over them.
    """
    return json.dumps(obj, indent=2, sort_keys=True, ensure_ascii=False) + "\n"


def write(path, obj):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write(canonical(obj))


def variables_of(kinds, defaults, source_label):
    """One registry entry per variable the source declares.

    `description` is the only field written that is not the author's, and it is
    provenance rather than prose: it names the source declaration this entry came
    from, so an author opening the project can find it in their own file.
    """
    out = []
    for name in sorted(kinds):
        kind = kinds[name]
        if kind not in ("flag", "counter", "text"):
            continue
        entry = {"id": name.lower(), "kind": kind,
                 "description": f"{source_label} {name}"}
        if name in defaults:
            entry["default"] = defaults[name]
        else:
            entry["default"] = {"flag": False, "counter": 0, "text": ""}[kind]
        out.append(entry)
    return {"variables": out}


def characters_of(speakers, ladders):
    """A character per speaker name, with its dialogues in source order.

    The ladder is ORDER ONLY — no rung carries a condition, because the source
    never gave one. That leaves the first rung winning forever, which the
    validator warns about and the report repeats: it is a real property of the
    import, not something to paper over with an invented gate.
    """
    out = {}
    for cid, name in sorted(speakers.items()):
        out[cid] = {"id": cid, "name": name,
                    "dialogues": [{"dialogue": d} for d in ladders.get(cid, [])]}
    return out


def write_project(root, dialogues, variables, characters):
    """Write the project, replacing what was there.

    `data/` is CLEARED first. Writing over the top left files from an earlier run
    behind — a rebuild that produced fewer dialogues than the one before it kept
    the extras, so the project on disk was the union of two imports. The content
    check duly reported 19 lines the source declares as loss sitting in the
    output, and the cause looked like a mapping bug rather than a stale file.
    """
    data = os.path.join(root, "data")
    if os.path.isdir(data):
        shutil.rmtree(data)
    for d in dialogues:
        write(os.path.join(root, "data", "dialogues", d["id"] + ".json"), d)
    for cid, c in characters.items():
        write(os.path.join(root, "data", "characters", cid + ".json"), c)
    write(os.path.join(root, "data", "variables.json"), variables)
    write(os.path.join(root, "data", "skills.json"), {"skills": []})
    write(os.path.join(root, "data", "portraits.json"), {"portraits": []})
    write(os.path.join(root, "data", "progression.json"),
          {"maxSkill": 8, "pointsPerLevel": 1, "startingSkills": {},
           "xpThresholds": [0, 100]})
