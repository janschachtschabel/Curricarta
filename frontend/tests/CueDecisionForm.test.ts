import { flushPromises, mount, type VueWrapper } from "@vue/test-utils";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import * as api from "@/api";
import { ApiError, type CueDecision } from "@/api";
import CueDecisionForm from "@/components/CueDecisionForm.vue";
import { t } from "@/i18n/de";
import { refusalText } from "@/refusals";

import { violations } from "./axe";
import { CUE, cueDecision } from "./lexiconFixtures";

let shown: VueWrapper | null = null;

function form(before: CueDecision | null = null): VueWrapper {
  shown = mount(CueDecisionForm, { props: { cue: CUE, before }, attachTo: document.body });
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

async function confirming(wrapper: VueWrapper, strength = "0.85", evidence = " KLP S. 14 "): Promise<void> {
  await control(wrapper, t("lexicon.cueForm.confirmed")).setValue(true);
  await control<HTMLSelectElement>(wrapper, t("lexicon.cueForm.strength")).setValue(strength);
  await control(wrapper, t("lexicon.cueForm.evidence")).setValue(evidence);
}

// a field's error, inside its field and named by it, the keyboard on the field
function errorAt(wrapper: VueWrapper, input: { attributes: (name: string) => string | undefined; element: Element }) {
  const error = wrapper.get(`#${input.attributes("id")}-error`);
  expect(input.attributes("aria-invalid")).toBe("true");
  expect(input.attributes("aria-describedby")).toContain(error.attributes("id"));
  expect(document.activeElement).toBe(input.element);
  return error.text();
}

beforeEach(() => {
  vi.restoreAllMocks();
});

afterEach(() => {
  shown?.unmount();
  shown = null;
  document.body.innerHTML = "";
});

describe("the decision on a research cue", () => {
  it("asks for a strength and where the cue was found only for a confirmation", async () => {
    const wrapper = form();

    expect(wrapper.get("fieldset legend").text()).toBe(t("lexicon.cueForm.legend"));
    expect(wrapper.findAll("select")).toHaveLength(0);
    await control(wrapper, t("lexicon.cueForm.confirmed")).setValue(true);

    const strengths = control<HTMLSelectElement>(wrapper, t("lexicon.cueForm.strength")).findAll("option");
    expect(strengths.map((one) => one.element.value)).toEqual(["", "0.50", "0.55", "0.60", "0.65", "0.70", "0.75", "0.80", "0.85", "0.90"]);
    expect(strengths[9].text()).toBe("0,90");
    expect(control(wrapper, t("lexicon.cueForm.evidence")).attributes("maxlength")).toBe("500");
    expect(control<HTMLTextAreaElement>(wrapper, t("lexicon.form.note")).attributes("maxlength")).toBe("2000");
    expect(await violations(wrapper.html())).toEqual([]);
  });

  it("confirms the cue at its strength with where it was found, and says so", async () => {
    const made = cueDecision({ strength: "0.85" });
    const sent = vi.spyOn(api, "decideCue").mockResolvedValue(made);
    const wrapper = form();

    await confirming(wrapper);
    await press(wrapper);

    expect(sent).toHaveBeenCalledWith({ cue: CUE, decision: "confirmed", strength: "0.85", evidence: "KLP S. 14", note: null });
    expect(wrapper.emitted("decided")).toEqual([[made]]);
  });

  it("rejects the cue with nothing but a note, a blank one none", async () => {
    const sent = vi.spyOn(api, "decideCue").mockResolvedValue(cueDecision({ decision: "rejected", strength: null }));
    const wrapper = form();

    await control(wrapper, t("lexicon.cueForm.rejected")).setValue(true);
    await control<HTMLTextAreaElement>(wrapper, t("lexicon.form.note")).setValue("  doppelt zu KLP  ");
    await press(wrapper);

    expect(sent).toHaveBeenCalledWith({ cue: CUE, decision: "rejected", strength: null, evidence: null, note: "doppelt zu KLP" });
  });

  it("names what is missing at its field before anything is sent", async () => {
    const sent = vi.spyOn(api, "decideCue");
    const wrapper = form();

    await press(wrapper);
    const radio = control(wrapper, t("lexicon.cueForm.confirmed"));
    expect(errorAt(wrapper, radio)).toContain(t("lexicon.cueForm.chooseDecision"));
    // heard on every choice the arrow keys reach
    const other = control(wrapper, t("lexicon.cueForm.rejected"));
    expect([other.attributes("aria-invalid"), other.attributes("aria-describedby")]).toEqual([
      "true",
      radio.attributes("aria-describedby"),
    ]);

    await radio.setValue(true);
    await press(wrapper);
    expect(errorAt(wrapper, control(wrapper, t("lexicon.cueForm.strength")))).toContain(t("lexicon.cueForm.chooseStrength"));

    await control<HTMLSelectElement>(wrapper, t("lexicon.cueForm.strength")).setValue("0.80");
    await control(wrapper, t("lexicon.cueForm.evidence")).setValue("   ");
    await press(wrapper);
    expect(errorAt(wrapper, control(wrapper, t("lexicon.cueForm.evidence")))).toContain(t("lexicon.cueForm.evidenceMissing"));
    expect(sent).not.toHaveBeenCalled();
  });

  it("says the problem where the keyboard stays, Enter pressed in another field", async () => {
    const wrapper = form();
    await control(wrapper, t("lexicon.cueForm.confirmed")).setValue(true);
    const evidence = control(wrapper, t("lexicon.cueForm.evidence"));
    await evidence.setValue("KLP S. 14");

    (evidence.element as HTMLInputElement).focus();
    await wrapper.get("form").trigger("submit");
    await flushPromises();

    expect(document.activeElement).toBe(evidence.element);
    expect(wrapper.get("[role=status]").text()).toContain(t("lexicon.cueForm.chooseStrength"));
  });

  it("starts from the decision before, untouched until the reader changes it", async () => {
    const wrapper = form(cueDecision({ strength: "0.9", evidence: "KLP S. 14", note: "aus HE" }));

    expect((control(wrapper, t("lexicon.cueForm.confirmed")).element as HTMLInputElement).checked).toBe(true);
    expect(control<HTMLSelectElement>(wrapper, t("lexicon.cueForm.strength")).element.value).toBe("0.90");
    expect(control(wrapper, t("lexicon.cueForm.evidence")).element.value).toBe("KLP S. 14");
    expect(wrapper.emitted("dirty")).toBeUndefined();

    await control<HTMLTextAreaElement>(wrapper, t("lexicon.form.note")).setValue("aus HE und NW");
    await control<HTMLTextAreaElement>(wrapper, t("lexicon.form.note")).setValue("aus HE");

    expect(wrapper.emitted("dirty")).toEqual([[true], [false]]);
  });

  it("offers to read the list again where the cue is gone meanwhile", async () => {
    vi.spyOn(api, "decideCue").mockRejectedValue(new ApiError("server", 404, "no_cue"));
    const wrapper = form();

    await confirming(wrapper);
    await press(wrapper);

    expect(wrapper.get("[role=alert]").text()).toContain(refusalText("no_cue"));
    await wrapper.get("[data-test=decision-reload]").trigger("click");
    expect(wrapper.emitted("reload")).toHaveLength(1);
    expect(wrapper.emitted("decided")).toBeUndefined();
  });

  it("sends once while it saves, and stays so until the form goes with the decision", async () => {
    let answer: (made: CueDecision) => void = () => undefined;
    const sent = vi.spyOn(api, "decideCue").mockReturnValue(new Promise((resolve) => (answer = resolve)));
    const wrapper = form();
    await confirming(wrapper);

    await press(wrapper);
    expect(submit(wrapper).attributes("aria-disabled")).toBe("true");
    await press(wrapper);
    answer(cueDecision());
    await flushPromises();
    await press(wrapper);

    expect(sent).toHaveBeenCalledTimes(1);
    expect(wrapper.emitted("decided")).toHaveLength(1);
  });

  it("keeps what was entered where saving fails", async () => {
    vi.spyOn(api, "decideCue").mockRejectedValue(new ApiError("server", 503, "service_unavailable"));
    const wrapper = form();
    await confirming(wrapper);

    await press(wrapper);

    expect(wrapper.get("[role=alert]").text()).toContain(t("lexicon.form.failed"));
    expect(wrapper.find("[data-test=decision-reload]").exists()).toBe(false);
    expect(control(wrapper, t("lexicon.cueForm.evidence")).element.value).toBe(" KLP S. 14 ");
    expect(submit(wrapper).attributes("aria-disabled")).toBeUndefined();
  });

  it("is left without a word sent", async () => {
    const sent = vi.spyOn(api, "decideCue");
    const wrapper = form();

    await wrapper.get("[data-test=decision-cancel]").trigger("click");

    expect(wrapper.emitted("cancel")).toHaveLength(1);
    expect(sent).not.toHaveBeenCalled();
  });
});
