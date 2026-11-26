import { flushPromises, mount, type VueWrapper } from "@vue/test-utils";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import * as api from "@/api";
import { ApiError } from "@/api";
import DocumentAssessments from "@/components/DocumentAssessments.vue";
import { t } from "@/i18n/de";

import { ASSESSMENT_FORM, CV, LVL, assessmentOf, assessmentsOf, examWithPart } from "./assessmentFixtures";
import { violations } from "./axe";

let shown: VueWrapper | null = null;

async function open(): Promise<VueWrapper> {
  shown = mount(DocumentAssessments, { props: { documentId: "d1", sector: "vocational" }, attachTo: document.body });
  await flushPromises();
  return shown;
}

const control = (wrapper: VueWrapper, label: string) => {
  const found = wrapper.findAll("label").find((one) => one.text() === label);
  if (!found) throw new Error(label);
  return wrapper.get<HTMLInputElement | HTMLSelectElement>(`#${found.attributes("for")}`);
};
const button = (wrapper: VueWrapper, name: string) => {
  const found = wrapper.findAll("button").find((one) => one.attributes("aria-label") === name || one.text() === name);
  if (!found) throw new Error(name);
  return found;
};
const fields = t("documents.page.assessments.fields.parent_id");

beforeEach(() => {
  vi.restoreAllMocks();
  vi.spyOn(api, "getAssessments").mockResolvedValue(assessmentsOf({ assessments: examWithPart() }));
  vi.spyOn(api, "getForm").mockResolvedValue(ASSESSMENT_FORM);
});

afterEach(() => {
  shown?.unmount();
  shown = null;
  document.body.innerHTML = "";
});

describe("a document's assessments on its page", () => {
  it("lists each with its parts under it, what it states in words", async () => {
    const wrapper = await open();

    expect(wrapper.get("h2").text()).toBe(t("documents.page.assessments.heading"));
    const [exam] = wrapper.findAll(".assessments__list > .assessment");
    expect(exam.get("h3").text()).toBe("Abschlussprüfung Vorgeschlagen");
    const part = exam.get(".assessment__parts > .assessment");
    expect(exam.get(".assessment__parts").attributes("aria-label")).toBe("Teile von „Abschlussprüfung“");
    const said = exam.get(".assessment__body .facts").text();
    for (const words of ["Prüfung", "Physik", "240 Minuten", "ja"]) expect(said).toContain(words);
    const partSaid = part.get(".facts").text();
    for (const words of ["Prüfungsteil", "Abschlussprüfung", "37,5 %", "LF 1 Optik", "Note 2 (Vorgeschlagen)"]) {
      expect(partSaid).toContain(words);
    }
    expect(partSaid).toContain(t("documents.page.assessments.none")); // no duration, no grading said
    expect(await violations(wrapper.element)).toEqual([]);
  });

  it("says that a document has none yet, and to an editor that one may be added", async () => {
    vi.mocked(api.getAssessments).mockResolvedValue(assessmentsOf());
    const wrapper = await open();

    expect(wrapper.text()).toContain(t("documents.page.assessments.noneTitle"));
    expect(wrapper.text()).toContain(t("documents.page.assessments.noneBodyEditable"));
    expect(button(wrapper, t("documents.page.assessments.add")).exists()).toBe(true);
  });

  it("is to read only where the document is frozen: no way to change it is offered", async () => {
    vi.mocked(api.getAssessments).mockResolvedValue(assessmentsOf({ assessments: examWithPart(), editable: false, closed: "frozen" }));
    const wrapper = await open();

    expect(wrapper.get("[data-test=assessments-read-only]").text()).toBe(t("documents.page.assessments.closed.frozen"));
    expect(wrapper.findAll("button")).toHaveLength(0);
    expect(wrapper.find("form").exists()).toBe(false);
  });

  it("shows it loading, then a failure with a retry that reads again; content no longer the reader's said apart", async () => {
    vi.mocked(api.getAssessments).mockRejectedValueOnce(new ApiError("server", 500, "internal", "boom"));
    shown = mount(DocumentAssessments, { props: { documentId: "d1", sector: "vocational" }, attachTo: document.body });
    expect(shown.text()).toContain(t("documents.page.assessments.loading"));
    await flushPromises();

    expect(shown.get("[role=alert]").text()).toContain(t("documents.page.assessments.loadFailed"));
    await shown.get("[role=alert] button").trigger("click");
    await flushPromises();
    expect(shown.find("[role=alert]").exists()).toBe(false);
    expect(shown.findAll(".assessment")).toHaveLength(2);

    shown.unmount();
    vi.mocked(api.getAssessments).mockRejectedValue(new ApiError("server", 403, "file_hidden", "hidden"));
    const hidden = await open();
    expect(hidden.text()).toContain(t("refusals.file_hidden"));
  });
});

