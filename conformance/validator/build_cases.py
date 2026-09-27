#!/usr/bin/env python3
"""
Generate the validator conformance case projects.

Each case is the same minimal, clean project with one seeded defect, so a
failing case names the rule that broke rather than "something in this project".
Regenerate with:

    python3 tooling/conformance/validator/build_cases.py

Output is canonically serialized (sorted keys, 2-space indent, trailing
newline) to match editor/core/src/serializer.ts, so `npm run normalize --check`
stays green over these trees.
"""

from __future__ import annotations

import copy
import json
import sys
import shutil
from pathlib import Path

CASES = Path(__file__).resolve().parent / "cases"
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from validate import validate_project  # noqa: E402

VALIDATORS = {"typescript", "python"}


# ---------------------------------------------------------------------------
# The base project: small, complete, and clean under both validators.
# ---------------------------------------------------------------------------

def base_project() -> dict[str, object]:
    return {
        "parlance.config.json": {"name": "conformance-fixture", "schemaVersion": 1},
        "data/skills.json": {
            "skills": [
                {
                    "cluster": "mind",
                    "description": "Noticing the detail that is out of place.",
                    "id": "observation",
                    "name": "Observation",
                }
            ]
        },
        "data/variables.json": {
            "variables": [
                {
                    "default": False,
                    "description": "The player has met the keeper.",
                    "id": "met_keeper",
                    "kind": "flag",
                },
                {
                    "default": False,
                    "description": "The keeper's story has been heard out.",
                    "id": "heard_story",
                    "kind": "flag",
                },
            ]
        },
        "data/factions/fac_villagers.json": {
            "id": "fac_villagers",
            "name": "Villagers",
            "reputationRange": {"max": 10, "min": -10},
            "summary": "The people who live here.",
        },
        "data/characters/npc_keeper.json": {
            "archetype": "keeper",
            "id": "npc_keeper",
            "name": "The Keeper",
        },
        "data/codex/cdx_village.json": {
            "body": "A village that keeps to itself.",
            "id": "cdx_village",
            "name": "The Village",
            "unlockedBy": {"flag": "met_keeper", "type": "flag", "value": True},
        },
        "data/endings/end_leave.json": {
            "id": "end_leave",
            "name": "You Leave",
            "summary": "The road takes you onward.",
            "unlockedBy": {"flag": "heard_story", "type": "flag", "value": True},
        },
        "data/dialogues/dlg_meet.json": {
            "entry": "node_open",
            "id": "dlg_meet",
            "offer": {},
            "nodes": [
                {
                    "id": "node_open",
                    "onEnter": [{"flag": "met_keeper", "type": "set_flag", "value": True}],
                    "text": "The keeper looks up.",
                    "choices": [
                        {"goto": "node_close", "id": "ch_listen", "text": "Listen."},
                    ],
                },
                {
                    "id": "node_close",
                    "isEnd": True,
                    "onEnter": [{"flag": "heard_story", "type": "set_flag", "value": True}],
                    "text": "They tell you what they saw.",
                },
            ],
            "speakerId": "npc_keeper",
            "title": "Meeting the Keeper",
        },
    }


class WithBom:
    """A file's JSON content, written with a leading UTF-8 byte-order mark —
    what Windows PowerShell 5.1 (`Set-Content -Encoding UTF8`) and older
    Notepad produce. Everything else is written canonically."""

    def __init__(self, content: object) -> None:
        self.content = content


class Text:
    """A non-JSON file (a lore Markdown document), written verbatim."""

    def __init__(self, content: str) -> None:
        self.content = content


def write_project(root: Path, files: dict[str, object]) -> None:
    for rel, content in files.items():
        path = root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        if isinstance(content, Text):
            path.write_text(content.content, encoding="utf-8")
            continue
        bom = "\ufeff" if isinstance(content, WithBom) else ""
        body = content.content if isinstance(content, WithBom) else content
        path.write_text(bom + json.dumps(body, indent=2, sort_keys=True, ensure_ascii=False) + "\n", encoding="utf-8")


# ---------------------------------------------------------------------------
# Cases — each seeds exactly one defect into a copy of the base project.
# ---------------------------------------------------------------------------

def case_clean_minimal(p: dict) -> None:
    """No defect: the floor every other case is measured against."""


def case_utf8_bom_loaded(p: dict) -> None:
    """A dir-mode entity AND an array registry saved with a UTF-8 BOM.

    Not a defect — a BOM is an encoding signature, and both implementations
    strip it on read. The case pins that they LOAD such files: the keeper is
    the dialogue's speaker and variables.json declares the flags the dialogue
    sets and the codex/ending read, so a loader that dropped either file would
    turn this clean project red with REF/FLAG errors. Both used to reject the
    file (the editor silently dropping the entity, the reference validator
    reporting invalid JSON), which is how a Notepad-edited character vanished
    from a writer's project (R4-1).
    """
    for rel in ("data/characters/npc_keeper.json", "data/variables.json", "parlance.config.json"):
        p[rel] = WithBom(p[rel])


def case_passive_goto_dangling(p: dict) -> None:
    """A passive check's goto naming a node that does not exist."""
    dlg = p["data/dialogues/dlg_meet.json"]
    dlg["nodes"][0]["choices"].append({
        "check": {"difficulty": 6, "mode": "passive", "skill": "observation"},
        "goto": "node_typo",
        "id": "ch_notice",
        "text": "[Observation] Notice the ledger.",
    })


def case_plain_goto_dangling(p: dict) -> None:
    """An ordinary choice pointing at a node that does not exist.

    The most common authoring mistake there is, and for a long time the least
    tested: a mutation probe disabled this check and the whole suite stayed
    green, while the rarer passive-check variant beside it was covered.
    """
    p["data/dialogues/dlg_meet.json"]["nodes"][0]["choices"].append({
        "goto": "node_typo",
        "id": "ch_leave",
        "text": "Leave.",
    })


def case_dead_end_node(p: dict) -> None:
    """A choice with no goto, no check, and a node that is not an ending.

    The player picks it and the conversation has nowhere to go.
    """
    p["data/dialogues/dlg_meet.json"]["nodes"][0]["choices"].append({
        "id": "ch_nowhere",
        "text": "Say nothing.",
    })


def case_project_rules_bad_dice(p: dict) -> None:
    """Unreadable dice notation in the PROJECT's rules, not on a single check.

    Reachable only because the conformance runner loads fixtures through the
    real storage layer. The hand-rolled loader it replaced never read
    rules.json, so this whole rule family sat outside the parity harness.
    """
    p["data/rules.json"] = {"check": {"dice": "2x6"}}


def case_advance_quest_unknown(p: dict) -> None:
    """An effect advancing a quest that does not exist."""
    p["data/dialogues/dlg_meet.json"]["nodes"][1]["onEnter"].append(
        {"quest": "qst_ghost", "toStage": "stg_one", "type": "advance_quest"}
    )


def case_duplicate_node_id(p: dict) -> None:
    """Two nodes in one dialogue sharing an id.

    The runtime resolves a node with `nodes.find` — FIRST match wins — so the
    author's second node is silently dead and every edge they believe points at
    it lands on the first one instead.
    """
    dlg = p["data/dialogues/dlg_meet.json"]
    dlg["nodes"].append({"id": "node_open", "isEnd": True, "text": "A second node_open."})


def case_npc_interactable_dialogue_places(p: dict) -> None:
    """An npc interactable's `dialogue` field still counts as a world placement.

    A speaker dialogue placed by an npc interactable's `dialogue` field — a
    misuse (the runtime resolves the character's offers, hence the LOC advisory) that nonetheless places the dialogue, so
    the OFFER stranded warning must NOT fire. This case exists because the
    TypeScript validator's local/derive split briefly counted only non-npc
    interactables as placements while the Python reference counted all of them
    — a divergence the shared cases could not see until this one pinned it.
    """
    p["data/dialogues/dlg_aside.json"] = {
        "entry": "n1",
        "id": "dlg_aside",
        "nodes": [{"id": "n1", "isEnd": True, "text": "A line reached via the yard."}],
        "speakerId": "npc_keeper",
        "title": "An Aside",
    }
    p["data/locations/loc_yard.json"] = {
        "id": "loc_yard",
        "interactables": [
            {"character": "npc_keeper", "dialogue": "dlg_aside", "id": "it_keeper", "kind": "npc"}
        ],
        "name": "The Yard",
        "spawns": [{"id": "sp_gate", "isDefault": True}],
    }


def case_offer_when_dangling(p: dict) -> None:
    """A dialogue's offer gate reading a variable nothing defines."""
    dlg = p["data/dialogues/dlg_meet.json"]
    offer = dict(dlg.get("offer", {}))
    offer["when"] = {
        "flag": "ghost_flag",
        "type": "flag",
        "value": True,
    }
    dlg["offer"] = offer


def case_cutscene_sets_ending_flag(p: dict) -> None:
    """The canonical finale: an ending gated on a flag only a cutscene sets."""
    p["data/variables.json"]["variables"].append({
        "default": False,
        "description": "The tale has been closed out.",
        "id": "tale_closed",
        "kind": "flag",
    })
    p["data/cutscenes/cs_farewell.json"] = {
        "asset": "cutscenes/farewell",
        "effectsOnComplete": [{"flag": "tale_closed", "type": "set_flag", "value": True}],
        "id": "cs_farewell",
        "name": "Farewell",
        "skippable": True,
    }
    p["data/endings/end_quiet.json"] = {
        "id": "end_quiet",
        "name": "A Quiet Ending",
        "summary": "You leave as you came.",
        "unlockedBy": {"flag": "tale_closed", "type": "flag", "value": True},
    }
    p["data/codex/cdx_keeper.json"] = {
        "body": "What the keeper told you, written down.",
        "id": "cdx_keeper",
        "name": "The Keeper's Account",
        "unlockedBy": {"flag": "tale_closed", "type": "flag", "value": True},
    }
    # Something has to play it, or the cutscene itself is unreachable.
    p["data/dialogues/dlg_meet.json"]["nodes"][1]["onEnter"].append(
        {"cutscene": "cs_farewell", "type": "play_cutscene"}
    )


def case_dup_id_registry(p: dict) -> None:
    """Two variables sharing an id in a single-file registry."""
    p["data/variables.json"]["variables"].append({
        "default": False,
        "description": "A second declaration of the same id.",
        "id": "met_keeper",
        "kind": "flag",
    })


def case_malformed_dice(p: dict) -> None:
    """Dice notation the parser cannot read."""
    p["data/dialogues/dlg_meet.json"]["nodes"][0]["choices"].append({
        "check": {
            "dice": "2x6",
            "difficulty": 8,
            "mode": "active",
            "onFailure": "node_close",
            "onSuccess": "node_close",
            "skill": "observation",
        },
        "id": "ch_press",
        "text": "[Observation] Read the room.",
    })


def _dice_check_choice(p: dict, dice: str) -> None:
    p["data/dialogues/dlg_meet.json"]["nodes"][0]["choices"].append({
        "check": {
            "dice": dice,
            "difficulty": 8,
            "mode": "active",
            "onFailure": "node_close",
            "onSuccess": "node_close",
            "skill": "observation",
        },
        "id": "ch_press",
        "text": "[Observation] Read the room.",
    })


def case_dice_too_many(p: dict) -> None:
    """More dice than the notation allows (adversarial review D8).

    The grammar alone accepted any `\\d+d\\d+`; the editor's probability table
    allocates n·m cells, so `200d1000` stalled the inspector for half a minute
    and an absurd side count threw a RangeError out of it. Both validators now
    bound N ≤ 100 and M ≤ 1000 in parse_dice / parseDice, so a per-check
    override past either bound is the same RULES error a malformed notation is.
    """
    _dice_check_choice(p, "101d6")


def case_dice_too_many_sides(p: dict) -> None:
    """A die with more sides than the notation allows (D8, the other bound)."""
    _dice_check_choice(p, "1d1001")


def case_offer_tie_capped(p: dict) -> None:
    """Six offers for one character tied on priority and specificity.

    The tie rule used to report every pair — N(N-1)/2 warnings, 499,501 at a
    thousand offers (adversarial review D1). Both validators now report the
    first OFFER_TIE_REPORT_CAP (10) ties in id order and ONE summary naming the
    pairs left unchecked: six offers make 15 pairs, so 10 tie warnings plus the
    summary — 11 OFFER warnings, the same on both sides. dlg_meet's own bare
    `offer` is the unconditional fallback, at a different specificity, so
    neither it nor the no-fallback rule takes part.
    """
    for letter in "abcdef":
        p[f"data/dialogues/dlg_tie_{letter}.json"] = {
            "entry": "n1",
            "id": f"dlg_tie_{letter}",
            "nodes": [{"id": "n1", "isEnd": True, "text": f"The keeper says {letter}."}],
            "offer": {"when": {"flag": "met_keeper", "type": "flag", "value": True}},
            "speakerId": "npc_keeper",
            "title": f"Tie {letter.upper()}",
        }


def case_difficulty_exceeds_dice(p: dict) -> None:
    """A 2d6 check gated above what 2d6 plus a plausible skill can roll."""
    p["data/dialogues/dlg_meet.json"]["nodes"][0]["choices"].append({
        "check": {
            "dice": "2d6",
            "difficulty": 40,
            "mode": "active",
            "onFailure": "node_close",
            "onSuccess": "node_close",
            "skill": "observation",
        },
        "id": "ch_impossible",
        "text": "[Observation] Attempt the impossible.",
    })


def _append_check_choice(p: dict, cid: str, check: dict) -> None:
    p["data/dialogues/dlg_meet.json"]["nodes"][0]["choices"].append({
        "check": check, "id": cid, "text": "[Observation] Read the room.",
    })


