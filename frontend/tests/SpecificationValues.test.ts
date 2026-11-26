// A specification's own values and its applicability contexts, edited on the document page (plan M3a, join of G
// and H): G's values' form with the specification as holder, its contexts one more kind of its set.
import { flushPromises, mount, type DOMWrapper, type VueWrapper } from "@vue/test-utils";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import * as api from "@/api";
import { ApiError, type Specification } from "@/api";
import DocumentScope from "@/components/DocumentScope.vue";
import { t } from "@/i18n/de";
import { clearSession, setSession } from "@/session";

import { violations } from "./axe";
import { SCOPE_FORM, specificationOf, specificationsOf, valuedSpecification } from "./scopeFixtures";

const CV = "https://w3id.org/wlo/curriculum/vocab#";
const CONTEXT_WORDS = "Schulbildung · formal · Einrichtung: Gymnasium · Jahrgangsstufe 5–6";

// a part of the page found: `get` leaves out `exists`
type Found<E extends Element = Element> = Omit<DOMWrapper<E>, "exists">;

let shown: VueWrapper | null = null;

async function open(specifications = [valuedSpecification()], more = {}): Promise<VueWrapper> {
  vi.mocked(api.getSpecifications).mockResolvedValue(specificationsOf({ specifications, ...more }));
  shown = mount(DocumentScope, { props: { documentId: "d1", sector: "school" }, attachTo: document.body });
  await flushPromises();
  return shown;
}

/** The values' section of the specification `title`. */
function values(wrapper: VueWrapper, title = "Physik"): Found {
  const heading = t("documents.page.scope.valuesHeading", { title });
  const found = wrapper.findAll(".value-section").find((one) => one.get("h4").text() === heading);
  if (!found) throw new Error(heading);
  return found;
}

function group(within: Found, legend: string): Found {
  const found = within.findAll("fieldset").find((one) => one.get("legend").text() === legend);
  if (!found) throw new Error(legend);
  return found;
}

function button(within: Found, label: string): Found {
  const found = within.findAll("button").find((one) => one.text() === label);
  if (!found) throw new Error(label);
  return found;
}

/** The control labelled `label` within `within`. */
function control(within: Found, label: string): Found<HTMLInputElement> {
  const found = within.findAll("label").find((one) => one.text().replace(/\s+/g, " ").trim().startsWith(label));
  if (!found) throw new Error(label);
  return within.get<HTMLInputElement>(`[id="${found.attributes("for")}"]`);
}

async function save(section: Found): Promise<void> {
  (section.get("form button[type=submit]").element as HTMLElement).focus();
  await section.get("form").trigger("submit");
  await flushPromises();
}

beforeEach(() => {
  vi.restoreAllMocks();
  vi.spyOn(api, "getSpecifications").mockResolvedValue(specificationsOf());
  vi.spyOn(api, "getForm").mockResolvedValue(SCOPE_FORM);
});

afterEach(() => {
  shown?.unmount();
  shown = null;
  document.body.innerHTML = "";
  clearSession();
});

describe("a specification's values and contexts in their form", () => {
  it("shows its own values and each context as entries, the context's values within it", async () => {
    const wrapper = await open();

    const section = values(wrapper);
    const context = group(section, "Geltungskontext 1");
    expect(control(context, "Bildungsbereich").element.value).toBe(CV + "sec_school");
    expect(control(context, "Einrichtung").element.value).toBe("Gymnasium");
    expect(control(group(context, "Zeitraum 1"), "Von").element.value).toBe("5");
    // a specification holds every kind, and contexts
    expect(section.findAll(".value-section__add").map((add) => add.text())).toEqual([
      "Niveau hinzufügen",
      "Zeitraum hinzufügen",
      "Umfang hinzufügen",
      "Niveau hinzufügen",
      "Zeitraum hinzufügen",
      "Geltungskontext hinzufügen",
    ]);
    expect(await violations(wrapper.html())).toEqual([]);
  });

  it("sends its values and contexts whole, on its revision, a context's values with it", async () => {
    const sent = vi.spyOn(api, "setSpecificationValues").mockResolvedValue(valuedSpecification());
    const wrapper = await open();
    const section = values(wrapper);

    await button(section, "Geltungskontext hinzufügen").trigger("click");
    const added = group(section, "Geltungskontext 2");
    expect(document.activeElement).toBe(control(added, "Bildungsbereich").element);
    await control(added, "Bildungsbereich").setValue(CV + "sec_school");
    await control(added, "Zielgruppe").setValue("Erwachsene");
    await button(added, "Niveau hinzufügen").trigger("click");
    await control(group(added, "Niveau 1"), "Niveau").setValue("https://w3id.org/wlo/curriculum/level/EQF-4");
    await save(section);

    expect(sent).toHaveBeenCalledWith("s1", 1, {
      level_assignments: [{ id: "l1", level: "https://w3id.org/wlo/curriculum/level/EQF-4" }],
      time_spans: [],
      workloads: [{ id: "w1", amount: 80, unit: CV + "unit_lesson", periods: [] }],
      contexts: [
        {
          id: "c1", sector: CV + "sec_school", formality: CV + "form_formal", institution_text: "Gymnasium", target_group_text: null,
          level_assignments: [],
          time_spans: [{ id: "t1", time_kind: CV + "time_gradeLevel", span_from: 5, span_to: 6 }],
        },
        {
          id: null, sector: CV + "sec_school", formality: null, institution_text: null, target_group_text: "Erwachsene",
          level_assignments: [{ id: null, level: "https://w3id.org/wlo/curriculum/level/EQF-4" }],
          time_spans: [],
        },
      ],
    });
    expect(section.get(".value-section__status").text()).toBe(t("documents.tree.form.saved"));
    // the list read again, as it stands now
    expect(api.getSpecifications).toHaveBeenCalledTimes(2);
  });

  it("takes a context away with its values, the keyboard on the next", async () => {
    const sent = vi.spyOn(api, "setSpecificationValues").mockResolvedValue(specificationOf());
    const wrapper = await open();
    const section = values(wrapper);

    await button(section, "Geltungskontext 1 entfernen").trigger("click");
    expect(document.activeElement).toBe(button(section, "Geltungskontext hinzufügen").element);
    await save(section);

    expect(sent.mock.calls[0]?.[2].contexts).toEqual([]);
  });
});