describe("an assessment the editors write", () => {
  it("is added with what it states, its problems said at their fields first", async () => {
    vi.mocked(api.getAssessments).mockResolvedValue(assessmentsOf());
    const added = vi.spyOn(api, "addAssessment").mockResolvedValue(assessmentOf());
    const dirty: boolean[] = [];
    const wrapper = await open();
    await button(wrapper, t("documents.page.assessments.add")).trigger("click");

    await wrapper.get("form").trigger("submit");
    await flushPromises();
    expect(control(wrapper, fields).attributes("aria-invalid")).toBe("true");
    expect(document.activeElement?.id).toBe(control(wrapper, fields).attributes("id"));
    expect(added).not.toHaveBeenCalled();

    await control(wrapper, fields).setValue("s1");
    await control(wrapper, t("documents.page.assessments.fields.assessment_kind")).setValue(CV + "ak_exam");
    await control(wrapper, t("documents.page.assessments.fields.label")).setValue("Abschlussprüfung");
    await control(wrapper, t("documents.page.assessments.fields.duration_minutes")).setValue("240");
    await control(wrapper, t("documents.page.assessments.fields.weight_percent")).setValue("12,5");
    await control(wrapper, t("documents.page.assessments.fields.graded")).setValue("yes");
    await wrapper.findAll<HTMLInputElement>("input[type=checkbox]")[0].setValue(true);
    dirty.push(...(wrapper.emitted("dirty") ?? []).map(([open]) => open as boolean));
    vi.mocked(api.getAssessments).mockResolvedValue(assessmentsOf({ assessments: [assessmentOf()] }));
    await wrapper.get("form").trigger("submit");
    await flushPromises();

    expect(added).toHaveBeenCalledWith("d1", {
      parent_id: "s1", assessment_kind: CV + "ak_exam", label: "Abschlussprüfung", duration_minutes: 240,
      weight_percent: 12.5, graded: true, targets: ["n1"],
    });
    expect(dirty).toContain(true);
    expect(wrapper.emitted("dirty")?.at(-1)).toEqual([false]);
    expect(wrapper.find("form.assessment-form").exists()).toBe(false);
    expect(wrapper.get(".assessments__status").text()).toBe(t("documents.page.assessments.added"));
    expect(wrapper.findAll(".assessment")).toHaveLength(1);
  });

  it("refuses a duration that is no whole number and a weight over 100 before it asks", async () => {
    const added = vi.spyOn(api, "addAssessment");
    const wrapper = await open();
    await button(wrapper, t("documents.page.assessments.add")).trigger("click");
    await control(wrapper, fields).setValue("s1");
    await control(wrapper, t("documents.page.assessments.fields.assessment_kind")).setValue(CV + "ak_exam");
    await control(wrapper, t("documents.page.assessments.fields.duration_minutes")).setValue("1,5");
    await control(wrapper, t("documents.page.assessments.fields.weight_percent")).setValue("100,5");

    await wrapper.get("form.assessment-form").trigger("submit");
    await flushPromises();

    expect(wrapper.text()).toContain(t("documents.page.assessments.problems.not_whole"));
    expect(wrapper.text()).toContain(t("documents.page.assessments.problems.not_weight"));
    expect(added).not.toHaveBeenCalled();
    expect(await violations(wrapper.element)).toEqual([]);
  });

  it("is edited by what changed alone; a parent among its own parts is refused at that field", async () => {
    const edited = vi.spyOn(api, "editAssessment")
      .mockRejectedValueOnce(new ApiError("server", 422, "invalid_field", "No.", { field: "parent_id", problem: "cycle" }))
      .mockResolvedValue(assessmentOf({ weight_percent: 40, revision: 2 }));
    const wrapper = await open();
    await button(wrapper, t("documents.page.assessments.editNamed", { title: "Abschlussprüfung" })).trigger("click");
    const parents = control(wrapper, fields);
    // itself and its part are no parent it may take; offered they are refused at the field
    expect(parents.findAll("option").map((option) => option.attributes("value"))).toEqual(["", "s1", "n1", "n2"]);

    await control(wrapper, t("documents.page.assessments.fields.weight_percent")).setValue("40");
    await wrapper.get("form.assessment-form").trigger("submit");
    await flushPromises();
    expect(edited).toHaveBeenLastCalledWith("a1", 1, { weight_percent: 40 });
    expect(wrapper.get("form.assessment-form").text()).toContain(t("documents.tree.problems.cycle"));

    await wrapper.get("form.assessment-form").trigger("submit");
    await flushPromises();
    expect(wrapper.find("form.assessment-form").exists()).toBe(false);
    expect(wrapper.get(".assessments__status").text()).toBe(t("documents.page.assessments.saved"));
  });

  it("changed meanwhile, shows it as it stands and keeps the entry for a second try", async () => {
    const current = assessmentOf({ revision: 3, label: "Neu" });
    const edited = vi.spyOn(api, "editAssessment")
      .mockRejectedValueOnce(new ApiError("server", 409, "stale_revision", "Changed.", { current }))
      .mockResolvedValue(assessmentOf({ revision: 4 }));
    const wrapper = await open();
    await button(wrapper, t("documents.page.assessments.editNamed", { title: "Abschlussprüfung" })).trigger("click");
    await control(wrapper, t("documents.page.assessments.fields.duration_minutes")).setValue("180");

    await wrapper.get("form.assessment-form").trigger("submit");
    await flushPromises();
    expect(wrapper.get("form.assessment-form [role=alert]").text()).toContain(t("documents.page.assessments.changedMeanwhile"));
    expect(control(wrapper, t("documents.page.assessments.fields.duration_minutes")).element.value).toBe("180");

    await wrapper.get("form.assessment-form").trigger("submit");
    await flushPromises();
    expect(edited).toHaveBeenLastCalledWith("a1", 3, { duration_minutes: 180 });
  });

  it("is taken away with its parts once that is confirmed", async () => {
    const dropped = vi.spyOn(api, "dropAssessment").mockResolvedValue({ assessments: 2 });
    const wrapper = await open();
    await button(wrapper, t("documents.page.assessments.dropNamed", { title: "Abschlussprüfung" })).trigger("click");

    const dialog = document.querySelector("[role=dialog]");
    expect(dialog?.textContent).toContain("„Abschlussprüfung“ geht mit 1 Teil");
    vi.mocked(api.getAssessments).mockResolvedValue(assessmentsOf());
    const confirm = [...(dialog?.querySelectorAll("button") ?? [])].find((one) => one.textContent?.trim() === t("documents.page.assessments.dropConfirm"));
    confirm?.click();
    await flushPromises();

    expect(dropped).toHaveBeenCalledWith("a1", 1);
    expect(wrapper.get(".assessments__status").text()).toBe(t("documents.page.assessments.dropped", { title: "Abschlussprüfung" }));
    expect(wrapper.text()).toContain(t("documents.page.assessments.noneTitle"));
  });

  it("has the levels at it set in the values' form, a grade among them", async () => {
    const set = vi.spyOn(api, "setAssessmentValues").mockResolvedValue(assessmentOf({ revision: 2 }));
    const wrapper = await open();

    const [section] = wrapper.findAll(".value-section");
    expect(section.get("h4").text()).toBe(t("documents.page.assessments.levelsHeading", { title: "Abschlussprüfung" }));
    await section.get(".value-section__add").trigger("click");
    const level = section.get<HTMLSelectElement>("select");
    await level.setValue(LVL + "grade-2");
    await section.get("form").trigger("submit");
    await flushPromises();

    expect(set).toHaveBeenCalledWith("a1", 1, expect.objectContaining({
      level_assignments: [expect.objectContaining({ level: LVL + "grade-2" })], time_spans: [], workloads: [],
    }));
  });
});
