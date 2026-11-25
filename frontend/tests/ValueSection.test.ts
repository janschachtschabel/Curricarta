import { flushPromises, mount, type VueWrapper } from "@vue/test-utils";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import * as api from "@/api";
import { ApiError, type HeldValues, type HeldWorkload, type NodeRow } from "@/api";
import ValueSection from "@/components/ValueSection.vue";
import { rowsOf, type Row } from "@/documentTree";
import { t } from "@/i18n/de";

import { violations } from "./axe";
import { CV, LVL, form_, node_, noValues, statement_ } from "./treeFixtures";

let shown: VueWrapper | null = null;
let saved = vi.fn();
let reviewed = vi.fn();

const STATED = { origin: CV + "orig_human", review_status: CV + "rev_proposed", revision: 1 };

function workload(id: string, amount: number, changes: Partial<HeldWorkload> = {}): HeldWorkload {
  return {
    id,
    ...STATED,
    amount,
    amount_to: null,
    unit: CV + "unit_lesson",
    workload_kind: null,
    is_recommendation: false,
    minutes_per_unit: null,
    total: false,
    periods: [],
    ...changes,
  };
}

function held(changes: Partial<HeldValues> = {}): HeldValues {
  return {
    level_assignments: [
      { id: "l1", ...STATED, level: LVL + "B1", level_to: null, relation: CV + "lrel_minimum", dimension: null, competence_dimension: LVL + "listening" },
    ],
    time_spans: [{ id: "t1", ...STATED, origin: CV + "orig_model", time_kind: CV + "time_gradeLevel", span_from: 7, span_to: 8, time_relation: null }],
    workloads: [workload("w1", 80, { is_recommendation: true })],
    ...changes,
  };
}

function nodeRow(values: HeldValues, revision = 3): Row {
  return rowsOf([node_("a", { revision, values })]).get("node:a") as Row;
}

/** The node as a set of its values answers it. */
function answered(values: HeldValues, revision: number): NodeRow {
  const { statements, children, ...row } = node_("a", { revision, values });
  void [statements, children];
  return row;
}

function section(row: Row, more: Record<string, unknown> = {}): VueWrapper {
  saved = vi.fn();
  reviewed = vi.fn();
  shown = mount(ValueSection, {
    props: { row, form: form_(), documentId: "d1", editable: true, reviewable: false, closedBy: null, onSaved: saved, onReviewed: reviewed, ...more },
    attachTo: document.body,
  });
  return shown;
}

async function save(wrapper: VueWrapper): Promise<void> {
  (wrapper.get("form button[type=submit]").element as HTMLElement).focus();
  await wrapper.get("form").trigger("submit");
  await flushPromises();
}

/** The entry whose group is named `legend`. */
function entry(wrapper: VueWrapper, legend: string) {
  const found = wrapper.findAll("fieldset").find((one) => one.get("legend").text() === legend);
  if (!found) throw new Error(legend);
  return found;
}

const amount = (wrapper: VueWrapper) => entry(wrapper, "Umfang 1").get("input");

const button = (wrapper: VueWrapper, label: string) => {
  const found = wrapper.findAll("button").find((one) => one.text() === label);
  if (!found) throw new Error(label);
  return found;
};

beforeEach(() => {
  vi.restoreAllMocks();
});

afterEach(() => {
  vi.useRealTimers();
  shown?.unmount();
  shown = null;
  document.body.innerHTML = "";
});

