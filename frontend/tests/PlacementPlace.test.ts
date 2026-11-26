import { flushPromises, mount, type VueWrapper } from "@vue/test-utils";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import * as api from "@/api";
import { ApiError, type Form, type TreeNode } from "@/api";
import NodePlacements from "@/components/NodePlacements.vue";
import { rowsOf, type Row } from "@/documentTree";
import { t } from "@/i18n/de";

import { CV, field, form_, node_, tree_, value_ } from "./treeFixtures";

// "An Stelle" in the placements' form (plan M3a L): a search over the outline, whose problem the server finds stands
// at the search, the keyboard taken there, as at any of the entry's fields.
const BINDING = CV + "obl_binding";
let shown: VueWrapper | null = null;

function form(): Form {
  const made = form_("higherEducation");
  made.node.push(field("obligation", "concept", [value_(BINDING, "verbindlich")]));
  return made;
}

function section(): VueWrapper {
  const nodes: TreeNode[] = [
    node_("m1", { revision: 4, fields: { original_title: "Analysis", code: "M 1" } }),
    node_("b1", { position: 2, fields: { original_title: "Pflichtbereich", code: "B" } }),
  ];
  shown = mount(NodePlacements, {
    props: {
      row: rowsOf(nodes).get("node:m1") as Row, tree: tree_(nodes, { specifications: [{ id: "ba", title: "Bachelor", variants: [] }] }),
      form: form(), documentId: "d1", editable: true, reviewable: false, closedBy: null,
    },
    attachTo: document.body,
  });
  return shown;
}

beforeEach(() => {
  vi.restoreAllMocks();
});

afterEach(() => {
  shown?.unmount();
  shown = null;
  document.body.innerHTML = "";
});

describe("the place of a placement in the node's form", () => {
  it("is chosen by its search and sent; a problem the server finds there stands at the search", async () => {
    const set = vi.spyOn(api, "setNodePlacements").mockRejectedValue(
      new ApiError("server", 422, "invalid_field", "Not offered.", { field: "placements[0].in_node_id", problem: "not_offered" }),
    );
    const wrapper = section();
    const add = wrapper.findAll("button").find((one) => one.text() === t("documents.tree.placements.add"));
    await add?.trigger("click");
    await wrapper.get("[data-test=places-offered] button").trigger("click");
    const kind = wrapper.findAll("label").find((one) => one.text() === t("documents.tree.placements.fields.obligation"));
    await wrapper.get(`#${kind?.attributes("for")}`).setValue(BINDING);

    (wrapper.get(".node-placements__save").element as HTMLElement).focus();
    await wrapper.get(".node-placements__form").trigger("submit");
    await flushPromises();

    expect(set).toHaveBeenCalledWith("m1", 4, [expect.objectContaining({ in_node_id: "b1" })]);
    const search = wrapper.get("input[type=search]");
    expect(document.activeElement).toBe(search.element);
    expect(search.attributes("aria-invalid")).toBe("true");
    const error = (search.attributes("aria-describedby") ?? "").split(" ").map((id) => document.getElementById(id)?.textContent?.trim());
    expect(error).toContain(t("documents.tree.problems.not_offered"));
  });
});
