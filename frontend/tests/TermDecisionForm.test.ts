import { flushPromises, mount, type VueWrapper } from "@vue/test-utils";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import * as api from "@/api";
import { ApiError, type FormValue, type HeldCue, type TermDecision } from "@/api";
import TermDecisionForm from "@/components/TermDecisionForm.vue";
import { t } from "@/i18n/de";
import type { Targets } from "@/lexiconTargets";
import { refusalText } from "@/refusals";

import { violations } from "./axe";
import { CV, SCHOOL, heldCue, nodeType, termDecision } from "./lexiconFixtures";

const AREA = nodeType("Inhaltsbereich", [CV + "fn_area"]);
const FIELD = nodeType("Lernfeld", [CV + "fn_unit"]);
const FRAME = nodeType("Rahmenteil", []);
let shown: VueWrapper | null = null;
let targets = vi.fn<Targets>();

interface Options {
  term?: string;
  held?: HeldCue[];
  before?: TermDecision | null;
}

function form({ term = "Lernbereich", held = [], before = null }: Options = {}): VueWrapper {
  shown = mount(TermDecisionForm, {
    props: { term: { sector: "school", regions: ["DE-NW"], term }, functions: [CV + "fn_unit"], held, before, targets },
    attachTo: document.body,
  });
  return shown;
}

const control = <T extends HTMLElement = HTMLInputElement>(wrapper: VueWrapper, label: string) => {
  const found = wrapper.findAll("label").find((one) => one.text() === label);
  if (!found) throw new Error(label);
  return found.attributes("for") ? wrapper.get<T>(`#${found.attributes("for")}`) : found.get<T>("input");
};
const submit = (wrapper: VueWrapper) => wrapper.get("button[type=submit]");

// the button pressed: the keyboard on it as the form is sent
async function press(wrapper: VueWrapper): Promise<void> {
  (submit(wrapper).element as HTMLButtonElement).focus();
  await wrapper.get("form").trigger("submit");
  await flushPromises();
}

async function newCue(wrapper: VueWrapper, target = FIELD.iri, role = "alt"): Promise<void> {
  await control(wrapper, t("lexicon.termForm.cue")).setValue(true);
  await flushPromises();
  await control<HTMLSelectElement>(wrapper, t("lexicon.termForm.target")).setValue(target);
  await control<HTMLSelectElement>(wrapper, t("lexicon.termForm.role")).setValue(role);
}

function errorAt(wrapper: VueWrapper, input: { attributes: (name: string) => string | undefined; element: Element }) {
  const error = wrapper.get(`#${input.attributes("id")}-error`);
  expect(input.attributes("aria-invalid")).toBe("true");
  expect(input.attributes("aria-describedby")).toContain(error.attributes("id"));
  expect(document.activeElement).toBe(input.element);
  return error.text();
}

beforeEach(() => {
  vi.restoreAllMocks();
  targets = vi.fn<Targets>(() => Promise.resolve<FormValue[]>([AREA, FIELD, FRAME]));
});

afterEach(() => {
  shown?.unmount();
  shown = null;
  document.body.innerHTML = "";
});

