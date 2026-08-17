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
"""
import json, sys, os, glob, re
from jsonschema import Draft7Validator
from referencing import Registry, Resource
from referencing.jsonschema import DRAFT7

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
STRICT = "--strict" in sys.argv

def _parse_root(argv):
    """--root <path> / --root=<path>, defaulting to this repo's own root."""
    for i, a in enumerate(argv):
        if a == "--root":
            if i + 1 >= len(argv):
                sys.exit("validate.py: --root needs a path")
            return os.path.abspath(argv[i + 1])
        if a.startswith("--root="):
            return os.path.abspath(a.split("=", 1)[1])
    return REPO_ROOT

ROOT = _parse_root(sys.argv[1:])
if not os.path.isdir(ROOT):
    sys.exit(f"validate.py: no such project root '{ROOT}'")

# parlance.config.json mirrors the editor's per-project overrides (see
# SETUP_AND_MANAGEMENT.md §4); absent or malformed falls back to defaults.
_cfg = {}
_cfg_path = os.path.join(ROOT, "parlance.config.json")
if os.path.exists(_cfg_path):
    try:
        with open(_cfg_path) as f: _cfg = json.load(f) or {}
    except (json.JSONDecodeError, OSError):
        _cfg = {}

DATA_DIR = os.path.join(ROOT, _cfg.get("data") or "data")
# Route/snapshot fixtures are regression tests, not narrative content, so they
# live beside data/ rather than inside it — a shipping game never loads them.
TESTS_DIR = os.path.join(ROOT, _cfg.get("tests") or "tests")
# Schemas ship with the tool: a project only needs its own schema/ to pin a
# specific contract version, so fall back to this repo's set (same rule the
# editor host applies).
SCHEMA_DIR = os.path.join(ROOT, _cfg.get("schema") or "schema")
if not os.path.isdir(SCHEMA_DIR):
    SCHEMA_DIR = os.path.join(REPO_ROOT, "schema")

errors, warnings = [], []
def err(m): errors.append(m)
def warn(m): warnings.append(m)
def load_json(p):
    with open(p) as f: return json.load(f)

schema_store = {}
for sp in glob.glob(os.path.join(SCHEMA_DIR, "*.schema.json")):
    s = load_json(sp); schema_store[os.path.basename(sp)] = s
    if "$id" in s: schema_store[s["$id"]] = s

# The schemas cross-reference each other by bare filename ("common.schema.json#/...")
# rather than by URL, so every one is registered under that name and resolution stays
# entirely offline — no schema is ever fetched.
#
# This uses `referencing` rather than jsonschema's RefResolver, which has been deprecated
# since jsonschema 4.18 and is slated for removal. RefResolver still worked, which is the
# problem: the warning was the only signal, and the removal would have broken this
# validator for every adopter on an ordinary `pip install`.
schema_registry = Registry().with_resources(
    (name, Resource(contents=s, specification=DRAFT7)) for name, s in schema_store.items()
)
def validator_for(fn):
    return Draft7Validator(schema_store[fn], registry=schema_registry)
def strip_comments(o):
    if isinstance(o, dict): return {k: strip_comments(v) for k,v in o.items() if k!="_comment"}
    if isinstance(o, list): return [strip_comments(x) for x in o]
    return o

skills, factions, characters, variables = {}, {}, {}, {}
items = {}
dialogues, quests, locations, endings = {}, {}, {}, {}
codex = {}
portraits, cutscenes = {}, {}
routes, snapshots = {}, {}

def schema_check(path, fn, obj):
    for e in sorted(validator_for(fn).iter_errors(strip_comments(obj)), key=str):
        err(f"[SCHEMA] {os.path.relpath(path,ROOT)}: {e.message} (at {'/'.join(map(str,e.path)) or 'root'})")

sp = os.path.join(DATA_DIR,"skills.json")
if os.path.exists(sp):
    for sk in load_json(sp).get("skills",[]): schema_check(sp,"skill.schema.json",sk); skills[sk["id"]]=sk
vp = os.path.join(DATA_DIR,"variables.json")
if os.path.exists(vp):
    for v in load_json(vp).get("variables",[]): schema_check(vp,"variable.schema.json",v); variables[v["id"]]=v
ip = os.path.join(DATA_DIR,"items.json")
if os.path.exists(ip):
    for it in load_json(ip).get("items",[]): schema_check(ip,"item.schema.json",it); items[it["id"]]=it
pp = os.path.join(DATA_DIR,"portraits.json")
if os.path.exists(pp):
    for pt in load_json(pp).get("portraits",[]): schema_check(pp,"portrait.schema.json",pt); portraits[pt["id"]]=pt
progression = None
prog_path = os.path.join(DATA_DIR,"progression.json")
if os.path.exists(prog_path):
    progression = load_json(prog_path); schema_check(prog_path,"progression.schema.json",progression)
rules = None
rules_path = os.path.join(DATA_DIR,"rules.json")
if os.path.exists(rules_path):
    rules = load_json(rules_path); schema_check(rules_path,"rules.schema.json",rules)
def load_dir(sub, fn, reg, base=None):
    # Recursive: dir-mode entities may be organised into nested zone/chapter
    # subdirs (e.g. dialogues/act1/dlg_foo.json). Ids stay globally unique.
    for p in glob.glob(os.path.join(base or DATA_DIR,sub,"**","*.json"), recursive=True):
        if p.endswith(".layout.json"): continue  # editor layout sidecars carry no entity data
        o=load_json(p); schema_check(p,fn,o)
        if o["id"] in reg: err(f"[DUP] duplicate id '{o['id']}' in {sub}/")
        reg[o["id"]]=(o,p)
load_dir("factions","faction.schema.json",factions)
load_dir("characters","character.schema.json",characters)
load_dir("dialogues","dialogue.schema.json",dialogues)
load_dir("quests","quest.schema.json",quests)
load_dir("locations","location.schema.json",locations)
load_dir("endings","ending.schema.json",endings)
load_dir("codex","codex.schema.json",codex)
load_dir("cutscenes","cutscene.schema.json",cutscenes)
load_dir("routes","route.schema.json",routes,TESTS_DIR)
load_dir("snapshots","snapshot.schema.json",snapshots,TESTS_DIR)

def ref_item(i,w):
    # Items are their own registry now, not a variable kind.
    if i not in items: err(f"[REF] {w}: unregistered item '{i}' (add to items.json)")
def ref_skill(s,w):
    if s not in skills: err(f"[REF] {w}: unknown skill '{s}'")
def ref_faction(f,w):
    if f not in factions: err(f"[REF] {w}: unknown faction '{f}'")
