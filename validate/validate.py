#!/usr/bin/env python3
"""
Parlance data validator — reference implementation.

PASS 1  SCHEMA       — every /data file matches its JSON Schema.
PASS 2  CONSISTENCY  — every cross-reference resolves.
PASS 3  RELATIONSHIPS — character<->dialogue coverage, task graph
                        (cycles, orphans, ordering), gate/check issues,
                        ending reachability, flag hygiene.

Severity:
  ERROR -> fails the build (exit 1). A real inconsistency.
  WARN  -> printed, does NOT fail the build. Likely mid-development.

Run from repo root:  python tooling/validate.py
Validate another project:  python tooling/validate.py --root examples/mistfall-inn
Add  --strict  to make warnings fail too.

Importable without side effects: `validate_project(root)` runs every pass and
returns a ProjectValidator whose `errors` / `warnings` lists hold Issue tuples
(`.code` is the bracket tag, `.message` the text after it).
"""
import argparse
import glob
import json
import os
import re
import sys
from collections import namedtuple

from jsonschema import Draft7Validator
from referencing import Registry, Resource
from referencing.jsonschema import DRAFT7

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# One reported finding. Printed as "[CODE] message"; severity decides which
# bucket (errors/warnings) it lands in and therefore the exit code.
Issue = namedtuple("Issue", ["severity", "code", "message"])

# --- Dice notation (mirrors editor/core/src/dice.ts — keep in lockstep) ------
# Grammar: NdM, n >= 1, m >= 2. The skill value is a modifier, not notation.
DICE_RE = re.compile(r"^(\d+)d(\d+)$")
DEFAULT_DICE = (1, 20)


def parse_dice(notation):
    """Parse "NdM" → (n, m). Raises ValueError with the same messages dice.ts
    throws, so both validators report identically."""
    m = DICE_RE.match(notation.strip())
    if not m:
        raise ValueError(f"Invalid dice notation '{notation}': expected NdM (e.g. 1d20, 2d6)")
    n, sides = int(m.group(1)), int(m.group(2))
    if n < 1:
        raise ValueError(f"Invalid dice notation '{notation}': need at least 1 die")
    if sides < 2:
        raise ValueError(f"Invalid dice notation '{notation}': die must have at least 2 sides")
    return (n, sides)


def strip_comments(o):
    if isinstance(o, dict):
        return {k: strip_comments(v) for k, v in o.items() if k != "_comment"}
    if isinstance(o, list):
        return [strip_comments(x) for x in o]
    return o


# {var_id} placeholders in PLAYER-FACING strings (TEXT pass).
PLACEHOLDER_RE = re.compile(r"\{([a-z][a-z0-9_]*)\}")