describe("a specification's values beside its title and field", () => {
  it("go on from the revision a save of its title left", async () => {
    vi.spyOn(api, "editSpecification").mockResolvedValue({ ...valuedSpecification(), title: "Physik", field_text: "Optik", revision: 2 });
    const sent = vi.spyOn(api, "setSpecificationValues").mockResolvedValue(valuedSpecification());
    const wrapper = await open();
    await control(values(wrapper), "Einrichtung").setValue("Realschule");

    const title = wrapper.get(".specification-form");
    await control(title, "Fach").setValue("Optik");
    await title.trigger("submit");
    await flushPromises();
    await save(values(wrapper));

    expect(sent.mock.calls[0]?.[1]).toBe(2);
    // the draft kept through it
    expect(sent.mock.calls[0]?.[2].contexts[0]?.institution_text).toBe("Realschule");
  });

  it("offer a context's levels by the rules of a context, the specification's own by its class's", async () => {
    const form = structuredClone(SCOPE_FORM);
    form.values.level_assignments.rules = [{ holder: "applicability_context", dimensions: [CV + "dim_qualification"], unless: null }];
    vi.mocked(api.getForm).mockResolvedValue(form);
    const wrapper = await open();
    const section = values(wrapper);
    await button(section, "Niveau hinzufügen").trigger("click");
    const context = group(section, "Geltungskontext 1");
    await button(context, "Niveau hinzufügen").trigger("click");

    const offered = (within: Found) => control(within, "Niveau").findAll("option").map((option) => option.text());
    expect(offered(group(context, "Niveau 1"))).not.toContain("EQR 4");
    expect(offered(section.findAll("fieldset").find((one) => one.get("legend").text() === "Niveau 1") as Found)).toContain("EQR 4");
  });
});