def ref_char(c,w):
    if c not in characters: err(f"[REF] {w}: unknown character '{c}'")
def ref_node_speaker(s,w):
    # Node-level speakerId, unlike the dialogue-level one, may name a character
    # OR a skill (N1 — a skill-voiced narration beat). Mirrors
    # checkNodeSpeakerRef in editor/core/src/validator.ts — keep in lockstep.
    is_char = s in characters; is_skill = s in skills
    if not is_char and not is_skill: err(f"[REF] {w}: unknown speaker '{s}' — not a character or skill id")
    elif is_char and is_skill: err(f"[REF] {w}: speaker '{s}' matches both a character and a skill id — ambiguous")
def ref_var(v,k,w):
    x=variables.get(v)
    if not x: err(f"[REF] {w}: unregistered {k} '{v}' (add to variables.json)")
    elif x["kind"]!=k: err(f"[REF] {w}: '{v}' is a {x['kind']}, used as {k}")

flags_written, flags_read = set(), set()
texts_written, texts_read = set(), set()
reps_adjusted, reps_read = set(), set()
rels_adjusted, rels_read = set(), set()
triggered_cutscenes = set()
xp_grants = []  # (amount, where) for XP checks + soft-cap sanity
def walk_condition(c,w):
    t=c.get("type")
    if t=="skill": ref_skill(c["skill"],w)
    elif t=="reputation": ref_faction(c["faction"],w); reps_read.add(c["faction"])
    elif t=="flag": ref_var(c["flag"],"flag",w); flags_read.add(c["flag"])
    elif t=="counter": ref_var(c["counter"],"counter",w)
    elif t=="item": ref_item(c["item"],w)
    elif t=="relationship": ref_char(c["character"],w); rels_read.add(c["character"])
    elif t=="quest":
        # Same REF pair as the advance_quest effect.
        if c["quest"] not in quests: err(f"[REF] {w}: unknown quest '{c['quest']}'")
        else:
            stg={s["id"] for s in quests[c["quest"]][0]["stages"]}
            if c["stage"] not in stg: err(f"[REF] {w}: quest condition stage '{c['stage']}' not in '{c['quest']}'")
    elif t=="questOutcome":
        if c["quest"] not in quests: err(f"[REF] {w}: unknown quest '{c['quest']}'")
        else:
            ocs={o["id"] for o in quests[c["quest"]][0].get("outcomes",[])}
            if c["outcome"] not in ocs: err(f"[REF] {w}: questOutcome '{c['outcome']}' not in '{c['quest']}'")
    elif t in ("all","any"):
        for s in c["of"]: walk_condition(s,w)
    elif t=="not": walk_condition(c["of"],w)
def walk_effect(e,w):
    t=e.get("type")
    if t=="set_flag": ref_var(e["flag"],"flag",w); flags_written.add(e["flag"])
    elif t=="adjust_reputation": ref_faction(e["faction"],w); reps_adjusted.add(e["faction"])
    elif t=="adjust_relationship": ref_char(e["character"],w); rels_adjusted.add(e["character"])
    elif t=="adjust_counter": ref_var(e["counter"],"counter",w)
    elif t in ("give_item","take_item"): ref_item(e["item"],w)
    elif t=="advance_quest":
        if e["quest"] not in quests: err(f"[REF] {w}: unknown quest '{e['quest']}'")
        else:
            stg={s["id"] for s in quests[e["quest"]][0]["stages"]}
            if e["toStage"] not in stg: err(f"[REF] {w}: advance_quest toStage '{e['toStage']}' not in '{e['quest']}'")
    elif t=="grant_xp":
        if e.get("amount",0) <= 0: warn(f"[XP] {w}: grant_xp amount {e.get('amount')} should be positive")
        xp_grants.append((e.get("amount",0), w))
    elif t=="set_active_dialogue":
        # Feed model: sets the `active_dialogue__{character}` flag, read by the
        # character's ladder. Register it as written so hygiene balances.
        flags_written.add(f"active_dialogue__{e['character']}")
        if e["character"] not in characters: err(f"[REF] {w}: set_active_dialogue unknown character '{e['character']}'")
        if e["dialogue"] not in dialogues: err(f"[REF] {w}: set_active_dialogue unknown dialogue '{e['dialogue']}'")
    elif t=="set_text":
        ref_var(e["variable"],"text",w); texts_written.add(e["variable"])
    elif t=="play_cutscene":
        if e["cutscene"] not in cutscenes: err(f"[REF] {w}: play_cutscene unknown cutscene '{e['cutscene']}'")
        triggered_cutscenes.add(e["cutscene"])

used_portraits = set()
for cid,(o,p) in characters.items():
    if "factionId" in o: ref_faction(o["factionId"], f"character '{cid}'")
    if "portrait" in o:
        if o["portrait"] not in portraits: err(f"[PORT] character '{cid}': portrait '{o['portrait']}' not found in registry")
        used_portraits.add(o["portrait"])
for pid,o in portraits.items():
    if o.get("character") and o["character"] not in characters:
        err(f"[PORT] portrait '{pid}': character '{o['character']}' not found")
for fid,(o,p) in factions.items():
    for x in o.get("opposes",[])+o.get("alliedWith",[]):
        if x not in factions: err(f"[REF] faction '{fid}': unknown related faction '{x}'")
    if fid in o.get("opposes",[]): warn(f"[LOGIC] faction '{fid}' opposes itself")

