import { flushPromises, mount, type VueWrapper } from "@vue/test-utils";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import * as api from "@/api";
import { ApiError } from "@/api";
import DocumentRules from "@/components/DocumentRules.vue";
import { t } from "@/i18n/de";

import { violations } from "./axe";
import { ruleOf, rulesOf } from "./ruleFixtures";

const CV = "https://w3id.org/wlo/curriculum/vocab#";
let shown: VueWrapper | null = null;

async function open(): Promise<VueWrapper> {
  shown = mount(DocumentRules, { props: { documentId: "d1" }, attachTo: document.body });
  await flushPromises();
  return shown;
}

/** The control of the field labelled `label` - its label's words, a required one's with its mark. */
function control(wrapper: VueWrapper, label: string) {
  const found = wrapper.findAll("label, legend").find((one) => one.text() === label || one.text() === `${label} (Pflichtfeld)`);
  if (!found) throw new Error(label);
  return found.element.tagName === "LEGEND" ? found.element.parentElement! : wrapper.get(`#${found.attributes("for")}`).element;
}
const input = (wrapper: VueWrapper, label: string) => wrapper.get<HTMLInputElement>(`#${(control(wrapper, label) as HTMLElement).id}`);
const words = (key: string) => t(`documents.page.rules.fields.${key}`);

beforeEach(() => {
  vi.restoreAllMocks();
  vi.spyOn(api, "getRules").mockResolvedValue(rulesOf());
});

afterEach(() => {
  shown?.unmount();
  shown = null;
  document.body.innerHTML = "";
});

describe("a document's rules on its page", () => {
  it("names each rule's kind, status, wording, values, option texts, links and anchors in words", async () => {
    const linked = ruleOf({
      id: "r2", kind: "prerequisite", verbatim: "Wer LF 1 bestanden hat.", min_count: null, max_count: null, min_amount: null,
      amount_unit: null, requirement_kind: CV + "req_formal", option_texts: [],
      applies_to: [{ id: "s1", kind: "specification", label: "Physik" }], requires: [{ id: "x", kind: "statement", label: null }],
      review_status: CV + "rev_confirmed",
    });
    vi.mocked(api.getRules).mockResolvedValue(rulesOf({ rules: [ruleOf(), linked] }));
    const wrapper = await open();

    expect(wrapper.get("h2").text()).toBe(t("documents.page.rules.heading"));
    const [selection, prerequisite] = wrapper.findAll("[data-test=rule]");
    expect(selection.get("h3").text()).toBe("Auswahlregel Vorgeschlagen");
    for (const said of ["Zwei aus vier Wahlmodulen.", "Anzahl: 2 bis 2", "Umfang: mindestens 10 ECTS-Leistungspunkt", "Modul A, Modul B", "Seite 3"]) {
      expect(selection.text()).toContain(said);
    }
    expect(selection.get("[data-test=rule-unlinked]").text()).toBe(t("documents.page.rules.unlinked"));
    expect(prerequisite.get("h3").text()).toBe("Voraussetzungsregel Bestätigt");
    expect(prerequisite.text()).toContain("Voraussetzung: formal (zwingend)");
    expect(prerequisite.text()).toContain("Physik");
    expect(prerequisite.text()).toContain("Aussage ohne Namen");
    expect(prerequisite.find("[data-test=rule-unlinked]").exists()).toBe(false);
    expect(await violations(wrapper.element)).toEqual([]);
  });

  it("says that a document has no rule, and offers to add one to who may", async () => {
    vi.mocked(api.getRules).mockResolvedValue(rulesOf({ rules: [] }));
    const wrapper = await open();

    expect(wrapper.text()).toContain(t("documents.page.rules.noneTitle"));
    expect(wrapper.get(".rules__add").text()).toBe(t("documents.page.rules.add"));
  });

  it("shows it loading, then a failure with a retry that reads again", async () => {
    vi.mocked(api.getRules).mockRejectedValueOnce(new ApiError("server", 500, "internal", "boom"));
    shown = mount(DocumentRules, { props: { documentId: "d1" }, attachTo: document.body });
    expect(shown.text()).toContain(t("documents.page.rules.loading"));
    await flushPromises();

    expect(shown.get("[role=alert]").text()).toContain(t("documents.page.rules.loadFailed"));
    await shown.get("[role=alert] button").trigger("click");
    await flushPromises();
    expect(shown.findAll("[data-test=rule]")).toHaveLength(1);
  });

  it("says content no longer the reader's apart, without a retry", async () => {
    vi.mocked(api.getRules).mockRejectedValue(new ApiError("server", 403, "file_hidden", "hidden"));
    const wrapper = await open();

    expect(wrapper.text()).toContain(t("refusals.file_hidden"));
    expect(wrapper.find("[role=alert] button").exists()).toBe(false);
  });

  it("is only to be read where the document is closed or not the caller's to change, and says why", async () => {
    vi.mocked(api.getRules).mockResolvedValue(rulesOf({ editable: false, closed: "frozen" }));
    const frozen = await open();

    expect(frozen.find("form").exists()).toBe(false);
    expect(frozen.find(".rules__add").exists()).toBe(false);
    expect(frozen.get("[data-test=rules-read-only]").text()).toBe(t("documents.page.rules.closed.frozen"));
    frozen.unmount();
    vi.mocked(api.getRules).mockResolvedValue(rulesOf({ editable: false }));
    const stranger = await open();
    expect(stranger.get("[data-test=rules-read-only]").text()).toBe(t("documents.page.rules.readOnly"));
  });
});