class ProjectValidator:
    """All registries + passes for one project root. Construct, then run()."""

    def __init__(self, root):
        self.root = os.path.abspath(root)
        self.errors = []    # list[Issue]
        self.warnings = []  # list[Issue]

        # parlance.config.json mirrors the editor's per-project overrides (see
        # SETUP_AND_MANAGEMENT.md §4); absent or malformed falls back to defaults.
        cfg = {}
        cfg_path = os.path.join(self.root, "parlance.config.json")
        if os.path.exists(cfg_path):
            try:
                with open(cfg_path) as f:
                    cfg = json.load(f) or {}
            except (json.JSONDecodeError, OSError):
                cfg = {}
        self.data_dir = os.path.join(self.root, cfg.get("data") or "data")
        # Route/snapshot fixtures are regression tests, not narrative content, so
        # they live beside data/ rather than inside it — a shipping game never
        # loads them.
        self.tests_dir = os.path.join(self.root, cfg.get("tests") or "tests")
        # Schemas ship with the tool: a project only needs its own schema/ to pin
        # a specific contract version, so fall back to this repo's set (same rule
        # the editor host applies).
        self.schema_dir = os.path.join(self.root, cfg.get("schema") or "schema")
        if not os.path.isdir(self.schema_dir):
            self.schema_dir = os.path.join(REPO_ROOT, "schema")

        # The schemas cross-reference each other by bare filename
        # ("common.schema.json#/...") rather than by URL, so every one is
        # registered under that name and resolution stays entirely offline — no
        # schema is ever fetched.
        #
        # `referencing` rather than jsonschema's RefResolver, which has been
        # deprecated since jsonschema 4.18 and is slated for removal.
        self.schema_store = {}
        for sp in glob.glob(os.path.join(self.schema_dir, "*.schema.json")):
            s = self._read_json(sp)
            if s is None:
                continue
            self.schema_store[os.path.basename(sp)] = s
            if "$id" in s:
                self.schema_store[s["$id"]] = s
        self.schema_registry = Registry().with_resources(
            (name, Resource(contents=s, specification=DRAFT7))
            for name, s in self.schema_store.items()
        )
        # Compiled-validator cache: one Draft7Validator per schema file, not one
        # per entity checked against it.
        self._validator_cache = {}

        # Registries
        self.skills, self.factions, self.characters, self.variables = {}, {}, {}, {}
        self.items = {}
        self.dialogues, self.quests, self.locations, self.endings = {}, {}, {}, {}
        self.codex = {}
        self.portraits, self.cutscenes = {}, {}
        self.routes, self.snapshots = {}, {}
        self.progression = None
        self.rules = None
        # Paths the single-file registries were loaded from (for messages).
        self._registry_paths = {}

        # Entities that failed the SCHEMA pass: (kind, id) pairs. They stay in
        # the registries so references to them still resolve, but the
        # consistency passes skip walking them — malformed input degrades to
        # reported SCHEMA errors instead of a KeyError mid-pass.
        self.schema_failed = set()

        # Tracking sets for the hygiene passes
        self.flags_written, self.flags_read = set(), set()
        self.texts_written, self.texts_read = set(), set()
        self.reps_adjusted, self.reps_read = set(), set()
        self.rels_adjusted, self.rels_read = set(), set()
        self.triggered_cutscenes = set()
        self.xp_grants = []  # (amount, where)
        self.used_portraits = set()
        self.chars_with_dialogue = set()
        # characterId -> [dialogue ids naming them as ROOT speaker]. The ladder
        # pass uses this to spot dialogues nothing can reach: a speakerId does
        # NOT make a dialogue discoverable — only a ladder rung, or
        # availableWhen, does.
        self.dialogues_by_speaker = {}

        self.default_dice = DEFAULT_DICE

    # -- issue plumbing ------------------------------------------------------

    def err(self, code, message):
        self.errors.append(Issue("error", code, message))

    def warn(self, code, message):
        self.warnings.append(Issue("warning", code, message))

    @property
    def issues(self):
        return self.errors + self.warnings

    def rel(self, path):
        return os.path.relpath(path, self.root)

    # -- loading -------------------------------------------------------------

    def _read_json(self, path):
        """Load a JSON file; malformed JSON becomes a SCHEMA error instead of a
        crash, and the file is skipped."""
        try:
            with open(path) as f:
                return json.load(f)
        except (json.JSONDecodeError, UnicodeDecodeError) as e:
            self.err("SCHEMA", f"{self.rel(path)}: invalid JSON: {e}")
            return None
        except OSError as e:
            self.err("SCHEMA", f"{self.rel(path)}: cannot read file: {e}")
            return None

    def _validator_for(self, fn):
        v = self._validator_cache.get(fn)
        if v is None:
            v = Draft7Validator(self.schema_store[fn], registry=self.schema_registry)
            self._validator_cache[fn] = v
        return v

    def schema_check(self, path, fn, obj):
        """Returns True when the entity is schema-clean."""
        ok = True
        for e in sorted(self._validator_for(fn).iter_errors(strip_comments(obj)), key=str):
            ok = False
            self.err("SCHEMA", f"{self.rel(path)}: {e.message} (at {'/'.join(map(str, e.path)) or 'root'})")
        return ok

    def valid(self, kind, eid):
        return (kind, eid) not in self.schema_failed

    def _load_registry_file(self, filename, list_key, schema_fn, reg, kind):
        """Single-file registry (skills.json, variables.json, ...). Mirrors the
        [DUP] check load_dir has — a duplicated id in one of these silently
        last-wins otherwise."""
        p = os.path.join(self.data_dir, filename)
        if not os.path.exists(p):
            return
        self._registry_paths[kind] = p
        doc = self._read_json(p)
        if doc is None:
            return
        entries = doc.get(list_key, []) if isinstance(doc, dict) else []
        for entry in entries:
            if not isinstance(entry, dict):
                self.err("SCHEMA", f"{self.rel(p)}: {list_key} entry is not an object: {entry!r}")
                continue
            ok = self.schema_check(p, schema_fn, entry)
            eid = entry.get("id")
            if not isinstance(eid, str):
                continue  # missing/invalid id already reported by the schema pass
            if eid in reg:
                self.err("DUP", f"duplicate {kind} id '{eid}' in {self.rel(p)}")
            reg[eid] = entry
            if not ok:
                self.schema_failed.add((kind, eid))

    def _load_dir(self, sub, schema_fn, reg, kind, base=None):
        # Recursive: dir-mode entities may be organised into nested zone/chapter
        # subdirs (e.g. dialogues/act1/dlg_foo.json). Ids stay globally unique.
        for p in glob.glob(os.path.join(base or self.data_dir, sub, "**", "*.json"), recursive=True):
            if p.endswith(".layout.json"):
                continue  # editor layout sidecars carry no entity data
            o = self._read_json(p)
            if o is None:
                continue
            if not isinstance(o, dict):
                self.err("SCHEMA", f"{self.rel(p)}: expected an object, got {type(o).__name__}")
                continue
            ok = self.schema_check(p, schema_fn, o)
            eid = o.get("id")
            if not isinstance(eid, str):
                continue  # missing/invalid id already reported by the schema pass
            if eid in reg:
                self.err(
                    "DUP",
                    f"duplicate {kind} id '{eid}' in {sub}/ "
                    f"({self.rel(reg[eid][1])} and {self.rel(p)})",
                )
            reg[eid] = (o, p)
            if not ok:
                self.schema_failed.add((kind, eid))

    def load(self):
        self._load_registry_file("skills.json", "skills", "skill.schema.json", self.skills, "skill")
        self._load_registry_file("variables.json", "variables", "variable.schema.json", self.variables, "variable")
        self._load_registry_file("items.json", "items", "item.schema.json", self.items, "item")
        self._load_registry_file("portraits.json", "portraits", "portrait.schema.json", self.portraits, "portrait")

        prog_path = os.path.join(self.data_dir, "progression.json")
        if os.path.exists(prog_path):
            self.progression = self._read_json(prog_path)
            if self.progression is not None:
                self.schema_check(prog_path, "progression.schema.json", self.progression)
        rules_path = os.path.join(self.data_dir, "rules.json")
        if os.path.exists(rules_path):
            self.rules = self._read_json(rules_path)
            if self.rules is not None:
                self.schema_check(rules_path, "rules.schema.json", self.rules)

        self._load_dir("factions", "faction.schema.json", self.factions, "faction")
        self._load_dir("characters", "character.schema.json", self.characters, "character")
        self._load_dir("dialogues", "dialogue.schema.json", self.dialogues, "dialogue")
        self._load_dir("quests", "quest.schema.json", self.quests, "quest")
        self._load_dir("locations", "location.schema.json", self.locations, "location")
        self._load_dir("endings", "ending.schema.json", self.endings, "ending")
        self._load_dir("codex", "codex.schema.json", self.codex, "codex")
        self._load_dir("cutscenes", "cutscene.schema.json", self.cutscenes, "cutscene")
        self._load_dir("routes", "route.schema.json", self.routes, "route", self.tests_dir)
        self._load_dir("snapshots", "snapshot.schema.json", self.snapshots, "snapshot", self.tests_dir)

    # -- ref helpers ---------------------------------------------------------

    def ref_item(self, i, w):
        # Items are their own registry now, not a variable kind.
        if i not in self.items:
            self.err("REF", f"{w}: unregistered item '{i}' (add to items.json)")

    def ref_skill(self, s, w):
        if s not in self.skills:
            self.err("REF", f"{w}: unknown skill '{s}'")

    def ref_faction(self, f, w):
        if f not in self.factions:
            self.err("REF", f"{w}: unknown faction '{f}'")

    def ref_char(self, c, w):
        if c not in self.characters:
            self.err("REF", f"{w}: unknown character '{c}'")

    def ref_node_speaker(self, s, w):
        # Node-level speakerId, unlike the dialogue-level one, may name a
        # character OR a skill (N1 — a skill-voiced narration beat). Mirrors
        # checkNodeSpeakerRef in editor/core/src/validator.ts — keep in lockstep.
        is_char = s in self.characters
        is_skill = s in self.skills
        if not is_char and not is_skill:
            self.err("REF", f"{w}: unknown speaker '{s}' — not a character or skill id")
        elif is_char and is_skill:
            self.err("REF", f"{w}: speaker '{s}' matches both a character and a skill id — ambiguous")

    def ref_var(self, v, k, w):
        x = self.variables.get(v)
        if not x:
            self.err("REF", f"{w}: unregistered {k} '{v}' (add to variables.json)")
        else:
            kind = x.get("kind")
            if kind is not None and kind != k:
                self.err("REF", f"{w}: '{v}' is a {kind}, used as {k}")

    def quest_stage_ids(self, qid):
        q = self.quests.get(qid)
        if not q:
            return set()
        return {s.get("id") for s in q[0].get("stages", []) if isinstance(s, dict)}

    def quest_outcome_ids(self, qid):
        q = self.quests.get(qid)
        if not q:
            return set()
        return {o.get("id") for o in q[0].get("outcomes", []) if isinstance(o, dict)}

    # -- condition / effect walkers -----------------------------------------

    def walk_condition(self, c, w):
        if not isinstance(c, dict):
            return
        t = c.get("type")
        if t == "skill":
            self.ref_skill(c["skill"], w)
        elif t == "reputation":
            self.ref_faction(c["faction"], w)
            self.reps_read.add(c["faction"])
        elif t == "flag":
            self.ref_var(c["flag"], "flag", w)
            self.flags_read.add(c["flag"])
        elif t == "counter":
            self.ref_var(c["counter"], "counter", w)
        elif t == "item":
            self.ref_item(c["item"], w)
        elif t == "relationship":
            self.ref_char(c["character"], w)
            self.rels_read.add(c["character"])
        elif t == "quest":
            # Same REF pair as the advance_quest effect.
            if c["quest"] not in self.quests:
                self.err("REF", f"{w}: unknown quest '{c['quest']}'")
            elif c["stage"] not in self.quest_stage_ids(c["quest"]):
                self.err("REF", f"{w}: quest condition stage '{c['stage']}' not in '{c['quest']}'")
        elif t == "questOutcome":
            if c["quest"] not in self.quests:
                self.err("REF", f"{w}: unknown quest '{c['quest']}'")
            elif c["outcome"] not in self.quest_outcome_ids(c["quest"]):
                self.err("REF", f"{w}: questOutcome '{c['outcome']}' not in '{c['quest']}'")
        elif t in ("all", "any"):
            for s in c["of"]:
                self.walk_condition(s, w)
        elif t == "not":
            self.walk_condition(c["of"], w)

    def walk_effect(self, e, w, site=None):
        """`site` is a STRUCTURAL marker for where the effect was authored,
        passed by the caller — "quest_outcome" only from the quest-outcome walk.
        The XP convention advisory keys on it, never on the `where` message
        text: a dialogue node id containing the word "outcome" used to silence
        the advisory here while validator.ts still reported it."""
        if not isinstance(e, dict):
            return
        t = e.get("type")
        if t == "set_flag":
            self.ref_var(e["flag"], "flag", w)
            self.flags_written.add(e["flag"])
        elif t == "adjust_reputation":
            self.ref_faction(e["faction"], w)
            self.reps_adjusted.add(e["faction"])
        elif t == "adjust_relationship":
            self.ref_char(e["character"], w)
            self.rels_adjusted.add(e["character"])
        elif t == "adjust_counter":
            self.ref_var(e["counter"], "counter", w)
        elif t in ("give_item", "take_item"):
            self.ref_item(e["item"], w)
        elif t == "advance_quest":
            if e["quest"] not in self.quests:
                self.err("REF", f"{w}: unknown quest '{e['quest']}'")
            elif e["toStage"] not in self.quest_stage_ids(e["quest"]):
                self.err("REF", f"{w}: advance_quest toStage '{e['toStage']}' not in '{e['quest']}'")
        elif t == "grant_xp":
            if e.get("amount", 0) <= 0:
                self.warn("XP", f"{w}: grant_xp amount {e.get('amount')} should be positive")
            self.xp_grants.append((e.get("amount", 0), w, site == "quest_outcome"))
        elif t == "set_active_dialogue":
            # Feed model: sets the `active_dialogue__{character}` flag, read by
            # the character's ladder. Register it as written so hygiene balances.
            self.flags_written.add(f"active_dialogue__{e['character']}")
            if e["character"] not in self.characters:
                self.err("REF", f"{w}: set_active_dialogue unknown character '{e['character']}'")
            if e["dialogue"] not in self.dialogues:
                self.err("REF", f"{w}: set_active_dialogue unknown dialogue '{e['dialogue']}'")
            else:
                # Speaker mismatch (LOGIC) — mirrors validator.ts: pushing a
                # dialogue whose root speaker is someone else onto a character
                # is almost always a copy-paste id slip.
                tgt = self.dialogues[e["dialogue"]][0]
                if tgt.get("speakerId") and tgt["speakerId"] != e["character"]:
                    self.warn(
                        "LOGIC",
                        f"{w}: set_active_dialogue pushes dialogue '{e['dialogue']}' "
                        f"(speaker '{tgt['speakerId']}') onto character '{e['character']}' — speaker mismatch",
                    )
        elif t == "set_text":
            self.ref_var(e["variable"], "text", w)
            self.texts_written.add(e["variable"])
        elif t == "play_cutscene":
            if e["cutscene"] not in self.cutscenes:
                self.err("REF", f"{w}: play_cutscene unknown cutscene '{e['cutscene']}'")
            self.triggered_cutscenes.add(e["cutscene"])

    def flags_in_condition(self, c, acc, visited=None):
        # Resolves THROUGH questOutcome into that outcome's reachedWhen —
        # otherwise an ending gated on an outcome looks flag-free and every
        # reachability check downstream silently passes. Mirrors validator.ts.
        if visited is None:
            visited = set()
        if not isinstance(c, dict):
            return acc
        t = c.get("type")
        if t == "flag":
            acc.add(c["flag"])
        elif t in ("all", "any"):
            for s in c["of"]:
                self.flags_in_condition(s, acc, visited)
        elif t == "not":
            self.flags_in_condition(c["of"], acc, visited)
        elif t == "questOutcome":
            key = f"{c['quest']}/{c['outcome']}"
            if key not in visited:
                visited.add(key)
                q = self.quests.get(c["quest"])
                if q:
                    oc = next((o for o in q[0].get("outcomes", []) if o.get("id") == c["outcome"]), None)
                    if oc and oc.get("reachedWhen"):
                        self.flags_in_condition(oc["reachedWhen"], acc, visited)
        return acc

    def positive_flag_needs(self, c, acc, negated=False, visited=None):
        """Flags this condition needs to be TRUE — i.e. flags some effect must
        set — accounting for `value: false` and `not` nesting.

        Used for the quest dependency graph only. Plain flags_in_condition
        treats `availableWhen: not(flag other_done)` as a dependency on the
        quest that sets other_done, so two mutually-exclusive quests (each
        gated on the other NOT being done) read as a circular dependency when
        they are actually just a fork.
        """
        if visited is None:
            visited = set()
        if not isinstance(c, dict):
            return acc
        t = c.get("type")
        if t == "flag":
            needed_value = bool(c.get("value", True)) != negated
            if needed_value:
                acc.add(c["flag"])
        elif t in ("all", "any"):
            for s in c["of"]:
                self.positive_flag_needs(s, acc, negated, visited)
        elif t == "not":
            self.positive_flag_needs(c["of"], acc, not negated, visited)
        elif t == "questOutcome" and not negated:
            key = f"{c['quest']}/{c['outcome']}"
            if key not in visited:
                visited.add(key)
                q = self.quests.get(c["quest"])
                if q:
                    oc = next((o for o in q[0].get("outcomes", []) if o.get("id") == c["outcome"]), None)
                    if oc and oc.get("reachedWhen"):
                        self.positive_flag_needs(oc["reachedWhen"], acc, negated, visited)
        return acc

    # -- passes --------------------------------------------------------------

    def resolve_rules(self):
        # --- Rules (RULES pass) — mirrors the parseDice call in validator.ts.
        # The project's default dice drive every active check, so malformed
        # notation here silently mis-resolves the whole game. Malformed is an
        # error; fall back to the engine default so the rest of the pass runs.
        if self.rules is not None and isinstance(self.rules, dict):
            notation = (self.rules.get("check") or {}).get("dice")
            if isinstance(notation, str):
                try:
                    self.default_dice = parse_dice(notation)
                except ValueError as e:
                    self.err("RULES", f"rules.check.dice: {e}")

    def check_variables(self):
        # Variable `default` must match `kind` (boolean⇔flag, number⇔counter,
        # string⇔text). The JSON schema documents this but cannot express it.
        p = self._registry_paths.get("variable")
        where = self.rel(p) if p else "variables.json"
        expected = {"flag": "a boolean", "counter": "a number", "text": "a string"}
        for vid, v in self.variables.items():
            if not self.valid("variable", vid):
                continue
            kind = v.get("kind")
            default = v.get("default")
            if default is None or kind not in expected:
                continue
            if kind == "flag":
                ok = isinstance(default, bool)
            elif kind == "counter":
                ok = isinstance(default, (int, float)) and not isinstance(default, bool)
            else:  # text
                ok = isinstance(default, str)
            if not ok:
                self.err(
                    "SCHEMA",
                    f"{where}: variable '{vid}': default does not match kind "
                    f"'{kind}' (expected {expected[kind]}, got {json.dumps(default)})",
                )

    def check_characters_portraits_factions(self):
        for cid, (o, _p) in self.characters.items():
            if not self.valid("character", cid):
                continue
            if "factionId" in o:
                self.ref_faction(o["factionId"], f"character '{cid}'")
            if "portrait" in o:
                if o["portrait"] not in self.portraits:
                    self.err("PORT", f"character '{cid}': portrait '{o['portrait']}' not found in registry")
                self.used_portraits.add(o["portrait"])
        for pid, o in self.portraits.items():
            if not self.valid("portrait", pid):
                continue
            if o.get("character") and o["character"] not in self.characters:
                self.err("PORT", f"portrait '{pid}': character '{o['character']}' not found")
        for fid, (o, _p) in self.factions.items():
            if not self.valid("faction", fid):
                continue
            for x in o.get("opposes", []) + o.get("alliedWith", []):
                if x not in self.factions:
                    self.err("REF", f"faction '{fid}': unknown related faction '{x}'")
            if fid in o.get("opposes", []):
                self.warn("LOGIC", f"faction '{fid}' opposes itself")

    def check_dialogues(self):
        for did, (dlg, _p) in self.dialogues.items():
            if not self.valid("dialogue", did):
                continue
            node_ids = {n["id"] for n in dlg["nodes"]}
            w0 = f"dialogue '{did}'"
            if dlg["entry"] not in node_ids:
                self.err("REF", f"{w0}: entry '{dlg['entry']}' is not a node")
            if dlg.get("speakerId"):
                self.ref_char(dlg["speakerId"], w0)
                self.chars_with_dialogue.add(dlg["speakerId"])
                self.dialogues_by_speaker.setdefault(dlg["speakerId"], []).append(did)
            # Walk dialogue-level availableWhen so ref checks and flag hygiene
            # apply — a flag read only by a dialogue gate is a real read.
            if dlg.get("availableWhen"):
                self.walk_condition(dlg["availableWhen"], f"{w0} availableWhen")
            seen = set()
            for n in dlg["nodes"]:
                if n["id"] in seen:
                    self.err("DUP", f"{w0}: duplicate node id '{n['id']}'")
                seen.add(n["id"])
            edges = {}  # node id -> targets it can reach in one hop
            for n in dlg["nodes"]:
                w = f"{w0} node '{n['id']}'"
                # 'end' is the dialogue-script text-mode sentinel ("-> end"
                # terminates a branch); a real node with that id collides with
                # it and round-trips wrong.
                if n["id"] == "end":
                    self.err("FLOW", f"{w}: node id 'end' is reserved (it is the dialogue-script text-mode end sentinel)")
                for e in n.get("onEnter", []):
                    self.walk_effect(e, w)
                if n.get("speakerId"):
                    self.ref_node_speaker(n["speakerId"], w)
                    if n["speakerId"] in self.characters:
                        self.chars_with_dialogue.add(n["speakerId"])
                if n.get("portrait"):
                    entry = self.portraits.get(n["portrait"])
                    if not entry:
                        self.err("PORT", f"{w}: portrait '{n['portrait']}' not found in registry")
                    elif entry.get("character"):
                        # Compare against the RESOLVED speaker (character only),
                        # not a raw id — a node whose effective speaker is a
                        # skill (or narration) legitimately carries a portrait
                        # override with no character involved, and a raw string
                        # compare would always mismatch those. Mirrors
                        # validator.ts's resolveSpeaker use.
                        speaker = n.get("speakerId") or dlg.get("speakerId")
                        if speaker in self.characters and entry["character"] != speaker:
                            self.warn(
                                "PORT",
                                f"{w}: portrait '{n['portrait']}' belongs to character "
                                f"'{entry['character']}', but speaker is '{speaker}' — expression mismatch",
                            )
                    self.used_portraits.add(n["portrait"])
                ch_list = n.get("choices", [])
                nxt = n.get("next")
                if nxt:
                    if ch_list:
                        self.err("FLOW", f"{w}: has both 'next' and 'choices' — a node auto-advances or offers choices, not both")
                    if n.get("isEnd"):
                        self.err("FLOW", f"{w}: has both 'next' and 'isEnd' — a node can't both end the dialogue and auto-advance")
                    edges.setdefault(n["id"], []).append(nxt)
                    if nxt not in node_ids:
                        self.err("REF", f"{w}: next '{nxt}' is not a node")
                if not ch_list and not n.get("isEnd") and not nxt:
                    self.err("FLOW", f"{w}: no choices, not isEnd, no next (player stuck)")
                # Mirrors validator.ts: a node whose every choice is gated can
                # present an empty choice list at runtime.
                if ch_list and not n.get("isEnd") and all("showIf" in c for c in ch_list):
                    self.warn("FLOW", f"{w}: all choices have showIf — player may be stuck if all conditions fail")
                cids = set()
                for ch in ch_list:
                    cw = f"{w} choice '{ch['id']}'"
                    if ch["id"] in cids:
                        self.err("DUP", f"{cw}: duplicate choice id")
                    cids.add(ch["id"])
                    if "showIf" in ch:
                        self.walk_condition(ch["showIf"], cw)
                    for e in ch.get("effects", []):
                        self.walk_effect(e, cw)
                    if "check" in ch:
                        k = ch["check"]
                        self.ref_skill(k["skill"], cw)
                        if k["mode"] == "active":
                            for key in ("onSuccess", "onFailure"):
                                if key not in k:
                                    self.err("GATE", f"{cw}: active check missing '{key}'")
                                else:
                                    edges.setdefault(n["id"], []).append(k[key])
                                    if k[key] not in node_ids:
                                        self.err("REF", f"{cw}: check {key} '{k[key]}' is not a node")
                            if "goto" in ch:
                                self.warn("GATE", f"{cw}: has both active check and goto; goto ignored")
                            # Dice-aware reachability (mirrors validator.ts):
                            # parse the effective dice, then warn if the
                            # difficulty can't be met even on the maximum roll
                            # (skill 0).
                            check_dice = self.default_dice
                            if isinstance(k.get("dice"), str):
                                try:
                                    check_dice = parse_dice(k["dice"])
                                except ValueError as e:
                                    self.err("RULES", f"{cw}: {e}")
                            n_dice, m_sides = check_dice
                            max_roll = n_dice * m_sides
                            if k["difficulty"] > max_roll:
                                self.warn(
                                    "GATE",
                                    f"{cw}: difficulty {k['difficulty']} exceeds max roll "
                                    f"({max_roll} on {n_dice}d{m_sides}); needs skill ≥ "
                                    f"{k['difficulty'] - max_roll} to ever pass",
                                )
                        else:
                            if "onSuccess" in k or "onFailure" in k:
                                self.warn("GATE", f"{cw}: passive check shouldn't define onSuccess/onFailure")
                            if "goto" not in ch and not n.get("isEnd"):
                                self.err("GATE", f"{cw}: passive-check choice needs a goto")
                            if "goto" in ch:
                                edges.setdefault(n["id"], []).append(ch["goto"])
                                if ch["goto"] not in node_ids:
                                    self.err("REF", f"{cw}: goto '{ch['goto']}' is not a node")
                    elif "goto" in ch:
                        edges.setdefault(n["id"], []).append(ch["goto"])
                        if ch["goto"] not in node_ids:
                            self.err("REF", f"{cw}: goto '{ch['goto']}' is not a node")
                    else:
                        if not n.get("isEnd"):
                            self.err("FLOW", f"{cw}: no goto, no check, not isEnd — dead end")
            # Walk from the entry. Counting in-edges instead would call a
            # disconnected island reachable — its nodes point at each other, so
            # every one of them has an inbound edge and none is reachable from
            # the entry. Mirrors the BFS in validator.ts.
            reachable = set()
            frontier = [dlg["entry"]]
            while frontier:
                current = frontier.pop()
                if current in reachable:
                    continue
                reachable.add(current)
                frontier.extend(edges.get(current, []))
            for n in dlg["nodes"]:
                if n["id"] not in reachable:
                    self.warn("REACH", f"{w0}: node '{n['id']}' is unreachable")

            # 'next' cycle check (D7) — mirrors validator.ts's chain-walk. Each
            # node has at most one 'next' (mutual exclusion enforced above), so
            # this is a pointer-chase per unvisited node, not a general graph
            # DFS: walk the chain marking nodes in-progress; landing back on an
            # in-progress node closes a cycle. goto cycles remain legal (hub
            # dialogues loop on purpose).
            by_id = {n["id"]: n for n in dlg["nodes"]}
            chain_state = {}
            for start in dlg["nodes"]:
                if start["id"] in chain_state:
                    continue
                chain = []
                cur = start["id"]
                while cur is not None and cur not in chain_state:
                    chain_state[cur] = "in-progress"
                    chain.append(cur)
                    cur = by_id.get(cur, {}).get("next")
                if cur is not None and chain_state.get(cur) == "in-progress":
                    self.err("FLOW", f"{w0}: 'next' cycle involving node '{cur}'")
                for nid in chain:
                    chain_state[nid] = "done"

    def check_coverage(self):
        # A character "has dialogue" if they speak one OR a ladder rung presents
        # one. Checking speakerId alone reports ladder-only characters as
        # uncovered.
        for cid, (o, _p) in self.characters.items():
            if not self.valid("character", cid):
                continue
            if cid not in self.chars_with_dialogue and not (o.get("dialogues") or []):
                self.warn("COVERAGE", f"character '{cid}' has no dialogue")

    def flags_written_by_task(self, q, value=None):
        out = set()
        for st in q.get("stages", []):
            for e in st.get("onComplete", []):
                if e.get("type") == "set_flag" and (value is None or bool(e.get("value")) == value):
                    out.add(e["flag"])
        for oc in q.get("outcomes", []):
            for e in oc.get("effects", []):
                if e.get("type") == "set_flag" and (value is None or bool(e.get("value")) == value):
                    out.add(e["flag"])
        return out

    def check_quests(self):
        valid_quests = {qid: qp for qid, qp in self.quests.items() if self.valid("quest", qid)}

        for qid, (q, _p) in valid_quests.items():
            for st in q["stages"]:
                for e in st.get("onComplete", []):
                    self.walk_effect(e, f"quest '{qid}' stage '{st['id']}'")
            for oc in q.get("outcomes", []):
                for e in oc.get("effects", []):
                    self.walk_effect(e, f"quest '{qid}' outcome '{oc['id']}'", site="quest_outcome")

        # Dependency edges are polarity-aware: an edge means "prod sets (to
        # true) a flag that qid needs to BE true". A gate on the ABSENCE of a
        # flag (not / value:false) is mutual exclusion, not a dependency — two
        # quests each gated on the other's completion flag being unset are a
        # fork, not a cycle.
        task_writes_true = {qid: self.flags_written_by_task(q, value=True) for qid, (q, _p) in valid_quests.items()}
        edges = {qid: set() for qid in valid_quests}
        for qid, (q, _p) in valid_quests.items():
            av = q.get("availableWhen")
            need = self.positive_flag_needs(av, set()) if av else set()
            for prod, wr in task_writes_true.items():
                if prod != qid and (need & wr):
                    edges[prod].add(qid)

        for qid, (q, _p) in valid_quests.items():
            ords = [s["order"] for s in q["stages"]]
            if len(set(ords)) != len(ords):
                self.err("QUEST", f"quest '{qid}': duplicate stage order {ords}")
            if ords != sorted(ords):
                self.warn("QUEST", f"quest '{qid}': stages not in ascending order {ords}")

        opened = {c for outs in edges.values() for c in outs}
        for qid, (q, _p) in valid_quests.items():
            trig = q.get("startsAvailable") or ("availableWhen" in q) or (qid in opened)
            out = bool(q.get("outcomes"))
            if not trig and not out:
                self.warn("QUEST", f"quest '{qid}' orphaned: no trigger and no outcome (ok if WIP)")
            elif not trig:
                self.warn("QUEST", f"quest '{qid}' has no trigger (nothing opens it)")
            if not out:
                # Mirrors validator.ts: a quest with no outcomes has undefined
                # success/failure conditions.
                self.warn("QUEST", f"quest '{qid}' has no outcomes — success/failure conditions are undefined")

        color = {qid: 0 for qid in valid_quests}

        def dfs(u, stack):
            color[u] = 1
            stack.append(u)
            for v in edges[u]:
                if color[v] == 1:
                    i = stack.index(v)
                    self.err("QUEST", f"circular dependency: {' -> '.join(stack[i:] + [v])}")
                elif color[v] == 0:
                    dfs(v, stack)
            stack.pop()
            color[u] = 2

        for qid in valid_quests:
            if color[qid] == 0:
                dfs(qid, [])

        # questOutcome reference cycles. The runtime guard returns false where a
        # cycle closes — total but silent — so report it here. Mirrors validator.ts.
        outcome_refs = {}
        for qid, (q, _p) in valid_quests.items():
            for oc in q.get("outcomes", []):
                refs = []

                def collect(c):
                    if not isinstance(c, dict):
                        return
                    ct = c.get("type")
                    if ct == "questOutcome":
                        refs.append(f"{c['quest']}/{c['outcome']}")
                    elif ct in ("all", "any"):
                        for s in c["of"]:
                            collect(s)
                    elif ct == "not":
                        collect(c["of"])

                if oc.get("reachedWhen"):
                    collect(oc["reachedWhen"])
                outcome_refs[f"{qid}/{oc['id']}"] = refs

        oc_color = {k: 0 for k in outcome_refs}

        def oc_dfs(u, stack):
            oc_color[u] = 1
            stack.append(u)
            for v in outcome_refs.get(u, []):
                if v not in outcome_refs:
                    continue  # dangling ref — already a REF error
                if oc_color[v] == 1:
                    i = stack.index(v)
                    self.err(
                        "QUEST",
                        f"questOutcome reference cycle: {' -> '.join(stack[i:] + [v])} — evaluates false where it closes",
                    )
                elif oc_color[v] == 0:
                    oc_dfs(v, stack)
            stack.pop()
            oc_color[u] = 2

        for k in outcome_refs:
            if oc_color[k] == 0:
                oc_dfs(k, [])

        for qid, (q, _p) in valid_quests.items():
            if "availableWhen" in q and "closedWhen" in q:
                a = self.flags_in_condition(q["availableWhen"], set())
                c = self.flags_in_condition(q["closedWhen"], set())
                if a & c:
                    self.warn("QUEST", f"quest '{qid}': flag(s) {a & c} gate both availableWhen and closedWhen")
            if "giverId" in q:
                self.ref_char(q["giverId"], f"quest '{qid}'")

        # count task conditions as reads (flag hygiene accuracy)
        for qid, (q, _p) in valid_quests.items():
            for key in ("availableWhen", "closedWhen"):
                if key in q:
                    self.walk_condition(q[key], f"quest '{qid}' {key}")
            for st in q["stages"]:
                if "completeWhen" in st:
                    self.walk_condition(st["completeWhen"], f"quest '{qid}' stage '{st['id']}'")
            for oc in q.get("outcomes", []):
                if "reachedWhen" in oc:
                    self.walk_condition(oc["reachedWhen"], f"quest '{qid}' outcome '{oc['id']}'")

        # Quest journal objectives (OBJ) — display-only routes shown for the
        # CURRENT stage. Every check here is about what the journal will SHOW;
        # completion is always completeWhen's job. Mirrors the OBJ pass in
        # editor/core/src/validator.ts. The controlled vocabulary for quest tags
        # is per-project, not a Parlance concept — projects declare it in
        # rules.json. Absent ⇒ any tag is accepted.
        quest_tag_vocabulary = None
        if isinstance(self.rules, dict):
            quest_tag_vocabulary = (self.rules.get("quest") or {}).get("tagVocabulary")

        for qid, (q, _p) in valid_quests.items():
            for st in q["stages"]:
                objectives = st.get("objectives", [])
                seen_obj = set()
                for ob in objectives:
                    ow = f"quest '{qid}' stage '{st['id']}' objective '{ob['id']}'"
                    if ob["id"] in seen_obj:
                        self.err("OBJ", f"{ow}: duplicate objective id within the stage")
                    seen_obj.add(ob["id"])
                    # REF pass + registers the read for the FLAG orphan pass.
                    if "showIf" in ob:
                        self.walk_condition(ob["showIf"], f"{ow} showIf")
                if "completeWhen" in st and not objectives:
                    self.warn("OBJ", f"quest '{qid}' stage '{st['id']}': has completeWhen but no objectives — the journal will show an empty current stage")
                if objectives and all("showIf" in ob for ob in objectives):
                    self.warn("OBJ", f"quest '{qid}' stage '{st['id']}': every objective is gated by showIf — the stage can present an empty list at runtime")
            if quest_tag_vocabulary is not None:
                for tag in q.get("tags", []):
                    if tag not in quest_tag_vocabulary:
                        self.warn("OBJ", f"quest '{qid}': tag '{tag}' is not in the project's quest tag vocabulary (rules.quest.tagVocabulary: {', '.join(quest_tag_vocabulary)})")

    def check_cutscenes(self):
        # Cutscene manifests: opaque engine asset key + on-complete effects.
        # `asset` is deliberately NOT resolved (an engine-side concern);
        # emptiness is enforced by the JSON schema. effectsOnComplete may itself
        # contain play_cutscene (a chain), so walk all before the unused check.
        #
        # This pass runs BEFORE the ENDING/CODEX reachability passes: a flag set
        # only by a cutscene's effectsOnComplete is a real write, and walking it
        # late made every ending gated on one look unreachable.
        for csid, (cs, _p) in self.cutscenes.items():
            if not self.valid("cutscene", csid):
                continue
            w = f"cutscene '{csid}'"
            ed = cs.get("entersDialogue")
            if ed is not None and ed not in self.dialogues:
                self.err("CUT", f"{w}: entersDialogue '{ed}' not found")
            # arrivesAt names where the player is put down afterwards; a
            # dangling location or spawn there strands the player
            # mid-transition, so it's an error rather than a warning.
            aa = cs.get("arrivesAt")
            if aa:
                if aa["location"] not in self.locations:
                    self.err("CUT", f"{w}: arrivesAt unknown location '{aa['location']}'")
                elif not any(s.get("id") == aa["spawn"] for s in (self.locations[aa["location"]][0].get("spawns") or [])):
                    self.err("CUT", f"{w}: arrivesAt spawn '{aa['spawn']}' not found in location '{aa['location']}'")
            for e in cs.get("effectsOnComplete", []):
                self.walk_effect(e, f"{w} effectsOnComplete")
        for csid in self.cutscenes:
            if csid not in self.triggered_cutscenes:
                self.warn("CUT", f"cutscene '{csid}' is never referenced by any play_cutscene effect")

        # Two play_cutscene effects reachable from the same dialogue node —
        # pendingCutscene is last-write-wins, so the ordering is ambiguous.
        for did, (dlg, _p) in self.dialogues.items():
            if not self.valid("dialogue", did):
                continue
            for n in dlg["nodes"]:
                fires = [e["cutscene"] for e in n.get("onEnter", []) if e.get("type") == "play_cutscene"]
                for ch in n.get("choices", []):
                    fires += [e["cutscene"] for e in ch.get("effects", []) if e.get("type") == "play_cutscene"]
                if len(fires) > 1:
                    self.warn("CUT", f"dialogue '{did}' node '{n['id']}' fires {len(fires)} play_cutscene effects ({', '.join(fires)}) — pendingCutscene is last-write-wins, ordering is ambiguous")

    def check_codex_endings(self):
        # Codex entries mirror the ending reachability check, but only where
        # there IS a condition: an entry with no unlockedBy is always available,
        # which is not a bug.
        for cid, (o, _p) in self.codex.items():
            if not self.valid("codex", cid):
                continue
            if "unlockedBy" not in o:
                continue
            self.walk_condition(o["unlockedBy"], f"codex '{cid}'")
            for fl in self.flags_in_condition(o["unlockedBy"], set()):
                if fl not in self.flags_written:
                    self.warn("CODEX", f"codex '{cid}' needs flag '{fl}' never set — may be unreachable")

        for eid, (o, _p) in self.endings.items():
            if not self.valid("ending", eid):
                continue
            self.walk_condition(o["unlockedBy"], f"ending '{eid}'")
            for fl in self.flags_in_condition(o["unlockedBy"], set()):
                if fl not in self.flags_written:
                    self.warn("ENDING", f"ending '{eid}' needs flag '{fl}' never set — may be unreachable")

    def check_routes(self):
        # Routes (ROUTE pass) — mirrors validateRouteRefs in editor/core/src/routeRunner.ts.
        route_err = lambda m: self.err("ROUTE", m)
        route_warn = lambda m: self.warn("ROUTE", m)
        # All-choices lists are rebuilt lazily, once per dialogue — not once per
        # route step.
        choices_cache = {}

        def all_choices_of(dlg):
            did = dlg["id"]
            if did not in choices_cache:
                choices_cache[did] = [c for n in dlg.get("nodes", []) for c in n.get("choices", [])]
            return choices_cache[did]

        for rid, (route, _p) in self.routes.items():
            if not self.valid("route", rid):
                continue
            if route.get("startSnapshot") and route["startSnapshot"] not in self.snapshots:
                route_err(f"unknown startSnapshot '{route['startSnapshot']}'")
            if route["dialogueId"] not in self.dialogues:
                route_err(f"unknown dialogueId '{route['dialogueId']}'")
                continue
            dialogue = self.dialogues[route["dialogueId"]][0]
            for i, step in enumerate(route["steps"]):
                if "cutscene" in step:
                    cs = self.cutscenes.get(step["cutscene"])
                    if not cs:
                        route_err(f"step {i}: unknown cutscene '{step['cutscene']}'")
                    elif cs[0].get("entersDialogue") and cs[0]["entersDialogue"] in self.dialogues:
                        dialogue = self.dialogues[cs[0]["entersDialogue"]][0]
                    continue
                # N2 advance step: N choiceless `next` hops. There is no choice
                # to resolve, so the reference checks below do not apply — the
                # runner is what proves the chain is walkable, and duplicating
                # that here would mean simulating the walk. Only the shape is
                # worth asserting.
                if "advance" in step:
                    n = step["advance"]
                    if not isinstance(n, int) or isinstance(n, bool) or n < 1:
                        route_err(f"step {i}: 'advance' must be a positive integer, got {n!r}")
                    continue
                if step.get("continuation"):
                    if step["continuation"] not in self.dialogues:
                        route_err(f"step {i}: unknown continuation dialogueId '{step['continuation']}'")
                    else:
                        dialogue = self.dialogues[step["continuation"]][0]
                choice = next((c for c in all_choices_of(dialogue) if c["id"] == step["choiceId"]), None)
                if not choice:
                    route_err(f"step {i}: choice '{step['choiceId']}' not found in dialogue '{dialogue['id']}'")
                elif step.get("forced") and not choice.get("check"):
                    route_warn(f"step {i}: choice '{step['choiceId']}' is forced but has no check — forced is a no-op")
            ae = route.get("assertEnd")
            if ae:
                if ae.get("endingAvailable") and ae["endingAvailable"] not in self.endings:
                    route_err(f"assertEnd.endingAvailable: unknown ending '{ae['endingAvailable']}'")
                if ae.get("pendingCutscene") and ae["pendingCutscene"] not in self.cutscenes:
                    route_err(f"assertEnd.pendingCutscene: unknown cutscene '{ae['pendingCutscene']}'")
                for flag in list(ae.get("flags", {}).keys()) + ae.get("forbiddenFlags", []):
                    v = self.variables.get(flag)
                    if not v:
                        route_warn(f"assertEnd: flag '{flag}' not declared in variables.json")
                    elif v.get("kind") != "flag":
                        route_err(f"assertEnd: '{flag}' is a {v.get('kind')}, used as flag")
                for qid, stage in ae.get("questStages", {}).items():
                    if qid not in self.quests:
                        route_err(f"assertEnd.questStages: unknown quest '{qid}'")
                    elif stage not in self.quest_stage_ids(qid):
                        route_err(f"assertEnd.questStages: stage '{stage}' not in quest '{qid}'")

    def check_snapshots(self):
        # Snapshots (SNAP pass) — mirrors the SNAP block in editor/core/src/validator.ts.
        for sid, (snap, _p) in self.snapshots.items():
            if not self.valid("snapshot", sid):
                continue
            w = f"snapshot '{sid}'"
            st = snap.get("state", {})
            for flag in st.get("flags", {}):
                self.ref_var(flag, "flag", w)
            for ctr in st.get("counters", {}):
                self.ref_var(ctr, "counter", w)
            for item in st.get("inventory", []):
                self.ref_item(item, w)
            for skill in st.get("skills", {}):
                self.ref_skill(skill, w)
            for skill in st.get("skillPointsSpent", {}):
                self.ref_skill(skill, f"{w} skillPointsSpent")
            for fac in st.get("reputation", {}):
                self.ref_faction(fac, w)
            for text in st.get("texts", {}):
                self.ref_var(text, "text", f"{w} texts")
            for cid in st.get("relationships", {}):
                self.ref_char(cid, f"{w} relationships")
            # questFired keys are `{quest}/{stage|outcome}/{id}` — a stale key
            # silently stops matching and lets a once-only effect re-fire from
            # this baseline. Mirrors the SNAP block in validator.ts.
            for key in snap.get("state", {}).get("questFired", []):
                parts = key.split("/")
                qid = parts[0] if parts else ""
                kind = parts[1] if len(parts) > 1 else None
                item_id = parts[2] if len(parts) > 2 else ""
                if not qid or not item_id or len(parts) > 3 or kind not in ("stage", "outcome"):
                    self.err("SNAP", f"{w}: questFired key '{key}' is not '{{quest}}/stage|outcome/{{id}}'")
                    continue
                if qid not in self.quests:
                    self.err("SNAP", f"{w}: questFired unknown quest '{qid}'")
                else:
                    known = self.quest_stage_ids(qid) if kind == "stage" else self.quest_outcome_ids(qid)
                    if item_id not in known:
                        self.err("SNAP", f"{w}: questFired {kind} '{item_id}' not in quest '{qid}'")
            for q, stage in st.get("questStages", {}).items():
                if q not in self.quests:
                    self.err("SNAP", f"{w}: questStages unknown quest '{q}'")
                elif stage not in self.quest_stage_ids(q):
                    self.err("SNAP", f"{w}: stage '{stage}' not in quest '{q}'")
            if st.get("pendingCutscene") and st["pendingCutscene"] not in self.cutscenes:
                self.err("SNAP", f"{w}: pendingCutscene unknown cutscene '{st['pendingCutscene']}'")
            # The visited set gates discovery: a stale id stops filtering
            # silently, so a route from this baseline would offer a one-shot the
            # real game would not.
            for did in snap.get("visitedDialogueIds", []):
                if did not in self.dialogues:
                    self.err("SNAP", f"{w}: visitedDialogueIds names unknown dialogue '{did}'")

    @staticmethod
    def dialogue_is_effectful(dlg):
        for n in dlg.get("nodes", []):
            if n.get("onEnter"):
                return True
            for ch in n.get("choices", []):
                if ch.get("effects"):
                    return True
        return False

    def check_locations_and_ladders(self):
        # Locations (LOC pass) — mirrors editor/core/src/validator.ts. Graph
        # integrity: exit targets + spawns, denial dialogues, gates,
        # interactables, reachability, and within-location id uniqueness.
        valid_locations = {lid: lp for lid, lp in self.locations.items() if self.valid("location", lid)}

        # Dialogues placed in the world without needing a ladder:
        # object/environment interactables name a dialogue directly, and an
        # exit's denialDialogue plays when a gate refuses. A speaker reachable
        # only those ways is correctly ladderless.
        # Every dialogue presented by ANY character's ladder — a rung makes a
        # dialogue discoverable regardless of whose ladder it sits in.
        dialogues_in_ladders = {
            rung["dialogue"]
            for c, _p in self.characters.values()
            for rung in (c.get("dialogues") or [])
        }
        dialogues_placed_in_world = set()
        for _lid, (loc, _lp) in valid_locations.items():
            for it in loc.get("interactables", []) or []:
                if it.get("dialogue"):
                    dialogues_placed_in_world.add(it["dialogue"])
            for ex in loc.get("exits", []) or []:
                if ex.get("denialDialogue"):
                    dialogues_placed_in_world.add(ex["denialDialogue"])

        # Dialogue ladder: dangling-ref (REF) + shallow shape checks (LADDER).
        # Mirrors checkDialogueLadder in editor/core/src/validator.ts.
        for cid, (o, _p) in self.characters.items():
            if not self.valid("character", cid):
                continue
            ladder = o.get("dialogues") or []
            w = f"character '{cid}'"
            for i, rung in enumerate(ladder):
                if rung["dialogue"] not in self.dialogues:
                    self.err("REF", f"{w}: dialogues[{i}] '{rung['dialogue']}' not found")
                if "showIf" in rung:
                    self.walk_condition(rung["showIf"], f"{w} dialogues[{i}].showIf")
            # dead rung: unconditional rung that is not last shadows every rung
            # below it.
            for i, rung in enumerate(ladder):
                if "showIf" not in rung and i < len(ladder) - 1:
                    shadowed = len(ladder) - 1 - i
                    self.warn("LADDER", f"{w}: dialogues[{i}] '{rung['dialogue']}' is unconditional but not last — shadows {shadowed} rung(s) below (dead rungs)")
            # stuck rung: unconditional + top-priority + effectful → wins
            # forever, re-fires.
            if ladder:
                top = ladder[0]
                if "showIf" not in top and top["dialogue"] in self.dialogues and self.dialogue_is_effectful(self.dialogues[top["dialogue"]][0]):
                    self.warn("LADDER", f"{w}: dialogues[0] '{top['dialogue']}' is unconditional, top-priority, and carries effects — it wins forever and re-fires on every re-entry")
            # no fallthrough: last rung gated → character may resolve to no
            # dialogue.
            if ladder and "showIf" in ladder[-1]:
                self.warn("LADDER", f"{w}: last ladder rung '{ladder[-1]['dialogue']}' has a showIf — no unconditional fallthrough, so the character may resolve to no dialogue in some states")
            # Stranded speaker-dialogues: naming this character as ROOT speaker
            # makes nothing discoverable — only a ladder rung (ANY character's),
            # an availableWhen, or a world placement does. Checked for EVERY
            # character: a ladder-owning character can still have a dialogue no
            # rung presents. This used to be nested inside `if not ladder`, and
            # to ignore ladder membership, so it disagreed with validator.ts in
            # both directions — the editor warned where CI was silent, and CI
            # warned where the editor was silent. Under --strict that is a
            # disagreement about the exit code.
            stranded = sorted(
                d for d in self.dialogues_by_speaker.get(cid, [])
                if not self.dialogues[d][0].get("availableWhen")
                and d not in dialogues_placed_in_world
                and d not in dialogues_in_ladders
            )
            if not ladder:
                # No ladder at all: resolveCharacterDialogue returns null, and
                # discovery only falls back to availableWhen.
                if stranded:
                    self.warn("LADDER", f"{w}: no dialogues ladder, so resolution returns null — {len(stranded)} dialogue(s) carry no availableWhen either and are unreachable: {', '.join(stranded)}")
            elif stranded:
                self.warn("LADDER", f"{w}: {len(stranded)} speaker dialogue(s) sit in no ladder rung, carry no availableWhen, and have no world placement — unreachable: {', '.join(stranded)}")

        spawns_by_loc = {lid: {s["id"] for s in loc.get("spawns", [])} for lid, (loc, _p) in valid_locations.items()}
        reachable_from = {lid: set() for lid in valid_locations}
        for lid, (loc, _p) in valid_locations.items():
            for ex in loc.get("exits", []):
                if ex["to"]["location"] in reachable_from:
                    reachable_from[ex["to"]["location"]].add(lid)

        for lid, (loc, _p) in valid_locations.items():
            w = f"location '{lid}'"

            # within-location id uniqueness (spawns / exits / interactables)
            for coll, kind in ((loc.get("spawns", []), "spawn"), (loc.get("exits", []), "exit"), (loc.get("interactables", []), "interactable")):
                seen = set()
                for item in coll:
                    if item["id"] in seen:
                        self.err("DUP", f"{w}: duplicate {kind} id '{item['id']}'")
                    seen.add(item["id"])

            for ex in loc.get("exits", []):
                ew = f"{w} exit '{ex['id']}'"
                if ex["to"]["location"] not in self.locations:
                    self.err("REF", f"{ew}: unknown target location '{ex['to']['location']}'")
                else:
                    # A target with ZERO declared spawns is NOT exempt. Exempting
                    # it (the old `if target_spawns and ...` guard) let the two
                    # transition kinds disagree about the same door: cutscene
                    # arrivesAt already errors on a spawnless target, so an exit
                    # accepting any name there meant the editor reported the
                    # door and CI did not. Mirrors validator.ts.
                    target_spawns = spawns_by_loc.get(ex["to"]["location"], set())
                    if ex["to"]["spawn"] not in target_spawns:
                        self.err("LOC", f"{ew}: spawn '{ex['to']['spawn']}' not defined in location '{ex['to']['location']}'")
                if ex.get("denialDialogue") and ex["denialDialogue"] not in self.dialogues:
                    self.err("REF", f"{ew}: denialDialogue '{ex['denialDialogue']}' not found")
                if "gate" in ex:
                    self.walk_condition(ex["gate"], f"{ew} gate")
                if ex.get("gateType") and "gate" not in ex:
                    self.warn("LOC", f"{ew}: gateType set but no gate condition — gate is never enforced")
                if "gate" in ex and not ex.get("gateType"):
                    self.warn("LOC", f"{ew}: gate condition set but no gateType — gate presentation unspecified")

            for it in loc.get("interactables", []):
                iw = f"{w} interactable '{it['id']}'"
                if it.get("kind") == "npc":
                    if not it.get("character"):
                        self.err("LOC", f"{iw}: kind 'npc' requires character field")
                    elif it["character"] not in self.characters:
                        self.err("REF", f"{iw}: unknown character '{it['character']}'")
                    elif not (self.characters[it["character"]][0].get("dialogues") or []):
                        # An npc interactable resolves through the ladder ONLY.
                        # Without one, resolveCharacterDialogue returns null and
                        # interacting does nothing.
                        self.warn("LOC", f"{iw}: character '{it['character']}' has no dialogues ladder, so resolution returns null and this interactable is a no-op — give them a ladder ending in an unconditional rung")
                    if it.get("dialogue"):
                        self.warn("LOC", f"{iw}: npc interactable has dialogue field; runtime resolves the character's dialogue ladder — did you mean character?")
                    if it.get("trigger") == "on_enter":
                        # A character who starts talking at you the moment you
                        # walk in is almost always a scene wearing an npc
                        # costume: model it as an object interactable so the
                        # trigger reads as authored intent.
                        self.warn("LOC", f"{iw}: npc interactable with trigger 'on_enter' talks at the player unprompted — model an automatic scene as kind 'object'")
                else:
                    if not it.get("dialogue"):
                        self.warn("LOC", f"{iw}: kind '{it.get('kind')}' has no dialogue — nothing happens when the player interacts with it")
                    elif it["dialogue"] not in self.dialogues:
                        self.err("REF", f"{iw}: unknown dialogue '{it['dialogue']}'")
                if "showIf" in it:
                    self.walk_condition(it["showIf"], f"{iw} showIf")

            is_start = "start" in loc.get("tags", [])
            has_incoming = len(reachable_from.get(lid, set())) > 0
            if not is_start and not has_incoming and len(self.locations) > 1:
                self.warn("LOC", f"{w}: unreachable — no exit points here and not tagged 'start'")

        # A spawn nothing arrives at is authored intent that never happens: the
        # door that was supposed to use it points somewhere else, and the player
        # lands in the wrong part of the room with nothing reporting it. A spawn
        # marked `"isDefault": true` is exempt — it is where the engine puts the
        # player when nothing named a spawn (new game, dev entry, a cutscene
        # arrival with no door), so by definition no exit points at it.
        arrived_at = {}
        for _lid, (loc, _p) in valid_locations.items():
            for ex in loc.get("exits", []) or []:
                arrived_at.setdefault(ex["to"]["location"], set()).add(ex["to"]["spawn"])
        for csid, (cs, _p) in self.cutscenes.items():
            if not self.valid("cutscene", csid):
                continue
            aa = cs.get("arrivesAt")
            if aa:
                arrived_at.setdefault(aa["location"], set()).add(aa["spawn"])

        for lid, (loc, _p) in valid_locations.items():
            used = arrived_at.get(lid, set())
            # "At most one default" is a promise the schema makes but cannot
            # express.
            defaults = [sp["id"] for sp in (loc.get("spawns", []) or []) if sp.get("isDefault") is True]
            if len(defaults) > 1:
                self.err("LOC", f"location '{lid}': {len(defaults)} spawns marked default ({', '.join(defaults)}) — exactly one arrival point can be the default")
            for sp in loc.get("spawns", []) or []:
                if sp.get("isDefault") is True or sp["id"] in used:
                    continue
                self.warn("LOC", f"location '{lid}': spawn '{sp['id']}' exists but no exit or cutscene arrives there — the door meant to use it is pointing somewhere else")

    def check_portrait_usage(self):
        for pid in self.portraits:
            if pid not in self.used_portraits:
                self.warn("PORT", f"portrait '{pid}' is registered but never used")

    # --- TEXT pass — {var_id} placeholders in PLAYER-FACING strings only.
    # Ids, names, summaries and other authoring-facing fields are never
    # interpolated, so a brace in one of them is just a brace. Mirrors validator.ts.
    def scan_text(self, text, w):
        if not text:
            return
        for vid in dict.fromkeys(PLACEHOLDER_RE.findall(text)):
            self.texts_read.add(vid)
            v = self.variables.get(vid)
            if not v:
                self.err("TEXT", f"{w}: placeholder '{{{vid}}}' is not a registered variable (add a kind:\"text\" variable)")
            elif v.get("kind") != "text":
                self.err("TEXT", f"{w}: placeholder '{{{vid}}}' refers to a {v.get('kind')}, not a text variable")

    def engine_written(self, vid):
        # writtenBy:"engine" means the HOST writes this at runtime (free text
        # the player typed, or computed state). Parlance has no input-capture
        # concept, so there is no authored effect to find — suppress the
        # never-written / read-never-set passes for them rather than inviting a
        # fake literal set_text to silence the warning.
        return (self.variables.get(vid) or {}).get("writtenBy") == "engine"

    def check_text(self):
        for did, (dlg, _p) in self.dialogues.items():
            if not self.valid("dialogue", did):
                continue
            for n in dlg["nodes"]:
                self.scan_text(n.get("text"), f"dialogue '{did}' node '{n['id']}' text")
                for ch in n.get("choices", []):
                    self.scan_text(ch.get("text"), f"dialogue '{did}' node '{n['id']}' choice '{ch['id']}' text")
        for qid, (q, _p) in self.quests.items():
            if not self.valid("quest", qid):
                continue
            self.scan_text(q.get("journalName"), f"quest '{qid}' journalName")
            for st in q["stages"]:
                self.scan_text(st.get("description"), f"quest '{qid}' stage '{st['id']}' description")
                for ob in st.get("objectives", []):
                    self.scan_text(ob.get("text"), f"quest '{qid}' stage '{st['id']}' objective '{ob['id']}' text")

        for vid, v in self.variables.items():
            if v.get("kind") != "text":
                continue
            if vid not in self.texts_written and not isinstance(v.get("default"), str) and not self.engine_written(vid):
                self.warn("TEXT", f"text variable '{vid}' is never written by a set_text effect and has no default — every '{{{vid}}}' will render as the raw placeholder")
            if vid not in self.texts_read:
                self.warn("TEXT", f"text variable '{vid}' is declared but never referenced in any authored string")

    def check_flag_hygiene(self):
        declared = {vid for vid, v in self.variables.items() if v.get("kind") == "flag"}
        for fl in declared:
            if fl in self.flags_read and fl not in self.flags_written and not self.engine_written(fl):
                self.warn("FLAG", f"'{fl}' read but never set — gate can never open")
            if fl in self.flags_written and fl not in self.flags_read:
                self.warn("FLAG", f"'{fl}' set but never read — possibly dead state")
            if fl not in self.flags_read and fl not in self.flags_written and not self.engine_written(fl):
                self.warn("FLAG", f"'{fl}' declared but never used")
        for fac in self.factions:
            if fac in self.reps_read and fac not in self.reps_adjusted:
                self.warn("REP", f"faction '{fac}' checked but never adjusted")
        # Relationship hygiene — same shape as REP.
        for ch in self.characters:
            if ch in self.rels_read and ch not in self.rels_adjusted:
                self.warn("REL", f"character '{ch}' relationship checked but never adjusted")

    def check_progression(self):
        # --- Progression (PROG / XP pass) — mirrors validator.ts ---
        progression = self.progression
        if progression is None or not isinstance(progression, dict):
            return
        w = "progression.json"
        thr = progression.get("xpThresholds")
        if not isinstance(thr, list) or len(thr) == 0:
            self.err("PROG", f"{w}: xpThresholds must be a non-empty array")
        else:
            for i in range(1, len(thr)):
                if thr[i] <= thr[i - 1]:
                    self.err("PROG", f"{w}: xpThresholds must be strictly increasing (index {i} = {thr[i]})")
                    break
        ppl = progression.get("pointsPerLevel")
        ms = progression.get("maxSkill")
        if not (isinstance(ppl, (int, float)) and ppl >= 1):
            self.err("PROG", f"{w}: pointsPerLevel must be ≥ 1")
        if not (isinstance(ms, (int, float)) and ms >= 1):
            self.err("PROG", f"{w}: maxSkill must be ≥ 1")

        def skill_cap(sid):
            # Per-skill `max` (skills.json) overrides the global maxSkill.
            return (self.skills.get(sid) or {}).get("max", ms)

        for sid, val in (progression.get("startingSkills") or {}).items():
            if sid not in self.skills:
                self.err("REF", f"{w}: startingSkills references unknown skill '{sid}'")
            if isinstance(ms, (int, float)) and val >= skill_cap(sid):
                self.warn("PROG", f"{w}: startingSkills['{sid}'] ({val}) ≥ its ceiling ({skill_cap(sid)}) — nothing to invest")
        if isinstance(ms, (int, float)) and ms >= 1 and isinstance(ppl, (int, float)) and ppl >= 1 and isinstance(thr, list) and thr:
            total_xp = sum(max(0, a) for a, _w, _s in self.xp_grants)
            level = 0
            for i, t2 in enumerate(thr):
                if total_xp >= t2:
                    level = i
                else:
                    break
            earnable = level * ppl
            cost = sum(max(0, skill_cap(sid) - (progression.get("startingSkills") or {}).get(sid, 0)) for sid in self.skills)
            if cost > 0 and earnable >= cost:
                self.warn("PROG", f"{w}: progression not actually capped — authored XP grants {earnable} point(s), enough to max all skills (cost {cost}).")

    def check_quest_resolution_reachability(self):
        # Quest-resolution reachability: effects with no condition can never fire.
        for qid, (q, _p) in self.quests.items():
            if not self.valid("quest", qid):
                continue
            for st in q.get("stages", []):
                if st.get("onComplete") and "completeWhen" not in st:
                    self.warn("QUEST", f"quest '{qid}' stage '{st['id']}': onComplete effects but no completeWhen — they can never fire")
            for oc in q.get("outcomes", []):
                if oc.get("effects") and "reachedWhen" not in oc:
                    self.warn("QUEST", f"quest '{qid}' outcome '{oc['id']}': effects but no reachedWhen — they can never fire")

    def check_xp_advisory(self):
        # XP advisory: grant_xp authored outside a quest outcome (convention =
        # quests only). Silent in a quest-free project: quests are optional, and
        # a dialogue-driven game has nowhere else to put XP — firing the
        # advisory on every grant would make --strict unusable for it.
        if self.quests:
            for _amount, where, from_quest_outcome in self.xp_grants:
                if not from_quest_outcome:
                    self.warn("XP", f"{where}: grant_xp authored outside a quest outcome — the convention is XP from quest outcomes only (advisory)")

    def check_check_discipline(self):
        # --- Priced/oneshot check discipline (CHECK) + mandatory-path lockout (REACH) ---
        ladder_read_flags = set()
        for cid, (o, _p) in self.characters.items():
            for rung in o.get("dialogues") or []:
                if "showIf" in rung:
                    self.flags_in_condition(rung["showIf"], ladder_read_flags)
        for did, (dlg, _p) in self.dialogues.items():
            if not self.valid("dialogue", did):
                continue
            nodes_by_id = {n["id"]: n for n in dlg["nodes"]}
            for n in dlg["nodes"]:
                for ch in n.get("choices", []):
                    k = ch.get("check")
                    if not k:
                        continue
                    cw = f"dialogue '{did}' node '{n['id']}' choice '{ch['id']}'"
                    # kind is authoring intent for ACTIVE checks; on a passive
                    # check it is silently ignored by the runtime, so saying it
                    # is a mistake.
                    if k.get("mode") != "active":
                        if "kind" in k:
                            self.warn("CHECK", f"{cw}: kind '{k['kind']}' on a passive check is ignored — passive checks never roll, so there is no pass/fail to price")
                        if k.get("acknowledgedLockout"):
                            self.warn("CHECK", f"{cw}: acknowledgedLockout on a passive check is ignored — it only applies to kind:'oneshot' active checks")
                        continue
                    # oneshot is exempt from the proceed requirement. Note there
                    # is NO structural tell that separates the two kinds: a
                    # oneshot's plot also proceeds (it proceeds without that
                    # perception), so a continuing onFailure branch is not
                    # evidence of mislabeling. Intent only.
                    if k.get("kind", "priced") != "priced":
                        continue
                    if k.get("acknowledgedLockout"):
                        self.warn("CHECK", f"{cw}: acknowledgedLockout is only meaningful with kind:'oneshot' — a priced check never locks anything out")
                    if "onFailure" not in k:
                        self.warn("CHECK", f"{cw}: priced check failure must proceed — add an onFailure branch that advances at a cost (or tag kind:'oneshot')")
                    else:
                        fail = nodes_by_id.get(k["onFailure"])
                        for e in (fail or {}).get("onEnter", []):
                            if e.get("type") == "set_flag" and e.get("flag") in ladder_read_flags:
                                self.warn("CHECK", f"{cw}: priced-gate failure sets ladder-reordering flag '{e['flag']}' — confirm this isn't a punishment-spiral cost (advisory)")
            inbound = {}
            for n in dlg["nodes"]:
                # next (N2) is an unconditional edge — every player takes it, so
                # it can never be the thing that walls someone off. Counts as
                # "other".
                if n.get("next"):
                    inbound.setdefault(n["next"], []).append("other")
                for ch in n.get("choices", []):
                    k = ch.get("check")
                    edges_kv = []
                    if k and k.get("mode") == "active":
                        # acknowledgedLockout: the author has declared this
                        # lockout intentional, so its success edge stops
                        # counting as a trap.
                        if k.get("kind") == "oneshot" and not k.get("acknowledgedLockout"):
                            success_kind = "oneshot-success"
                        else:
                            success_kind = "other"
                        edges_kv.append((k.get("onSuccess"), success_kind))
                        edges_kv.append((k.get("onFailure"), "other"))
                    elif ch.get("goto"):
                        edges_kv.append((ch["goto"], "other"))
                    for tgt, kind in edges_kv:
                        if tgt:
                            inbound.setdefault(tgt, []).append(kind)
            for node_id, edges in inbound.items():
                if node_id == dlg["entry"]:
                    continue
                if edges and all(x == "oneshot-success" for x in edges):
                    self.warn("REACH", f"dialogue '{did}': node '{node_id}' is reachable only by succeeding oneshot (pass-or-fail) checks — an unlucky or under-built player can be permanently walled off (tag the check acknowledgedLockout:true if that is the intent)")

    def check_lorerefs(self):
        def check_loreref(o, w):
            lr = o.get("loreRef")
            if lr and not os.path.exists(os.path.join(self.root, lr["file"])):
                self.err("LORE", f"{w}: loreRef file '{lr['file']}' missing")

        for kind, reg in (
            ("faction", self.factions), ("character", self.characters),
            ("dialogue", self.dialogues), ("quest", self.quests),
            ("location", self.locations), ("ending", self.endings),
            ("codex", self.codex),
        ):
            for k, (o, p) in reg.items():
                check_loreref(o, f"{kind} '{o.get('id', k)}' ({self.rel(p)})")
        for kind, reg in (("skill", self.skills), ("item", self.items)):
            p = self._registry_paths.get(kind)
            where_file = f" ({self.rel(p)})" if p else ""
            for entity in reg.values():
                check_loreref(entity, f"{kind} '{entity['id']}'{where_file}")

    # -- driver --------------------------------------------------------------

    def run(self):
        self.load()
        self.resolve_rules()
        self.check_variables()
        self.check_characters_portraits_factions()
        self.check_dialogues()
        self.check_coverage()
        self.check_quests()
        # Cutscenes BEFORE endings/codex: their effectsOnComplete are flag
        # writes the reachability passes must see.
        self.check_cutscenes()
        self.check_codex_endings()
        self.check_routes()
        self.check_snapshots()
        self.check_locations_and_ladders()
        self.check_portrait_usage()
        self.check_text()
        self.check_flag_hygiene()
        self.check_progression()
        self.check_quest_resolution_reachability()
        self.check_xp_advisory()
        self.check_check_discipline()
        self.check_lorerefs()
        return self.issues

    def summary_line(self):
        return (
            f"Loaded: {len(self.skills)} skills, {len(self.factions)} factions, {len(self.characters)} characters, "
            f"{len(self.dialogues)} dialogues, {len(self.variables)} variables, {len(self.quests)} quests, "
            f"{len(self.locations)} locations, {len(self.endings)} endings, {len(self.codex)} codex, {len(self.portraits)} portraits, "
            f"{len(self.cutscenes)} cutscenes, {len(self.routes)} routes, {len(self.snapshots)} snapshots.\n"
        )


