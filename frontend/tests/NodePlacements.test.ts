import { flushPromises, mount, type VueWrapper } from "@vue/test-utils";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import * as api from "@/api";
import { ApiError, type Form, type NodeRow, type Placement, type Tree, type TreeNode } from "@/api";
import NodePlacements from "@/components/NodePlacements.vue";
import { rowsOf, type Row } from "@/documentTree";
import { t } from "@/i18n/de";

import { violations } from "./axe";
import { CV, field, form_, node_, noValues, tree_, value_ } from "./treeFixtures";

const BINDING = CV + "obl_binding";
const ELECTIVE = CV + "obl_elective";
const SPECIFICATIONS: Tree["specifications"] = [
  { id: "ba", title: "Bachelor Mathematik", variants: [{ id: "v1", label: "Schwerpunkt Statistik" }] },
  { id: "ma", title: "Master Mathematik", variants: [] },
];

let shown: VueWrapper | null = null;
let saved = vi.fn();

function placement(id: string, changes: Partial<Placement> = {}): Placement {
  return {
    id,
    node_id: "m1",
    position: 1,
    specification_id: "ba",
    variant_id: null,
    in_node_id: null,
    obligation: BINDING,
    grade_weight: null,
    iri: null,
    origin: CV + "orig_human",
    review_status: CV + "rev_proposed",
    revision: 1,
    values: noValues(),
    ...changes,
  };
}

function formWithObligations(): Form {
  const form = form_("higherEducation");
  form.node.push(field("obligation", "concept", [value_(BINDING, "verbindlich"), value_(ELECTIVE, "Wahl")]));
  return form;
}

function outline(placements: Placement[], revision = 4): TreeNode[] {
  return [
    node_("m1", { revision, placements, fields: { original_title: "Analysis", code: "M 1" } }),
    node_("b1", { position: 2, fields: { original_title: "Pflichtbereich", code: "B" } }),
  ];
}

function section(placements: Placement[], more: Record<string, unknown> = {}, tree: Partial<Tree> = {}): VueWrapper {
  const nodes = outline(placements);
  const row = rowsOf(nodes).get("node:m1") as Row;
  saved = vi.fn();
  shown = mount(NodePlacements, {
    props: {
      row,
      tree: tree_(nodes, { specifications: SPECIFICATIONS, ...tree }),
      form: formWithObligations(),
      documentId: "d1",
      editable: true,
      reviewable: false,
      closedBy: null,
      onSaved: saved,
      ...more,
    },
    attachTo: document.body,
  });
  return shown;
}

/** The node as a set of its placements answers it. */
function answered(placements: Placement[], revision: number): NodeRow {
  const { statements, children, ...row } = node_("m1", { revision, placements });
  void [statements, children];
  return row;
}

const button = (wrapper: VueWrapper, label: string) => {
  const found = wrapper.findAll("button").find((one) => one.text() === label);
  if (!found) throw new Error(label);
  return found;
};

function entry(wrapper: VueWrapper, place: number) {
  const found = wrapper.findAll("fieldset").find((one) => one.get("legend").text() === `Verwendung ${place}`);
  if (!found) throw new Error(`Verwendung ${place}`);
  return found;
}

const select = (wrapper: VueWrapper, place: number, label: string) => {
  const fieldset = entry(wrapper, place);
  const found = fieldset.findAll("label").find((one) => one.text() === label);
  if (!found) throw new Error(label);
  return fieldset.get(`#${found.attributes("for")}`);
};

async function save(wrapper: VueWrapper): Promise<void> {
  (wrapper.get(".node-placements__save").element as HTMLElement).focus();
  await wrapper.get("form").trigger("submit");
  await flushPromises();
}

beforeEach(() => {
  vi.restoreAllMocks();
});

afterEach(() => {
  shown?.unmount();
  shown = null;
  document.body.innerHTML = "";
});