describe("the decision on a new term", () => {
  it("offers a new cue, a term peculiar to its document, or a misread one", () => {
    const wrapper = form();

    expect(wrapper.findAll("input[type=radio]").map((one) => one.element.getAttribute("value"))).toEqual(["cue", "document", "error"]);
    expect(wrapper.findAll("select")).toHaveLength(0);
    expect(targets).not.toHaveBeenCalled(); // read only once a new cue is asked for
  });

  it("offers no new cue of a word under four signs, and says why", () => {
    const wrapper = form({ term: "LF" });

    const cue = control(wrapper, t("lexicon.termForm.cue"));
    expect(cue.attributes("disabled")).toBeDefined();
    // the server's refusal in the same words
    expect(wrapper.get(`#${cue.attributes("aria-describedby")}`).text()).toBe(refusalText("too_short"));
  });

  it("takes the keyboard to the first choice it offers where something is missing", async () => {
    const wrapper = form({ term: "LF" });

    await press(wrapper);

    expect(errorAt(wrapper, control(wrapper, t("lexicon.termForm.document")))).toContain(t("lexicon.termForm.chooseDecision"));
  });

  it("says the problem where the keyboard stays, Enter pressed in another field", async () => {
    const wrapper = form();
    await control(wrapper, t("lexicon.termForm.cue")).setValue(true);
    await flushPromises();
    const role = control<HTMLSelectElement>(wrapper, t("lexicon.termForm.role"));
    await role.setValue("alt");

    (role.element as HTMLSelectElement).focus();
    await wrapper.get("form").trigger("submit");
    await flushPromises();

    expect(document.activeElement).toBe(role.element);
    expect(wrapper.find("[role=status]:not(.field__hint)").text()).toContain(t("lexicon.termForm.chooseTarget"));
  });

  it("asks for a node type of the sector, a suggested function's first, and a role", async () => {
    const wrapper = form();

    await control(wrapper, t("lexicon.termForm.cue")).setValue(true);
    await flushPromises();

    expect(targets).toHaveBeenCalledWith("school");
    const groups = control<HTMLSelectElement>(wrapper, t("lexicon.termForm.target")).findAll("optgroup");
    expect(groups.map((group) => [group.attributes("label"), group.findAll("option").map((one) => one.text())])).toEqual([
      [t("lexicon.termForm.suggested"), ["Lernfeld"]],
      [t("lexicon.termForm.others"), ["Inhaltsbereich", "Rahmenteil"]],
    ]);
    const roles = control<HTMLSelectElement>(wrapper, t("lexicon.termForm.role")).findAll("option");
    expect(roles.map((one) => one.element.value)).toEqual(["", "pref", "alt", "cue"]);
    expect(roles[2].text()).toBe(t("lexicon.termForm.roles.alt"));
    expect(await violations(wrapper.html())).toEqual([]);
  });

  // one problem a press took a press more for each further one (UI review m6)
  it("says a missing node type and role at one press, the keyboard at the first", async () => {
    const wrapper = form();
    await control(wrapper, t("lexicon.termForm.cue")).setValue(true);
    await flushPromises();

    await press(wrapper);

    expect(errorAt(wrapper, control(wrapper, t("lexicon.termForm.target")))).toContain(t("lexicon.termForm.chooseTarget"));
    const role = control(wrapper, t("lexicon.termForm.role"));
    expect(role.attributes("aria-invalid")).toBe("true");
    expect(wrapper.get(`#${role.attributes("id")}-error`).text()).toContain(t("lexicon.termForm.chooseRole"));
    expect(role.attributes("aria-required")).toBe("true");
  });

  it("makes the term a new cue to its node type with its role", async () => {
    const made = termDecision({ maps_to: FIELD.iri });
    const sent = vi.spyOn(api, "decideTerm").mockResolvedValue(made);
    const wrapper = form();

    await newCue(wrapper);
    await press(wrapper);

    expect(sent).toHaveBeenCalledWith({
      sector: "school",
      regions: ["DE-NW"],
      term: "Lernbereich",
      decision: "cue",
      maps_to: FIELD.iri,
      role: "alt",
      note: null,
    });
    // with the label it was chosen by: the list may not hold it
    expect(wrapper.emitted("decided")).toEqual([[made, { [FIELD.iri]: "Lernfeld" }]]);
  });

  it("says a term peculiar to its document with neither target nor role, a note kept", async () => {
    const sent = vi.spyOn(api, "decideTerm").mockResolvedValue(termDecision({ decision: "document" }));
    const wrapper = form();

    await newCue(wrapper);
    await control(wrapper, t("lexicon.termForm.document")).setValue(true);
    await control<HTMLTextAreaElement>(wrapper, t("lexicon.form.note")).setValue(" nur im KLP ");
    await press(wrapper);

    expect(sent).toHaveBeenCalledWith(expect.objectContaining({ decision: "document", maps_to: null, role: null, note: "nur im KLP" }));
  });

  it("names what is missing at its field before anything is sent", async () => {
    const sent = vi.spyOn(api, "decideTerm");
    const wrapper = form();

    await press(wrapper);
    const cue = control(wrapper, t("lexicon.termForm.cue"));
    expect(errorAt(wrapper, cue)).toContain(t("lexicon.termForm.chooseDecision"));
    for (const label of [t("lexicon.termForm.document"), t("lexicon.termForm.error")]) {
      expect(control(wrapper, label).attributes("aria-describedby")).toBe(cue.attributes("aria-describedby"));
    }

    await cue.setValue(true);
    await flushPromises();
    await press(wrapper);
    expect(errorAt(wrapper, control(wrapper, t("lexicon.termForm.target")))).toContain(t("lexicon.termForm.chooseTarget"));

    await control<HTMLSelectElement>(wrapper, t("lexicon.termForm.target")).setValue(AREA.iri);
    await press(wrapper);
    expect(errorAt(wrapper, control(wrapper, t("lexicon.termForm.role")))).toContain(t("lexicon.termForm.chooseRole"));
    expect(sent).not.toHaveBeenCalled();
  });

  it("says when the import would leave the cue out: the own lexicon holds the word", async () => {
    const wrapper = form({ held: [heldCue()] });

    await newCue(wrapper, FIELD.iri);

    const target = control<HTMLSelectElement>(wrapper, t("lexicon.termForm.target"));
    const warning = wrapper.get("[data-test=skipped]");
    expect(warning.text()).toBe(t("lexicon.termForm.skipped.word"));
    expect(target.attributes("aria-describedby")).toContain(warning.attributes("id"));
    expect(wrapper.get("[role=status]").text()).toBe(t("lexicon.termForm.skipped.word")); // said as it appears
  });

  it("says it of an own pattern only for one of the pattern's targets", async () => {
    const wrapper = form({ held: [heldCue({ by_word: false, surface_form: null, pattern: "^Lernbereich", maps_to: [AREA.iri] })] });

    await newCue(wrapper, FIELD.iri);
    expect(wrapper.find("[data-test=skipped]").exists()).toBe(false);
    await control<HTMLSelectElement>(wrapper, t("lexicon.termForm.target")).setValue(AREA.iri);

    expect(wrapper.get("[data-test=skipped]").text()).toBe(t("lexicon.termForm.skipped.pattern"));
    expect(wrapper.get("[role=status]").text()).toBe(t("lexicon.termForm.skipped.pattern"));
  });

  it("says when the node types did not come, and reads them again on the reader's word", async () => {
    targets.mockRejectedValueOnce(new ApiError("server", 503, "service_unavailable"));
    const wrapper = form();

    await control(wrapper, t("lexicon.termForm.cue")).setValue(true);
    await flushPromises();
    expect(wrapper.get("[data-test=targets-failed]").text()).toContain(t("lexicon.termForm.targetsFailed"));
    await wrapper.get("[data-test=targets-failed] button").trigger("click");
    await flushPromises();

    expect(targets).toHaveBeenCalledTimes(2);
    expect(control<HTMLSelectElement>(wrapper, t("lexicon.termForm.target")).findAll("option")).toHaveLength(4);
  });

  it("says in its status that the node types are read, and that they did not come", async () => {
    let fail: (error: unknown) => void = () => undefined;
    targets.mockReturnValueOnce(new Promise((_, reject) => (fail = reject)));
    const wrapper = form();

    await control(wrapper, t("lexicon.termForm.cue")).setValue(true);
    await flushPromises();
    expect(wrapper.get("[role=status]").text()).toBe(t("lexicon.termForm.targetsLoading"));
    fail(new ApiError("server", 503, "service_unavailable"));
    await flushPromises();

    expect(wrapper.get("[role=status]").text()).toBe(t("lexicon.termForm.targetsFailed"));
    expect(wrapper.findAll("[role=status]")).toHaveLength(1);
  });

  it("keeps its retry while the node types are read again, then takes the keyboard to them", async () => {
    let answer: (types: FormValue[]) => void = () => undefined;
    targets.mockRejectedValueOnce(new ApiError("server", 503, "service_unavailable"));
    targets.mockReturnValueOnce(new Promise((resolve) => (answer = resolve)));
    const wrapper = form();
    await control(wrapper, t("lexicon.termForm.cue")).setValue(true);
    await flushPromises();
    const retry = wrapper.get("[data-test=targets-failed] button");

    (retry.element as HTMLButtonElement).focus();
    await retry.trigger("click");
    await flushPromises();
    expect(retry.attributes("aria-disabled")).toBe("true");
    expect(document.activeElement).toBe(retry.element);
    await retry.trigger("click");
    expect(targets).toHaveBeenCalledTimes(2); // pressed again while busy: asked once
    answer([AREA, FIELD]);
    await flushPromises();

    expect(document.activeElement).toBe(control(wrapper, t("lexicon.termForm.target")).element);
  });

  it("says why it cannot save a new cue while its node types are missing", async () => {
    targets.mockRejectedValueOnce(new ApiError("server", 503, "service_unavailable"));
    const sent = vi.spyOn(api, "decideTerm");
    const wrapper = form();
    await control(wrapper, t("lexicon.termForm.cue")).setValue(true);
    await flushPromises();

    await press(wrapper);

    expect(wrapper.get("[role=alert]").text()).toContain(t("lexicon.termForm.targetsMissing"));
    expect(sent).not.toHaveBeenCalled();

    // read again: what was missing is there, and the form no longer says it is not
    await wrapper.get("[data-test=targets-failed] button").trigger("click");
    await flushPromises();
    expect(wrapper.find("select").exists()).toBe(true);
    expect(wrapper.find("[role=alert]").exists()).toBe(false);
  });

  it("says that the node types are still being read where a new cue is saved meanwhile", async () => {
    targets.mockReturnValueOnce(new Promise(() => undefined));
    const wrapper = form();
    await control(wrapper, t("lexicon.termForm.cue")).setValue(true);
    await flushPromises();

    await press(wrapper);

    expect(wrapper.get("[role=alert]").text()).toContain(t("lexicon.termForm.targetsPending"));
  });

  it("takes back what it said of the import once the reason is gone", async () => {
    const wrapper = form({ held: [heldCue({ by_word: false, surface_form: null, pattern: "^Lernbereich", maps_to: [AREA.iri] })] });
    await newCue(wrapper, AREA.iri);
    expect(wrapper.get("[role=status]").text()).toBe(t("lexicon.termForm.skipped.pattern"));

    await control<HTMLSelectElement>(wrapper, t("lexicon.termForm.target")).setValue(FIELD.iri);

    expect(wrapper.get("[role=status]").text()).toBe("");
  });

  it("starts reading the node types of a decision before once it is in the page, so the waiting is heard", async () => {
    targets.mockReturnValueOnce(new Promise(() => undefined));

    const wrapper = form({ before: termDecision() });

    // the status region in the page empty first: a region shown with its words is often not read
    expect(wrapper.get("[role=status]").text()).toBe("");
    await flushPromises();
    expect(wrapper.get("[role=status]").text()).toBe(t("lexicon.termForm.targetsLoading"));
  });

  it("starts from the decision before, its target among the node types once they are read", async () => {
    const wrapper = form({ before: termDecision({ maps_to: AREA.iri, role: "pref", note: "wie BY" }) });
    await flushPromises();

    expect((control(wrapper, t("lexicon.termForm.cue")).element as HTMLInputElement).checked).toBe(true);
    expect(control<HTMLSelectElement>(wrapper, t("lexicon.termForm.target")).element.value).toBe(AREA.iri);
    expect(control<HTMLSelectElement>(wrapper, t("lexicon.termForm.role")).element.value).toBe("pref");
    expect(control<HTMLTextAreaElement>(wrapper, t("lexicon.form.note")).element.value).toBe("wie BY");
    expect(wrapper.emitted("dirty")).toBeUndefined();

    await control<HTMLTextAreaElement>(wrapper, t("lexicon.form.note")).setValue("wie BY und HE");
    expect(wrapper.emitted("dirty")).toEqual([[true]]);
  });

  it("asks again for a node type the profile no longer offers", async () => {
    const sent = vi.spyOn(api, "decideTerm");
    const wrapper = form({ before: termDecision({ maps_to: SCHOOL + "Ausgemustert", role: "pref" }) });
    await flushPromises();

    expect(control<HTMLSelectElement>(wrapper, t("lexicon.termForm.target")).element.value).toBe("");
    expect(wrapper.emitted("dirty")).toBeUndefined();
    await press(wrapper);

    expect(errorAt(wrapper, control(wrapper, t("lexicon.termForm.target")))).toContain(t("lexicon.termForm.chooseTarget"));
    expect(sent).not.toHaveBeenCalled();
  });

  it("offers to read the list again where the term is gone, and says another refusal", async () => {
    vi.spyOn(api, "decideTerm")
      .mockRejectedValueOnce(new ApiError("server", 404, "no_term"))
      .mockRejectedValueOnce(new ApiError("server", 422, "not_a_node_type"));
    const wrapper = form();
    await newCue(wrapper);

    await press(wrapper);
    expect(wrapper.get("[role=alert]").text()).toContain(refusalText("no_term"));
    await wrapper.get("[data-test=decision-reload]").trigger("click");
    expect(wrapper.emitted("reload")).toHaveLength(1);

    await press(wrapper);
    expect(wrapper.get("[role=alert]").text()).toContain(refusalText("not_a_node_type"));
    expect(wrapper.find("[data-test=decision-reload]").exists()).toBe(false);
  });

  it("sends once while it saves", async () => {
    let answer: (made: TermDecision) => void = () => undefined;
    const sent = vi.spyOn(api, "decideTerm").mockReturnValue(new Promise((resolve) => (answer = resolve)));
    const wrapper = form();
    await newCue(wrapper);

    await press(wrapper);
    expect(submit(wrapper).attributes("aria-disabled")).toBe("true");
    await press(wrapper);
    answer(termDecision());
    await flushPromises();

    expect(sent).toHaveBeenCalledTimes(1);
  });

  it("is left without a word sent", async () => {
    const wrapper = form();

    await wrapper.get("[data-test=decision-cancel]").trigger("click");

    expect(wrapper.emitted("cancel")).toHaveLength(1);
  });
});