describe("a rule's form", () => {
  it("shows the fields its kind holds, and those of another kind once it is chosen", async () => {
    const wrapper = await open();

    expect(() => control(wrapper, words("options"))).not.toThrow();
    expect(() => control(wrapper, words("requires"))).toThrow();
    await input(wrapper, words("kind")).setValue("prerequisite");
    expect(() => control(wrapper, words("requires"))).not.toThrow();
    expect(() => control(wrapper, words("options"))).toThrow();
    expect(await violations(wrapper.element)).toEqual([]);
  });

  it("sends only what changed, on the revision read, numbers the German way and links by their ids", async () => {
    const saved = ruleOf({ max_count: 3, min_amount: 7.5, options: [{ id: "n1", kind: "node", label: "LF 1 Optik" }], revision: 2 });
    vi.spyOn(api, "editRule").mockResolvedValue(saved);
    const dirty: boolean[] = [];
    shown = mount(DocumentRules, { props: { documentId: "d1", onDirty: (open: boolean) => dirty.push(open) }, attachTo: document.body });
    await flushPromises();
    const wrapper = shown;

    await input(wrapper, words("max_count")).setValue("3");
    await input(wrapper, words("min_amount")).setValue("7,5");
    const options = control(wrapper, words("options")) as HTMLElement;
    const box = options.querySelector<HTMLInputElement>("input[value=n1]")!;
    box.click();
    await flushPromises();
    expect(dirty.at(-1)).toBe(true);
    await wrapper.get("form").trigger("submit");
    await flushPromises();

    expect(api.editRule).toHaveBeenCalledWith("r1", 1, { max_count: 3, min_amount: 7.5, options: ["n1"] });
    expect(wrapper.get("form [role=status]").text()).toBe(t("documents.page.rules.saved"));
    expect(wrapper.get("[data-test=rule]").text()).toContain("LF 1 Optik");
    expect(dirty.at(-1)).toBe(false);
  });

  it("sends nothing where nothing changed, and finds an entry's problem before it is sent", async () => {
    vi.spyOn(api, "editRule").mockResolvedValue(ruleOf({ revision: 2 }));
    const wrapper = await open();

    await wrapper.get("form").trigger("submit");
    expect(wrapper.get("form [role=status]").text()).toBe(t("documents.page.rules.unchanged"));
    await input(wrapper, words("min_count")).setValue("2,5");
    const submit = wrapper.get("form button[type=submit]");
    (submit.element as HTMLElement).focus();
    await wrapper.get("form").trigger("submit");
    await flushPromises();

    expect(api.editRule).not.toHaveBeenCalled();
    const count = input(wrapper, words("min_count"));
    expect(wrapper.get(`#${count.attributes("id")}-error`).text()).toContain(t("documents.page.rules.problems.not_count"));
    expect(document.activeElement).toBe(count.element);
  });

  it("puts a problem the server names at its field, the entry kept", async () => {
    vi.spyOn(api, "editRule").mockRejectedValue(new ApiError("server", 422, "invalid_field", "no", { field: "amount_unit", problem: "not_offered" }));
    const wrapper = await open();
    await input(wrapper, words("max_count")).setValue("4");

    await wrapper.get("form").trigger("submit");
    await flushPromises();

    const unit = input(wrapper, words("amount_unit"));
    expect(unit.attributes("aria-invalid")).toBe("true");
    expect(wrapper.text()).toContain(t("documents.tree.problems.not_offered"));
    expect(input(wrapper, words("max_count")).element.value).toBe("4");
  });

  it("shows the rule as it stands where it was changed meanwhile, and says so", async () => {
    const current = ruleOf({ verbatim: "Drei aus vier.", revision: 3 });
    vi.spyOn(api, "editRule").mockRejectedValue(new ApiError("server", 409, "stale_revision", "stale", { current }));
    const wrapper = await open();
    await input(wrapper, words("max_count")).setValue("4");

    await wrapper.get("form").trigger("submit");
    await flushPromises();

    expect(wrapper.get("[data-test=rule]").text()).toContain("Drei aus vier.");
    expect(wrapper.get("form [role=alert]").text()).toContain(t("documents.page.rules.changedMeanwhile"));
    expect(input(wrapper, words("max_count")).element.value).toBe("4");
  });

  it("reads the section again where the document was closed meanwhile", async () => {
    vi.spyOn(api, "editRule").mockRejectedValue(new ApiError("server", 409, "frozen", "frozen"));
    const wrapper = await open();
    vi.mocked(api.getRules).mockResolvedValue(rulesOf({ editable: false, closed: "frozen" }));
    await input(wrapper, words("max_count")).setValue("4");

    await wrapper.get("form").trigger("submit");
    await flushPromises();

    expect(api.getRules).toHaveBeenCalledTimes(2);
    expect(wrapper.find("form").exists()).toBe(false);
  });

  it("takes a run's rule away after a question, rejecting it, and reads the list again", async () => {
    vi.spyOn(api, "takeRule").mockResolvedValue({ outcome: "rejected", revision: 2 });
    const wrapper = await open();
    const take = wrapper.findAll("form button").find((button) => button.text() === t("documents.page.rules.reject"));
    expect(take?.attributes("aria-label")).toBe(t("documents.page.rules.rejectNamed", { rule: "Zwei aus vier Wahlmodulen." }));

    await take?.trigger("click");
    expect(document.body.textContent).toContain(t("documents.page.rules.rejectTitle"));
    (document.querySelector("[data-test=confirm]") as HTMLElement).click();
    await flushPromises();

    expect(api.takeRule).toHaveBeenCalledWith("r1", 1);
    expect(wrapper.get(".rules__status").text()).toBe(t("documents.page.rules.rejected"));
    expect(api.getRules).toHaveBeenCalledTimes(2);
  });

  it("offers no second rejection of a run's rule rejected already", async () => {
    vi.mocked(api.getRules).mockResolvedValue(rulesOf({ rules: [ruleOf({ review_status: CV + "rev_rejected", revision: 2 })] }));
    const wrapper = await open();

    expect(wrapper.get("h3").text()).toBe("Auswahlregel Verworfen");
    expect(wrapper.findAll("form button").map((button) => button.text())).not.toContain(t("documents.page.rules.reject"));
  });

  it("offers to delete an editor's own rule", async () => {
    vi.mocked(api.getRules).mockResolvedValue(rulesOf({ rules: [ruleOf({ by_hand: true })] }));
    const wrapper = await open();

    expect(wrapper.findAll("form button").map((button) => button.text())).toContain(t("documents.page.rules.delete"));
  });
});