def validate_project(root):
    """Run every pass over a project root; returns the ProjectValidator."""
    v = ProjectValidator(root)
    v.run()
    return v


def format_issue(issue):
    return f"[{issue.code}] {issue.message}"


def report(v, strict):
    """Print the classic report; returns the process exit code."""
    print(v.summary_line())
    if v.warnings:
        print(f"WARN  {len(v.warnings)} warning(s):")
        for w in v.warnings:
            print("  " + format_issue(w))
        print()
    if v.errors:
        print(f"FAIL  {len(v.errors)} error(s):")
        for e in v.errors:
            print("  " + format_issue(e))
        return 1
    if strict and v.warnings:
        print("FAIL  --strict: warnings treated as errors.")
        return 1
    print("OK  No errors." + ("" if not v.warnings else "  (warnings above are non-fatal.)"))
    return 0


def main(argv=None):
    parser = argparse.ArgumentParser(
        prog="validate.py",
        description="Parlance data validator — reference implementation.",
    )
    parser.add_argument("--root", metavar="PATH", default=None,
                        help="project root to validate (default: this repository)")
    parser.add_argument("--strict", action="store_true",
                        help="treat warnings as errors (exit 1)")
    args = parser.parse_args(argv)

    root = os.path.abspath(args.root) if args.root else REPO_ROOT
    if not os.path.isdir(root):
        sys.exit(f"validate.py: no such project root '{root}'")

    v = ProjectValidator(root)
    try:
        v.run()
    except Exception:
        # An internal crash must not hide what was already found: a malformed
        # file's SCHEMA errors are usually the explanation for the crash itself.
        print(v.summary_line())
        if v.warnings:
            print(f"WARN  {len(v.warnings)} warning(s) collected before the crash:")
            for w in v.warnings:
                print("  " + format_issue(w))
            print()
        if v.errors:
            print(f"FAIL  {len(v.errors)} error(s) collected before the crash:")
            for e in v.errors:
                print("  " + format_issue(e))
            print()
        print("validate.py: internal error — traceback follows.", file=sys.stderr)
        raise
    return report(v, args.strict)


if __name__ == "__main__":
    sys.exit(main())