describe("a node's placements as they read", () => {
  it("names each where it is, at which node, how binding and with what weight", async () => {
    const wrapper = section(
      [placement("p1", { in_node_id: "b1", grade_weight: 1.5 }), placement("p2", { specification_id: null, variant_id: "v1", obligation: ELECTIVE })],
      { editable: false },
    );

    expect(wrapper.get("h3").text()).toBe("Verwendungen");
    expect(wrapper.findAll(".node-placements__words").map((one) => one.text())).toEqual([
      "Bachelor Mathematik · an B Pflichtbereich · verbindlich · Notengewicht 1,5",
      "Bachelor Mathematik – Schwerpunkt Statistik · Wahl",
    ]);
    // each with its time and workload there, under its own heading; nothing to change where the tree only reads
    expect(wrapper.findAll("h4").map((one) => one.text())).toEqual([
      "Zeit und Umfang: Bachelor Mathematik",
      "Zeit und Umfang: Bachelor Mathematik – Schwerpunkt Statistik",
    ]);
    expect(wrapper.find("form").exists()).toBe(false);
    expect(await violations(wrapper.html())).toEqual([]);
  });

  it("says where the node is placed nowhere yet", async () => {
    const wrapper = section([], { editable: false });

    expect(wrapper.get(".node-placements__none").text()).toBe(t("documents.tree.placements.none"));
    expect(await violations(wrapper.html())).toEqual([]);
  });

  it("offers nothing to add where the document names no specification", async () => {
    const wrapper = section([], {}, { specifications: [] });

    expect(wrapper.get(".node-placements__none").text()).toBe(t("documents.tree.placements.noPlaces"));
    expect(wrapper.find("form").exists()).toBe(false);
    expect(await violations(wrapper.html())).toEqual([]);
  });
});