describe("a new rule", () => {
  it("finds what it lacks before it is sent, each at its field", async () => {
    vi.spyOn(api, "addRule");
    const wrapper = await open();
    await wrapper.get(".rules__add").trigger("click");
    expect(document.activeElement?.textContent).toBe(t("documents.page.rules.newHeading"));

    const form = wrapper.get("form.rule-new");
    (form.get("button[type=submit]").element as HTMLElement).focus();
    await form.trigger("submit");
    await flushPromises();

    expect(api.addRule).not.toHaveBeenCalled();
    expect(form.findAll(".field__error")).toHaveLength(3);
    expect(form.text()).toContain(t("documents.page.rules.problems.not_page"));
    expect(await violations(wrapper.element)).toEqual([]);
  });

  it("is added on the page it stands on, the list read again, the keyboard back at the button", async () => {
    vi.spyOn(api, "addRule").mockResolvedValue(ruleOf({ id: "r9", kind: "completion", by_hand: true }));
    const wrapper = await open();
    await wrapper.get(".rules__add").trigger("click");
    const form = wrapper.get("form.rule-new");
    await form.get("select").setValue("completion");
    await form.get("textarea").setValue("Bestanden ist, wer alles besteht.");
    await form.get("input[inputmode=numeric]").setValue("4");

    await form.trigger("submit");
    await flushPromises();

    expect(api.addRule).toHaveBeenCalledWith("d1", {
      kind: "completion", verbatim: "Bestanden ist, wer alles besteht.", anchors: [{ page: 4 }],
    });
    expect(wrapper.find("form.rule-new").exists()).toBe(false);
    expect(wrapper.get(".rules__status").text()).toBe(t("documents.page.rules.created"));
    expect(document.activeElement).toBe(wrapper.get(".rules__add").element);
    expect(api.getRules).toHaveBeenCalledTimes(2);
  });

  it("puts a page the file has not at the page", async () => {
    vi.spyOn(api, "addRule").mockRejectedValue(new ApiError("server", 422, "invalid_field", "no", { field: "anchors", problem: "no_page" }));
    const wrapper = await open();
    await wrapper.get(".rules__add").trigger("click");
    const form = wrapper.get("form.rule-new");
    await form.get("select").setValue("completion");
    await form.get("textarea").setValue("Alles.");
    await form.get("input[inputmode=numeric]").setValue("999");

    await form.trigger("submit");
    await flushPromises();

    expect(form.get("input[inputmode=numeric]").attributes("aria-invalid")).toBe("true");
  });

  it("is dropped by its cancel, nothing sent", async () => {
    vi.spyOn(api, "addRule");
    const wrapper = await open();
    await wrapper.get(".rules__add").trigger("click");

    await wrapper.findAll("form.rule-new button").find((button) => button.text() === t("documents.page.rules.cancel"))?.trigger("click");
    await flushPromises();

    expect(wrapper.find("form.rule-new").exists()).toBe(false);
    expect(api.addRule).not.toHaveBeenCalled();
    expect(document.activeElement).toBe(wrapper.get(".rules__add").element);
  });
});