describe("a row's values as they read", () => {
  it("lists each in words under its kind, with who stated it and how far it is reviewed", async () => {
    const wrapper = section(nodeRow(held()), { editable: false });

    expect(wrapper.get("h3").text()).toBe("Niveau, Zeit, Umfang");
    expect(wrapper.findAll("dt").map((term) => term.text())).toEqual(["Niveau", "Zeitraum", "Umfang"]);
    expect(wrapper.findAll(".value-list__words").map((one) => one.text())).toEqual([
      "GER B1, Mindestniveau, Hören",
      "Jahrgangsstufe 7–8",
      "80 Unterrichtsstunden, Richtwert",
    ]);
    expect(wrapper.findAll(".value-list__stated")[1]?.text()).toBe("vom Modell · Vorgeschlagen");
    // nothing to change where the tree only reads
    expect(wrapper.find("form").exists()).toBe(false);
    expect(wrapper.find("button").exists()).toBe(false);
    expect(await violations(wrapper.html())).toEqual([]);
  });

  it("says where nothing is entered yet", async () => {
    const wrapper = section(nodeRow(noValues()), { editable: false });

    expect(wrapper.get(".value-list__none").text()).toBe(t("documents.tree.values.none"));
    expect(await violations(wrapper.html())).toEqual([]);
  });

  it("shows a statement's level and time in its wording beside its values, to copy from", () => {
    const statement = statement_("s1", { fields: { verbatim: "Sie hören.", levelText: "Niveau B1", timeText: "ab Klasse 7" } });
    const row = rowsOf([node_("a", { statements: [statement] })]).get("statement:s1") as Row;
    const wrapper = section(row);

    const texts = wrapper.get(".value-section__texts");
    expect(texts.findAll("dt, dd").map((one) => one.text())).toEqual(["Niveau im Wortlaut", "Niveau B1", "Zeit im Wortlaut", "ab Klasse 7"]);
    // a statement holds levels alone
    expect(wrapper.findAll(".value-section__add").map((add) => add.text())).toEqual(["Niveau hinzufügen"]);
  });

  it("offers each value's review status to the editors, and tells the panel how it went", async () => {
    vi.spyOn(api, "setReview").mockResolvedValue({ revisions: [{ id: "w1", revision: 2 }] });
    const wrapper = section(nodeRow(held()), { reviewable: true });

    const groups = wrapper.findAll("[role=group]");
    expect(groups).toHaveLength(3);
    expect(document.getElementById(groups[2]?.attributes("aria-labelledby") ?? "")?.textContent).toBe(
      "Prüfstand von „80 Unterrichtsstunden, Richtwert“",
    );
    await groups[2]?.findAll("button")[1]?.trigger("click");
    await flushPromises();

    expect(reviewed).toHaveBeenCalledWith({ outcome: "set", status: "confirmed", revision: 2 }, "node:a");
    expect(await violations(wrapper.html())).toEqual([]);
  });

  it("tells a value gone meanwhile as one changed: the tree is read again, its row is not gone", async () => {
    vi.spyOn(api, "setReview").mockRejectedValue(
      new ApiError("server", 409, "stale_revision", "Changed.", { stale: [{ kind: "workload", id: "w1", current: null }] }),
    );
    const wrapper = section(nodeRow(held()), { editable: false, reviewable: true });

    await wrapper.findAll("[role=group]")[2]?.findAll("button")[1]?.trigger("click");
    await flushPromises();

    expect(reviewed).toHaveBeenCalledWith({ outcome: "stale" }, "node:a");
  });
});