def case_check_modifier_clean(p: dict) -> None:
    """An active check with well-formed conditional modifiers (no defect)."""
    _append_check_choice(p, "ch_mod", {
        "difficulty": 10, "mode": "active",
        "onFailure": "node_close", "onSuccess": "node_close", "skill": "observation",
        "modifiers": [
            {"when": {"flag": "met_keeper", "type": "flag", "value": True}, "bonus": 2, "label": "Rapport"},
            {"when": {"flag": "heard_story", "type": "flag", "value": True}, "bonus": -1},
        ],
    })


def case_check_modifier_when_dangling(p: dict) -> None:
    """A modifier `when` reading a flag that no variable declares."""
    _append_check_choice(p, "ch_mod", {
        "difficulty": 10, "mode": "active",
        "onFailure": "node_close", "onSuccess": "node_close", "skill": "observation",
        "modifiers": [{"when": {"flag": "no_such_flag", "type": "flag", "value": True}, "bonus": 2}],
    })


def case_check_modifier_zero_bonus(p: dict) -> None:
    """A modifier with a bonus of 0 — dead authoring."""
    _append_check_choice(p, "ch_mod", {
        "difficulty": 10, "mode": "active",
        "onFailure": "node_close", "onSuccess": "node_close", "skill": "observation",
        "modifiers": [{"when": {"flag": "met_keeper", "type": "flag", "value": True}, "bonus": 0}],
    })


def case_check_priced_failure_sets_offer_flag(p: dict) -> None:
    """A priced check whose failure branch sets a flag an offer gates on — the
    CHECK punishment-spiral advisory (a derive-pass rule, located on the choice)."""
    _append_check_choice(p, "ch_press", {
        "difficulty": 10, "mode": "active",
        "onFailure": "node_setback", "onSuccess": "node_close", "skill": "observation",
    })
    p["data/dialogues/dlg_meet.json"]["nodes"].append({
        "id": "node_setback", "next": "node_close", "text": "The keeper bristles.",
        "onEnter": [{"flag": "met_keeper", "type": "set_flag", "value": True}],
    })
    p["data/dialogues/dlg_later.json"] = {
        "entry": "n1",
        "id": "dlg_later",
        "nodes": [{"id": "n1", "isEnd": True, "text": "The keeper nods again."}],
        "offer": {"when": {"flag": "met_keeper", "type": "flag", "value": True}},
        "speakerId": "npc_keeper",
        "title": "Later",
    }


def case_check_modifier_empty(p: dict) -> None:
    """An empty modifiers list — remove the field."""
    _append_check_choice(p, "ch_mod", {
        "difficulty": 10, "mode": "active",
        "onFailure": "node_close", "onSuccess": "node_close", "skill": "observation",
        "modifiers": [],
    })


def case_check_difficulty_reachable_with_bonus(p: dict) -> None:
    """A 2d6 DC 14 check that a +2 modifier lifts within reach (no GATE warning)."""
    _append_check_choice(p, "ch_mod", {
        "dice": "2d6", "difficulty": 14, "mode": "active",
        "onFailure": "node_close", "onSuccess": "node_close", "skill": "observation",
        "modifiers": [{"when": {"flag": "met_keeper", "type": "flag", "value": True}, "bonus": 2}],
    })


def case_check_difficulty_exceeds_dice_plus_bonus(p: dict) -> None:
    """A 2d6 DC 40 check no modifier can reach — the GATE warning names the headroom."""
    _append_check_choice(p, "ch_mod", {
        "dice": "2d6", "difficulty": 40, "mode": "active",
        "onFailure": "node_close", "onSuccess": "node_close", "skill": "observation",
        "modifiers": [{"when": {"flag": "met_keeper", "type": "flag", "value": True}, "bonus": 2}],
    })


def case_node_id_end(p: dict) -> None:
    """A node literally named `end` — the text grammar's terminal sentinel."""
    dlg = p["data/dialogues/dlg_meet.json"]
    dlg["nodes"][1]["id"] = "end"
    dlg["nodes"][0]["choices"][0]["goto"] = "end"


def case_variable_default_kind_mismatch(p: dict) -> None:
    """A flag whose default is a string."""
    p["data/variables.json"]["variables"][0]["default"] = "yes"


def case_quest_mutex_no_cycle(p: dict) -> None:
    """Two mutually exclusive quests — a legitimate choose-one, not a cycle."""
    p["data/variables.json"]["variables"].extend([
        {"default": False, "description": "Path A taken.", "id": "took_a", "kind": "flag"},
        {"default": False, "description": "Path B taken.", "id": "took_b", "kind": "flag"},
    ])
    for tag, other in (("a", "b"), ("b", "a")):
        p[f"data/quests/qst_path_{tag}.json"] = {
            "availableWhen": {
                "of": {"flag": f"took_{other}", "type": "flag", "value": True},
                "type": "not",
            },
            "id": f"qst_path_{tag}",
            "name": f"Path {tag.upper()}",
            "outcomes": [{
                "description": f"You committed to path {tag.upper()}.",
                "id": f"out_{tag}",
                "kind": "success",
            }],
            "stages": [{
                "completeWhen": {"flag": "heard_story", "type": "flag", "value": True},
                "description": f"Walk path {tag.upper()}.",
                "id": f"stg_{tag}",
                "objectives": [{"id": f"ob_{tag}", "text": f"Commit to path {tag.upper()}."}],
                "onComplete": [{"flag": f"took_{tag}", "type": "set_flag", "value": True}],
                "order": 1,
            }],
            "summary": f"The {tag.upper()} route.",
        }


def case_dialogue_island_unreachable(p: dict) -> None:
    """Nodes wired to each other but not to the entry."""
    dlg = p["data/dialogues/dlg_meet.json"]
    dlg["nodes"].extend([
        {
            "choices": [{"goto": "node_island_b", "id": "ch_x", "text": "Onward."}],
            "id": "node_island_a",
            "text": "An island.",
        },
        {
            "choices": [{"goto": "node_island_a", "id": "ch_y", "text": "Back."}],
            "id": "node_island_b",
            "text": "The other half of the island.",
        },
    ])


# ---------------------------------------------------------------------------
# Shared fragments for the cases below.
# ---------------------------------------------------------------------------

def _flag(p: dict, vid: str, description: str, **extra) -> None:
    p["data/variables.json"]["variables"].append(
        {"default": False, "description": description, "id": vid, "kind": "flag", **extra}
    )


def _add_choice(p: dict, **choice) -> None:
    """Append a choice to the base dialogue's entry node.

    The entry node keeps its ungated `ch_listen`, so adding a gated choice
    beside it never trips the all-choices-are-showIf FLOW warning — the seeded
    defect stays the only finding.
    """
    p["data/dialogues/dlg_meet.json"]["nodes"][0]["choices"].append(choice)


def _errand_quest(**overrides) -> dict:
    """A small, otherwise-clean quest: trigger, one stage, one outcome."""
    quest = {
        "id": "qst_errand",
        "name": "A Small Errand",
        "outcomes": [{
            "description": "You heard the keeper out.",
            "id": "out_done",
            "kind": "success",
            "reachedWhen": {"flag": "heard_story", "type": "flag", "value": True},
        }],
        "stages": [{
            "completeWhen": {"flag": "heard_story", "type": "flag", "value": True},
            "description": "You listened.",
            "id": "stg_listen",
            "objectives": [{"id": "ob_listen", "text": "Hear the keeper out."}],
            "order": 1,
        }],
        "startsAvailable": True,
        "summary": "Hear the keeper out.",
    }
    quest.update(overrides)
    return quest


# ---------------------------------------------------------------------------
# Cases for issue-code families that had no shared case at all.
# ---------------------------------------------------------------------------

def case_passive_check_kind_ignored(p: dict) -> None:
    """`kind` on a PASSIVE check — the runtime ignores it, so saying it lies.

    A passive check never rolls, so there is no pass/fail to price. The rule is
    the whole CHECK family's canary: everything else in that pass keys off the
    same mode/kind split.
    """
    _add_choice(
        p,
        check={"difficulty": 4, "kind": "priced", "mode": "passive", "skill": "observation"},
        goto="node_close",
        id="ch_notice",
        text="[Observation] The ledger is open.",
    )


def case_character_no_dialogue(p: dict) -> None:
    """A character nothing speaks for and no ladder presents."""
    p["data/characters/npc_silent.json"] = {
        "archetype": "bystander",
        "id": "npc_silent",
        "name": "The Silent One",
    }


def case_cutscene_enters_dialogue_dangling(p: dict) -> None:
    """A cutscene handing off to a dialogue that does not exist.

    Played by the finale node, so the cutscene is referenced — the dangling
    hand-off is the only defect, not the unused-cutscene warning beside it.
    """
    p["data/cutscenes/cs_recap.json"] = {
        "asset": "cutscenes/recap",
        "effectsOnComplete": [],
        "entersDialogue": "dlg_ghost",
        "id": "cs_recap",
        "name": "Recap",
        "skippable": True,
    }
    p["data/dialogues/dlg_meet.json"]["nodes"][1]["onEnter"].append(
        {"cutscene": "cs_recap", "type": "play_cutscene"}
    )


def case_flag_read_never_set(p: dict) -> None:
    """A gate reading a declared flag that no effect ever sets."""
    _flag(p, "saw_ledger", "The player has seen the ledger.")
    _add_choice(
        p,
        goto="node_close",
        id="ch_ledger",
        showIf={"flag": "saw_ledger", "type": "flag", "value": True},
        text="Mention the ledger.",
    )


def case_exit_spawn_not_in_target(p: dict) -> None:
    """A door pointing at a spawn the target location does not declare."""
    p["data/locations/loc_yard.json"] = {
        "exits": [{"id": "ex_north", "to": {"location": "loc_hall", "spawn": "sp_typo"}}],
        "id": "loc_yard",
        "name": "The Yard",
        "spawns": [{"id": "sp_gate", "isDefault": True}],
        "tags": ["start"],
    }
    p["data/locations/loc_hall.json"] = {
        "id": "loc_hall",
        "name": "The Hall",
        "spawns": [{"id": "sp_south", "isDefault": True}],
    }


def case_faction_opposes_itself(p: dict) -> None:
    """A faction listed among its own opponents."""
    p["data/factions/fac_villagers.json"]["opposes"] = ["fac_villagers"]


def case_duplicate_objective_id(p: dict) -> None:
    """Two journal objectives in one stage sharing an id."""
    quest = _errand_quest()
    quest["stages"][0]["objectives"] = [
        {"id": "ob_listen", "text": "Hear the keeper out."},
        {"id": "ob_listen", "text": "Hear them out again."},
    ]
    p["data/quests/qst_errand.json"] = quest


def case_character_portrait_dangling(p: dict) -> None:
    """A character pointing at a portrait no registry declares."""
    p["data/characters/npc_keeper.json"]["portrait"] = "por_ghost"


def case_progression_thresholds_not_increasing(p: dict) -> None:
    """XP thresholds that plateau — levelForXp would stop being a function."""
    p["data/progression.json"] = {
        "maxSkill": 5,
        "pointsPerLevel": 1,
        "startingSkills": {},
        "xpThresholds": [0, 100, 100],
    }


def case_relationship_read_never_adjusted(p: dict) -> None:
    """Standing with a character gates a choice, but nothing ever moves it."""
    _add_choice(
        p,
        goto="node_close",
        id="ch_trusted",
        showIf={"character": "npc_keeper", "op": ">=", "type": "relationship", "value": 1},
        text="Speak as a friend.",
    )


def case_reputation_read_never_adjusted(p: dict) -> None:
    """Faction standing gates a choice, but nothing ever moves it."""
    _add_choice(
        p,
        goto="node_close",
        id="ch_known",
        showIf={"faction": "fac_villagers", "op": ">=", "type": "reputation", "value": 1},
        text="Trade on your good name.",
    )


def case_snapshot_unknown_quest(p: dict) -> None:
    """A test baseline pinned to a quest that no longer exists.

    Lives under tests/, not data/ — a shipping game never reads it, which is
    exactly why a stale id here rots unnoticed.
    """
    p["tests/snapshots/snap_start.json"] = {
        "id": "snap_start",
        "name": "Start",
        "schemaVersion": 1,
        "state": {
            "counters": {},
            "flags": {},
            "inventory": [],
            "questStages": {"qst_ghost": "stg_one"},
            "reputation": {},
            "skills": {},
        },
    }


def case_text_placeholder_undeclared(p: dict) -> None:
    """A `{placeholder}` naming no registered variable — renders raw."""
    p["data/dialogues/dlg_meet.json"]["nodes"][0]["text"] = (
        "The keeper looks up at {player_name}."
    )


def case_grant_xp_nonpositive(p: dict) -> None:
    """A reward that rewards nothing.

    Quest-free on purpose: the XP-convention advisory stays silent in a project
    with no quests, so the non-positive-amount rule is the only XP finding.
    """
    p["data/dialogues/dlg_meet.json"]["nodes"][1]["onEnter"].append(
        {"amount": 0, "type": "grant_xp"}
    )


def case_loreref_unicode_form(p: dict) -> None:
    """A loreRef whose accented name is in the other Unicode form from the file.

    Not a defect. macOS can hand back a decomposed name (NFD: "e" + U+0301)
    while git commits and Linux/Windows store it composed (NFC: "\u00e9"). Both
    forms name the same file, so both validators accept either — before this,
    the reference read as missing on Linux and in CI but not on the Mac that
    wrote it, and the two validators disagreed there.
    """
    p["lore/caf\u00e9.md"] = Text("# Caf\u00e9\n\nWhere the keeper drinks.\n")
    p["data/characters/npc_keeper.json"]["loreRef"] = {"file": "lore/cafe\u0301.md"}


def case_loreref_file_missing(p: dict) -> None:
    """A pointer into the canon that no longer resolves."""
    p["data/characters/npc_keeper.json"]["loreRef"] = {"file": "lore/keeper.md"}


