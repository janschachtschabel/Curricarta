import { flushPromises } from "@vue/test-utils";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { nextTick, ref } from "vue";

import * as api from "@/api";
import { ApiError, type NodeRow, type Placement } from "@/api";
import { t } from "@/i18n/de";
import { usePlacementSave } from "@/placementSave";

import { CV, node_, noValues } from "./treeFixtures";

const BINDING = CV + "obl_binding";

function placement(changes: Partial<Placement> = {}): Placement {
  return {
    id: "p1", node_id: "m1", position: 1, specification_id: "ba", variant_id: null, in_node_id: null, obligation: BINDING,
    grade_weight: null, iri: null, origin: CV + "orig_human", review_status: CV + "rev_proposed", revision: 1, values: noValues(),
    ...changes,
  };
}

function nodeRow(revision: number, placements: Placement[]): NodeRow {
  const { statements, children, ...row } = node_("m1", { revision, placements });
  void [statements, children];
  return row;
}

beforeEach(() => {
  vi.restoreAllMocks();
});

describe("a node's placements saved", () => {
  it("send nothing where nothing changed, and the problems where an entry is short", async () => {
    const set = vi.spyOn(api, "setNodePlacements");
    const saving = usePlacementSave(ref(nodeRow(4, [placement()])));

    expect((await saving.save()).outcome).toBe("unchanged");
    saving.entries.value = [{ ...saving.entries.value[0], obligation: "" }];
    const short = await saving.save();

    expect(short.outcome).toBe("invalid");
    expect(short.faults?.[0]?.[1]).toBe(t("documents.tree.problems.required"));
    expect(set).not.toHaveBeenCalled();
  });

  it("go on from the node's revision a set of one's values counted, and from none other", async () => {
    const set = vi.spyOn(api, "setNodePlacements").mockResolvedValue(nodeRow(6, []));
    const saving = usePlacementSave(ref(nodeRow(4, [placement()])));
    saving.entries.value = [];

    saving.moved(5); // the next after 4: the values' set alone counted it
    saving.moved(7); // not the next after 5: someone else changed the node meanwhile
    const done = await saving.save();

    expect(done.outcome).toBe("saved");
    expect(set).toHaveBeenCalledWith("m1", 5, []);
  });

  it("say what refused the set: a change meanwhile, the tree closing, the node gone, anything else", async () => {
    const saving = usePlacementSave(ref(nodeRow(4, [placement()])));
    saving.entries.value = [];
    const refuse = (error: Error) => vi.spyOn(api, "setNodePlacements").mockRejectedValueOnce(error);

    refuse(new ApiError("server", 409, "stale_revision", "Changed.", { current: nodeRow(5, [placement()]) }));
    expect((await saving.save()).outcome).toBe("stale");
    expect(saving.failure.value?.text).toContain(t("documents.tree.placements.changedMeanwhile"));
    refuse(new ApiError("server", 409, "job_open", "Busy."));
    expect((await saving.save()).outcome).toBe("closed");
    expect(saving.closed.value).toBe("job_open");
    refuse(new ApiError("server", 404, "no_node", "Gone."));
    expect((await saving.save()).outcome).toBe("gone");
    refuse(new Error("network"));
    expect((await saving.save()).outcome).toBe("failed");
    expect(saving.failure.value?.text).toBe(t("documents.tree.placements.saveFailed"));
    expect(saving.entries.value).toEqual([]); // the draft kept throughout
  });

  it("follow the node read anew where no entry changed, and keep the entries where one did", async () => {
    const node = ref(nodeRow(4, [placement()]));
    const saving = usePlacementSave(node);

    node.value = nodeRow(5, [placement({ obligation: CV + "obl_elective" })]);
    await nextTick();
    expect(saving.entries.value.map((one) => one.obligation)).toEqual([CV + "obl_elective"]);

    saving.entries.value = [];
    node.value = nodeRow(6, [placement()]);
    await nextTick();
    await flushPromises();
    expect(saving.entries.value).toEqual([]);
  });
});