chars_with_dialogue=set()
# characterId -> [dialogue ids naming them as ROOT speaker]. The ladder pass uses
# this to spot dialogues nothing can reach: a speakerId does NOT make a dialogue
# discoverable — only a ladder rung, or availableWhen, does.
dialogues_by_speaker={}
for did,(dlg,p) in dialogues.items():
    node_ids={n["id"] for n in dlg["nodes"]}; w0=f"dialogue '{did}'"
    if dlg["entry"] not in node_ids: err(f"[REF] {w0}: entry '{dlg['entry']}' is not a node")
    if dlg.get("speakerId"):
        ref_char(dlg["speakerId"],w0)
        chars_with_dialogue.add(dlg["speakerId"])
        dialogues_by_speaker.setdefault(dlg["speakerId"],[]).append(did)
    seen=set()
    for n in dlg["nodes"]:
        if n["id"] in seen: err(f"[DUP] {w0}: duplicate node id '{n['id']}'")
        seen.add(n["id"])
    reachable=set()
    for n in dlg["nodes"]:
        w=f"{w0} node '{n['id']}'"
        for e in n.get("onEnter",[]): walk_effect(e,w)
        if n.get("speakerId"):
            ref_node_speaker(n["speakerId"],w)
            if n["speakerId"] in characters: chars_with_dialogue.add(n["speakerId"])
        if n.get("portrait"):
            entry = portraits.get(n["portrait"])
            if not entry:
                err(f"[PORT] {w}: portrait '{n['portrait']}' not found in registry")
            elif entry.get("character"):
                # Compare against the RESOLVED speaker (character only), not a
                # raw id — a node whose effective speaker is a skill (or
                # narration) legitimately carries a portrait override with no
                # character involved, and a raw string compare would always
                # mismatch those. Mirrors validator.ts's resolveSpeaker use.
                speaker = n.get("speakerId") or dlg.get("speakerId")
                if speaker in characters and entry["character"] != speaker:
                    warn(f"[PORT] {w}: portrait '{n['portrait']}' belongs to character '{entry['character']}', but speaker is '{speaker}' — expression mismatch")
            used_portraits.add(n["portrait"])
        ch_list=n.get("choices",[])
        nxt = n.get("next")
        if nxt:
            if ch_list: err(f"[FLOW] {w}: has both 'next' and 'choices' — a node auto-advances or offers choices, not both")
            if n.get("isEnd"): err(f"[FLOW] {w}: has both 'next' and 'isEnd' — a node can't both end the dialogue and auto-advance")
            reachable.add(nxt)
            if nxt not in node_ids: err(f"[REF] {w}: next '{nxt}' is not a node")
        if not ch_list and not n.get("isEnd") and not nxt: err(f"[FLOW] {w}: no choices, not isEnd, no next (player stuck)")
        cids=set()
        for ch in ch_list:
            cw=f"{w} choice '{ch['id']}'"
            if ch["id"] in cids: err(f"[DUP] {cw}: duplicate choice id")
            cids.add(ch["id"])
            if "showIf" in ch: walk_condition(ch["showIf"],cw)
            for e in ch.get("effects",[]): walk_effect(e,cw)
            if "check" in ch:
                k=ch["check"]; ref_skill(k["skill"],cw)
                if k["mode"]=="active":
                    for key in ("onSuccess","onFailure"):
                        if key not in k: err(f"[GATE] {cw}: active check missing '{key}'")
                        else:
                            reachable.add(k[key])
                            if k[key] not in node_ids: err(f"[REF] {cw}: check {key} '{k[key]}' is not a node")
                    if "goto" in ch: warn(f"[GATE] {cw}: has both active check and goto; goto ignored")
                    if k["difficulty"]>20: warn(f"[GATE] {cw}: difficulty {k['difficulty']} very high; may be unpassable")
                else:
                    if "onSuccess" in k or "onFailure" in k: warn(f"[GATE] {cw}: passive check shouldn't define onSuccess/onFailure")
                    if "goto" not in ch and not n.get("isEnd"): err(f"[GATE] {cw}: passive-check choice needs a goto")
                    if "goto" in ch: reachable.add(ch["goto"])
            elif "goto" in ch:
                reachable.add(ch["goto"])
                if ch["goto"] not in node_ids: err(f"[REF] {cw}: goto '{ch['goto']}' is not a node")
            else:
                if not n.get("isEnd"): err(f"[FLOW] {cw}: no goto, no check, not isEnd — dead end")
    for n in dlg["nodes"]:
        if n["id"]!=dlg["entry"] and n["id"] not in reachable:
            warn(f"[REACH] {w0}: node '{n['id']}' is unreachable")

    # 'next' cycle check (D7) — mirrors validator.ts's chain-walk. Each node has
    # at most one 'next' (mutual exclusion enforced above), so this is a
    # pointer-chase per unvisited node, not a general graph DFS: walk the chain
    # marking nodes in-progress; landing back on an in-progress node closes a
    # cycle. goto cycles remain legal (hub dialogues loop on purpose).
    by_id = {n["id"]: n for n in dlg["nodes"]}
    chain_state = {}
    for start in dlg["nodes"]:
        if start["id"] in chain_state: continue
        chain = []
        cur = start["id"]
        while cur is not None and cur not in chain_state:
            chain_state[cur] = "in-progress"
            chain.append(cur)
            cur = by_id.get(cur, {}).get("next")
        if cur is not None and chain_state.get(cur) == "in-progress":
            err(f"[FLOW] {w0}: 'next' cycle involving node '{cur}'")
        for nid in chain: chain_state[nid] = "done"

# A character "has dialogue" if they speak one OR a ladder rung presents one.
# Checking speakerId alone reports ladder-only characters as uncovered.
for cid,(o,p) in characters.items():
    if cid not in chars_with_dialogue and not (o.get("dialogues") or []):
        warn(f"[COVERAGE] character '{cid}' has no dialogue")

def flags_in_condition(c,acc,visited=None):
    # Resolves THROUGH questOutcome into that outcome's reachedWhen — otherwise
    # an ending gated on an outcome looks flag-free and every reachability check
    # downstream silently passes. Mirrors validator.ts.
    if visited is None: visited=set()
    t=c.get("type")
    if t=="flag": acc.add(c["flag"])
    elif t in ("all","any"):
        for s in c["of"]: flags_in_condition(s,acc,visited)
    elif t=="not": flags_in_condition(c["of"],acc,visited)
    elif t=="questOutcome":
        key=f"{c['quest']}/{c['outcome']}"
        if key not in visited:
            visited.add(key)
            q=quests.get(c["quest"])
            if q:
                oc=next((o for o in q[0].get("outcomes",[]) if o["id"]==c["outcome"]), None)
                if oc and oc.get("reachedWhen"): flags_in_condition(oc["reachedWhen"],acc,visited)
    return acc
def flags_written_by_task(q):
    out=set()
    for st in q.get("stages",[]):
        for e in st.get("onComplete",[]):
            if e["type"]=="set_flag": out.add(e["flag"])
    for oc in q.get("outcomes",[]):
        for e in oc.get("effects",[]):
            if e["type"]=="set_flag": out.add(e["flag"])
    return out

task_writes={qid:flags_written_by_task(q) for qid,(q,p) in quests.items()}
for qid,(q,_p) in quests.items():
    for st in q["stages"]:
        for e in st.get("onComplete",[]): walk_effect(e, f"quest '{qid}' stage '{st['id']}'")
    for oc in q.get("outcomes",[]):
        for e in oc.get("effects",[]): walk_effect(e, f"quest '{qid}' outcome '{oc['id']}'")
edges={qid:set() for qid in quests}
for qid,(q,p) in quests.items():
    av=q.get("availableWhen")
    need=flags_in_condition(av,set()) if av else set()
    for prod,wr in task_writes.items():
        if prod!=qid and (need & wr): edges[prod].add(qid)

