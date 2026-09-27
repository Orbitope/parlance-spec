/**
 * The pure project loader: a map of data-dir-relative path → file content in,
 * a `ProjectData` out. No fs, no Node, no network — read the files however your
 * platform does (fs, fetch, an asset bundle, a zip) and hand the text here.
 */
import type {
  ProjectData,
  Skill,
  Variable,
  Faction,
  Character,
  Dialogue,
  Quest,
  Location,
  Ending,
  Codex,
  Item,
  Portrait,
  Cutscene,
  RouteSpec,
  Snapshot,
  Rules,
  Progression,
  CustomEntityDefinition,
  CustomEntity,
} from "./types.js";
import { setOwn } from "./own.js";

/** JSON.parse, tolerating a leading UTF-8 byte-order mark (editors on Windows write one). */
function parseJson(text: string): unknown {
  return JSON.parse(text.charCodeAt(0) === 0xfeff ? text.slice(1) : text) as unknown;
}

/** A plural names a path under data/: plain name characters only. Anything
 *  else ("../x", "a/b", "") is refused by every loader and by the writers. */
export function isSafePlural(plural: unknown): plural is string {
  return typeof plural === "string" && /^[A-Za-z0-9_-]+$/.test(plural);
}

function tryParse(content: string | undefined): unknown {
  if (content === undefined) return undefined;
  try {
    return parseJson(content);
  } catch {
    return undefined;
  }
}

/**
 * Load a project from an in-memory map of data-dir-relative path → file content
 * (POSIX separators, e.g. "dialogues/act1/dlg_foo.json"). No fs, no Node: the
 * caller reads the files however its platform does. Every `.json` file under
 * the data directory goes in; anything the format does not name is ignored.
 *
 * It does NOT validate. Malformed JSON in a built-in entity file throws (a
 * SyntaxError naming nothing but the parse position — run the validator in CI
 * so a shipped build never hits it); a structurally wrong registry or entity
 * is skipped rather than thrown on. Ids are written as own properties, so an
 * entity id that spells a prototype key (`constructor`) loads like any other.
 */
export function loadProjectFromFileMap(files: ReadonlyMap<string, string>): ProjectData {
  function readArray<T extends { id: string }>(file: string, key: string): Record<string, T> {
    const content = files.get(file);
    if (content === undefined) return {};
    // Tolerates the wrong shape (a registry whose list is an object, a `[null]`
    // entry): such a file used to throw here and take the whole load with it.
    // The validator reports the shape; this only has to not crash.
    const raw = parseJson(content) as Record<string, unknown> | null;
    const arr = raw !== null && typeof raw === "object" && !Array.isArray(raw) && Array.isArray(raw[key]) ? (raw[key] as unknown[]) : [];
    const result: Record<string, T> = {};
    for (const item of arr) {
      const e = item as T | null;
      if (e && typeof e === "object" && typeof e.id === "string" && e.id) setOwn(result, e.id, e);
    }
    return result;
  }

  // Recursive by construction: dir-mode entities may live in nested zone/chapter
  // subdirs (e.g. dialogues/act1/dlg_foo.json). Ids stay globally unique and flat.
  function readDir<T extends { id: string }>(dir: string): Record<string, T> {
    const prefix = `${dir}/`;
    const result: Record<string, T> = {};
    for (const [path, content] of files) {
      if (!path.startsWith(prefix)) continue;
      if (!path.endsWith(".json") || path.endsWith(".layout.json")) continue;
      const entity = parseJson(content) as T | null;
      if (entity && typeof entity === "object" && !Array.isArray(entity) && typeof entity.id === "string" && entity.id) setOwn(result, entity.id, entity);
    }
    return result;
  }

  function readOne<T>(file: string): T | undefined {
    const content = files.get(file);
    return content === undefined ? undefined : (parseJson(content) as T);
  }

  const rules = readOne<Rules>("rules.json");
  const progression = readOne<Progression>("progression.json");
  const entityTypes = readOne<Record<string, CustomEntityDefinition>>("types.json");

  // The same rules as the editor's own custom-type loader, over the file map: a
  // folder of rows when the folder holds any file, else the registry file in
  // either form; a malformed file is skipped (this used to throw and take the
  // whole load with it); unsafe plurals load nothing; own-property writes for
  // every file-supplied key.
  const customEntities: Record<string, Record<string, CustomEntity>> = {};
  if (entityTypes && typeof entityTypes === "object") {
    for (const [typeId, typeDef] of Object.entries(entityTypes)) {
      const res: Record<string, CustomEntity> = {};
      setOwn(customEntities, typeId, res);
      if (!typeDef || typeof typeDef !== "object") continue;
      const plural = typeDef.plural || `${typeId}s`;
      if (!isSafePlural(plural)) continue;
      const prefix = `${plural}/`;
      const hasDir = [...files.keys()].some((k) => k.startsWith(prefix));
      if (hasDir) {
        for (const [path, content] of files) {
          if (!path.startsWith(prefix) || !path.endsWith(".json") || path.endsWith(".layout.json")) continue;
          const e = tryParse(content) as CustomEntity | undefined;
          if (e && typeof e.id === "string" && e.id) setOwn(res, e.id, e);
        }
        continue;
      }
      const raw = tryParse(files.get(`${plural}.json`)) as Record<string, unknown> | undefined;
      if (!raw || typeof raw !== "object") continue;
      const list = Array.isArray(raw[plural]) ? (raw[plural] as unknown[]) : Object.values(raw);
      for (const item of list) {
        const e = item as CustomEntity | null;
        if (e && typeof e === "object" && typeof e.id === "string" && e.id) setOwn(res, e.id, e);
      }
    }
  }

  return {
    skills:     readArray<Skill>("skills.json", "skills"),
    variables:  readArray<Variable>("variables.json", "variables"),
    factions:   readDir<Faction>("factions"),
    characters: readDir<Character>("characters"),
    dialogues:  readDir<Dialogue>("dialogues"),
    quests:     readDir<Quest>("quests"),
    locations:  readDir<Location>("locations"),
    endings:    readDir<Ending>("endings"),
    codex:      readDir<Codex>("codex"),
    items:      readArray<Item>("items.json", "items"),
    portraits:  readArray<Portrait>("portraits.json", "portraits"),
    cutscenes:  readDir<Cutscene>("cutscenes"),
    routes:     readDir<RouteSpec>("routes"),
    snapshots:  readDir<Snapshot>("snapshots"),
    ...(rules !== undefined ? { rules } : {}),
    ...(progression !== undefined ? { progression } : {}),
    ...(entityTypes !== undefined ? { entityTypes, customEntities } : {}),
  };
}