def case_ending_flag_never_set(p: dict) -> None:
    """An ending gated on a flag no effect anywhere writes — unwinnable."""
    _flag(p, "burned_ledger", "The ledger was burned.")
    p["data/endings/end_ashes.json"] = {
        "id": "end_ashes",
        "name": "Ashes",
        "summary": "Nothing is left to read.",
        "unlockedBy": {"flag": "burned_ledger", "type": "flag", "value": True},
    }


def case_codex_flag_never_set(p: dict) -> None:
    """A codex entry gated on a flag no effect anywhere writes."""
    _flag(p, "read_ledger", "The ledger was read.")
    p["data/codex/cdx_ledger.json"] = {
        "body": "Columns of names, and one crossed out.",
        "id": "cdx_ledger",
        "name": "The Ledger",
        "unlockedBy": {"flag": "read_ledger", "type": "flag", "value": True},
    }


def case_quest_circular_dependency(p: dict) -> None:
    """Two quests each waiting on the other's completion flag — neither opens.

    The positive counterpart of `quest-mutex-no-cycle`: same two-quest shape,
    but gated on the other quest being DONE rather than NOT done, which is a
    real cycle and must be reported.
    """
    _flag(p, "alpha_done", "Alpha is finished.")
    _flag(p, "beta_done", "Beta is finished.")
    for tag, other in (("alpha", "beta"), ("beta", "alpha")):
        p[f"data/quests/qst_{tag}.json"] = {
            "availableWhen": {"flag": f"{other}_done", "type": "flag", "value": True},
            "id": f"qst_{tag}",
            "name": tag.capitalize(),
            "outcomes": [{
                "description": f"{tag.capitalize()} is behind you.",
                "id": f"out_{tag}",
                "kind": "success",
                "reachedWhen": {"flag": f"{tag}_done", "type": "flag", "value": True},
            }],
            "stages": [{
                "completeWhen": {"flag": "heard_story", "type": "flag", "value": True},
                "description": f"You finished {tag}.",
                "id": f"stg_{tag}",
                "objectives": [{"id": f"ob_{tag}", "text": f"Finish {tag}."}],
                "onComplete": [{"flag": f"{tag}_done", "type": "set_flag", "value": True}],
                "order": 1,
            }],
            "summary": f"The {tag} errand.",
        }


# ---------------------------------------------------------------------------
# Negative cases — legitimate constructions a rule must NOT flag. These are what
# stop a future fix from over-firing; the positive cases alone cannot.
# ---------------------------------------------------------------------------

def case_check_difficulty_at_max_roll(p: dict) -> None:
    """A difficulty exactly equal to the maximum roll — hard, not impossible.

    Pins the boundary of the dice-aware reachability warning: `>` not `>=`. A
    20 on 1d20 passes a difficulty-20 check with skill 0.
    """
    _add_choice(
        p,
        check={
            "difficulty": 20,
            "mode": "active",
            "onFailure": "node_close",
            "onSuccess": "node_close",
            "skill": "observation",
        },
        id="ch_precise",
        text="[Observation] Read the room exactly.",
    )


def case_default_spawn_unused_ok(p: dict) -> None:
    """The default arrival point, which by definition no exit names.

    Pins the exemption in the unused-spawn warning: `isDefault` is the marker,
    not a magic spawn id, and a lone start location must stay clean.
    """
    p["data/locations/loc_hall.json"] = {
        "id": "loc_hall",
        "name": "The Hall",
        "spawns": [{"id": "sp_main", "isDefault": True}],
        "tags": ["start"],
    }


def case_engine_written_flag(p: dict) -> None:
    """A flag the HOST writes at runtime, read by an authored gate.

    `writtenBy: "engine"` is how data declares that boundary; Parlance has no
    input-capture concept, so there is no authored effect to find. The hygiene
    pass must stay quiet rather than inviting a fake set_flag to silence it.
    """
    _flag(p, "player_named", "The host captured a name.", writtenBy="engine")
    _add_choice(
        p,
        goto="node_close",
        id="ch_named",
        showIf={"flag": "player_named", "type": "flag", "value": True},
        text="Give your name.",
    )


def case_xp_from_quest_outcome(p: dict) -> None:
    """XP granted where the convention says it belongs — on a quest outcome.

    The advisory fires on grants authored anywhere else, and only in a project
    that has quests; this pins the exemption it is built around.
    """
    quest = _errand_quest()
    quest["outcomes"][0]["effects"] = [{"amount": 10, "type": "grant_xp"}]
    p["data/quests/qst_errand.json"] = quest


def case_ending_via_quest_outcome_unreachable(p: dict) -> None:
    """An ending gated on a quest OUTCOME whose own condition can never hold.

    Reachability has to resolve THROUGH `questOutcome` into that outcome's
    `reachedWhen`. Stop at the outcome and the ending looks flag-free, so the
    check silently passes and the ENDING rule stops meaning anything for every
    outcome-gated finale — which is most of them.

    This is the POSITIVE half of the pair, and it is the half with teeth: a
    validator that stops resolving through questOutcome goes quieter, not
    louder, so `ending-via-quest-outcome` below cannot catch it on its own. A
    mutation probe proved exactly that — disabling the resolution survived the
    whole suite until this case existed.
    """
    _flag(p, "never_happens", "A thing that never happens.")
    quest = _errand_quest()
    quest["outcomes"] = [{
        "description": "The thing that never happens happened.",
        "id": "out_lost",
        "kind": "failure",
        "reachedWhen": {"flag": "never_happens", "type": "flag", "value": True},
    }]
    p["data/quests/qst_errand.json"] = quest
    p["data/endings/end_lost.json"] = {
        "id": "end_lost",
        "name": "Lost",
        "summary": "It never came to pass.",
        "unlockedBy": {"outcome": "out_lost", "quest": "qst_errand", "type": "questOutcome"},
    }


def case_ending_via_quest_outcome(p: dict) -> None:
    """An ending gated on a quest OUTCOME that IS satisfiable.

    The mirror of `ending-via-quest-outcome-unreachable`: resolving through the
    outcome must not turn a perfectly reachable finale into a warning.
    """
    p["data/quests/qst_errand.json"] = _errand_quest()
    p["data/endings/end_told.json"] = {
        "id": "end_told",
        "name": "The Story Told",
        "summary": "You carry it with you.",
        "unlockedBy": {"outcome": "out_done", "quest": "qst_errand", "type": "questOutcome"},
    }


# ---------------------------------------------------------------------------
# Cases pinning drifts this suite found. Each one is a rule the two
# implementations disagreed about until it was written down here.
# ---------------------------------------------------------------------------

def case_exit_spawn_into_spawnless_location(p: dict) -> None:
    """A door into a location that declares NO spawns at all.

    Found as a drift: the Python validator exempted spawnless targets, so an
    exit could name any spawn there and CI stayed silent while the editor
    reported the door. Cutscene `arrivesAt` already errors on a spawnless
    target, so exempting exits let the two transition kinds disagree about the
    same doorway.
    """
    p["data/locations/loc_yard.json"] = {
        "exits": [{"id": "ex_north", "to": {"location": "loc_hall", "spawn": "sp_anything"}}],
        "id": "loc_yard",
        "name": "The Yard",
        "spawns": [{"id": "sp_gate", "isDefault": True}],
        "tags": ["start"],
    }
    p["data/locations/loc_hall.json"] = {"id": "loc_hall", "name": "The Hall"}


def case_snapshot_stale_questfired(p: dict) -> None:
    """A baseline that remembers firing a quest the project no longer has.

    Found as a drift: only the TypeScript validator parsed `questFired` keys. A
    stale key does not fail loudly — it just stops matching, and a route from
    this baseline re-fires a once-only effect the real game would not.
    """
    p["tests/snapshots/snap_mid.json"] = {
        "id": "snap_mid",
        "name": "Mid-run",
        "schemaVersion": 1,
        "state": {
            "counters": {},
            "flags": {},
            "inventory": [],
            "questFired": ["qst_ghost/stage/stg_one"],
            "questStages": {},
            "reputation": {},
            "skills": {},
        },
    }


def case_snapshot_relationship_dangling(p: dict) -> None:
    """A baseline carrying standing with a character who does not exist.

    Found as a drift: the Python validator walked a snapshot's flags, counters,
    inventory, skills and reputation but not its `relationships`, `texts` or
    `skillPointsSpent`.
    """
    p["tests/snapshots/snap_known.json"] = {
        "id": "snap_known",
        "name": "Known Locally",
        "schemaVersion": 1,
        "state": {
            "counters": {},
            "flags": {},
            "inventory": [],
            "questStages": {},
            "relationships": {"npc_ghost": 3},
            "reputation": {},
            "skills": {},
        },
    }


def case_xp_node_named_outcome(p: dict) -> None:
    """A grant_xp on a DIALOGUE node whose id happens to contain "outcome".

    Found as a drift: the Python advisory asked whether the word "outcome"
    appeared in its own message, so renaming a node was enough to silence it
    while the editor kept reporting. The exemption is structural — where the
    effect was authored — not a substring of the report.
    """
    dlg = p["data/dialogues/dlg_meet.json"]
    dlg["nodes"][1]["id"] = "node_outcome"
    dlg["nodes"][0]["choices"][0]["goto"] = "node_outcome"
    dlg["nodes"][1]["onEnter"].append({"amount": 5, "type": "grant_xp"})
    # The advisory is silent in a quest-free project, so the project needs one.
    p["data/quests/qst_errand.json"] = _errand_quest()



# ---------------------------------------------------------------------------
# COND — conditional narration (tooling/NODE_CONDITIONS_SPEC.md)
# ---------------------------------------------------------------------------

def _cond_gate() -> dict:
    return {"flag": "met_keeper", "type": "flag", "value": True}


def case_cond_node_showif_clean(p: dict) -> None:
    """A LEGAL conditional node: gated, has next, no choices, no isEnd.

    The positive case matters as much as the seeded defects. A rule that fires on
    correct data is worse than one that never fires, because it trains authors to
    ignore the code.
    """
    dlg = p["data/dialogues/dlg_meet.json"]
    dlg["nodes"].insert(1, {
        "id": "node_aside",
        "showIf": _cond_gate(),
        "text": "You have been here before, and they know it.",
        "next": "node_close",
    })
    dlg["nodes"][0]["choices"][0]["goto"] = "node_aside"


def case_cond_showif_without_next(p: dict) -> None:
    """showIf on an INTERSTITIAL node with nowhere to go when the gate fails.

    Neither choices nor isEnd, so a failed gate skips it — and there is no
    `next` to skip to. (Until the line-only gate landed this case seeded
    node_close, an isEnd node; that shape is legal now, see
    cond-showif-isend-clean.)
    """
    dlg = p["data/dialogues/dlg_meet.json"]
    dlg["nodes"].insert(1, {
        "id": "node_aside",
        "showIf": _cond_gate(),
        "text": "You have been here before, and they know it.",
    })
    dlg["nodes"][0]["choices"][0]["goto"] = "node_aside"


def case_cond_showif_with_choices(p: dict) -> None:
    """A LEGAL gate on a node that offers choices: it hides the LINE only.

    The node is still reached, its choices are still offered and its onEnter
    still fires — so no COND error, and no "do NOT fire" advisory either. This
    was a COND error before the line-only gate; the clean case pins that the
    rule is gone from BOTH validators, not just one.
    """
    dlg = p["data/dialogues/dlg_meet.json"]
    dlg["nodes"][0]["showIf"] = _cond_gate()      # node_open carries choices AND onEnter


def case_cond_showif_isend_clean(p: dict) -> None:
    """A LEGAL gate on an isEnd node: the line hides, the dialogue still ends."""
    dlg = p["data/dialogues/dlg_meet.json"]
    dlg["nodes"][1]["showIf"] = _cond_gate()      # node_close: isEnd, carries onEnter


def case_cond_empty_text_with_choices(p: dict) -> None:
    """A gate on a choice node with NO line — nothing to hide."""
    dlg = p["data/dialogues/dlg_meet.json"]
    dlg["nodes"][0]["showIf"] = _cond_gate()
    del dlg["nodes"][0]["text"]


def case_textless_choices_clean(p: dict) -> None:
    """A text-less node that offers choices — the option-block shape (legal)."""
    dlg = p["data/dialogues/dlg_meet.json"]
    del dlg["nodes"][0]["text"]


def case_textless_no_choices(p: dict) -> None:
    """A node with neither text nor choices — nothing to present."""
    dlg = p["data/dialogues/dlg_meet.json"]
    del dlg["nodes"][1]["text"]                   # node_close: isEnd, no choices


def _gated_choice(cid: str, goto: str = "node_close") -> dict:
    return {"goto": goto, "id": cid, "showIf": _cond_gate(), "text": "Only if they know you."}


def case_choice_fallback_clean(p: dict) -> None:
    """Every regular choice is gated, and one ungated fallback covers the gap.

    Without the fallback this node gets the FLOW "may be stuck" warning; the
    fallback proves it cannot strand anyone, so the warning must NOT fire.
    """
    node = p["data/dialogues/dlg_meet.json"]["nodes"][0]
    node["choices"] = [
        _gated_choice("ch_know"),
        {"fallback": True, "goto": "node_close", "id": "ch_leave", "text": "Leave."},
    ]


def case_choice_fallback_gated_still_stuck(p: dict) -> None:
    """A fallback that is ITSELF gated proves nothing — the warning stands."""
    node = p["data/dialogues/dlg_meet.json"]["nodes"][0]
    node["choices"] = [
        _gated_choice("ch_know"),
        {"fallback": True, "goto": "node_close", "id": "ch_leave",
         "showIf": {"flag": "heard_story", "type": "flag", "value": True}, "text": "Leave."},
    ]


def case_choice_fallback_duplicate(p: dict) -> None:
    """Two fallbacks on one node — they show together; one is enough."""
    node = p["data/dialogues/dlg_meet.json"]["nodes"][0]
    node["choices"] = [
        _gated_choice("ch_know"),
        {"fallback": True, "goto": "node_close", "id": "ch_leave", "text": "Leave."},
        {"fallback": True, "goto": "node_close", "id": "ch_wait", "text": "Wait."},
    ]