for qid,(q,p) in quests.items():
    ords=[s["order"] for s in q["stages"]]
    if len(set(ords))!=len(ords): err(f"[QUEST] quest '{qid}': duplicate stage order {ords}")
    if ords!=sorted(ords): warn(f"[QUEST] quest '{qid}': stages not in ascending order {ords}")

opened={c for outs in edges.values() for c in outs}
for qid,(q,p) in quests.items():
    trig=q.get("startsAvailable") or ("availableWhen" in q) or (qid in opened)
    out=bool(q.get("outcomes"))
    if not trig and not out: warn(f"[QUEST] quest '{qid}' orphaned: no trigger and no outcome (ok if WIP)")
    elif not trig: warn(f"[QUEST] quest '{qid}' has no trigger (nothing opens it)")

color={qid:0 for qid in quests}
def dfs(u,stack):
    color[u]=1; stack.append(u)
    for v in edges[u]:
        if color[v]==1:
            i=stack.index(v); err(f"[QUEST] circular dependency: {' -> '.join(stack[i:]+[v])}")
        elif color[v]==0: dfs(v,stack)
    stack.pop(); color[u]=2
for qid in quests:
    if color[qid]==0: dfs(qid,[])

# questOutcome reference cycles. The runtime guard returns false where a cycle
# closes — total but silent — so report it here. Mirrors validator.ts.
outcome_refs = {}
for qid,(q,_p) in quests.items():
    for oc in q.get("outcomes",[]):
        refs=[]
        def collect(c):
            ct=c.get("type")
            if ct=="questOutcome": refs.append(f"{c['quest']}/{c['outcome']}")
            elif ct in ("all","any"):
                for s in c["of"]: collect(s)
            elif ct=="not": collect(c["of"])
        if oc.get("reachedWhen"): collect(oc["reachedWhen"])
        outcome_refs[f"{qid}/{oc['id']}"]=refs

oc_color={k:0 for k in outcome_refs}
def oc_dfs(u,stack):
    oc_color[u]=1; stack.append(u)
    for v in outcome_refs.get(u,[]):
        if v not in outcome_refs: continue  # dangling ref — already a REF error
        if oc_color[v]==1:
            i=stack.index(v)
            err(f"[QUEST] questOutcome reference cycle: {' -> '.join(stack[i:]+[v])} — evaluates false where it closes")
        elif oc_color[v]==0: oc_dfs(v,stack)
    stack.pop(); oc_color[u]=2
for k in outcome_refs:
    if oc_color[k]==0: oc_dfs(k,[])

for qid,(q,p) in quests.items():
    if "availableWhen" in q and "closedWhen" in q:
        a=flags_in_condition(q["availableWhen"],set()); c=flags_in_condition(q["closedWhen"],set())
        if a & c: warn(f"[QUEST] quest '{qid}': flag(s) {a&c} gate both availableWhen and closedWhen")
    if "giverId" in q: ref_char(q["giverId"], f"quest '{qid}'")

# count task conditions as reads (flag hygiene accuracy)
for qid,(q,_p) in quests.items():
    for key in ("availableWhen","closedWhen"):
        if key in q: walk_condition(q[key], f"quest '{qid}' {key}")
    for st in q["stages"]:
        if "completeWhen" in st: walk_condition(st["completeWhen"], f"quest '{qid}' stage '{st['id']}'")
    for oc in q.get("outcomes",[]):
        if "reachedWhen" in oc: walk_condition(oc["reachedWhen"], f"quest '{qid}' outcome '{oc['id']}'")

# Quest journal objectives (OBJ) — display-only routes shown for the CURRENT
# stage. Every check here is about what the journal will SHOW; completion is
# always completeWhen's job. Mirrors the OBJ pass in editor/core/src/validator.ts.
# The controlled vocabulary for quest tags is per-project, not a Parlance
# concept — projects declare it in rules.json. Absent ⇒ any tag is accepted.
QUEST_TAG_VOCABULARY = ((rules or {}).get("quest") or {}).get("tagVocabulary")

for qid,(q,_p) in quests.items():
    for st in q["stages"]:
        objectives = st.get("objectives", [])
        seen_obj = set()
        for ob in objectives:
            ow = f"quest '{qid}' stage '{st['id']}' objective '{ob['id']}'"
            if ob["id"] in seen_obj:
                err(f"[OBJ] {ow}: duplicate objective id within the stage")
            seen_obj.add(ob["id"])
            # REF pass + registers the read for the FLAG orphan pass.
            if "showIf" in ob: walk_condition(ob["showIf"], f"{ow} showIf")
        if "completeWhen" in st and not objectives:
            warn(f"[OBJ] quest '{qid}' stage '{st['id']}': has completeWhen but no objectives — the journal will show an empty current stage")
        if objectives and all("showIf" in ob for ob in objectives):
            warn(f"[OBJ] quest '{qid}' stage '{st['id']}': every objective is gated by showIf — the stage can present an empty list at runtime")
    if QUEST_TAG_VOCABULARY is not None:
        for tag in q.get("tags", []):
            if tag not in QUEST_TAG_VOCABULARY:
                warn(f"[OBJ] quest '{qid}': tag '{tag}' is not in the project's quest tag vocabulary (rules.quest.tagVocabulary: {', '.join(QUEST_TAG_VOCABULARY)})")

# Codex entries mirror the ending reachability check, but only where there IS a
# condition: an entry with no unlockedBy is always available, which is not a bug.
for cid,(o,p) in codex.items():
    if "unlockedBy" not in o: continue
    walk_condition(o["unlockedBy"], f"codex '{cid}'")
    for fl in flags_in_condition(o["unlockedBy"],set()):
        if fl not in flags_written: warn(f"[CODEX] codex '{cid}' needs flag '{fl}' never set — may be unreachable")

for eid,(o,p) in endings.items():
    walk_condition(o["unlockedBy"], f"ending '{eid}'")
    for fl in flags_in_condition(o["unlockedBy"],set()):
        if fl not in flags_written: warn(f"[ENDING] ending '{eid}' needs flag '{fl}' never set — may be unreachable")

# Cutscene manifests: opaque engine asset key + on-complete effects.
# `asset` is deliberately NOT resolved (an engine-side concern); emptiness is
# enforced by the JSON schema. effectsOnComplete may itself contain
# play_cutscene (a chain), so walk all before the unused check.
for csid,(cs,p) in cutscenes.items():
    w = f"cutscene '{csid}'"
    ed = cs.get("entersDialogue")
    if ed is not None and ed not in dialogues:
        err(f"[CUT] {w}: entersDialogue '{ed}' not found")
    # arrivesAt names where the player is put down afterwards; a dangling
    # location or spawn there strands the player mid-transition, so it's an
    # error rather than a warning.
    aa = cs.get("arrivesAt")
    if aa:
        if aa["location"] not in locations:
            err(f"[CUT] {w}: arrivesAt unknown location '{aa['location']}'")
        elif not any(s.get("id") == aa["spawn"] for s in (locations[aa["location"]][0].get("spawns") or [])):
            err(f"[CUT] {w}: arrivesAt spawn '{aa['spawn']}' not found in location '{aa['location']}'")
    for e in cs.get("effectsOnComplete",[]):
        walk_effect(e, f"{w} effectsOnComplete")
