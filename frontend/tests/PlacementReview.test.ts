import { flushPromises, mount, type VueWrapper } from "@vue/test-utils";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import * as api from "@/api";
import { ApiError, type Form, type NodeRow, type Placement, type Tree, type TreeNode } from "@/api";
import NodePlacements from "@/components/NodePlacements.vue";
import { rowsOf, type Row } from "@/documentTree";
import { t } from "@/i18n/de";

import { violations } from "./axe";
import { CV, field, form_, node_, noValues, tree_, value_ } from "./treeFixtures";

// The editors' review of a node's placements (plan M3a L): the statuses of each stored one in a group named for it,
// beside who stated it; set at its revision, which counts the node's revision too - the answer names it, and an open
// draft of the placements goes on from it, as from the review of a placement's value, rather than meeting a refusal
// that says another changed the node.
const BINDING = CV + "obl_binding";
const SPECIFICATIONS: Tree["specifications"] = [{ id: "ba", title: "Bachelor Mathematik", variants: [] }];
const STATED = { origin: CV + "orig_human", review_status: CV + "rev_proposed", revision: 1 };
const TITLE = "Verwendung 1: Bachelor Mathematik";

let shown: VueWrapper | null = null;
let reviewed = vi.fn();

function placement(changes: Partial<Placement> = {}): Placement {
  return {
    id: "p1", node_id: "m1", position: 1, specification_id: "ba", variant_id: null, in_node_id: null,
    obligation: BINDING, grade_weight: null, iri: null, ...STATED, values: noValues(), ...changes,
  };
}

function withSemester(): Placement {
  const span = { id: "t1", ...STATED, time_kind: CV + "time_semester", span_from: 3, span_to: null, time_relation: null };
  return placement({ values: { ...noValues(), time_spans: [span] } });
}

function form(): Form {
  const made = form_("higherEducation");
  made.node.push(field("obligation", "concept", [value_(BINDING, "verbindlich")]));
  return made;
}

function outline(placements: Placement[]): TreeNode[] {
  return [node_("m1", { revision: 4, placements, fields: { original_title: "Analysis", code: "M 1" } })];
}

function section(placements: Placement[], more: Record<string, unknown> = {}): VueWrapper {
  const nodes = outline(placements);
  reviewed = vi.fn();
  shown = mount(NodePlacements, {
    props: {
      row: rowsOf(nodes).get("node:m1") as Row, tree: tree_(nodes, { specifications: SPECIFICATIONS }), form: form(),
      documentId: "d1", editable: true, reviewable: true, closedBy: null, onReviewed: reviewed, ...more,
    },
    attachTo: document.body,
  });
  return shown;
}

function answered(placements: Placement[], revision: number): NodeRow {
  const { statements, children, ...row } = node_("m1", { revision, placements });
  void [statements, children];
  return row;
}

function group(wrapper: VueWrapper, name: string) {
  const found = wrapper.findAll("[role=group]").find((one) => document.getElementById(one.attributes("aria-labelledby") ?? "")?.textContent === name);
  if (!found) throw new Error(name);
  return found;
}

function toggle(within: ReturnType<VueWrapper["get"]>, label: string) {
  const found = within.findAll("button").find((one) => one.text() === label);
  if (!found) throw new Error(label);
  return found;
}