def case_choice_fallback_pointless(p: dict) -> None:
    """A fallback beside no gated sibling — it is always offered, the flag does nothing."""
    node = p["data/dialogues/dlg_meet.json"]["nodes"][0]
    node["choices"].append({"fallback": True, "goto": "node_close", "id": "ch_leave", "text": "Leave."})


def _passive_choice(cid: str = "ch_notice", **extra) -> dict:
    return {"check": {"difficulty": 6, "mode": "passive", "skill": "observation"},
            "goto": "node_close", "id": cid, "text": "[Observation] Notice the ledger.", **extra}


def case_choice_passive_only_fallback_suppressed(p: dict) -> None:
    """Every non-fallback choice is a passive check, beside a fallback (D13).

    The runtime counts a passive choice as visible whenever its showIf passes —
    the reveal is the game's display rule — so the fallback is suppressed while
    a game that hides the unrevealed passive shows nothing clickable. The
    passive choice is gated so the fallback is not also "pointless": one defect.
    """
    node = p["data/dialogues/dlg_meet.json"]["nodes"][0]
    node["choices"] = [
        _passive_choice(showIf=_cond_gate()),
        {"fallback": True, "goto": "node_close", "id": "ch_leave", "text": "Leave."},
    ]


def case_choice_passive_only_no_fallback(p: dict) -> None:
    """The node's only choice is a passive check, with no fallback at all (D13)."""
    p["data/dialogues/dlg_meet.json"]["nodes"][0]["choices"] = [_passive_choice()]


def case_choice_passive_beside_plain_clean(p: dict) -> None:
    """A passive check beside an ordinary choice: something is always clickable."""
    _add_choice(p, **_passive_choice())


def case_choice_locked_clean(p: dict) -> None:
    """A gated choice shown locked with its own lockedText, and a project default (legal)."""
    p["data/rules.json"] = {"choices": {"whenLockedDefault": "show"}}
    node = p["data/dialogues/dlg_meet.json"]["nodes"][0]
    node["choices"].append({
        "goto": "node_close", "id": "ch_ledger", "lockedText": "[Requires the keeper's trust]",
        "showIf": _cond_gate(), "text": "Ask about the ledger.", "whenLocked": "show",
    })


def case_choice_locked_without_showif(p: dict) -> None:
    """whenLocked/lockedText on a choice with no gate — it can never be locked."""
    node = p["data/dialogues/dlg_meet.json"]["nodes"][0]
    node["choices"][0]["whenLocked"] = "show"
    node["choices"][0]["lockedText"] = "[Locked]"


def case_node_unknown_key(p: dict) -> None:
    """A node carrying a key the schema does not declare (`foo: 1`).

    Every `schema/*.json` says `additionalProperties: false` and the Python
    reference always enforced it, but the editor's zod objects were passthrough
    (adversarial review A3): a misspelled optional field — `isend`, `showif` —
    was a silent no-op in the editor and a SCHEMA error in CI. Seeded in a
    separate, speakerless, offer-less dialogue for the same reason as
    choice-when-locked-invalid: Python drops a schema-invalid file from every
    later rule, so seeding dlg_meet would fan out into python-only FLAG/CODEX/
    ENDING noise that says nothing about this rule.
    """
    p["data/dialogues/dlg_extra.json"] = {
        "entry": "n1",
        "id": "dlg_extra",
        "nodes": [{"foo": 1, "id": "n1", "isEnd": True, "text": "Well?"}],
        "title": "Extra",
    }


def case_choice_when_locked_invalid(p: dict) -> None:
    """whenLocked outside its enum — a schema error, not a runtime guess.

    Seeded in a SEPARATE dialogue that sets no flags: the Python reference drops
    a schema-invalid file from every later rule, while the TypeScript guard keeps
    a shape-safe one in the pass, so seeding dlg_meet would cascade into a
    python-only FLAG/CODEX/ENDING fan-out that says nothing about this rule.
    """
    p["data/dialogues/dlg_extra.json"] = {
        "entry": "n1",
        "id": "dlg_extra",
        "nodes": [{
            "id": "n1", "isEnd": True, "text": "Well?",
            "choices": [
                {"id": "c_ok", "text": "Fine."},
                {"id": "c_locked", "showIf": _cond_gate(), "text": "Tell me.", "whenLocked": "grey"},
            ],
        }],
        "speakerId": "npc_keeper",
        "title": "Extra",
    }


def case_choice_locked_text_placeholder_undeclared(p: dict) -> None:
    """lockedText is player-facing and interpolated, so its placeholders are checked too."""
    node = p["data/dialogues/dlg_meet.json"]["nodes"][0]
    node["choices"][0]["showIf"] = _cond_gate()
    node["choices"][0]["whenLocked"] = "show"
    node["choices"][0]["lockedText"] = "[Requires {no_such_var}]"


def case_cond_empty_text(p: dict) -> None:
    """A gated node with no words — a conditional effects BLOCK.

    `text` is required but unconstrained, so "" is legal; with showIf and
    onEnter it becomes `if (cond) { effects }`, the construct the spec's §10
    names as a non-goal. Rejected as an error so it never becomes an idiom.
    """
    dlg = p["data/dialogues/dlg_meet.json"]
    dlg["nodes"].insert(1, {
        "id": "node_silent",
        "showIf": _cond_gate(),
        "text": "",
        "next": "node_close",
        "onEnter": [{"flag": "heard_story", "type": "set_flag", "value": True}],
    })
    dlg["nodes"][0]["choices"][0]["goto"] = "node_silent"


def case_cond_cycle(p: dict) -> None:
    """Two gated nodes pointing at each other — resolution cannot escape."""
    dlg = p["data/dialogues/dlg_meet.json"]
    dlg["nodes"].insert(1, {"id": "node_a", "showIf": _cond_gate(),
                            "text": "Round.", "next": "node_b"})
    dlg["nodes"].insert(2, {"id": "node_b", "showIf": _cond_gate(),
                            "text": "And round.", "next": "node_a"})
    dlg["nodes"][0]["choices"][0]["goto"] = "node_a"


def case_cond_effects_advisory(p: dict) -> None:
    """A gated node carrying onEnter — the effects silently do not fire."""
    dlg = p["data/dialogues/dlg_meet.json"]
    dlg["nodes"].insert(1, {
        "id": "node_aside",
        "showIf": _cond_gate(),
        "text": "They almost say something.",
        "next": "node_close",
        "onEnter": [{"flag": "heard_story", "type": "set_flag", "value": True}],
    })
    dlg["nodes"][0]["choices"][0]["goto"] = "node_aside"


# ---------------------------------------------------------------------------
# OFFER family (ws 17) — the saliency-model equivalents of the LADDER cases.
# Each converts npc_keeper from a ladder to self-declaring dialogue offers.
# ---------------------------------------------------------------------------

def _minimal_dialogue(did: str, text: str, offer: dict) -> dict:
    return {
        "entry": "n1",
        "id": did,
        "nodes": [{"id": "n1", "isEnd": True, "text": text}],
        "offer": offer,
        "speakerId": "npc_keeper",
        "title": did,
    }


def case_offer_no_fallback(p: dict) -> None:
    """A character whose every offer is gated — resolution can return null."""
    p["data/characters/npc_keeper.json"].pop("dialogues", None)
    p["data/dialogues/dlg_meet.json"]["offer"] = {"when": {"flag": "met_keeper", "type": "flag", "value": True}}


def case_offer_prioritized_fallback(p: dict) -> None:
    """An offer with a priority tier but no `when` — wins forever, re-fires."""
    p["data/characters/npc_keeper.json"].pop("dialogues", None)
    p["data/dialogues/dlg_meet.json"]["offer"] = {"priority": 1}


def case_offer_tie(p: dict) -> None:
    """Two offers of equal priority and specificity that are not exclusive —
    the id silently decides which wins. A fallback is present so the no-fallback
    rule stays quiet and this pins the tie rule on its own."""
    p["data/characters/npc_keeper.json"].pop("dialogues", None)
    p["data/dialogues/dlg_meet.json"]["offer"] = {"when": {"flag": "heard_story", "type": "flag", "value": True}}
    p["data/dialogues/dlg_aside.json"] = _minimal_dialogue(
        "dlg_aside", "Something else.", {"when": {"flag": "met_keeper", "type": "flag", "value": True}}
    )
    p["data/dialogues/dlg_greet.json"] = _minimal_dialogue("dlg_greet", "Hello again.", {})


def case_flag_exclusive_group_set_together(p: dict) -> None:
    """Two flags of one exclusive group (rules.flag.exclusiveGroups) set to
    true in the SAME effect list — an error in both validators (FLAG). The
    rule landed in both validators at once (#118) with no case, which is
    exactly the drift the harness exists to catch: a rule that stops firing
    in one of them looks like clean data."""
    p["data/rules.json"] = {"flag": {"exclusiveGroups": [["met_keeper", "heard_story"]]}}
    p["data/dialogues/dlg_meet.json"]["nodes"][0]["onEnter"].append(
        {"flag": "heard_story", "type": "set_flag", "value": True}
    )


def case_flag_exclusive_group_set_apart(p: dict) -> None:
    """The same group, with its flags set in different nodes: exclusivity is
    about one effect list, so this is clean — the rule must not fire across
    lists, or every group would be an error somewhere."""
    p["data/rules.json"] = {"flag": {"exclusiveGroups": [["met_keeper", "heard_story"]]}}


def case_offer_numeric_exclusive_no_tie(p: dict) -> None:
    """Three characters, each with a family of equal-specificity offers the
    oracle must prove pairwise exclusive, so NO tie warning: the keeper's
    sequence on one counter (`== 0` / `== 1` / `== 2`), a `not flag` against
    its flag, and an item held / not held. Fallbacks keep the no-fallback rule
    quiet. Offers of different characters never tie with each other, which is
    why each family gets its own character — a counter gate and an item gate on
    ONE character are a real tie."""
    p["data/characters/npc_keeper.json"].pop("dialogues", None)
    p["data/variables.json"]["variables"].append(
        {"id": "keeper_talks", "kind": "counter", "default": 0, "description": "Times the keeper has been talked to."}
    )
    p["data/items.json"] = {"items": [{"id": "it_token", "name": "Token", "description": "A token."}]}
    p["data/characters/npc_flagged.json"] = {"id": "npc_flagged", "name": "Flagged"}
    p["data/characters/npc_holder.json"] = {"id": "npc_holder", "name": "Holder"}
    cnt = lambda v: {"counter": "keeper_talks", "op": "==", "type": "counter", "value": v}  # noqa: E731
    p["data/dialogues/dlg_meet.json"]["offer"] = {"when": cnt(0)}
    p["data/dialogues/dlg_meet.json"]["nodes"][-1].setdefault("onEnter", []).append(
        {"counter": "keeper_talks", "delta": 1, "type": "adjust_counter"}
    )
    p["data/dialogues/dlg_second.json"] = _minimal_dialogue("dlg_second", "Second.", {"when": cnt(1)})
    p["data/dialogues/dlg_third.json"] = _minimal_dialogue("dlg_third", "Third.", {"when": cnt(2)})
    p["data/dialogues/dlg_greet.json"] = _minimal_dialogue("dlg_greet", "Hello again.", {})
    p["data/dialogues/dlg_unmet.json"] = _minimal_dialogue(
        "dlg_unmet", "Unmet.",
        {"character": "npc_flagged", "when": {"of": {"flag": "met_keeper", "type": "flag", "value": True}, "type": "not"}},
    )
    p["data/dialogues/dlg_met.json"] = _minimal_dialogue(
        "dlg_met", "Met.", {"character": "npc_flagged", "when": {"flag": "met_keeper", "type": "flag", "value": True}}
    )
    p["data/dialogues/dlg_flagged_default.json"] = _minimal_dialogue("dlg_flagged_default", "Hm.", {"character": "npc_flagged"})
    p["data/dialogues/dlg_token.json"] = _minimal_dialogue(
        "dlg_token", "Token.", {"character": "npc_holder", "when": {"has": True, "item": "it_token", "type": "item"}}
    )
    p["data/dialogues/dlg_no_token.json"] = _minimal_dialogue(
        "dlg_no_token", "No token.", {"character": "npc_holder", "when": {"has": False, "item": "it_token", "type": "item"}}
    )
    p["data/dialogues/dlg_holder_default.json"] = _minimal_dialogue("dlg_holder_default", "Hm.", {"character": "npc_holder"})


def case_offer_numeric_overlap_ties(p: dict) -> None:
    """Two ranges of one counter that OVERLAP (`>= 5` and `>= 10`) are not
    exclusive: at 10 both pass at equal specificity, so the tie warning must
    still fire. Guards the numeric oracle against over-eager exclusivity."""
    p["data/characters/npc_keeper.json"].pop("dialogues", None)
    p["data/variables.json"]["variables"].append(
        {"id": "keeper_talks", "kind": "counter", "default": 0, "description": "Times the keeper has been talked to."}
    )
    p["data/dialogues/dlg_meet.json"]["offer"] = {
        "when": {"counter": "keeper_talks", "op": ">=", "type": "counter", "value": 5}
    }
    p["data/dialogues/dlg_meet.json"]["nodes"][-1].setdefault("onEnter", []).append(
        {"counter": "keeper_talks", "delta": 1, "type": "adjust_counter"}
    )
    p["data/dialogues/dlg_regular.json"] = _minimal_dialogue(
        "dlg_regular", "Regular.", {"when": {"counter": "keeper_talks", "op": ">=", "type": "counter", "value": 10}}
    )
    p["data/dialogues/dlg_greet.json"] = _minimal_dialogue("dlg_greet", "Hello again.", {})