for csid in cutscenes:
    if csid not in triggered_cutscenes:
        warn(f"[CUT] cutscene '{csid}' is never referenced by any play_cutscene effect")

# Two play_cutscene effects reachable from the same dialogue node —
# pendingCutscene is last-write-wins, so the ordering is ambiguous.
for did,(dlg,p) in dialogues.items():
    for n in dlg["nodes"]:
        fires = [e["cutscene"] for e in n.get("onEnter",[]) if e.get("type")=="play_cutscene"]
        for ch in n.get("choices",[]):
            fires += [e["cutscene"] for e in ch.get("effects",[]) if e.get("type")=="play_cutscene"]
        if len(fires) > 1:
            warn(f"[CUT] dialogue '{did}' node '{n['id']}' fires {len(fires)} play_cutscene effects ({', '.join(fires)}) — pendingCutscene is last-write-wins, ordering is ambiguous")

# Routes (ROUTE pass) — mirrors validateRouteRefs in editor/core/src/routeRunner.ts.
def route_err(m): err(f"[ROUTE] {m}")
def route_warn(m): warn(f"[ROUTE] {m}")
for rid,(route,_p) in routes.items():
    if route.get("startSnapshot") and route["startSnapshot"] not in snapshots:
        route_err(f"unknown startSnapshot '{route['startSnapshot']}'")
    if route["dialogueId"] not in dialogues:
        route_err(f"unknown dialogueId '{route['dialogueId']}'")
        continue
    dialogue = dialogues[route["dialogueId"]][0]
    for i,step in enumerate(route["steps"]):
        if "cutscene" in step:
            cs = cutscenes.get(step["cutscene"])
            if not cs:
                route_err(f"step {i}: unknown cutscene '{step['cutscene']}'")
            elif cs[0].get("entersDialogue") and cs[0]["entersDialogue"] in dialogues:
                dialogue = dialogues[cs[0]["entersDialogue"]][0]
            continue
        # N2 advance step: N choiceless `next` hops. There is no choice to
        # resolve, so the reference checks below do not apply — the runner is what
        # proves the chain is walkable, and duplicating that here would mean
        # simulating the walk. Only the shape is worth asserting.
        if "advance" in step:
            n = step["advance"]
            if not isinstance(n, int) or isinstance(n, bool) or n < 1:
                route_err(f"step {i}: 'advance' must be a positive integer, got {n!r}")
            continue
        if step.get("continuation"):
            if step["continuation"] not in dialogues:
                route_err(f"step {i}: unknown continuation dialogueId '{step['continuation']}'")
            else:
                dialogue = dialogues[step["continuation"]][0]
        all_choices = [c for n in dialogue["nodes"] for c in n.get("choices",[])]
        choice = next((c for c in all_choices if c["id"]==step["choiceId"]), None)
        if not choice:
            route_err(f"step {i}: choice '{step['choiceId']}' not found in dialogue '{dialogue['id']}'")
        elif step.get("forced") and not choice.get("check"):
            route_warn(f"step {i}: choice '{step['choiceId']}' is forced but has no check — forced is a no-op")
    ae = route.get("assertEnd")
    if ae:
        if ae.get("endingAvailable") and ae["endingAvailable"] not in endings:
            route_err(f"assertEnd.endingAvailable: unknown ending '{ae['endingAvailable']}'")
        if ae.get("pendingCutscene") and ae["pendingCutscene"] not in cutscenes:
            route_err(f"assertEnd.pendingCutscene: unknown cutscene '{ae['pendingCutscene']}'")
        for flag in list(ae.get("flags",{}).keys()) + ae.get("forbiddenFlags",[]):
            v = variables.get(flag)
            if not v:
                route_warn(f"assertEnd: flag '{flag}' not declared in variables.json")
            elif v["kind"] != "flag":
                route_err(f"assertEnd: '{flag}' is a {v['kind']}, used as flag")
        for qid,stage in ae.get("questStages",{}).items():
            if qid not in quests:
                route_err(f"assertEnd.questStages: unknown quest '{qid}'")
            elif not any(s["id"]==stage for s in quests[qid][0]["stages"]):
                route_err(f"assertEnd.questStages: stage '{stage}' not in quest '{qid}'")

# Snapshots (SNAP pass) — mirrors the SNAP block in editor/core/src/validator.ts.
for sid,(snap,_p) in snapshots.items():
    w = f"snapshot '{sid}'"
    st = snap.get("state",{})
    for flag in st.get("flags",{}): ref_var(flag,"flag",w)
    for ctr in st.get("counters",{}): ref_var(ctr,"counter",w)
    for item in st.get("inventory",[]): ref_item(item,w)
    for skill in st.get("skills",{}): ref_skill(skill,w)
    for fac in st.get("reputation",{}): ref_faction(fac,w)
    for q,stage in st.get("questStages",{}).items():
        if q not in quests: err(f"[SNAP] {w}: questStages unknown quest '{q}'")
        elif not any(s["id"]==stage for s in quests[q][0]["stages"]): err(f"[SNAP] {w}: stage '{stage}' not in quest '{q}'")
    if st.get("pendingCutscene") and st["pendingCutscene"] not in cutscenes:
        err(f"[SNAP] {w}: pendingCutscene unknown cutscene '{st['pendingCutscene']}'")

# Locations (LOC pass) — mirrors editor/core/src/validator.ts. Graph integrity:
# exit targets + spawns, denial dialogues, gates, interactables,
# reachability, and within-location id uniqueness.
def dialogue_is_effectful(dlg):
    for n in dlg.get("nodes", []):
        if n.get("onEnter"): return True
        for ch in n.get("choices", []):
            if ch.get("effects"): return True
    return False

# Dialogues placed in the world without needing a ladder: object/environment
# interactables name a dialogue directly, and an exit's denialDialogue plays when a
# gate refuses. A speaker reachable only those ways is correctly ladderless.
dialogues_placed_in_world = set()
for _lid,(_loc,_lp) in locations.items():
    for _it in _loc.get("interactables",[]) or []:
        if _it.get("dialogue"): dialogues_placed_in_world.add(_it["dialogue"])
    for _ex in _loc.get("exits",[]) or []:
        if _ex.get("denialDialogue"): dialogues_placed_in_world.add(_ex["denialDialogue"])