describe("a row's values in their form", () => {
  it("adds an entry with the keyboard at its first field, and says a draft is open", async () => {
    const wrapper = section(nodeRow(held()));
    expect(wrapper.emitted("dirty")).toEqual([[false]]);

    await button(wrapper, "Umfang hinzufügen").trigger("click");

    expect(wrapper.findAll("fieldset legend").map((legend) => legend.text())).toContain("Umfang 2");
    expect(document.activeElement?.closest("fieldset")?.querySelector("legend")?.textContent).toBe("Umfang 2");
    expect(document.activeElement?.tagName).toBe("INPUT");
    expect(wrapper.emitted("dirty")?.at(-1)).toEqual([true]);
    expect(await violations(wrapper.html())).toEqual([]);
  });

  it("takes an entry away with the keyboard on the next one, else on the button that adds its kind", async () => {
    const wrapper = section(nodeRow({ ...noValues(), workloads: [workload("w1", 80), workload("w2", 20)] }));

    await button(wrapper, "Umfang 1 entfernen").trigger("click");
    // the next took its place and its name
    expect(document.activeElement?.closest("fieldset")?.querySelector("legend")?.textContent).toBe("Umfang 1");
    expect((document.activeElement as HTMLInputElement).value).toBe("20");
    await button(wrapper, "Umfang 1 entfernen").trigger("click");
    expect(document.activeElement).toBe(button(wrapper, "Umfang hinzufügen").element);
    expect(wrapper.text()).toContain(t("documents.tree.values.none"));
  });

  it("finds nothing to save where nothing changed, nor where an entry added was taken away again", async () => {
    const sent = vi.spyOn(api, "setNodeValues");
    const wrapper = section(nodeRow(held()));
    await button(wrapper, "Niveau hinzufügen").trigger("click");
    await button(wrapper, "Niveau 2 entfernen").trigger("click");

    await save(wrapper);

    expect(sent).not.toHaveBeenCalled();
    expect(wrapper.get(".value-section__status").text()).toBe("Nichts geändert, nichts zu speichern.");
    expect(wrapper.emitted("dirty")?.at(-1)).toEqual([false]);
  });

  it("saves the whole set on the holder's revision, says so, and stands on the holder as it answers", async () => {
    const after = held({ workloads: [workload("w1", 90, { is_recommendation: true })] });
    const sent = vi.spyOn(api, "setNodeValues").mockResolvedValue(answered(after, 4));
    const wrapper = section(nodeRow(held()));
    await amount(wrapper).setValue("90");

    await save(wrapper);

    expect(sent).toHaveBeenCalledWith("a", 3, {
      level_assignments: [{ id: "l1", level: LVL + "B1", level_to: null, relation: CV + "lrel_minimum", dimension: null, competence_dimension: LVL + "listening" }],
      time_spans: [{ id: "t1", time_kind: CV + "time_gradeLevel", span_from: 7, span_to: 8, time_relation: null }],
      workloads: [
        { id: "w1", amount: 90, amount_to: null, unit: CV + "unit_lesson", workload_kind: null, is_recommendation: true, minutes_per_unit: null, total: false, periods: [] },
      ],
    });
    expect(wrapper.get(".value-section__status").text()).toBe("Gespeichert.");
    expect(saved).toHaveBeenCalledTimes(1);
    expect(wrapper.emitted("dirty")?.at(-1)).toEqual([false]);
  });

  it("says a field's problem before anything is asked, the keyboard at the field", async () => {
    const sent = vi.spyOn(api, "setNodeValues");
    const wrapper = section(nodeRow(noValues()));
    await button(wrapper, "Umfang hinzufügen").trigger("click");
    await wrapper.get("fieldset input").setValue("viel");

    await save(wrapper);

    expect(sent).not.toHaveBeenCalled();
    expect(document.activeElement).toBe(wrapper.get("fieldset input").element);
    expect(wrapper.get("fieldset .field__error").text()).toBe(t("documents.tree.values.problems.not_number"));
    expect(await violations(wrapper.html())).toEqual([]);
  });

  it("lets no problem pass to another entry when one before it is taken away", async () => {
    const wrapper = section(nodeRow(noValues()));
    await button(wrapper, "Umfang hinzufügen").trigger("click");
    await button(wrapper, "Umfang hinzufügen").trigger("click");
    await entry(wrapper, "Umfang 2").get("input").setValue("20");
    await entry(wrapper, "Umfang 2").get("select").setValue(CV + "unit_hour");
    await save(wrapper); // the first's amount and unit are missing
    expect(entry(wrapper, "Umfang 1").find(".field__error").exists()).toBe(true);

    await button(wrapper, "Umfang 1 entfernen").trigger("click");

    // the second, the first now, is not given the problems of the one taken away
    expect(wrapper.findAll(".field__error")).toHaveLength(0);
  });

  it("says the server's problem at the field of the entry it names, the keyboard taken there", async () => {
    vi.spyOn(api, "setNodeValues").mockRejectedValue(
      new ApiError("server", 422, "invalid_field", "Not offered.", { field: "workloads[0].unit", problem: "not_offered" }),
    );
    const wrapper = section(nodeRow(held()));
    await amount(wrapper).setValue("90");

    await save(wrapper);

    const unit = entry(wrapper, "Umfang 1").get("select");
    expect(document.activeElement).toBe(unit.element);
    expect(unit.attributes("aria-invalid")).toBe("true");
    expect(document.getElementById(unit.attributes("aria-describedby") ?? "")?.textContent?.trim()).toBe(
      t("documents.tree.problems.not_offered"),
    );
  });

  it("says a problem of a part the form does not show above it, the draft kept", async () => {
    vi.spyOn(api, "setNodeValues").mockRejectedValue(
      new ApiError("server", 422, "invalid_field", "Gone.", { field: "workloads[0].id", problem: "unknown_value" }),
    );
    const wrapper = section(nodeRow(held()));
    await amount(wrapper).setValue("90");

    await save(wrapper);

    expect(wrapper.get(".value-section__problem[role=alert]").text()).toContain(t("documents.tree.problems.unknown_value"));
    expect((amount(wrapper).element as HTMLInputElement).value).toBe("90");
  });

  it("lays a set that met another beside it, both as they read, and saves the choice on the stored revision", async () => {
    const theirs = held({ workloads: [workload("w1", 70, { is_recommendation: true })] });
    const sent = vi
      .spyOn(api, "setNodeValues")
      .mockRejectedValueOnce(new ApiError("server", 409, "stale_revision", "Changed.", { current: answered(theirs, 5) }))
      .mockResolvedValueOnce(answered(held({ workloads: [workload("w1", 90, { is_recommendation: true })] }), 6));
    const wrapper = section(nodeRow(held()));
    await amount(wrapper).setValue("90");

    await save(wrapper);

    const panel = wrapper.get(".value-conflict");
    expect(document.activeElement).toBe(panel.element);
    expect(panel.findAll("dd").map((one) => one.text())).toEqual(["90 Unterrichtsstunden, Richtwert", "70 Unterrichtsstunden, Richtwert"]);
    expect(await violations(wrapper.html())).toEqual([]);
    await save(wrapper); // undecided: not saved, said, the keyboard back to the choice
    expect(sent).toHaveBeenCalledTimes(1);
    expect(wrapper.get(".value-section__status").text()).toBe(t("documents.tree.conflict.undecided"));
    await button(wrapper, t("documents.tree.conflict.keep")).trigger("click");
    await save(wrapper);

    expect(sent.mock.calls[1]?.[1]).toBe(5);
    expect(sent.mock.calls[1]?.[2].workloads[0]?.amount).toBe(90);
    expect(wrapper.find(".value-conflict").exists()).toBe(false);
  });

  it("takes the stored set of a kind both changed where the user chooses it", async () => {
    const theirs = held({ workloads: [workload("w1", 70)] });
    vi.spyOn(api, "setNodeValues").mockRejectedValueOnce(
      new ApiError("server", 409, "stale_revision", "Changed.", { current: answered(theirs, 5) }),
    );
    const wrapper = section(nodeRow(held()));
    await amount(wrapper).setValue("90");
    await save(wrapper);

    await button(wrapper, t("documents.tree.conflict.take")).trigger("click");

    expect((amount(wrapper).element as HTMLInputElement).value).toBe("70");
    // what the user has now is what is stored: nothing left to save
    expect(wrapper.emitted("dirty")?.at(-1)).toEqual([false]);
  });

  it("says a failure above the form, which stays to try again", async () => {
    vi.spyOn(api, "setNodeValues").mockRejectedValue(new ApiError("network", 0));
    const wrapper = section(nodeRow(held()));
    await amount(wrapper).setValue("90");

    await save(wrapper);

    expect(wrapper.get(".value-section__problem[role=alert]").text()).toContain(t("documents.tree.values.saveFailed"));
    expect((amount(wrapper).element as HTMLInputElement).value).toBe("90");
  });

  it("tells the panel when the tree closed on a save, and keeps the draft to copy without a form", async () => {
    vi.spyOn(api, "setNodeValues").mockRejectedValue(new ApiError("server", 409, "frozen", "Frozen."));
    const wrapper = section(nodeRow(held()));
    await amount(wrapper).setValue("90");

    await save(wrapper);

    expect(wrapper.emitted("closed")).toEqual([["frozen"]]);
    expect(wrapper.find("form").exists()).toBe(false);
    expect(wrapper.get(".value-section__closed [role=alert]").text()).toBe(t("refusals.frozen"));
    expect(wrapper.get(".value-section__closed").text()).toContain("90 Unterrichtsstunden, Richtwert");
    expect(document.activeElement).toBe(wrapper.get(".value-section__closed").element);
    expect(await violations(wrapper.html())).toEqual([]);
  });

  it("keeps an open draft to copy where the tree, read anew, closed under it", async () => {
    const wrapper = section(nodeRow(held()));
    await amount(wrapper).setValue("90");

    await wrapper.setProps({ closedBy: "job_open" });

    expect(wrapper.find("form").exists()).toBe(false);
    expect(wrapper.get(".value-section__closed [role=alert]").text()).toBe(t("refusals.job_open"));
  });

  it("says when the row is gone", async () => {
    vi.spyOn(api, "setNodeValues").mockRejectedValue(new ApiError("server", 404, "no_node", "No such node."));
    const wrapper = section(nodeRow(held()));
    await amount(wrapper).setValue("90");

    await save(wrapper);

    expect(wrapper.emitted("gone")).toHaveLength(1);
  });

  it("goes on from the revision a review left, read anew, without meeting it as another's change", async () => {
    const sent = vi.spyOn(api, "setNodeValues").mockResolvedValue(answered(held(), 9));
    const wrapper = section(nodeRow(held(), 3));
    await amount(wrapper).setValue("90");

    // a value reviewed: the holder's revision moved, its values' review status with it
    const reviewedValues = held({ workloads: [workload("w1", 80, { is_recommendation: true, review_status: CV + "rev_confirmed", revision: 2 })] });
    await wrapper.setProps({ row: nodeRow(reviewedValues, 4) });
    await save(wrapper);

    expect(sent.mock.calls[0]?.[1]).toBe(4);
    expect(sent.mock.calls[0]?.[2].workloads[0]?.amount).toBe(90);
  });

  it("takes the row read anew where nothing was changed, the keyboard staying on its control", async () => {
    const wrapper = section(nodeRow(held()));
    const box = amount(wrapper);
    (box.element as HTMLElement).focus();

    await wrapper.setProps({ row: nodeRow(held({ workloads: [workload("w1", 85, { is_recommendation: true })] }), 4) });

    expect((amount(wrapper).element as HTMLInputElement).value).toBe("85");
    expect(document.activeElement).toBe(amount(wrapper).element);
  });
});