def _route_from_meet(p: dict, target: str) -> None:
    """Put a set_active_dialogue effect for npc_keeper naming `target` on the
    keeper's meeting scene, and declare the flag the effect writes."""
    p["data/variables.json"]["variables"].append(
        {"id": "active_dialogue__npc_keeper", "kind": "flag", "default": False,
         "description": "Engine-written: routes the keeper to a queued scene."}
    )
    p["data/dialogues/dlg_meet.json"]["nodes"][-1].setdefault("onEnter", []).append(
        {"character": "npc_keeper", "dialogue": target, "type": "set_active_dialogue"}
    )


def case_active_dialogue_target_not_forced(p: dict) -> None:
    """set_active_dialogue names a dialogue that carries no offer for the routed
    character gated on active_dialogue__<character>: the flag routes nothing
    and the queued scene never plays. Both validators warn (OFFER); the
    presenter matches, so no LOGIC mismatch."""
    p["data/characters/npc_keeper.json"].pop("dialogues", None)
    p["data/dialogues/dlg_meet.json"]["offer"] = {}
    p["data/dialogues/dlg_later.json"] = _minimal_dialogue(
        "dlg_later", "Later.", {"when": {"flag": "heard_story", "type": "flag", "value": True}}
    )
    _route_from_meet(p, "dlg_later")


def case_active_dialogue_forced_outranked(p: dict) -> None:
    """The forced offer exists but sits at tier 0 beside a more specific
    ordinary offer, so while the flag is set the ordinary one wins the ranking
    and routing plays the wrong scene. Both validators warn (OFFER)."""
    p["data/characters/npc_keeper.json"].pop("dialogues", None)
    p["data/dialogues/dlg_meet.json"]["offer"] = {}
    p["data/dialogues/dlg_forced.json"] = _minimal_dialogue(
        "dlg_forced", "Forced.", {"when": {"flag": "active_dialogue__npc_keeper", "type": "flag", "value": True}}
    )
    p["data/dialogues/dlg_specific.json"] = _minimal_dialogue(
        "dlg_specific", "Specific.",
        {"when": {"of": [
            {"flag": "met_keeper", "type": "flag", "value": True},
            {"flag": "heard_story", "type": "flag", "value": True},
        ], "type": "all"}},
    )
    _route_from_meet(p, "dlg_forced")


def case_active_dialogue_cross_character_forced(p: dict) -> None:
    """The contract-blessed cross-character forced pattern: a scene SPOKEN by
    the guide but OFFERED FOR the keeper, at tier 1, gated on the keeper's
    routing flag. Neither a LOGIC speaker mismatch nor an OFFER warning."""
    p["data/characters/npc_keeper.json"].pop("dialogues", None)
    p["data/characters/npc_guide.json"] = {"id": "npc_guide", "name": "Guide"}
    p["data/dialogues/dlg_meet.json"]["offer"] = {}
    d = _minimal_dialogue(
        "dlg_handoff", "The guide steps in.",
        {"character": "npc_keeper", "priority": 1,
         "when": {"flag": "active_dialogue__npc_keeper", "type": "flag", "value": True}},
    )
    d["speakerId"] = "npc_guide"
    p["data/dialogues/dlg_handoff.json"] = d
    p["data/dialogues/dlg_guide_default.json"] = _minimal_dialogue("dlg_guide_default", "Hm.", {"character": "npc_guide"})
    _route_from_meet(p, "dlg_handoff")


def case_offer_outcome_gate_reads_flags(p: dict) -> None:
    """An offer gated on a questOutcome reads, transitively, every flag that
    outcome's reachedWhen reads — through a `not`, too. A flag that is set in a
    scene and read ONLY that way is live state, not dead: no FLAG warning."""
    p["data/characters/npc_keeper.json"].pop("dialogues", None)
    p["data/variables.json"]["variables"].append(
        {"id": "saw_omen", "kind": "flag", "default": False, "description": "The player saw the omen."}
    )
    p["data/dialogues/dlg_meet.json"]["offer"] = {}
    p["data/dialogues/dlg_meet.json"]["nodes"][-1].setdefault("onEnter", []).append(
        {"flag": "saw_omen", "type": "set_flag", "value": True}
    )
    quest = _errand_quest()
    quest["outcomes"][0]["reachedWhen"] = {
        "of": {"flag": "saw_omen", "type": "flag", "value": False}, "type": "not"
    }
    p["data/quests/qst_errand.json"] = quest
    p["data/dialogues/dlg_aside.json"] = _minimal_dialogue(
        "dlg_aside", "After the omen.", {"when": {"outcome": "out_done", "quest": "qst_errand", "type": "questOutcome"}}
    )


def case_offer_character_dangling(p: dict) -> None:
    """offer.character names a character that does not exist."""
    p["data/characters/npc_keeper.json"].pop("dialogues", None)
    p["data/dialogues/dlg_meet.json"]["offer"] = {"character": "npc_ghost"}


def case_offer_character_covers(p: dict) -> None:
    """A character with no speaking part and no ladder, but who is the
    offer.character of a dialogue, counts as covered (ws 17) — no COVERAGE."""
    p["data/characters/npc_keeper.json"].pop("dialogues", None)
    p["data/characters/player.json"] = {"id": "player", "name": "Player"}
    p["data/dialogues/dlg_meet.json"]["offer"] = {"character": "player"}


def case_migrate_character_dialogues(p: dict) -> None:
    """A stale project still carrying the retired character `dialogues` ladder —
    MIGRATE names the script, and the bare additionalProperties reject is
    suppressed so the message is actionable (ws 17)."""
    p["data/characters/npc_keeper.json"]["dialogues"] = [{"dialogue": "dlg_meet"}]


def case_offer_no_character(p: dict) -> None:
    """A dialogue that opts in with an offer but has neither speakerId nor
    offer.character — nothing ever gathers it (ws 17)."""
    p["data/dialogues/dlg_nobody.json"] = {
        "entry": "node_a",
        "id": "dlg_nobody",
        "nodes": [{"id": "node_a", "isEnd": True, "text": "Spoken by no one, offered to no one."}],
        "offer": {},
    }


def case_custom_entity_valid(p: dict) -> None:
    """A custom entity type with valid definitions and references."""
    p["data/types.json"] = {
        "spell": {
            "name": "Spell",
            "plural": "spells",
            "fields": {
                "manaCost": {"type": "number", "default": 10},
                "element": {"type": "enum", "options": ["fire", "ice", "lightning"]},
                "grantedBy": {"type": "reference", "target": "character"},
            },
        }
    }
    p["data/spells/fireball.json"] = {
        "id": "fireball",
        "name": "Fireball",
        "manaCost": 15,
        "element": "fire",
        "grantedBy": "npc_keeper",
    }


def case_custom_entity_missing_field(p: dict) -> None:
    """A custom entity missing a required field."""
    p["data/types.json"] = {
        "spell": {
            "name": "Spell",
            "plural": "spells",
            "fields": {
                "manaCost": {"type": "number", "required": True},
            },
        }
    }
    p["data/spells/fireball.json"] = {
        "id": "fireball",
        "name": "Fireball",
    }


# ---- custom-entity STORAGE shapes -------------------------------------------
# The editor's grid reads and writes custom rows in every shape the loaders
# accept: one file per row (nested zones allowed), a {"<plural>": [...]} array
# registry, and an id-keyed object registry — and each is written back in its own
# shape. A clean case cannot prove a loader FOUND the rows (zero rows is also
# clean), so each seeds one dangling reference that only fires if they loaded.

_SPELL_TYPE = {
    "spell": {
        "name": "Spell",
        "plural": "spells",
        "fields": {"grantedBy": {"type": "reference", "target": "character"}},
    }
}


def case_custom_entity_registry_array(p: dict) -> None:
    """Custom rows in a data/<plural>.json array registry are loaded and checked."""
    p["data/types.json"] = _SPELL_TYPE
    p["data/spells.json"] = {"spells": [
        {"id": "fireball", "grantedBy": "npc_keeper"},
        {"id": "frostbite", "grantedBy": "npc_gone"},
    ]}


def case_custom_entity_registry_keyed(p: dict) -> None:
    """Custom rows in an id-keyed object registry (keys need not equal ids) are loaded and checked."""
    p["data/types.json"] = _SPELL_TYPE
    p["data/spells.json"] = {
        "fb": {"id": "fireball", "grantedBy": "npc_keeper"},
        "fr": {"id": "frostbite", "grantedBy": "npc_gone"},
    }


def case_custom_entity_nested_directory(p: dict) -> None:
    """Custom rows filed in nested zone folders under data/<plural>/ are loaded and checked."""
    p["data/types.json"] = _SPELL_TYPE
    p["data/spells/act_one/fireball.json"] = {"id": "fireball", "grantedBy": "npc_keeper"}
    p["data/spells/act_two/north/frostbite.json"] = {"id": "frostbite", "grantedBy": "npc_gone"}


def case_custom_entity_default_plural(p: dict) -> None:
    """A type declared with no plural — or an empty one — is stored under <id>s."""
    p["data/types.json"] = {
        "spell": {"name": "Spell", "fields": {"grantedBy": {"type": "reference", "target": "character"}}},
        "rune": {"name": "Rune", "plural": "", "fields": {"carvedBy": {"type": "reference", "target": "character"}}},
    }
    p["data/spells/frostbite.json"] = {"id": "frostbite", "grantedBy": "npc_gone"}
    p["data/runes/ember.json"] = {"id": "ember", "carvedBy": "npc_lost"}


def case_custom_entity_cross_type_reference(p: dict) -> None:
    """A custom type referencing another custom type, singly and as a list; one list item dangles."""
    p["data/types.json"] = {
        "spell": {"name": "Spell", "plural": "spells", "fields": {}},
        "school": {
            "name": "School",
            "plural": "schools",
            "fields": {
                "signature": {"type": "reference", "target": "spell"},
                "teaches": {"type": "array", "items": {"type": "reference", "target": "spell"}},
            },
        },
    }
    p["data/spells/fireball.json"] = {"id": "fireball"}
    p["data/schools/embers.json"] = {"id": "embers", "signature": "fireball", "teaches": ["fireball", "frostbite"]}


def case_custom_entity_field_types(p: dict) -> None:
    """Values of the wrong type in every scalar field kind, and a non-list in a list field."""
    p["data/types.json"] = {
        "spell": {
            "name": "Spell",
            "plural": "spells",
            "fields": {
                "manaCost": {"type": "number"},
                "ritual": {"type": "boolean"},
                "element": {"type": "enum", "options": ["fire", "ice"]},
                "incantation": {"type": "string"},
                "reagents": {"type": "array", "items": {"type": "string"}},
            },
        }
    }
    p["data/spells/fireball.json"] = {
        "id": "fireball",
        "manaCost": "15",
        "ritual": 1,
        "element": "water",
        "incantation": 7,
        "reagents": "ash",
    }


def case_types_declaration_plurals(p: dict) -> None:
    """Declarations whose plural escapes data/, collides with a built-in folder, or with another type."""
    p["data/types.json"] = {
        "spell": {"name": "Spell", "plural": "../escape", "fields": {}},
        "rumour": {"name": "Rumour", "plural": "dialogues", "fields": {}},
        "rune": {"name": "Rune", "plural": "glyphs", "fields": {}},
        "sigil": {"name": "Sigil", "plural": "glyphs", "fields": {}},
    }


def case_types_declaration_plural_portability(p: dict) -> None:
    """Plurals that collide only on a case-insensitive disk (macOS, Windows), a
    Windows device name, and a trailing newline a `$` regex would admit."""
    p["data/types.json"] = {
        "rune": {"name": "Rune", "plural": "glyphs", "fields": {}},
        "sigil": {"name": "Sigil", "plural": "Glyphs", "fields": {}},
        "rumour": {"name": "Rumour", "plural": "Dialogues", "fields": {}},
        "device": {"name": "Device", "plural": "aux", "fields": {}},
        "trail": {"name": "Trail", "plural": "trails\n", "fields": {}},
    }


def case_types_declaration_fields(p: dict) -> None:
    """Field declarations that silently misbehave, and a type named after a built-in target."""
    p["data/types.json"] = {
        "character": {"name": "Hero", "plural": "heroes", "fields": {}},
        "spell": {
            "name": "Spell",
            "plural": "spells",
            "fields": {
                "element": {"type": "enum", "options": []},
                "power": {"type": "float"},
                "caster": {"type": "reference"},
                "school": {"type": "reference", "target": "school"},
                "combos": {"type": "array", "items": {"type": "reference", "target": "combo"}},
                "notes": "text",
            },
        },
    }


def case_types_declaration_not_object(p: dict) -> None:
    """A declaration that is not an object, and one whose fields are not an object."""
    p["data/types.json"] = {
        "spell": "a spell",
        "rune": {"name": "Rune", "plural": "runes", "fields": ["power"]},
    }
    p["data/runes/ember.json"] = {"id": "ember"}


def case_custom_entity_prototype_keys(p: dict) -> None:
    """'__proto__' as a type id and as a row id are ordinary keys: loaded and checked like any other."""
    p["data/types.json"] = {
        "__proto__": {"name": "Proto", "plural": "protos", "fields": {"owner": {"type": "reference", "target": "character"}}},
    }
    p["data/protos/p1.json"] = {"id": "__proto__", "owner": "npc_gone"}


def case_custom_entity_bad_reference(p: dict) -> None:
    """A custom entity with a dangling reference."""
    p["data/types.json"] = {
        "spell": {
            "name": "Spell",
            "plural": "spells",
            "fields": {
                "grantedBy": {"type": "reference", "target": "character"},
            },
        }
    }
    p["data/spells/fireball.json"] = {
        "id": "fireball",
        "name": "Fireball",
        "grantedBy": "npc_missing",
    }