# Dialogue ladder: dangling-ref (REF) + shallow shape checks (LADDER).
# Mirrors checkDialogueLadder in editor/core/src/validator.ts.
for cid,(o,_p) in characters.items():
    ladder = o.get("dialogues") or []
    w = f"character '{cid}'"
    for i,rung in enumerate(ladder):
        if rung["dialogue"] not in dialogues:
            err(f"[REF] {w}: dialogues[{i}] '{rung['dialogue']}' not found")
        if "showIf" in rung: walk_condition(rung["showIf"], f"{w} dialogues[{i}].showIf")
    # dead rung: unconditional rung that is not last shadows every rung below it.
    for i,rung in enumerate(ladder):
        if "showIf" not in rung and i < len(ladder)-1:
            shadowed = len(ladder)-1-i
            warn(f"[LADDER] {w}: dialogues[{i}] '{rung['dialogue']}' is unconditional but not last — shadows {shadowed} rung(s) below (dead rungs)")
    # stuck rung: unconditional + top-priority + effectful → wins forever, re-fires.
    if ladder:
        top = ladder[0]
        if "showIf" not in top and top["dialogue"] in dialogues and dialogue_is_effectful(dialogues[top["dialogue"]][0]):
            warn(f"[LADDER] {w}: dialogues[0] '{top['dialogue']}' is unconditional, top-priority, and carries effects — it wins forever and re-fires on every re-entry")
    # no fallthrough: last rung gated → character may resolve to no dialogue.
    if ladder and "showIf" in ladder[-1]:
        warn(f"[LADDER] {w}: last ladder rung '{ladder[-1]['dialogue']}' has a showIf — no unconditional fallthrough, so the character may resolve to no dialogue in some states")
    # no ladder at all, but dialogues name them as speaker: resolveCharacterDialogue
    # returns null, and discovery only falls back to availableWhen. Any
    # dialogue with neither is authored but unreachable.
    if not ladder:
        stranded = sorted(
            d for d in dialogues_by_speaker.get(cid, [])
            if not dialogues[d][0].get("availableWhen")
            and d not in dialogues_placed_in_world
        )
        if stranded:
            warn(f"[LADDER] {w}: no dialogues ladder, so resolution returns null — {len(stranded)} dialogue(s) carry no availableWhen either and are unreachable: {', '.join(stranded)}")

spawns_by_loc = {lid: {s["id"] for s in loc.get("spawns", [])} for lid,(loc,_p) in locations.items()}
reachable_from = {lid: set() for lid in locations}
for lid,(loc,_p) in locations.items():
    for ex in loc.get("exits", []):
        if ex["to"]["location"] in reachable_from: reachable_from[ex["to"]["location"]].add(lid)

for lid,(loc,_p) in locations.items():
    w = f"location '{lid}'"

    # within-location id uniqueness (spawns / exits / interactables)
    for coll, kind in ((loc.get("spawns", []), "spawn"), (loc.get("exits", []), "exit"), (loc.get("interactables", []), "interactable")):
        seen = set()
        for item in coll:
            if item["id"] in seen: err(f"[DUP] {w}: duplicate {kind} id '{item['id']}'")
            seen.add(item["id"])

    for ex in loc.get("exits", []):
        ew = f"{w} exit '{ex['id']}'"
        if ex["to"]["location"] not in locations:
            err(f"[REF] {ew}: unknown target location '{ex['to']['location']}'")
        else:
            target_spawns = spawns_by_loc.get(ex["to"]["location"], set())
            if target_spawns and ex["to"]["spawn"] not in target_spawns:
                err(f"[LOC] {ew}: spawn '{ex['to']['spawn']}' not defined in location '{ex['to']['location']}'")
        if ex.get("denialDialogue") and ex["denialDialogue"] not in dialogues:
            err(f"[REF] {ew}: denialDialogue '{ex['denialDialogue']}' not found")
        if "gate" in ex: walk_condition(ex["gate"], f"{ew} gate")
        if ex.get("gateType") and "gate" not in ex:
            warn(f"[LOC] {ew}: gateType set but no gate condition — gate is never enforced")
        if "gate" in ex and not ex.get("gateType"):
            warn(f"[LOC] {ew}: gate condition set but no gateType — gate presentation unspecified")

    for it in loc.get("interactables", []):
        iw = f"{w} interactable '{it['id']}'"
        if it.get("kind") == "npc":
            if not it.get("character"):
                err(f"[LOC] {iw}: kind 'npc' requires character field")
            elif it["character"] not in characters:
                err(f"[REF] {iw}: unknown character '{it['character']}'")
            elif not (characters[it["character"]][0].get("dialogues") or []):
                # An npc interactable resolves through the ladder ONLY. Without one,
                # resolveCharacterDialogue returns null and interacting does nothing.
                warn(f"[LOC] {iw}: character '{it['character']}' has no dialogues ladder, so resolution returns null and this interactable is a no-op — give them a ladder ending in an unconditional rung")
            if it.get("dialogue"):
                warn(f"[LOC] {iw}: npc interactable has dialogue field; runtime resolves the character's dialogue ladder — did you mean character?")
            if it.get("trigger") == "on_enter":
                # A character who starts talking at you the moment you walk in is
                # almost always a scene wearing an npc costume: model it as an
                # object interactable so the trigger reads as authored intent.
                warn(f"[LOC] {iw}: npc interactable with trigger 'on_enter' talks at the player unprompted — model an automatic scene as kind 'object'")
        else:
            if not it.get("dialogue"):
                warn(f"[LOC] {iw}: kind '{it.get('kind')}' has no dialogue — nothing happens when the player interacts with it")
            elif it["dialogue"] not in dialogues:
                err(f"[REF] {iw}: unknown dialogue '{it['dialogue']}'")
        if "showIf" in it: walk_condition(it["showIf"], f"{iw} showIf")

    is_start = "start" in loc.get("tags", [])
    has_incoming = len(reachable_from.get(lid, set())) > 0
    if not is_start and not has_incoming and len(locations) > 1:
        warn(f"[LOC] {w}: unreachable — no exit points here and not tagged 'start'")

# A spawn nothing arrives at is authored intent that never happens: the door that
# was supposed to use it points somewhere else, and the player lands in the wrong
# part of the room with nothing reporting it. A spawn marked `"isDefault": true` is
# exempt — it is where the engine puts the player when nothing named a spawn (new
# game, dev entry, a cutscene arrival with no door), so by definition no exit
# points at it.
arrived_at = {}
for _lid, (_loc, _p) in locations.items():
    for _ex in _loc.get("exits", []) or []:
        arrived_at.setdefault(_ex["to"]["location"], set()).add(_ex["to"]["spawn"])