describe("a node's placements in their form", () => {
  it("adds an entry with the keyboard at its first field, in the document's one specification, and says a draft is open", async () => {
    const wrapper = section([], {}, { specifications: SPECIFICATIONS.slice(1) });
    expect(wrapper.emitted("dirty")).toEqual([[false]]);

    await button(wrapper, "Verwendung hinzufügen").trigger("click");

    expect(document.activeElement?.closest("fieldset")?.querySelector("legend")?.textContent).toBe("Verwendung 1");
    expect((select(wrapper, 1, "Spezifikation").element as HTMLSelectElement).value).toBe("ma");
    expect(wrapper.emitted("dirty")?.at(-1)).toEqual([true]);
    expect(wrapper.get(".node-placements__status").text()).toBe("Verwendung 1 hinzugefügt.");
  });

  it("sends the whole set on the node's revision, a kept one by its id, and tells the panel", async () => {
    const set = vi.spyOn(api, "setNodePlacements").mockResolvedValue(answered([placement("p1"), placement("p9", { position: 2 })], 5));
    const wrapper = section([placement("p1")]);

    await button(wrapper, "Verwendung hinzufügen").trigger("click");
    await select(wrapper, 2, "Variante").setValue("v1");
    await select(wrapper, 2, "An Stelle").setValue("b1");
    await select(wrapper, 2, "Verbindlichkeit (Pflichtfeld)").setValue(ELECTIVE);
    await select(wrapper, 2, "Notengewicht").setValue("2,5");
    await save(wrapper);

    expect(set).toHaveBeenCalledWith("m1", 4, [
      { id: "p1", specification_id: "ba", variant_id: null, in_node_id: null, obligation: BINDING, grade_weight: null },
      { id: null, specification_id: null, variant_id: "v1", in_node_id: "b1", obligation: ELECTIVE, grade_weight: 2.5 },
    ]);
    expect(saved).toHaveBeenCalledWith(answered([placement("p1"), placement("p9", { position: 2 })], 5));
    // the node itself is no place it may be at
    const places = select(wrapper, 2, "An Stelle").findAll("option").map((one) => one.text());
    expect(places).not.toContain("M 1 Analysis");
  });

  it("takes an entry away, the keyboard to the button that adds one", async () => {
    const set = vi.spyOn(api, "setNodePlacements").mockResolvedValue(answered([], 5));
    const wrapper = section([placement("p1")]);

    await button(wrapper, "Verwendung 1 entfernen").trigger("click");

    expect(document.activeElement?.textContent?.trim()).toBe("Verwendung hinzufügen");
    expect(wrapper.get(".node-placements__status").text()).toBe("Verwendung 1 entfernt.");
    await save(wrapper);
    expect(set).toHaveBeenCalledWith("m1", 4, []);
  });

  it("names the problems at their fields before anything is sent", async () => {
    const set = vi.spyOn(api, "setNodePlacements");
    const wrapper = section([]);

    await button(wrapper, "Verwendung hinzufügen").trigger("click");
    await select(wrapper, 1, "Spezifikation").setValue("");
    await select(wrapper, 1, "Notengewicht").setValue("viel");
    await save(wrapper);

    expect(set).not.toHaveBeenCalled();
    const errors = entry(wrapper, 1).findAll(".field__error").map((one) => one.text());
    expect(errors).toEqual([t("documents.tree.placements.problems.nowhere"), t("documents.tree.problems.required"), t("documents.tree.values.problems.not_number")]);
    expect(document.activeElement).toBe(select(wrapper, 1, "Spezifikation").element);
    expect(await violations(wrapper.html())).toEqual([]);
  });

  it("puts a problem the server found at its entry's field", async () => {
    vi.spyOn(api, "setNodePlacements").mockRejectedValue(
      new ApiError("server", 422, "invalid_field", "Refused.", { field: "placements[1].variant_id", problem: "not_offered" }),
    );
    const wrapper = section([placement("p1"), placement("p2", { position: 2, variant_id: "v1" })]);

    await select(wrapper, 2, "Notengewicht").setValue("2");
    await save(wrapper);

    expect(entry(wrapper, 2).findAll(".field__error").map((one) => one.text())).toHaveLength(1);
    expect(document.activeElement).toBe(select(wrapper, 2, "Variante").element);
  });

  it("keeps the entries where the node changed meanwhile, and saves again on its new revision", async () => {
    const set = vi
      .spyOn(api, "setNodePlacements")
      .mockRejectedValueOnce(new ApiError("server", 409, "stale_revision", "Changed.", { current: answered([placement("p1")], 6) }))
      .mockResolvedValueOnce(answered([placement("p1", { obligation: ELECTIVE })], 7));
    const wrapper = section([placement("p1")]);

    await select(wrapper, 1, "Verbindlichkeit (Pflichtfeld)").setValue(ELECTIVE);
    await save(wrapper);

    expect(wrapper.get("[role=alert]").text()).toContain(t("documents.tree.placements.changedMeanwhile"));
    expect((select(wrapper, 1, "Verbindlichkeit (Pflichtfeld)").element as HTMLSelectElement).value).toBe(ELECTIVE);
    await save(wrapper);
    expect(set).toHaveBeenLastCalledWith("m1", 6, [expect.objectContaining({ id: "p1", obligation: ELECTIVE })]);
  });

  it("says why it is closed where the tree closed under an open draft, the draft kept to copy", async () => {
    const wrapper = section([placement("p1")]);
    await select(wrapper, 1, "Verbindlichkeit (Pflichtfeld)").setValue(ELECTIVE);

    await wrapper.setProps({ closedBy: "frozen" });

    expect(wrapper.find("form").exists()).toBe(false);
    expect(wrapper.get(".node-placements__closed [role=alert]").text()).toBeTruthy();
    expect(wrapper.get(".node-placements__closed").text()).toContain("Bachelor Mathematik · Wahl");
  });

  it("names its save button with its visible words first", () => {
    const wrapper = section([placement("p1")]);

    const save_ = wrapper.get(".node-placements__save");
    expect(save_.attributes("aria-label")?.startsWith(save_.text())).toBe(true);
  });
});