def case_offer_forced_only_is_not_a_gap(p: dict) -> None:
    """A routing-only character: its one offer is forced through
    active_dialogue__npc_keeper, so "no fallback" is the design, not a defect —
    the no-fallback OFFER warning must stay silent (ws 17)."""
    p["data/variables.json"]["variables"].append({
        "default": False,
        "description": "Routing flag: the keeper's scene has been queued (set by set_active_dialogue).",
        "id": "active_dialogue__npc_keeper",
        "kind": "flag",
    })
    p["data/dialogues/dlg_meet.json"]["offer"] = {
        "priority": 1,
        "when": {"flag": "active_dialogue__npc_keeper", "type": "flag", "value": True},
    }
    # Something must route there, or the flag is a FLAG read-never-set warning.
    p["data/dialogues/dlg_aside.json"] = {
        "entry": "node_a",
        "id": "dlg_aside",
        "nodes": [{
            "id": "node_a",
            "isEnd": True,
            "onEnter": [{"character": "npc_keeper", "dialogue": "dlg_meet", "type": "set_active_dialogue"}],
            "text": "Go and see the keeper.",
        }],
        "offer": {},
        "speakerId": "npc_keeper",
    }


def case_offer_interactable_not_noop(p: dict) -> None:
    """An npc interactable whose character has an OFFER is NOT a no-op — the
    interactable-source check reads offers (ws 17)."""
    p["data/dialogues/dlg_meet.json"]["offer"] = {}
    p["data/locations/loc_hall.json"] = {
        "id": "loc_hall",
        "interactables": [{"character": "npc_keeper", "id": "ix_keeper", "kind": "npc"}],
        "name": "The Hall",
        "spawns": [{"id": "sp_main", "isDefault": True}],
        "tags": ["start"],
    }


def case_binding_clean(p: dict) -> None:
    """A binding whose VO keys all match voiceable node text — clean.

    The whole BIND family (validate.py check_bindings) had NO conformance case.
    It is python-only by construction: asset bindings are not part of the
    TypeScript project model, so there is nothing for validate() to check.
    Without a case, a used_vo_keys derivation that silently stopped populating
    would read as clean data — the exact drift the harness exists to catch."""
    p["data/bindings/godot.json"] = {
        "profile": "godot",
        "vo": {
            "dialogue/dlg_meet/nodes/node_open/text": "res://vo/open.ogg",
            "dialogue/dlg_meet/nodes/node_close/text": "res://vo/close.ogg",
        },
    }


def case_binding_vo_dangling(p: dict) -> None:
    """A VO binding for a key that no node produces — check_bindings must flag
    it dangling. The two real node-text keys are also bound, so the only BIND
    finding is the dangling one (no unbound noise). Guards the used_vo_keys
    derivation from the other side: if it emptied, every real key here would be
    called dangling instead, and this assertion would still fail loudly."""
    p["data/bindings/godot.json"] = {
        "profile": "godot",
        "vo": {
            "dialogue/dlg_meet/nodes/node_open/text": "res://vo/open.ogg",
            "dialogue/dlg_meet/nodes/node_close/text": "res://vo/close.ogg",
            "dialogue/dlg_meet/nodes/node_ghost/text": "res://vo/ghost.ogg",
        },
    }


# ---------------------------------------------------------------------------
# 0.15 — tags on lines and choices; engine commands (the `engine` effect).
# ---------------------------------------------------------------------------

def case_tags_on_lines_clean(p: dict) -> None:
    """node.tags and choice.tags are opaque pass-through: no rule reads them.

    Both validators must ACCEPT the shape (a schema that forgot the field would
    reject the whole dialogue as SCHEMA), and neither may invent a finding for
    a tag — including one that happens to equal an entity id.
    """
    dlg = p["data/dialogues/dlg_meet.json"]
    dlg["nodes"][0]["tags"] = ["mood:angry", "sfx:door", "npc_keeper"]
    dlg["nodes"][0]["choices"][0]["tags"] = ["tone:calm", "two words"]


def _engine(p: dict, effect: dict, rules: dict | None = None) -> None:
    p["data/dialogues/dlg_meet.json"]["nodes"][1]["onEnter"].append(effect)
    if rules is not None:
        p["data/rules.json"] = rules


ENGINE_RULES = {"engine": {"commands": {"shake": {"args": 1, "description": "camera shake (intensity)"}, "sfx": {"args": "any"}}}}


def case_engine_command_declared_clean(p: dict) -> None:
    """A declared engine command with the declared argument count: no finding.

    The effect changes no state, reads no id, and is returned to the engine in
    order among the other effects — so it must not trip FLAG/REF hygiene either.
    """
    _engine(p, {"type": "engine", "command": "shake", "args": [0.5]}, ENGINE_RULES)
    _engine(p, {"type": "engine", "command": "sfx", "args": ["door_slam", 0.8, True]})


def case_engine_command_undeclared(p: dict) -> None:
    """A typo'd command once the project declares its vocabulary: a warning,
    because at runtime the engine silently ignores a name it does not know."""
    _engine(p, {"type": "engine", "command": "shaek", "args": [0.5]}, ENGINE_RULES)


def case_engine_command_bad_name(p: dict) -> None:
    """A command that is not lowercase snake_case: an error, with or without a
    declared vocabulary (no rules.json here — the name rule stands alone)."""
    _engine(p, {"type": "engine", "command": "Shake-Camera"})


def case_engine_command_arg_count(p: dict) -> None:
    """A declared command called with the wrong number of arguments."""
    _engine(p, {"type": "engine", "command": "shake", "args": [0.5, 2]}, ENGINE_RULES)


def case_engine_command_undeclared_prototype_name(p: dict) -> None:
    """An undeclared command whose name is an Object.prototype member
    (`constructor`, valid snake_case). A lookup that reads through the
    prototype chain calls it declared; the vocabulary is the project's own
    keys only, so it must warn exactly like any other undeclared name."""
    _engine(p, {"type": "engine", "command": "constructor"}, ENGINE_RULES)


def case_engine_command_undeclared_vocabulary_ok(p: dict) -> None:
    """No rules.engine.commands: any snake_case command is accepted silently."""
    _engine(p, {"type": "engine", "command": "anything_goes", "args": ["x", 1, False]})


# ---- Malformed-but-plausible shapes (E4 / A3 audit) ------------------------
# Each is a file a script or an agent writes: valid JSON, wrong shape. Both
# validators must report a SCHEMA error and keep going — never a traceback on
# the Python side, never a thrown validate() on the TypeScript side.

def case_id_trailing_newline(p: dict) -> None:
    """An entity id with a trailing newline. ^[a-z][a-z0-9_]*$ REJECTS it in
    every JavaScript engine and, under Python's re.search, ACCEPTED it — `$`
    also matches before a final newline there. The reference validator now
    evaluates schema patterns with ECMA-262 anchoring, so both sides agree."""
    p["data/characters/npc_keeper.json"]["id"] = "npc_keeper\n"


def case_types_json_array(p: dict) -> None:
    """data/types.json as an array of declarations instead of an object keyed
    by type id. The reference used to skip it silently."""
    p["data/types.json"] = [{"name": "Spell", "plural": "spells"}]


def case_custom_row_id_not_snake_case(p: dict) -> None:
    """A custom row whose id is not lowercase snake_case. No JSON Schema
    describes a custom row, so the loader applies the id pattern by hand — the
    id becomes a filename and a URL segment, and the editor refuses to write
    one like this. The row is still registered so the reference to it holds."""
    p["data/types.json"] = {
        "spell": {"name": "Spell", "plural": "spells",
                  "fields": {"grantedBy": {"type": "reference", "target": "character"}}},
    }
    p["data/spells/fireball.json"] = {"id": "Fire Ball", "grantedBy": "npc_keeper"}


def case_progression_thresholds_not_numbers(p: dict) -> None:
    """xpThresholds holding a string. The schema rejects it; the ordering rule
    must not then compare a string to an integer (a TypeError, until it did
    not run over non-numbers)."""
    p["data/progression.json"] = {
        "maxSkill": 5,
        "pointsPerLevel": 1,
        "startingSkills": {},
        "xpThresholds": ["a", 1],
    }


def case_registry_entries_not_array(p: dict) -> None:
    """skills.json whose `skills` is null rather than an array — what a script
    writes when it has nothing to say. Used to be a TypeError on the loader's
    for-loop, before any pass ran."""
    p["data/skills.json"] = {"skills": None}


def case_quest_stages_null_referenced(p: dict) -> None:
    """A quest whose `stages` is null, reached through a VALID dialogue's
    advance_quest. The quest fails its schema; the dialogue's REF check then
    reads the quest's stage ids and must find none rather than iterate null."""
    p["data/quests/qst_errand.json"] = {
        "id": "qst_errand", "name": "The Errand", "stages": None,
        "summary": "Fetch something for the keeper.",
    }
    p["data/dialogues/dlg_meet.json"]["nodes"][-1]["onEnter"].append(
        {"quest": "qst_errand", "toStage": "stg_go", "type": "advance_quest"}
    )


def case_loreref_not_object(p: dict) -> None:
    """A loreRef written as the bare path string instead of {"file": ...}. The
    LORE rule used to index the string with ["file"] — a TypeError."""
    p["data/characters/npc_keeper.json"]["loreRef"] = "lore/keeper.md"


def case_engine_command_trailing_newline(p: dict) -> None:
    """An engine command name with a trailing newline. The ENGINE name rule is
    a hand-rolled regex on both sides; a `.match` against `^...$` admitted the
    newline in Python while the same regex rejected it in JavaScript."""
    _engine(p, {"type": "engine", "command": "shake\n"})


def case_route_unknown_dialogue(p: dict) -> None:
    """A route whose entry dialogue does not exist. Lives under tests/, so a
    shipping game never reads it — which is why a stale id rots unnoticed."""
    p["tests/routes/rt_ghost.json"] = {
        "id": "rt_ghost",
        "dialogueId": "dlg_ghost",
        "steps": [{"choiceId": "ch_listen"}],
    }


def case_route_unknown_choice(p: dict) -> None:
    """A route step naming a choice the dialogue does not offer."""
    p["tests/routes/rt_meet.json"] = {
        "id": "rt_meet",
        "dialogueId": "dlg_meet",
        "steps": [{"choiceId": "ch_ghost"}],
    }


