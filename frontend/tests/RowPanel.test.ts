import { flushPromises, mount, type VueWrapper } from "@vue/test-utils";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import * as api from "@/api";

import RowPanel from "@/components/RowPanel.vue";
import { rowsOf, type Row } from "@/documentTree";
import { t } from "@/i18n/de";

import { CV, field, form_, node_, noValues, statement_, tree_, value_ } from "./treeFixtures";

let shown: VueWrapper | null = null;

beforeEach(() => {
  vi.restoreAllMocks();
});

afterEach(() => {
  shown?.unmount();
  shown = null;
  document.body.innerHTML = "";
});

const NODES = [node_("a", { fields: { original_title: "Optik", code: "LF 1" } })];
const ROW = rowsOf(NODES).get("node:a") as Row;

describe("the panel of a row being added", () => {
  it("gives the form why the tree, read anew, closed under it", async () => {
    shown = mount(RowPanel, {
      props: {
        row: ROW,
        tree: tree_(NODES),
        form: form_(),
        documentId: "d1",
        creating: { kind: "node", document: "d1", parent: "a" },
      },
      attachTo: document.body,
    });
    await shown.get(".row-creator input").setValue("Neu");

    await shown.setProps({ tree: tree_(NODES, { editable: false, closed: "frozen" }) });

    expect(shown.get(".row-creator__closed [role=alert]").text()).toBe(t("refusals.frozen"));
    expect(shown.find(".row-creator form").exists()).toBe(false);
  });
});

describe("the values of the row chosen", () => {
  const WORKLOAD = {
    id: "w1",
    origin: CV + "orig_human",
    review_status: CV + "rev_proposed",
    revision: 1,
    amount: 80,
    amount_to: null,
    unit: CV + "unit_lesson",
    workload_kind: null,
    is_recommendation: false,
    minutes_per_unit: null,
    total: false,
    periods: [],
  };
  const VALUED = [node_("a", { fields: { original_title: "Optik", code: "LF 1" }, values: { ...noValues(), workloads: [WORKLOAD] } })];
  const VALUED_ROW = rowsOf(VALUED).get("node:a") as Row;

  function panel(tree = tree_(VALUED)): VueWrapper {
    shown = mount(RowPanel, { props: { row: VALUED_ROW, tree, form: form_(), documentId: "d1" }, attachTo: document.body });
    return shown;
  }

  it("stand in their form where the tree is open, a draft of them open to the leave guard as one of the fields", async () => {
    const wrapper = panel();

    expect(wrapper.get(".value-section h3").text()).toBe("Niveau, Zeit, Umfang");
    await wrapper.get(".value-section fieldset input").setValue("90");
    expect(wrapper.emitted("dirty")?.at(-1)).toEqual([true]);
    // the fields' editor has no draft: the values' still keeps the guard asking
    await wrapper.get(".row-editor input").setValue("Licht");
    await wrapper.get(".row-editor input").setValue("Optik");
    expect(wrapper.emitted("dirty")?.at(-1)).toEqual([true]);
  });

  it("have the tree read again once saved or reviewed: the holder's revision moved", async () => {
    vi.spyOn(api, "setNodeValues").mockResolvedValue({ ...VALUED[0], revision: 2 });
    vi.spyOn(api, "setReview").mockResolvedValue({ revisions: [{ id: "w1", revision: 2 }], nodes: [] });
    const wrapper = panel();
    await wrapper.get(".value-section fieldset input").setValue("90");
    await wrapper.get(".value-section form").trigger("submit");
    await flushPromises();
    expect(wrapper.emitted("changed")).toHaveLength(1);

    const toggles = wrapper.get(".value-section [role=group]");
    await toggles.findAll("button")[1]?.trigger("click");
    await flushPromises();

    expect(wrapper.emitted("changed")).toHaveLength(2);
    // the value's, told apart from the row's own: "Prüfstand: Bestätigt."
    expect(wrapper.get(".row-panel__status").text()).toBe("Prüfstand von „80 Unterrichtsstunden“: Bestätigt.");
  });

  it("read in words where the tree is closed", () => {
    const wrapper = panel(tree_(VALUED, { editable: false, reviewable: false, closed: "frozen" }));

    expect(wrapper.find(".value-section form").exists()).toBe(false);
    expect(wrapper.get(".value-list__words").text()).toBe("80 Unterrichtsstunden");
  });
});


describe("the placements of the node chosen", () => {
  const SPECIFICATIONS = [{ id: "ba", title: "Bachelor", variants: [] }];

  function panel(row: Row, tree = tree_(NODES, { specifications: SPECIFICATIONS })): VueWrapper {
    const form = form_();
    form.node.push(field("obligation", "concept", [value_(CV + "obl_binding", "verbindlich")]));
    shown = mount(RowPanel, { props: { row, tree, form, documentId: "d1" }, attachTo: document.body });
    return shown;
  }

  it("stand under a node's values, a draft of them open to the leave guard; a statement has none", async () => {
    const wrapper = panel(ROW);

    expect(wrapper.get(".node-placements h3").text()).toBe("Verwendungen");
    await wrapper.get(".node-placements__add").trigger("click");
    expect(wrapper.emitted("dirty")?.at(-1)).toEqual([true]);

    const said = rowsOf([node_("s", { statements: [statement_("s1")] })]).get("statement:s1") as Row;
    shown?.unmount();
    expect(panel(said).find(".node-placements").exists()).toBe(false);
  });

  it("have the tree read again once saved", async () => {
    const [first] = NODES;
    if (!first) throw new Error("no node");
    const { statements, children, ...row } = first;
    void [statements, children];
    vi.spyOn(api, "setNodePlacements").mockResolvedValue({ ...row, revision: 2 });
    const wrapper = panel(ROW);
    await wrapper.get(".node-placements__add").trigger("click");
    const obligation = wrapper.findAll(".node-placements select").at(-1);
    expect(obligation).toBeDefined();
    await obligation?.setValue(CV + "obl_binding");
    await wrapper.get(".node-placements form").trigger("submit");
    await flushPromises();

    expect(wrapper.emitted("changed")).toHaveLength(1);
  });

  it("go on from the revision the node's own review left, under a draft opened before it", async () => {
    const [first] = NODES;
    if (!first) throw new Error("no node");
    const { statements, children, ...row } = first;
    void [statements, children];
    vi.spyOn(api, "setReview").mockResolvedValue({ revisions: [{ id: "a", revision: 2 }], nodes: [] });
    const set = vi.spyOn(api, "setNodePlacements").mockResolvedValue({ ...row, revision: 3 });
    const wrapper = panel(ROW);
    await wrapper.get(".node-placements__add").trigger("click");
    await wrapper.findAll(".node-placements select").at(-1)?.setValue(CV + "obl_binding");

    const own = wrapper.findAll("[role=group]").find((one) => one.text().startsWith(t("documents.tree.review.label")));
    await own?.findAll("button")[1]?.trigger("click");
    await flushPromises();
    await wrapper.get(".node-placements form").trigger("submit");
    await flushPromises();

    expect(set).toHaveBeenCalledWith("a", 2, [expect.objectContaining({ obligation: CV + "obl_binding" })]);
  });
});
