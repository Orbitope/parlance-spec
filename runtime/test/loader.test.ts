/**
 * The pure loader is the one piece of this package a game calls before any
 * contract function, and neither official port has one — so its edge cases are
 * pinned here, against the package itself, rather than only through core.
 */
import { describe, it, expect } from "vitest";
import { loadProjectFromFileMap, createDefaultState, stepDialogue } from "../src/index.js";

const dialogue = (id: string) =>
  JSON.stringify({ id, entry: "n1", nodes: [{ id: "n1", text: `Hello from ${id}.`, isEnd: true }] });

describe("loadProjectFromFileMap", () => {
  it("assembles registries and per-entity folders, nested folders included", () => {
    const p = loadProjectFromFileMap(
      new Map([
        ["skills.json", JSON.stringify({ skills: [{ id: "wit", name: "Wit" }] })],
        ["variables.json", JSON.stringify({ variables: [{ id: "met", kind: "flag", default: true }] })],
        ["dialogues/dlg_top.json", dialogue("dlg_top")],
        ["dialogues/act1/scene2/dlg_deep.json", dialogue("dlg_deep")],
      ]),
    );
    expect(Object.keys(p.skills)).toEqual(["wit"]);
    expect(Object.keys(p.dialogues).sort()).toEqual(["dlg_deep", "dlg_top"]);
    expect(createDefaultState(p).flags).toEqual({ met: true });
    expect(stepDialogue(p.dialogues["dlg_deep"]!, "n1", createDefaultState(p), p).node.text).toBe("Hello from dlg_deep.");
  });

  it("tolerates a UTF-8 byte-order mark (editors on Windows write one)", () => {
    const p = loadProjectFromFileMap(new Map([["dialogues/dlg_bom.json", "﻿" + dialogue("dlg_bom")]]));
    expect(Object.keys(p.dialogues)).toEqual(["dlg_bom"]);
  });

  it("skips canvas layout sidecars and non-JSON files", () => {
    const p = loadProjectFromFileMap(
      new Map([
        ["dialogues/dlg_a.json", dialogue("dlg_a")],
        ["dialogues/dlg_a.layout.json", JSON.stringify({ id: "dlg_layout_ghost", positions: {} })],
        ["dialogues/notes.txt", "not json"],
      ]),
    );
    expect(Object.keys(p.dialogues)).toEqual(["dlg_a"]);
  });

  it("loads an entity whose id spells a prototype key as an ordinary own entry", () => {
    const p = loadProjectFromFileMap(
      new Map([
        ["dialogues/__proto__.json", dialogue("__proto__")],
        ["dialogues/constructor.json", dialogue("constructor")],
      ]),
    );
    expect(Object.keys(p.dialogues).sort()).toEqual(["__proto__", "constructor"]);
    expect(Object.getPrototypeOf(p.dialogues)).toBe(Object.prototype);
    expect(p.dialogues["constructor"]!.nodes[0]!.text).toBe("Hello from constructor.");
  });

  it("skips wrong-shaped registries and entries instead of throwing", () => {
    const p = loadProjectFromFileMap(
      new Map([
        ["skills.json", JSON.stringify({ skills: { wit: { id: "wit" } } })],
        ["items.json", JSON.stringify({ items: [null, 7, { name: "no id" }, { id: "item_ok", name: "Ok" }] })],
      ]),
    );
    expect(p.skills).toEqual({});
    expect(Object.keys(p.items ?? {})).toEqual(["item_ok"]);
  });

  it("skips a malformed custom-type row and refuses an unsafe plural", () => {
    const p = loadProjectFromFileMap(
      new Map([
        ["types.json", JSON.stringify({ drink: { name: "Drink", plural: "drinks", fields: {} }, bad: { name: "B", plural: "../x", fields: {} } })],
        ["drinks/ale.json", JSON.stringify({ id: "ale", name: "Ale" })],
        ["drinks/broken.json", "{ not json"],
        ["../x.json", JSON.stringify({ "../x": [{ id: "escaped" }] })],
      ]),
    );
    expect(Object.keys(p.customEntities?.["drink"] ?? {})).toEqual(["ale"]);
    expect(p.customEntities?.["bad"]).toEqual({});
  });

  it("omits the optional singletons when their files are absent", () => {
    const p = loadProjectFromFileMap(new Map());
    expect("rules" in p || "progression" in p || "entityTypes" in p).toBe(false);
    expect(p.dialogues).toEqual({});
  });
});
