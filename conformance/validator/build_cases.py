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
import shutil
from pathlib import Path

CASES = Path(__file__).resolve().parent / "cases"


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
            "dialogues": [{"dialogue": "dlg_meet"}],
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


def write_project(root: Path, files: dict[str, object]) -> None:
    for rel, content in files.items():
        path = root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(content, indent=2, sort_keys=True, ensure_ascii=False) + "\n")


# ---------------------------------------------------------------------------
# Cases — each seeds exactly one defect into a copy of the base project.
# ---------------------------------------------------------------------------

def case_clean_minimal(p: dict) -> None:
    """No defect: the floor every other case is measured against."""


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


def case_ladder_stranded_dialogue(p: dict) -> None:
    """A character WITH a ladder that still owns an unreachable dialogue.

    Naming a character as speaker makes nothing discoverable: only a ladder
    rung, an availableWhen, or a world placement does. This case exists because
    the two validators disagreed on it — the TypeScript one checked every
    character, the Python one only characters with no ladder at all, so the
    editor warned where CI was silent.
    """
    p["data/dialogues/dlg_aside.json"] = {
        "entry": "n1",
        "id": "dlg_aside",
        "nodes": [{"id": "n1", "isEnd": True, "text": "A line nothing can reach."}],
        "speakerId": "npc_keeper",
        "title": "An Aside",
    }


def case_dialogue_availablewhen_dangling(p: dict) -> None:
    """A dialogue gate reading a variable nothing defines."""
    p["data/dialogues/dlg_meet.json"]["availableWhen"] = {
        "flag": "ghost_flag",
        "type": "flag",
        "value": True,
    }


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


def case_ladder_dead_rung(p: dict) -> None:
    """An unconditional ladder rung that is not last — it shadows the rest.

    The top rung is deliberately effect-free so the stuck-rung warning does not
    fire alongside it: this case pins the dead-rung rule on its own.
    """
    p["data/dialogues/dlg_aside.json"] = {
        "entry": "n1",
        "id": "dlg_aside",
        "nodes": [{"id": "n1", "isEnd": True, "text": "Nothing new today."}],
        "speakerId": "npc_keeper",
        "title": "An Aside",
    }
    p["data/characters/npc_keeper.json"]["dialogues"] = [
        {"dialogue": "dlg_aside"},
        {"dialogue": "dlg_meet"},
    ]


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
    """showIf with nowhere to go when the gate fails."""
    dlg = p["data/dialogues/dlg_meet.json"]
    dlg["nodes"][1]["showIf"] = _cond_gate()      # node_close: isEnd, no next


def case_cond_showif_with_choices(p: dict) -> None:
    """showIf on a node that offers choices — not interstitial narration."""
    dlg = p["data/dialogues/dlg_meet.json"]
    dlg["nodes"][0]["showIf"] = _cond_gate()      # node_open carries choices
    dlg["nodes"][0]["next"] = "node_close"


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


CASE_BUILDERS = {
    "clean-minimal": (case_clean_minimal, {"noErrors": True}),
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
    "ladder-stranded-dialogue": (
        case_ladder_stranded_dialogue,
        {"must": [{"code": "LADDER", "contains": "dlg_aside", "severity": "warning"}]},
    ),
    "plain-goto-dangling": (
        case_plain_goto_dangling,
        {"must": [{"code": "REF", "contains": "node_typo", "severity": "error"}]},
    ),
    "dead-end-node": (
        case_dead_end_node,
        {"must": [{"code": "FLOW", "contains": "dead end", "severity": "error"}]},
    ),
    "dialogue-availablewhen-dangling": (
        case_dialogue_availablewhen_dangling,
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
        {"must": [{"code": "REACH", "contains": "unreachable", "severity": "warning"}]},
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
        {"must": [{"code": "FLAG", "contains": "saw_ledger", "severity": "warning"}]},
    ),
    "ladder-dead-rung": (
        case_ladder_dead_rung,
        {"must": [{"code": "LADDER", "contains": "dead rungs", "severity": "warning"}]},
    ),
    "exit-spawn-not-in-target": (
        case_exit_spawn_not_in_target,
        {"must": [{"code": "LOC", "contains": "sp_typo", "severity": "error"}]},
    ),
    "faction-opposes-itself": (
        case_faction_opposes_itself,
        {"must": [{"code": "LOGIC", "contains": "opposes itself", "severity": "warning"}]},
    ),
    "duplicate-objective-id": (
        case_duplicate_objective_id,
        {"must": [{"code": "OBJ", "contains": "duplicate objective id", "severity": "error"}]},
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
        {"must": [{"code": "REL", "contains": "never adjusted", "severity": "warning"}]},
    ),
    "reputation-read-never-adjusted": (
        case_reputation_read_never_adjusted,
        {"must": [{"code": "REP", "contains": "never adjusted", "severity": "warning"}]},
    ),
    "snapshot-unknown-quest": (
        case_snapshot_unknown_quest,
        {"must": [{"code": "SNAP", "contains": "qst_ghost", "severity": "error"}]},
    ),
    "text-placeholder-undeclared": (
        case_text_placeholder_undeclared,
        {"must": [{"code": "TEXT", "contains": "player_name", "severity": "error"}]},
    ),
    "grant-xp-nonpositive": (
        case_grant_xp_nonpositive,
        {"must": [{"code": "XP", "contains": "should be positive", "severity": "warning"}]},
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
        # The seeder gates node_close, which is BOTH next-less and isEnd — so this
        # one case pins two rules. Both assertions matter: an ablation run found
        # the isEnd rule could be deleted with every case still green.
        {"must": [
            {"code": "COND", "contains": "no 'next'", "severity": "error"},
            {"code": "COND", "contains": "'isEnd'", "severity": "error"},
        ]},
    ),
    "cond-showif-with-choices": (
        case_cond_showif_with_choices,
        {"must": [{"code": "COND", "contains": "'choices'", "severity": "error"}]},
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
        print(f"wrote {name}")


if __name__ == "__main__":
    main()