async function weighAndSave(wrapper: VueWrapper): Promise<void> {
  const weight = wrapper.findAll("label").find((one) => one.text() === "Notengewicht");
  await wrapper.get(`#${weight?.attributes("for")}`).setValue("2");
  (wrapper.get(".node-placements__save").element as HTMLElement).focus();
  await wrapper.get(".node-placements__form").trigger("submit");
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

describe("a placement's review in the node's panel", () => {
  it("offers the editors its statuses beside who stated it, in a group named for it", async () => {
    const wrapper = section([placement()]);

    const toggles = group(wrapper, `Prüfstand von „${TITLE}“`);
    expect(toggles.findAll("button").map((one) => one.attributes("aria-pressed"))).toEqual(["true", "false", "false"]);
    expect(wrapper.get(".node-placements__stated").text()).toBe("redaktionell · Vorgeschlagen");
    expect(await violations(wrapper.html())).toEqual([]);
    expect(section([placement()], { reviewable: false }).find("[role=group]").exists()).toBe(false);
  });

  it("sets it at its revision, says so by its name and tells the panel", async () => {
    const sent = vi.spyOn(api, "setReview").mockResolvedValue({ revisions: [{ id: "p1", revision: 2 }], nodes: [{ id: "m1", revision: 5 }] });
    const wrapper = section([placement()]);

    await toggle(group(wrapper, `Prüfstand von „${TITLE}“`), "Bestätigt").trigger("click");
    await flushPromises();

    expect(sent).toHaveBeenCalledWith("d1", "confirmed", [{ kind: "placement", id: "p1", revision: 1 }]);
    expect(wrapper.get(".node-placements__status").text()).toBe(`Prüfstand von „${TITLE}“: Bestätigt.`);
    expect(reviewed).toHaveBeenCalledWith(expect.objectContaining({ outcome: "set" }), "placement:p1", `Prüfstand von „${TITLE}“: Bestätigt.`);
    // the status just set stays pressed while the tree is not read again, and the next is set at the revision it left
    const toggles = group(wrapper, `Prüfstand von „${TITLE}“`);
    expect(toggle(toggles, "Bestätigt").attributes("aria-pressed")).toBe("true");
    await toggle(toggles, "Verworfen").trigger("click");
    await flushPromises();
    expect(sent).toHaveBeenLastCalledWith("d1", "rejected", [{ kind: "placement", id: "p1", revision: 2 }]);
  });

  it.each([
    ["job_open", 409],
    ["not_editor", 403],
  ])("says a review the tree closed to or refused (%s), of a placement and of a value at one", async (code, status) => {
    vi.spyOn(api, "setReview").mockRejectedValue(new ApiError("server", status, code));
    const wrapper = section([withSemester()]);

    await toggle(group(wrapper, `Prüfstand von „${TITLE}“`), "Bestätigt").trigger("click");
    await flushPromises();
    expect(wrapper.get(".node-placements__status").text()).toBe(t(`refusals.${code}`));
    await toggle(wrapper.get(".value-section [role=group]"), "Verworfen").trigger("click");
    await flushPromises();
    expect(wrapper.get(".node-placements__status").text()).toBe(t(`refusals.${code}`));
    expect(reviewed).toHaveBeenLastCalledWith(expect.objectContaining({ code }), "placement:p1", undefined);
  });

  it("says one changed meanwhile by its name", async () => {
    vi.spyOn(api, "setReview").mockRejectedValue(
      new ApiError("server", 409, "stale_revision", "Changed.", { stale: [{ kind: "placement", id: "p1", current: 2 }] }),
    );
    const wrapper = section([placement()]);

    await toggle(group(wrapper, `Prüfstand von „${TITLE}“`), "Bestätigt").trigger("click");
    await flushPromises();

    expect(wrapper.get(".node-placements__status").text()).toBe(t("documents.tree.placements.reviewStale", { title: TITLE }));
  });
});

describe("an open draft of the placements beside one's own review", () => {
  it("goes on from the node's revision the review of a placement moved, without a refusal", async () => {
    vi.spyOn(api, "setReview").mockResolvedValue({ revisions: [{ id: "p1", revision: 2 }], nodes: [{ id: "m1", revision: 5 }] });
    const set = vi.spyOn(api, "setNodePlacements").mockResolvedValue(answered([placement({ grade_weight: 2 })], 6));
    const wrapper = section([placement()]);

    await toggle(group(wrapper, `Prüfstand von „${TITLE}“`), "Bestätigt").trigger("click");
    await flushPromises();
    await weighAndSave(wrapper);

    expect(set).toHaveBeenCalledWith("m1", 5, [expect.objectContaining({ id: "p1", grade_weight: 2 })]);
    expect(wrapper.text()).not.toContain(t("documents.tree.placements.changedMeanwhile"));
  });

  it("goes on from the node's revision the review of a placement's value moved, under a draft opened before it", async () => {
    vi.spyOn(api, "setReview").mockResolvedValue({ revisions: [{ id: "t1", revision: 2 }], nodes: [{ id: "m1", revision: 5 }] });
    const set = vi.spyOn(api, "setNodePlacements").mockResolvedValue(answered([withSemester()], 6));
    const wrapper = section([withSemester()]);
    const weight = wrapper.findAll("label").find((one) => one.text() === "Notengewicht");
    await wrapper.get(`#${weight?.attributes("for")}`).setValue("1");

    await toggle(wrapper.get(".value-section [role=group]"), "Bestätigt").trigger("click");
    await flushPromises();
    await weighAndSave(wrapper);

    expect(set).toHaveBeenCalledWith("m1", 5, [expect.objectContaining({ id: "p1", grade_weight: 2 })]);
    expect(wrapper.text()).not.toContain(t("documents.tree.placements.changedMeanwhile"));
  });

  it("is refused as changed meanwhile where another moved the node too", async () => {
    vi.spyOn(api, "setReview").mockResolvedValue({ revisions: [{ id: "p1", revision: 2 }], nodes: [{ id: "m1", revision: 7 }] });
    const set = vi.spyOn(api, "setNodePlacements");
    const wrapper = section([placement()]);

    await toggle(group(wrapper, `Prüfstand von „${TITLE}“`), "Bestätigt").trigger("click");
    await flushPromises();
    set.mockRejectedValue(new ApiError("server", 409, "stale_revision", "Changed.", { current: answered([placement()], 7) }));
    await weighAndSave(wrapper);

    expect(set).toHaveBeenCalledWith("m1", 4, expect.anything());
  });
});