describe("a refusal of a specification's set", () => {
  it("keeps the draft to copy where the document was frozen meanwhile, and reads the list again", async () => {
    vi.spyOn(api, "setSpecificationValues").mockRejectedValue(new ApiError("server", 409, "frozen", "Frozen."));
    const wrapper = await open();
    const section = values(wrapper);
    await control(group(section, "Geltungskontext 1"), "Einrichtung").setValue("Realschule");
    vi.mocked(api.getSpecifications).mockResolvedValue(
      specificationsOf({ specifications: [valuedSpecification()], editable: false, closed: "frozen" }),
    );

    await save(section);

    const kept = values(wrapper);
    expect(kept.find("form").exists()).toBe(false);
    expect(kept.get("[role=alert]").text()).toContain(t("refusals.frozen"));
    expect(kept.text()).toContain("Einrichtung: Realschule");
    expect(api.getSpecifications).toHaveBeenCalledTimes(2);
  });

  async function refused(field: string, problem = "not_offered"): Promise<Found> {
    vi.spyOn(api, "setSpecificationValues").mockRejectedValue(new ApiError("server", 422, "invalid_field", "No.", { field, problem }));
    const wrapper = await open();
    const section = values(wrapper);
    await control(group(section, "Geltungskontext 1"), "Einrichtung").setValue("Realschule");
    await save(section);
    return section;
  }

  it("stands at a context's field, the keyboard taken there", async () => {
    const section = await refused("contexts[0].sector");

    const sector = control(group(section, "Geltungskontext 1"), "Bildungsbereich");
    expect(sector.attributes("aria-invalid")).toBe("true");
    expect(document.activeElement).toBe(sector.element);
  });

  it("stands at the field of a context's value", async () => {
    const section = await refused("contexts[0].time_spans[0].time_kind");

    const kind = control(group(group(section, "Geltungskontext 1"), "Zeitraum 1"), "Art des Zeitraums");
    expect(kind.attributes("aria-invalid")).toBe("true");
    expect(document.activeElement).toBe(kind.element);
  });

  it("stands at a context's kind where the store refused a value of it, by the button that adds one", async () => {
    const section = await refused("contexts[0].time_spans", "refused");

    const add = button(group(section, "Geltungskontext 1"), "Zeitraum hinzufügen");
    expect(document.activeElement).toBe(add.element);
    expect(document.getElementById(add.attributes("aria-describedby") ?? "")?.textContent?.trim()).toBe(
      t("documents.tree.problems.refused"),
    );
    expect(section.find(".value-section__problem").exists()).toBe(false);
  });

  it("stands at the context where the store refused it, named and taking the keyboard", async () => {
    const section = await refused("contexts[0]", "refused");

    const problem = group(section, "Geltungskontext 1").get(".context-item__problem");
    // the context refused, not a value
    expect(problem.text()).toBe(`Geltungskontext 1: ${t("documents.tree.values.contextRefused")}`);
    expect(document.activeElement).toBe(problem.element);
    // heard again whenever the keyboard comes back into the context
    expect(group(section, "Geltungskontext 1").attributes("aria-describedby")).toBe(problem.attributes("id"));
  });

  it("lays the set beside the specification as another stored it meanwhile", async () => {
    const theirs: Specification = { ...valuedSpecification(), revision: 2, contexts: [] };
    vi.spyOn(api, "setSpecificationValues").mockRejectedValue(new ApiError("server", 409, "stale_revision", "Stale.", { current: theirs }));
    const wrapper = await open();
    const section = values(wrapper);
    await control(group(section, "Geltungskontext 1"), "Einrichtung").setValue("Realschule");

    await save(section);

    const panel = section.get(".value-conflict");
    expect(document.activeElement).toBe(panel.element);
    expect(panel.get(".value-conflict__kind").text()).toBe("Geltungskontext");
    expect(panel.text()).toContain("Schulbildung · formal · Einrichtung: Realschule · Jahrgangsstufe 5–6");
    await button(panel, t("documents.tree.conflict.keep")).trigger("click");
    vi.mocked(api.setSpecificationValues).mockResolvedValue(theirs);
    await save(section);
    // the user's kept, sent again on the revision the specification stands at
    const [, revision, set] = vi.mocked(api.setSpecificationValues).mock.calls[1] ?? [];
    expect(revision).toBe(2);
    expect(set?.contexts.map((one) => one.institution_text)).toEqual(["Realschule"]);
  });
});

describe("a specification's values to read only", () => {
  it("offer no form where the document is frozen", async () => {
    const wrapper = await open([valuedSpecification()], { editable: false, closed: "frozen" });

    expect(wrapper.find(".value-section").exists()).toBe(false);
    expect(wrapper.get("[data-test=scope-context]").text()).toContain("Gymnasium");
  });

  it("keep a draft to copy where a job closed the document under it", async () => {
    const wrapper = await open();
    await control(group(values(wrapper), "Geltungskontext 1"), "Einrichtung").setValue("Realschule");

    vi.mocked(api.getSpecifications).mockResolvedValue(
      specificationsOf({ specifications: [valuedSpecification()], editable: false, closed: "job_open" }),
    );
    await wrapper.setProps({ refresh: 1 });
    await flushPromises();

    const section = values(wrapper);
    expect(section.find("form").exists()).toBe(false);
    expect(section.get("[role=alert]").text()).toContain(t("refusals.job_open"));
    expect(section.text()).toContain("Einrichtung: Realschule");
  });
});

describe("the review of a specification's contexts and values", () => {
  it("sets a context's status by its table at its revision, says so in words naming it, and reads the list again", async () => {
    setSession({ id: "a1", name: "Redaktion", roles: ["redaktion"] });
    const reviewed = vi.spyOn(api, "setReview").mockResolvedValue({ revisions: [{ id: "c1", revision: 2 }] });
    const wrapper = await open();
    const section = values(wrapper);

    const toggles = section.findAll("[role=group]").find((one) => one.text().startsWith(`Prüfstand von „${CONTEXT_WORDS}“`));
    if (!toggles) throw new Error("the context's toggles");
    await button(toggles, "Bestätigt").trigger("click");
    await flushPromises();

    expect(reviewed).toHaveBeenCalledWith("d1", "confirmed", [{ kind: "applicability_context", id: "c1", revision: 1 }]);
    expect(wrapper.get(".scope__status").text()).toBe(`Prüfstand von „${CONTEXT_WORDS}“: Bestätigt.`);
    expect(api.getSpecifications).toHaveBeenCalledTimes(2);
  });

  it("is not offered to an owner who is no editor", async () => {
    setSession({ id: "a1", name: "Lehrkraft", roles: ["nutzer"] });
    const wrapper = await open();

    expect(values(wrapper).find("[role=group]").exists()).toBe(false);
  });
});