CASE_BUILDERS = {
    "clean-minimal": (case_clean_minimal, {"noErrors": True}),
    "utf8-bom-loaded": (
        case_utf8_bom_loaded,
        {"noErrors": True,
         "mustNot": [{"code": "SCHEMA"}, {"code": "REF"}, {"code": "FLAG"}]},
    ),
    "passive-goto-dangling": (
        case_passive_goto_dangling,
        {"must": [{"code": "REF", "contains": "node_typo", "severity": "error"}]},
    ),
    "project-rules-bad-dice": (
        case_project_rules_bad_dice,
        {"must": [{"code": "RULES", "contains": "2x6", "severity": "error"}]},
    ),
    "advance-quest-unknown": (
        case_advance_quest_unknown,
        {"must": [{"code": "REF", "contains": "qst_ghost", "severity": "error"}]},
    ),
    "duplicate-node-id": (
        case_duplicate_node_id,
        {"must": [{"code": "DUP", "contains": "node_open", "severity": "error"}]},
    ),
    "npc-interactable-dialogue-places": (
        case_npc_interactable_dialogue_places,
        {
            # The advisory proves the shape is present and exercised...
            "must": [{"code": "LOC", "contains": "did you mean character", "severity": "warning"}],
            # ...and the placement suppresses the stranded warning in BOTH validators.
            "mustNot": [{"code": "OFFER", "contains": "dlg_aside"}],
        },
    ),
    "plain-goto-dangling": (
        case_plain_goto_dangling,
        {"must": [{"code": "REF", "contains": "node_typo", "severity": "error",
                   "at": {"entityType": "dialogue", "entityId": "dlg_meet", "path": "nodes/node_open/choices/ch_leave"}}]},
    ),
    "dead-end-node": (
        case_dead_end_node,
        {"must": [{"code": "FLOW", "contains": "dead end", "severity": "error",
                   "at": {"entityType": "dialogue", "entityId": "dlg_meet", "path": "nodes/node_open/choices/ch_nowhere"}}]},
    ),
    "offer-when-dangling": (
        case_offer_when_dangling,
        {"must": [{"code": "REF", "contains": "ghost_flag", "severity": "error"}]},
    ),
    "cutscene-sets-ending-flag": (
        case_cutscene_sets_ending_flag,
        {"noErrors": True, "mustNot": [{"code": "ENDING"}, {"code": "CODEX"}]},
    ),
    "dup-id-registry": (
        case_dup_id_registry,
        {
            # Python-only by construction: the TypeScript validator is handed an
            # id-keyed ProjectData, so a duplicate id has already collapsed
            # before validate() sees it. That check lives in the loader there
            # (projectStorage.loadAll), not in the rule set.
            "validators": ["python"],
            "must": [{"code": "DUP", "contains": "met_keeper", "severity": "error"}],
        },
    ),
    "malformed-dice": (
        case_malformed_dice,
        {"must": [{"code": "RULES", "contains": "2x6", "severity": "error"}]},
    ),
    "difficulty-exceeds-dice": (
        case_difficulty_exceeds_dice,
        {"must": [{"code": "GATE", "contains": "difficulty", "severity": "warning"}]},
    ),
    "dice-too-many": (
        case_dice_too_many,
        {"must": [{"code": "RULES", "contains": "'101d6': at most 100 dice", "severity": "error"}]},
    ),
    "dice-too-many-sides": (
        case_dice_too_many_sides,
        {"must": [{"code": "RULES", "contains": "'1d1001': a die has at most 1000 sides", "severity": "error"}]},
    ),
    "offer-tie-capped": (
        case_offer_tie_capped,
        {"noErrors": True,
         "must": [
             {"code": "OFFER", "contains": "offers 'dlg_tie_a' and 'dlg_tie_b' have equal priority", "severity": "warning"},
             {"code": "OFFER", "contains": "5 more offer pair(s) share a priority and specificity and were not checked", "severity": "warning"},
         ],
         "mustNot": [{"code": "OFFER", "contains": "offers 'dlg_tie_d' and 'dlg_tie_f'"}]},
    ),
    "check-modifier-clean": (
        case_check_modifier_clean,
        {"noErrors": True, "mustNot": [{"code": "GATE"}, {"code": "CHECK"}]},
    ),
    "check-modifier-when-dangling": (
        case_check_modifier_when_dangling,
        {"must": [{"code": "REF", "contains": "modifier 0", "severity": "error"}]},
    ),
    "check-modifier-zero-bonus": (
        case_check_modifier_zero_bonus,
        {"must": [{"code": "CHECK", "contains": "bonus 0", "severity": "warning",
                   "at": {"entityType": "dialogue", "entityId": "dlg_meet", "path": "nodes/node_open/choices/ch_mod/check"}}]},
    ),
    "check-priced-failure-sets-offer-flag": (
        case_check_priced_failure_sets_offer_flag,
        {"must": [{"code": "CHECK", "contains": "punishment-spiral", "severity": "warning",
                   "at": {"entityType": "dialogue", "entityId": "dlg_meet", "path": "nodes/node_open/choices/ch_press/check"}}]},
    ),
    "check-modifier-empty": (
        case_check_modifier_empty,
        {"must": [{"code": "CHECK", "contains": "empty modifiers", "severity": "warning"}]},
    ),
    "check-difficulty-reachable-with-bonus": (
        case_check_difficulty_reachable_with_bonus,
        {"mustNot": [{"code": "GATE", "contains": "exceeds max roll"}]},
    ),
    "check-difficulty-exceeds-dice-plus-bonus": (
        case_check_difficulty_exceeds_dice_plus_bonus,
        {"must": [{"code": "GATE", "contains": "even with +2 from modifiers", "severity": "warning"}]},
    ),
    "node-id-end": (
        case_node_id_end,
        {"must": [{"code": "FLOW", "contains": "reserved", "severity": "error"}]},
    ),
    "variable-default-kind-mismatch": (
        case_variable_default_kind_mismatch,
        {"must": [{"code": "SCHEMA", "contains": "default does not match kind", "severity": "error"}]},
    ),
    "quest-mutex-no-cycle": (
        case_quest_mutex_no_cycle,
        {"noErrors": True, "mustNot": [{"code": "QUEST", "contains": "circular"}]},
    ),
    "dialogue-island-unreachable": (
        case_dialogue_island_unreachable,
        {"must": [{"code": "REACH", "contains": "unreachable", "severity": "warning",
                   "at": {"entityType": "dialogue", "entityId": "dlg_meet", "path": "nodes/node_island_a"}}]},
    ),

    # -- One case per issue-code family that had no shared case at all --------
    "passive-check-kind-ignored": (
        case_passive_check_kind_ignored,
        {"must": [{"code": "CHECK", "contains": "on a passive check is ignored", "severity": "warning"}]},
    ),
    "character-no-dialogue": (
        case_character_no_dialogue,
        {"must": [{"code": "COVERAGE", "contains": "npc_silent", "severity": "warning"}]},
    ),
    "cutscene-enters-dialogue-dangling": (
        case_cutscene_enters_dialogue_dangling,
        {"must": [{"code": "CUT", "contains": "dlg_ghost", "severity": "error"}]},
    ),
    "flag-read-never-set": (
        case_flag_read_never_set,
        {"must": [{"code": "FLAG", "contains": "saw_ledger", "severity": "warning",
                   "at": {"entityType": "variable", "entityId": "saw_ledger", "path": None}}]},
    ),
    "exit-spawn-not-in-target": (
        case_exit_spawn_not_in_target,
        {"must": [{"code": "LOC", "contains": "sp_typo", "severity": "error",
                   "at": {"entityType": "location", "entityId": "loc_yard", "path": "exits/ex_north"}}]},
    ),
    "faction-opposes-itself": (
        case_faction_opposes_itself,
        {"must": [{"code": "LOGIC", "contains": "opposes itself", "severity": "warning"}]},
    ),
    "duplicate-objective-id": (
        case_duplicate_objective_id,
        {"must": [{"code": "OBJ", "contains": "duplicate objective id", "severity": "error",
                   "at": {"entityType": "quest", "entityId": "qst_errand", "path": "stages/stg_listen/objectives/ob_listen"}}]},
    ),
    "character-portrait-dangling": (
        case_character_portrait_dangling,
        {"must": [{"code": "PORT", "contains": "por_ghost", "severity": "error"}]},
    ),
    "progression-thresholds-not-increasing": (
        case_progression_thresholds_not_increasing,
        {"must": [{"code": "PROG", "contains": "strictly increasing", "severity": "error"}]},
    ),
    "relationship-read-never-adjusted": (
        case_relationship_read_never_adjusted,
        {"must": [{"code": "REL", "contains": "never adjusted", "severity": "warning",
                   "at": {"entityType": "character", "entityId": "npc_keeper", "path": None}}]},
    ),
    "reputation-read-never-adjusted": (
        case_reputation_read_never_adjusted,
        {"must": [{"code": "REP", "contains": "never adjusted", "severity": "warning",
                   "at": {"entityType": "faction", "entityId": "fac_villagers", "path": None}}]},
    ),
    "snapshot-unknown-quest": (
        case_snapshot_unknown_quest,
        {"must": [{"code": "SNAP", "contains": "qst_ghost", "severity": "error"}]},
    ),
    "text-placeholder-undeclared": (
        case_text_placeholder_undeclared,
        {"must": [{"code": "TEXT", "contains": "player_name", "severity": "error",
                   "at": {"entityType": "dialogue", "entityId": "dlg_meet", "path": "nodes/node_open/text"}}]},
    ),
    "grant-xp-nonpositive": (
        case_grant_xp_nonpositive,
        {"must": [{"code": "XP", "contains": "should be positive", "severity": "warning"}]},
    ),
    "loreref-unicode-form": (
        case_loreref_unicode_form,
        {"noErrors": True, "mustNot": [{"code": "LORE"}]},
    ),
    "loreref-file-missing": (
        case_loreref_file_missing,
        {"must": [{"code": "LORE", "contains": "loreRef file 'lore/keeper.md' missing", "severity": "error"}]},
    ),
    "ending-flag-never-set": (
        case_ending_flag_never_set,
        {"must": [{"code": "ENDING", "contains": "burned_ledger", "severity": "warning"}]},
    ),
    "codex-flag-never-set": (
        case_codex_flag_never_set,
        {"must": [{"code": "CODEX", "contains": "read_ledger", "severity": "warning"}]},
    ),
    "quest-circular-dependency": (
        case_quest_circular_dependency,
        {"must": [{"code": "QUEST", "contains": "circular dependency", "severity": "error"}]},
    ),
    "ending-via-quest-outcome-unreachable": (
        case_ending_via_quest_outcome_unreachable,
        {"must": [{"code": "ENDING", "contains": "never_happens", "severity": "warning"}]},
    ),

    # -- Negative cases: legitimate shapes a rule must not flag ---------------
    "check-difficulty-at-max-roll": (
        case_check_difficulty_at_max_roll,
        {"noErrors": True, "mustNot": [{"code": "GATE", "contains": "exceeds max roll"}]},
    ),
    "default-spawn-unused-ok": (
        case_default_spawn_unused_ok,
        {"noErrors": True, "mustNot": [{"code": "LOC"}]},
    ),
    "engine-written-flag": (
        case_engine_written_flag,
        {"noErrors": True, "mustNot": [{"code": "FLAG", "contains": "player_named"}]},
    ),
    "xp-from-quest-outcome": (
        case_xp_from_quest_outcome,
        {"noErrors": True, "mustNot": [{"code": "XP"}]},
    ),
    "ending-via-quest-outcome": (
        case_ending_via_quest_outcome,
        {"noErrors": True, "mustNot": [{"code": "ENDING", "contains": "end_told"}]},
    ),

    # -- Drifts this suite found, pinned so they cannot come back -------------
    "exit-spawn-into-spawnless-location": (
        case_exit_spawn_into_spawnless_location,
        {"must": [{"code": "LOC", "contains": "sp_anything", "severity": "error"}]},
    ),
    "snapshot-stale-questfired": (
        case_snapshot_stale_questfired,
        {"must": [{"code": "SNAP", "contains": "questFired unknown quest 'qst_ghost'", "severity": "error"}]},
    ),
    "snapshot-relationship-dangling": (
        case_snapshot_relationship_dangling,
        {"must": [{"code": "REF", "contains": "npc_ghost", "severity": "error"}]},
    ),
    "xp-node-named-outcome": (
        case_xp_node_named_outcome,
        {"must": [{"code": "XP", "contains": "outside a quest outcome", "severity": "warning"}]},
    ),

    # -- COND: conditional narration (tooling/NODE_CONDITIONS_SPEC.md) -------
    "cond-node-showif-clean": (
        case_cond_node_showif_clean,
        {"noErrors": True, "mustNot": [{"code": "COND", "contains": "node_aside"}]},
    ),
    "cond-showif-without-next": (
        case_cond_showif_without_next,
        {"must": [{"code": "COND", "contains": "no 'next'", "severity": "error"}]},
    ),
    # Line-only gates (0.15): a gate on a node with choices or isEnd is LEGAL —
    # it hides the line, never the node — so these two are clean baselines that
    # also pin the absence of the onEnter advisory (those effects DO fire).
    "cond-showif-with-choices": (
        case_cond_showif_with_choices,
        {"noErrors": True,
         "mustNot": [{"code": "COND"}, {"code": "FLOW"}]},
    ),
    "cond-showif-isend-clean": (
        case_cond_showif_isend_clean,
        {"noErrors": True,
         "mustNot": [{"code": "COND"}]},
    ),
    "cond-empty-text-with-choices": (
        case_cond_empty_text_with_choices,
        {"must": [{"code": "COND", "contains": "no line to hide", "severity": "error"}]},
    ),
    "textless-choices-clean": (
        case_textless_choices_clean,
        {"noErrors": True, "mustNot": [{"code": "FLOW"}, {"code": "SCHEMA"}]},
    ),
    "textless-no-choices": (
        case_textless_no_choices,
        {"must": [{"code": "FLOW", "contains": "no text and no choices", "severity": "error"}]},
    ),
    "choice-fallback-clean": (
        case_choice_fallback_clean,
        {"noErrors": True, "mustNot": [{"code": "FLOW"}]},
    ),
    "choice-fallback-gated-still-stuck": (
        case_choice_fallback_gated_still_stuck,
        {"must": [{"code": "FLOW", "contains": "may be stuck", "severity": "warning"}]},
    ),
    "choice-fallback-duplicate": (
        case_choice_fallback_duplicate,
        {"must": [{"code": "FLOW", "contains": "fallback choices", "severity": "warning"}],
         "mustNot": [{"code": "FLOW", "contains": "may be stuck"}]},
    ),
    "choice-fallback-pointless": (
        case_choice_fallback_pointless,
        {"must": [{"code": "FLOW", "contains": "no gated sibling", "severity": "warning"}]},
    ),
    "choice-passive-only-fallback-suppressed": (
        case_choice_passive_only_fallback_suppressed,
        {"noErrors": True,
         "must": [{"code": "FLOW", "contains": "every non-fallback choice is a passive check ('ch_notice')", "severity": "warning"},
                  {"code": "FLOW", "contains": "fallback 'ch_leave' is suppressed", "severity": "warning"}],
         "mustNot": [{"code": "FLOW", "contains": "no gated sibling"}, {"code": "FLOW", "contains": "may be stuck"}]},
    ),
    "choice-passive-only-no-fallback": (
        case_choice_passive_only_no_fallback,
        {"noErrors": True,
         "must": [{"code": "FLOW", "contains": "there is no fallback", "severity": "warning"}]},
    ),
    "choice-passive-beside-plain-clean": (
        case_choice_passive_beside_plain_clean,
        {"noErrors": True, "mustNot": [{"code": "FLOW"}]},
    ),
    "choice-locked-clean": (
        case_choice_locked_clean,
        {"noErrors": True, "mustNot": [{"code": "FLOW"}, {"code": "TEXT"}, {"code": "RULES"}, {"code": "SCHEMA"}]},
    ),
    "choice-locked-without-showif": (
        case_choice_locked_without_showif,
        {"must": [{"code": "FLOW", "contains": "can never be locked", "severity": "warning"}]},
    ),
    "choice-when-locked-invalid": (
        case_choice_when_locked_invalid,
        {"must": [{"code": "SCHEMA", "severity": "error"}]},
    ),
    "node-unknown-key": (
        case_node_unknown_key,
        {"must": [{"code": "SCHEMA", "contains": "'foo'", "severity": "error",
                   # zod's dialect: array positions, not ids (lib/issueNav resolves them).
                   "at": {"entityType": "dialogue", "entityId": "dlg_extra", "path": "nodes/0"}}]},
    ),
    "choice-locked-text-placeholder-undeclared": (
        case_choice_locked_text_placeholder_undeclared,
        {"must": [{"code": "TEXT", "contains": "no_such_var", "severity": "error"}]},
    ),
    "cond-empty-text": (
        case_cond_empty_text,
        {"must": [{"code": "COND", "contains": "empty text", "severity": "error"}]},
    ),
    "cond-cycle": (
        case_cond_cycle,
        {"must": [{"code": "COND", "contains": "cycle among conditional nodes", "severity": "error"}]},
    ),
    "cond-effects-advisory": (
        case_cond_effects_advisory,
        {"must": [{"code": "COND", "contains": "do NOT fire", "severity": "warning"}]},
    ),
    "offer-no-fallback": (
        case_offer_no_fallback,
        {"must": [{"code": "OFFER", "contains": "none is unconditional", "severity": "warning"}]},
    ),
    "offer-prioritized-fallback": (
        case_offer_prioritized_fallback,
        {"must": [{"code": "OFFER", "contains": "priority 1 but no 'when'", "severity": "warning"}]},
    ),
    "offer-tie": (
        case_offer_tie,
        {"must": [{"code": "OFFER", "contains": "not provably exclusive", "severity": "warning"}]},
    ),
    "flag-exclusive-group-set-together": (
        case_flag_exclusive_group_set_together,
        {"must": [{"code": "FLAG", "contains": "mutually-exclusive flags simultaneously", "severity": "error"}]},
    ),
    "flag-exclusive-group-set-apart": (
        case_flag_exclusive_group_set_apart,
        {"noErrors": True, "mustNot": [{"code": "FLAG", "contains": "mutually-exclusive"}]},
    ),
    "binding-clean": (
        case_binding_clean,
        {"validators": ["python"], "noErrors": True, "mustNot": [{"code": "BIND"}]},
    ),
    "binding-vo-dangling": (
        case_binding_vo_dangling,
        {
            "validators": ["python"],
            "must": [{"code": "BIND", "contains": "dangling VO binding 'dialogue/dlg_meet/nodes/node_ghost/text'", "severity": "warning"}],
            "mustNot": [{"code": "BIND", "contains": "dangling VO binding 'dialogue/dlg_meet/nodes/node_open"}],
        },
    ),
    "offer-numeric-exclusive-no-tie": (
        case_offer_numeric_exclusive_no_tie,
        {"noErrors": True, "mustNot": [{"code": "OFFER", "contains": "not provably exclusive"}]},
    ),
    "offer-numeric-overlap-ties": (
        case_offer_numeric_overlap_ties,
        {"must": [{"code": "OFFER", "contains": "not provably exclusive", "severity": "warning"}]},
    ),
    "active-dialogue-target-not-forced": (
        case_active_dialogue_target_not_forced,
        {"must": [{"code": "OFFER", "contains": "routes nothing", "severity": "warning"}],
         "mustNot": [{"code": "LOGIC", "contains": "speaker mismatch"}]},
    ),
    "active-dialogue-forced-outranked": (
        case_active_dialogue_forced_outranked,
        {"must": [{"code": "OFFER", "contains": "can be out-ranked", "severity": "warning"}],
         "mustNot": [{"code": "OFFER", "contains": "routes nothing"}]},
    ),
    "active-dialogue-cross-character-forced": (
        case_active_dialogue_cross_character_forced,
        {"noErrors": True,
         "mustNot": [{"code": "LOGIC", "contains": "speaker mismatch"},
                     {"code": "OFFER", "contains": "routes nothing"},
                     {"code": "OFFER", "contains": "can be out-ranked"}]},
    ),
    "offer-outcome-gate-reads-flags": (
        case_offer_outcome_gate_reads_flags,
        {"noErrors": True, "mustNot": [{"code": "FLAG", "contains": "saw_omen"}]},
    ),
    "offer-character-dangling": (
        case_offer_character_dangling,
        {"must": [{"code": "REF", "contains": "npc_ghost", "severity": "error"}]},
    ),
    "offer-forced-only-not-a-gap": (
        case_offer_forced_only_is_not_a_gap,
        {"noErrors": True, "mustNot": [{"code": "OFFER", "contains": "none is unconditional"}]},
    ),
    "offer-no-character": (
        case_offer_no_character,
        {"must": [{"code": "OFFER", "contains": "names no character", "severity": "warning"}]},
    ),
    "migrate-character-dialogues": (
        case_migrate_character_dialogues,
        {
            "must": [{"code": "MIGRATE", "contains": "migrate_ladders", "severity": "error"}],
            "mustNot": [{"code": "SCHEMA"}],
        },
    ),
    "offer-interactable-not-noop": (
        case_offer_interactable_not_noop,
        {"noErrors": True, "mustNot": [{"code": "LOC", "contains": "no-op"}]},
    ),
    "offer-character-covers": (
        case_offer_character_covers,
        {"noErrors": True, "mustNot": [{"code": "COVERAGE"}]},
    ),
    "custom-entity-valid": (
        case_custom_entity_valid,
        {"noErrors": True},
    ),
    "custom-entity-missing-field": (
        case_custom_entity_missing_field,
        {"must": [{"code": "SCHEMA", "contains": "missing required field 'manaCost'", "severity": "error"}]},
    ),
    "custom-entity-bad-reference": (
        case_custom_entity_bad_reference,
        {"must": [{"code": "REF", "contains": "unknown character 'npc_missing'", "severity": "error"}]},
    ),
    "custom-entity-registry-array": (
        case_custom_entity_registry_array,
        {"must": [{"code": "REF", "contains": "spells 'frostbite' field 'grantedBy': unknown character 'npc_gone'", "severity": "error"}]},
    ),
    "custom-entity-registry-keyed": (
        case_custom_entity_registry_keyed,
        {"must": [{"code": "REF", "contains": "spells 'frostbite' field 'grantedBy': unknown character 'npc_gone'", "severity": "error"}]},
    ),
    "custom-entity-nested-directory": (
        case_custom_entity_nested_directory,
        {"must": [{"code": "REF", "contains": "spells 'frostbite' field 'grantedBy': unknown character 'npc_gone'", "severity": "error"}]},
    ),
    "custom-entity-default-plural": (
        case_custom_entity_default_plural,
        {"must": [
            {"code": "REF", "contains": "spells 'frostbite' field 'grantedBy': unknown character 'npc_gone'", "severity": "error"},
            {"code": "REF", "contains": "runes 'ember' field 'carvedBy': unknown character 'npc_lost'", "severity": "error"},
        ]},
    ),
    "custom-entity-cross-type-reference": (
        case_custom_entity_cross_type_reference,
        {"must": [{"code": "REF", "contains": "field 'teaches[1]': unknown spell 'frostbite'", "severity": "error"}],
         "mustNot": [{"code": "REF", "contains": "'signature'"}]},
    ),
    "custom-entity-field-types": (
        case_custom_entity_field_types,
        {"must": [
            {"code": "SCHEMA", "contains": "field 'manaCost' expected number", "severity": "error"},
            {"code": "SCHEMA", "contains": "field 'ritual' expected boolean", "severity": "error"},
            {"code": "SCHEMA", "contains": "field 'element' invalid value 'water'", "severity": "error"},
            {"code": "SCHEMA", "contains": "field 'incantation' expected string", "severity": "error"},
            {"code": "SCHEMA", "contains": "field 'reagents' expected array", "severity": "error"},
        ]},
    ),
    "types-declaration-plurals": (
        case_types_declaration_plurals,
        {"must": [
            {"code": "SCHEMA", "contains": "types 'spell': plural '../escape' is not a plain name", "severity": "error"},
            {"code": "SCHEMA", "contains": "types 'rumour': plural 'dialogues' is a built-in folder or file", "severity": "error"},
            {"code": "SCHEMA", "contains": "types 'sigil': plural 'glyphs' is also used by type 'rune'", "severity": "error"},
        ]},
    ),
    "types-declaration-plural-portability": (
        case_types_declaration_plural_portability,
        {"must": [
            {"code": "SCHEMA", "contains": "types 'sigil': plural 'Glyphs' is also used by type 'rune'", "severity": "error"},
            {"code": "SCHEMA", "contains": "types 'rumour': plural 'Dialogues' is a built-in folder or file", "severity": "error"},
            {"code": "SCHEMA", "contains": "types 'device': plural 'aux' is a reserved file name on Windows", "severity": "error"},
            {"code": "SCHEMA", "contains": "types 'trail': plural 'trails", "severity": "error"},
        ]},
    ),
    "types-declaration-fields": (
        case_types_declaration_fields,
        {"must": [
            {"code": "SCHEMA", "contains": "types 'character': a custom type cannot be named after the built-in type 'character'", "severity": "error"},
            {"code": "SCHEMA", "contains": "types 'spell' field 'element': an enum needs at least one option", "severity": "error"},
            {"code": "SCHEMA", "contains": "types 'spell' field 'power': unknown type 'float'", "severity": "error"},
            {"code": "SCHEMA", "contains": "types 'spell' field 'caster': a reference needs a target", "severity": "error"},
            {"code": "SCHEMA", "contains": "types 'spell' field 'school': unknown reference target 'school'", "severity": "error"},
            {"code": "SCHEMA", "contains": "types 'spell' field 'combos[]': unknown reference target 'combo'", "severity": "error"},
            {"code": "SCHEMA", "contains": "types 'spell' field 'notes': must be an object", "severity": "error"},
        ]},
    ),
    "types-declaration-not-object": (
        case_types_declaration_not_object,
        {"must": [
            {"code": "SCHEMA", "contains": "types 'spell': the declaration must be an object", "severity": "error"},
            {"code": "SCHEMA", "contains": "types 'rune': fields must be an object", "severity": "error"},
        ]},
    ),
    "custom-entity-prototype-keys": (
        case_custom_entity_prototype_keys,
        {"must": [{"code": "REF", "contains": "protos '__proto__' field 'owner': unknown character 'npc_gone'", "severity": "error"}]},
    ),
    # ---- 0.15: tags on lines/choices; engine commands ----
    "tags-on-lines-clean": (
        case_tags_on_lines_clean,
        {"noErrors": True, "mustNot": [{"code": "SCHEMA"}, {"code": "REF"}]},
    ),
    "engine-command-declared-clean": (
        case_engine_command_declared_clean,
        {"noErrors": True, "mustNot": [{"code": "ENGINE"}, {"code": "SCHEMA"}, {"code": "FLAG"}]},
    ),
    "engine-command-undeclared": (
        case_engine_command_undeclared,
        {"must": [{"code": "ENGINE", "contains": "'shaek' is not declared", "severity": "warning"}]},
    ),
    "engine-command-bad-name": (
        case_engine_command_bad_name,
        {"must": [{"code": "ENGINE", "contains": "'Shake-Camera' is not lowercase snake_case", "severity": "error"}]},
    ),
    "engine-command-arg-count": (
        case_engine_command_arg_count,
        {"must": [{"code": "ENGINE", "contains": "takes 1 argument(s), got 2", "severity": "warning"}]},
    ),
    "engine-command-undeclared-prototype-name": (
        case_engine_command_undeclared_prototype_name,
        {"must": [{"code": "ENGINE", "contains": "'constructor' is not declared", "severity": "warning"}]},
    ),
    "engine-command-undeclared-vocabulary-ok": (
        case_engine_command_undeclared_vocabulary_ok,
        {"noErrors": True, "mustNot": [{"code": "ENGINE"}, {"code": "SCHEMA"}]},
    ),
    # ---- malformed-but-plausible shapes (E4 / A3 audit); ROUTE family ----
    "id-trailing-newline": (
        case_id_trailing_newline,
        {"must": [{"code": "SCHEMA", "contains": "npc_keeper", "severity": "error"}]},
    ),
    "engine-command-trailing-newline": (
        case_engine_command_trailing_newline,
        {"must": [{"code": "ENGINE", "contains": "is not lowercase snake_case", "severity": "error"}]},
    ),
    # The four python-only cases below are shapes the TypeScript zod schemas do
    # not reject today (a strict-schema change is under way); widen each to
    # both validators once the TypeScript conformance run reports the SCHEMA.
    "types-json-array": (
        case_types_json_array,
        {"validators": ["python"],
         "must": [{"code": "SCHEMA", "contains": "types.json", "severity": "error"}]},
    ),
    "custom-row-id-not-snake-case": (
        case_custom_row_id_not_snake_case,
        {"validators": ["python"],
         "must": [{"code": "SCHEMA", "contains": "row id \"Fire Ball\" is not lowercase snake_case", "severity": "error"}],
         "mustNot": [{"code": "REF"}]},
    ),
    "progression-thresholds-not-numbers": (
        case_progression_thresholds_not_numbers,
        {"validators": ["python"],
         "must": [{"code": "SCHEMA", "contains": "progression.json", "severity": "error"}],
         "mustNot": [{"code": "PROG", "contains": "strictly increasing"}]},
    ),
    "registry-entries-not-array": (
        case_registry_entries_not_array,
        {"validators": ["python"],
         "must": [{"code": "SCHEMA", "contains": "skills", "severity": "error"}]},
    ),
    "quest-stages-null-referenced": (
        case_quest_stages_null_referenced,
        {"must": [{"code": "SCHEMA", "contains": "qst_errand", "severity": "error"},
                  {"code": "REF", "contains": "qst_errand", "severity": "error"}]},
    ),
    "loreref-not-object": (
        case_loreref_not_object,
        {
         "must": [{"code": "SCHEMA", "contains": "npc_keeper", "severity": "error"}],
         "mustNot": [{"code": "LORE"}]},
    ),
    "route-unknown-dialogue": (
        case_route_unknown_dialogue,
        {"must": [{"code": "ROUTE", "contains": "dlg_ghost", "severity": "error"}]},
    ),
    "route-unknown-choice": (
        case_route_unknown_choice,
        {"must": [{"code": "ROUTE", "contains": "ch_ghost", "severity": "error"}]},
    ),
}


def main() -> None:
    for name, (seed, expected) in CASE_BUILDERS.items():
        case_dir = CASES / name
        if case_dir.exists():
            shutil.rmtree(case_dir)
        files = copy.deepcopy(base_project())
        seed(files)
        write_project(case_dir / "project", files)
        (case_dir / "expected.json").write_text(
            json.dumps(expected, indent=2, sort_keys=True) + "\n"
        )
        # The reference validator's FULL output — every (severity, code) — so the
        # TypeScript harness can compare its multiset to the Python one per case,
        # not just check the hand-written pins. A rule that fires in one
        # implementation and not the other is invisible to pins alone.
        for v in expected.get("validators", []):
            assert v in VALIDATORS, f"{name}: unknown validator {v!r} (a typo here silently skips the case on BOTH sides)"
        full = sorted([[iss.severity, iss.code] for iss in validate_project(str(CASES / name / "project")).issues])
        (CASES / name / "expected.full.json").write_text(json.dumps(full, indent=2) + "\n", encoding="utf-8")
        print(f"wrote {name}")


if __name__ == "__main__":
    main()