for _csid, (_cs, _p) in cutscenes.items():
    _aa = _cs.get("arrivesAt")
    if _aa:
        arrived_at.setdefault(_aa["location"], set()).add(_aa["spawn"])

for lid, (loc, p) in locations.items():
    used = arrived_at.get(lid, set())
    # "At most one default" is a promise the schema makes but cannot express.
    _defaults = [sp["id"] for sp in (loc.get("spawns", []) or []) if sp.get("isDefault") is True]
    if len(_defaults) > 1:
        err(f"[LOC] location '{lid}': {len(_defaults)} spawns marked default "
            f"({', '.join(_defaults)}) — exactly one arrival point can be the default")
    for sp in loc.get("spawns", []) or []:
        if sp.get("isDefault") is True or sp["id"] in used:
            continue
        warn(f"[LOC] location '{lid}': spawn '{sp['id']}' exists but no exit or cutscene "
             "arrives there — the door meant to use it is pointing somewhere else")

for pid in portraits:
    if pid not in used_portraits: warn(f"[PORT] portrait '{pid}' is registered but never used")

# --- TEXT pass — {var_id} placeholders in PLAYER-FACING strings only.
# Ids, names, summaries and other authoring-facing fields are never
# interpolated, so a brace in one of them is just a brace. Mirrors validator.ts.
PLACEHOLDER_RE = re.compile(r"\{([a-z][a-z0-9_]*)\}")

def scan_text(text, w):
    if not text: return
    for vid in dict.fromkeys(PLACEHOLDER_RE.findall(text)):
        texts_read.add(vid)
        v = variables.get(vid)
        if not v:
            err(f"[TEXT] {w}: placeholder '{{{vid}}}' is not a registered variable (add a kind:\"text\" variable)")
        elif v["kind"] != "text":
            err(f"[TEXT] {w}: placeholder '{{{vid}}}' refers to a {v['kind']}, not a text variable")

for did,(dlg,_p) in dialogues.items():
    for n in dlg["nodes"]:
        scan_text(n.get("text"), f"dialogue '{did}' node '{n['id']}' text")
        for ch in n.get("choices",[]):
            scan_text(ch.get("text"), f"dialogue '{did}' node '{n['id']}' choice '{ch['id']}' text")
for qid,(q,_p) in quests.items():
    scan_text(q.get("journalName"), f"quest '{qid}' journalName")
    for st in q["stages"]:
        scan_text(st.get("description"), f"quest '{qid}' stage '{st['id']}' description")
        for ob in st.get("objectives",[]):
            scan_text(ob.get("text"), f"quest '{qid}' stage '{st['id']}' objective '{ob['id']}' text")

# writtenBy:"engine" means the HOST writes this at runtime (free text the player
# typed, or computed state). Parlance has no input-capture concept, so there is no
# authored effect to find — suppress the never-written / read-never-set passes for
# them rather than inviting a fake literal set_text to silence the warning.
def engine_written(vid):
    return (variables.get(vid) or {}).get("writtenBy") == "engine"

for vid,v in variables.items():
    if v["kind"] != "text": continue
    if vid not in texts_written and not isinstance(v.get("default"), str) and not engine_written(vid):
        warn(f"[TEXT] text variable '{vid}' is never written by a set_text effect and has no default — every '{{{vid}}}' will render as the raw placeholder")
    if vid not in texts_read:
        warn(f"[TEXT] text variable '{vid}' is declared but never referenced in any authored string")

declared={vid for vid,v in variables.items() if v["kind"]=="flag"}
for fl in declared:
    if fl in flags_read and fl not in flags_written and not engine_written(fl): warn(f"[FLAG] '{fl}' read but never set — gate can never open")
    if fl in flags_written and fl not in flags_read: warn(f"[FLAG] '{fl}' set but never read — possibly dead state")
    if fl not in flags_read and fl not in flags_written and not engine_written(fl): warn(f"[FLAG] '{fl}' declared but never used")
for fac in factions:
    if fac in reps_read and fac not in reps_adjusted: warn(f"[REP] faction '{fac}' checked but never adjusted")

# Relationship hygiene — same shape as REP.
for ch in characters:
    if ch in rels_read and ch not in rels_adjusted: warn(f"[REL] character '{ch}' relationship checked but never adjusted")

# --- Rules (RULES pass) — mirrors the parseDice call in validator.ts.
# The project's default dice drive every active check, so malformed notation here
# silently mis-resolves the whole game. dice.ts owns the grammar: NdM, n >= 1,
# m >= 2.
DICE_RE = re.compile(r"^(\d+)d(\d+)$")
if rules is not None:
    notation = (rules.get("check") or {}).get("dice")
    if notation is not None:
        m = DICE_RE.match(notation.strip())
        if not m:
            err(f"[RULES] rules.check.dice: invalid dice notation '{notation}': expected NdM (e.g. 1d20, 2d6)")
        elif int(m.group(1)) < 1:
            err(f"[RULES] rules.check.dice: invalid dice notation '{notation}': need at least 1 die")
        elif int(m.group(2)) < 2:
            err(f"[RULES] rules.check.dice: invalid dice notation '{notation}': die must have at least 2 sides")

# --- Progression (PROG / XP pass) — mirrors validator.ts ---
if progression is not None:
    w = "progression.json"
    thr = progression.get("xpThresholds")
    if not isinstance(thr, list) or len(thr) == 0:
        err(f"[PROG] {w}: xpThresholds must be a non-empty array")
    else:
        for i in range(1, len(thr)):
            if thr[i] <= thr[i-1]:
                err(f"[PROG] {w}: xpThresholds must be strictly increasing (index {i} = {thr[i]})"); break
    ppl = progression.get("pointsPerLevel")
    ms = progression.get("maxSkill")
    if not (isinstance(ppl,(int,float)) and ppl >= 1): err(f"[PROG] {w}: pointsPerLevel must be ≥ 1")
    if not (isinstance(ms,(int,float)) and ms >= 1): err(f"[PROG] {w}: maxSkill must be ≥ 1")
    def skill_cap(sid):
        # Per-skill `max` (skills.json) overrides the global maxSkill.
        return (skills.get(sid) or {}).get("max", ms)
    for sid,val in (progression.get("startingSkills") or {}).items():
        if sid not in skills: err(f"[REF] {w}: startingSkills references unknown skill '{sid}'")
        if isinstance(ms,(int,float)) and val >= skill_cap(sid):
            warn(f"[PROG] {w}: startingSkills['{sid}'] ({val}) ≥ its ceiling ({skill_cap(sid)}) — nothing to invest")
    if isinstance(ms,(int,float)) and ms >= 1 and isinstance(ppl,(int,float)) and ppl >= 1 and isinstance(thr,list) and thr:
        total_xp = sum(max(0,a) for a,_ in xp_grants)
        level = 0
        for i,t2 in enumerate(thr):
            if total_xp >= t2: level = i
            else: break
        earnable = level * ppl
        cost = sum(max(0, skill_cap(sid) - (progression.get("startingSkills") or {}).get(sid,0)) for sid in skills)
        if cost > 0 and earnable >= cost:
            warn(f"[PROG] {w}: progression not actually capped — authored XP grants {earnable} point(s), enough to max all skills (cost {cost}).")

