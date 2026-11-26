import { flushPromises, mount, type VueWrapper } from "@vue/test-utils";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import * as api from "@/api";
import { ApiError, type HeldValues, type NodeRow } from "@/api";
import ValueSection from "@/components/ValueSection.vue";
import { rowsOf, type Row } from "@/documentTree";
import { t } from "@/i18n/de";

import { violations } from "./axe";
import { CV, form_, node_, noValues } from "./treeFixtures";

// A workload's periods in the values' form (plan M3a G, carried to L): a group within the workload, named for it, each
// period an entry of its own - added with the keyboard at its first field, changed, taken away -, sent with the
// workload, a problem the server finds at one standing at that period's field.
let shown: VueWrapper | null = null;

const STATED = { origin: CV + "orig_human", review_status: CV + "rev_proposed", revision: 1 };

function held(): HeldValues {
  return {
    ...noValues(),
    workloads: [
      {
        id: "w1",
        ...STATED,
        amount: 4,
        amount_to: null,
        unit: CV + "unit_lesson",
        workload_kind: null,
        is_recommendation: false,
        minutes_per_unit: null,
        total: false,
        periods: [{ id: "p1", ...STATED, time_kind: CV + "time_gradeLevel", span_from: 7, span_to: null, time_relation: null }],
      },
    ],
  };
}

function nodeRow(): Row {
  return rowsOf([node_("a", { revision: 3, values: held() })]).get("node:a") as Row;
}

function answered(): NodeRow {
  const { statements, children, ...row } = node_("a", { revision: 4, values: held() });
  void [statements, children];
  return row;
}

function section(): VueWrapper {
  shown = mount(ValueSection, {
    props: { row: nodeRow(), form: form_(), documentId: "d1", editable: true, reviewable: false, closedBy: null },
    attachTo: document.body,
  });
  return shown;
}

function group(within: VueWrapper | ReturnType<VueWrapper["get"]>, legend: string) {
  const found = within.findAll("fieldset").find((one) => one.get("legend").text() === legend);
  if (!found) throw new Error(legend);
  return found;
}

function button(within: ReturnType<VueWrapper["get"]>, label: string) {
  const found = within.findAll("button").find((one) => one.text() === label);
  if (!found) throw new Error(label);
  return found;
}

async function save(wrapper: VueWrapper): Promise<void> {
  (wrapper.get("form button[type=submit]").element as HTMLElement).focus();
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

describe("a workload's periods in the values' form", () => {
  it("stand in a group within the workload, each an entry with its fields", async () => {
    const wrapper = section();

    const periods = group(group(wrapper, "Umfang 1"), "Zeiträume von Umfang 1");
    const first = group(periods, "Zeitraum 1");
    expect((first.get("select").element as HTMLSelectElement).value).toBe(CV + "time_gradeLevel");
    expect((first.findAll("input")[0]?.element as HTMLInputElement).value).toBe("7");
    expect(await violations(wrapper.html())).toEqual([]);
  });

  it("are added with the keyboard at the new period, changed and taken away, and sent with their workload", async () => {
    const sent = vi.spyOn(api, "setNodeValues").mockResolvedValue(answered());
    const wrapper = section();
    const periods = () => group(group(wrapper, "Umfang 1"), "Zeiträume von Umfang 1");

    await button(periods(), "Zeitraum hinzufügen").trigger("click");
    const added = group(periods(), "Zeitraum 2");
    expect(document.activeElement).toBe(added.get("select").element);
    await added.get("select").setValue(CV + "time_semester");
    await added.findAll("input")[0]?.setValue("2");
    await button(group(periods(), "Zeitraum 1"), "Zeitraum 1 entfernen").trigger("click");
    await save(wrapper);

    expect(sent).toHaveBeenCalledWith("a", 3, expect.objectContaining({
      workloads: [expect.objectContaining({
        id: "w1",
        periods: [{ id: null, time_kind: CV + "time_semester", span_from: 2, span_to: null, time_relation: null }],
      })],
    }));
  });

  it("have a problem the server finds at one said at that period's field, the keyboard taken there", async () => {
    vi.spyOn(api, "setNodeValues").mockRejectedValue(
      new ApiError("server", 422, "invalid_field", "Not offered.", { field: "workloads[0].periods[0].time_kind", problem: "not_offered" }),
    );
    const wrapper = section();
    await group(group(wrapper, "Umfang 1"), "Zeiträume von Umfang 1").findAll("input")[0]?.setValue("8");

    await save(wrapper);

    const kind = group(group(wrapper, "Zeiträume von Umfang 1"), "Zeitraum 1").get("select");
    expect(document.activeElement).toBe(kind.element);
    expect(kind.attributes("aria-invalid")).toBe("true");
    expect(document.getElementById(kind.attributes("aria-describedby") ?? "")?.textContent?.trim()).toBe(
      t("documents.tree.problems.not_offered"),
    );
    expect(wrapper.find(".value-section__problem").exists()).toBe(false);
  });

  it("have a problem at one said with the workload it is of where the keyboard rests elsewhere", async () => {
    const wrapper = section();
    const periods = group(group(wrapper, "Umfang 1"), "Zeiträume von Umfang 1");
    await button(periods, "Zeitraum hinzufügen").trigger("click");
    const amount = group(wrapper, "Umfang 1").get("input");
    (amount.element as HTMLElement).focus();

    await wrapper.get("form").trigger("submit");
    await flushPromises();

    expect(document.activeElement).toBe(amount.element);
    expect(wrapper.get(".value-section__status").text()).toBe("Umfang 1, Art des Zeitraums: Dieses Feld braucht einen Wert.");
  });
});