# Quest-resolution reachability: effects with no condition can never fire.
for qid,(q,_p) in quests.items():
    for st in q.get("stages",[]):
        if st.get("onComplete") and "completeWhen" not in st:
            warn(f"[QUEST] quest '{qid}' stage '{st['id']}': onComplete effects but no completeWhen — they can never fire")
    for oc in q.get("outcomes",[]):
        if oc.get("effects") and "reachedWhen" not in oc:
            warn(f"[QUEST] quest '{qid}' outcome '{oc['id']}': effects but no reachedWhen — they can never fire")

# XP advisory: grant_xp authored outside a quest outcome (convention = quests only).
for amount, where in xp_grants:
    if "outcome" not in where:
        warn(f"[XP] {where}: grant_xp authored outside a quest outcome — the convention is XP from quest outcomes only (advisory)")

# --- Priced/oneshot check discipline (CHECK) + mandatory-path lockout (REACH) ---
ladder_read_flags = set()
for cid,(o,_p) in characters.items():
    for rung in o.get("dialogues") or []:
        if "showIf" in rung: flags_in_condition(rung["showIf"], ladder_read_flags)
for did,(dlg,_p) in dialogues.items():
    nodes_by_id = {n["id"]: n for n in dlg["nodes"]}
    for n in dlg["nodes"]:
        for ch in n.get("choices",[]):
            k = ch.get("check")
            if not k: continue
            cw = f"dialogue '{did}' node '{n['id']}' choice '{ch['id']}'"
            # kind is authoring intent for ACTIVE checks; on a passive check it is
            # silently ignored by the runtime, so saying it is a mistake.
            if k.get("mode") != "active":
                if "kind" in k:
                    warn(f"[CHECK] {cw}: kind '{k['kind']}' on a passive check is ignored — passive checks never roll, so there is no pass/fail to price")
                if k.get("acknowledgedLockout"):
                    warn(f"[CHECK] {cw}: acknowledgedLockout on a passive check is ignored — it only applies to kind:'oneshot' active checks")
                continue
            # oneshot is exempt from the proceed requirement. Note there is NO
            # structural tell that separates the two kinds: a oneshot's plot also
            # proceeds (it proceeds without that perception), so a continuing
            # onFailure branch is not evidence of mislabeling. Intent only.
            if k.get("kind","priced") != "priced": continue
            if k.get("acknowledgedLockout"):
                warn(f"[CHECK] {cw}: acknowledgedLockout is only meaningful with kind:'oneshot' — a priced check never locks anything out")
            if "onFailure" not in k:
                warn(f"[CHECK] {cw}: priced check failure must proceed — add an onFailure branch that advances at a cost (or tag kind:'oneshot')")
            else:
                fail = nodes_by_id.get(k["onFailure"])
                for e in (fail or {}).get("onEnter",[]):
                    if e.get("type")=="set_flag" and e.get("flag") in ladder_read_flags:
                        warn(f"[CHECK] {cw}: priced-gate failure sets ladder-reordering flag '{e['flag']}' — confirm this isn't a punishment-spiral cost (advisory)")
    inbound = {}
    for n in dlg["nodes"]:
        # next (N2) is an unconditional edge — every player takes it, so it can
        # never be the thing that walls someone off. Counts as "other".
        if n.get("next"): inbound.setdefault(n["next"], []).append("other")
        for ch in n.get("choices",[]):
            k = ch.get("check")
            edges_kv = []
            if k and k.get("mode")=="active":
                # acknowledgedLockout: the author has declared this lockout
                # intentional, so its success edge stops counting as a trap.
                if k.get("kind")=="oneshot" and not k.get("acknowledgedLockout"):
                    success_kind = "oneshot-success"
                else:
                    success_kind = "other"
                edges_kv.append((k.get("onSuccess"), success_kind))
                edges_kv.append((k.get("onFailure"), "other"))
            elif ch.get("goto"):
                edges_kv.append((ch["goto"], "other"))
            for tgt,kind in edges_kv:
                if tgt: inbound.setdefault(tgt, []).append(kind)
    for node_id, edges in inbound.items():
        if node_id == dlg["entry"]: continue
        if edges and all(x=="oneshot-success" for x in edges):
            warn(f"[REACH] dialogue '{did}': node '{node_id}' is reachable only by succeeding oneshot (pass-or-fail) checks — an unlucky or under-built player can be permanently walled off (tag the check acknowledgedLockout:true if that is the intent)")

def check_loreref(o,w):
    lr=o.get("loreRef")
    if lr and not os.path.exists(os.path.join(ROOT,lr["file"])): err(f"[LORE] {w}: loreRef file '{lr['file']}' missing")
for reg in (factions,characters,dialogues,quests,locations,endings,codex):
    for k,(o,p) in reg.items(): check_loreref(o,o.get("id",k))
for sk in skills.values(): check_loreref(sk,f"skill '{sk['id']}'")

print(f"Loaded: {len(skills)} skills, {len(factions)} factions, {len(characters)} characters, "
      f"{len(dialogues)} dialogues, {len(variables)} variables, {len(quests)} quests, "
      f"{len(locations)} locations, {len(endings)} endings, {len(codex)} codex, {len(portraits)} portraits, "
      f"{len(cutscenes)} cutscenes, {len(routes)} routes, {len(snapshots)} snapshots.\n")
if warnings:
    print(f"WARN  {len(warnings)} warning(s):")
    for w in warnings: print("  "+w)
    print()
if errors:
    print(f"FAIL  {len(errors)} error(s):")
    for e in errors: print("  "+e)
    sys.exit(1)
if STRICT and warnings:
    print("FAIL  --strict: warnings treated as errors."); sys.exit(1)
print("OK  No errors." + ("" if not warnings else "  (warnings above are non-fatal.)"))
sys.exit(0)
