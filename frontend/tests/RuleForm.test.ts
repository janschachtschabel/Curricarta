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

/** The section with its first rule's form open - or the rule's form at `index`. */
async function opened(index = 0, onDirty?: (open: boolean) => void): Promise<VueWrapper> {
  shown = mount(DocumentRules, { props: { documentId: "d1", onDirty }, attachTo: document.body });
  await flushPromises();
  await shown.findAll(".rules__edit")[index]?.trigger("click");
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

describe("a rule's form", () => {
  it("shows the fields its kind holds, and those of another kind once it is chosen", async () => {
    const wrapper = await opened();

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
    const wrapper = await opened(0, (open) => dirty.push(open));
    expect(dirty.at(-1) ?? false).toBe(false); // nothing typed yet

    await input(wrapper, words("max_count")).setValue("3");
    await input(wrapper, words("min_amount")).setValue("7,5");
    const options = control(wrapper, words("options")) as HTMLElement;
    const box = [...options.querySelectorAll("[data-test=targets-offered] label")].find((one) => one.textContent === "LF 1 Optik");
    (document.getElementById(box!.getAttribute("for")!) as HTMLInputElement).click();
    await flushPromises();
    expect(options.querySelector("[data-test=targets-chosen]")?.textContent).toContain("LF 1 Optik");
    expect(dirty.at(-1)).toBe(true);
    await wrapper.get("form").trigger("submit");
    await flushPromises();

    expect(api.editRule).toHaveBeenCalledWith("r1", 1, { max_count: 3, min_amount: 7.5, options: ["n1"] });
    expect(wrapper.get(".rule-form__status").text()).toBe(t("documents.page.rules.saved"));
    expect(wrapper.get("[data-test=rule]").text()).toContain("LF 1 Optik");
    expect(dirty.at(-1)).toBe(false);
  });

  it("sends nothing where nothing changed, and finds an entry's problem before it is sent", async () => {
    vi.spyOn(api, "editRule").mockResolvedValue(ruleOf({ revision: 2 }));
    const wrapper = await opened();

    await wrapper.get("form").trigger("submit");
    expect(wrapper.get(".rule-form__status").text()).toBe(t("documents.page.rules.unchanged"));
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
    const wrapper = await opened();
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
    const wrapper = await opened();
    await input(wrapper, words("max_count")).setValue("4");

    await wrapper.get("form").trigger("submit");
    await flushPromises();

    expect(wrapper.get("[data-test=rule]").text()).toContain("Drei aus vier.");
    expect(wrapper.get("form [role=alert]").text()).toContain(t("documents.page.rules.changedMeanwhile"));
    expect(input(wrapper, words("max_count")).element.value).toBe("4");
  });

  it("reads the section again where the document was closed meanwhile", async () => {
    vi.spyOn(api, "editRule").mockRejectedValue(new ApiError("server", 409, "frozen", "frozen"));
    const wrapper = await opened();
    vi.mocked(api.getRules).mockResolvedValue(rulesOf({ editable: false, closed: "frozen" }));
    await input(wrapper, words("max_count")).setValue("4");

    await wrapper.get("form").trigger("submit");
    await flushPromises();

    expect(api.getRules).toHaveBeenCalledTimes(2);
    expect(wrapper.find("form").exists()).toBe(false);
  });

  it("takes a run's rule away after a question, rejecting it, and reads the list again", async () => {
    vi.spyOn(api, "takeRule").mockResolvedValue({ outcome: "rejected", revision: 2 });
    const wrapper = await opened();
    const take = wrapper.findAll("form button").find((button) => button.text() === t("documents.page.rules.reject"));
    expect(take?.attributes("aria-label")).toBe(
      t("documents.page.rules.rejectNamed", { rule: "Auswahlregel „Zwei aus vier Wahlmodulen.“" }),
    );

    await take?.trigger("click");
    expect(document.body.textContent).toContain(t("documents.page.rules.rejectTitle"));
    (document.querySelector("[data-test=confirm]") as HTMLElement).click();
    await flushPromises();

    expect(api.takeRule).toHaveBeenCalledWith("r1", 1);
    expect(wrapper.get(".rules__status").text()).toBe(t("documents.page.rules.rejected"));
    expect(api.getRules).toHaveBeenCalledTimes(2);
    expect(document.activeElement).toBe(wrapper.get("#document-rules").element);
  });

  it("offers no second rejection of a run's rule rejected already", async () => {
    vi.mocked(api.getRules).mockResolvedValue(rulesOf({ rules: [ruleOf({ review_status: CV + "rev_rejected", revision: 2 })] }));
    const wrapper = await opened();

    expect(wrapper.get("h3").text()).toBe("Auswahlregel Verworfen");
    expect(wrapper.findAll("form button").map((button) => button.text())).not.toContain(t("documents.page.rules.reject"));
  });

  it("offers to delete an editor's own rule", async () => {
    vi.mocked(api.getRules).mockResolvedValue(rulesOf({ rules: [ruleOf({ by_hand: true })] }));
    const wrapper = await opened();

    expect(wrapper.findAll("form button").map((button) => button.text())).toContain(t("documents.page.rules.delete"));
  });

  it("opens on its button with the keyboard at its heading, and closes back to the button at once where clean", async () => {
    vi.spyOn(api, "editRule");
    shown = mount(DocumentRules, { props: { documentId: "d1" }, attachTo: document.body });
    await flushPromises();
    expect(shown.find("form").exists()).toBe(false);
    const button = shown.get(".rules__edit");
    expect(button.attributes("aria-label")).toBe(
      t("documents.page.rules.editNamed", { rule: "Auswahlregel „Zwei aus vier Wahlmodulen.“" }),
    );

    await button.trigger("click");
    await flushPromises();
    expect(document.activeElement?.textContent).toBe(t("documents.page.rules.formHeading", { kind: "Auswahlregel" }));
    await shown.findAll("form button").find((one) => one.text() === t("documents.page.rules.close"))?.trigger("click");
    await flushPromises();

    expect(document.body.textContent).not.toContain(t("documents.page.rules.discardTitle"));
    expect(shown.find("form").exists()).toBe(false);
    expect(document.activeElement).toBe(shown.get(".rules__edit").element);
    expect(api.editRule).not.toHaveBeenCalled();
  });

  it("asks before it closes over a draft: kept on cancel, dropped on confirm, nothing sent", async () => {
    vi.spyOn(api, "editRule");
    const wrapper = await opened();
    await input(wrapper, words("max_count")).setValue("5");
    const close = () => wrapper.findAll("form button").find((one) => one.text() === t("documents.page.rules.close"))?.trigger("click");

    await close();
    expect(document.body.textContent).toContain(t("documents.page.rules.discardTitle"));
    (document.querySelector("[data-test=cancel]") as HTMLElement).click();
    await flushPromises();
    expect(wrapper.find("form").exists()).toBe(true);
    expect(input(wrapper, words("max_count")).element.value).toBe("5");

    await close();
    (document.querySelector("[data-test=confirm]") as HTMLElement).click();
    await flushPromises();
    expect(wrapper.find("form").exists()).toBe(false);
    expect(document.activeElement).toBe(wrapper.get(".rules__edit").element);
    expect(api.editRule).not.toHaveBeenCalled();
  });

  it("names a rule on its buttons by its kind and the start of its wording", async () => {
    const long = "Wahlpflicht ".repeat(40).trim();
    vi.mocked(api.getRules).mockResolvedValue(rulesOf({ rules: [ruleOf({ verbatim: long })] }));
    const wrapper = await opened();

    const name = wrapper.get("form button[type=submit]").attributes("aria-label") ?? "";
    expect(name.startsWith(t("documents.page.rules.save"))).toBe(true);
    expect(name.length).toBeLessThan(140);
    expect(name).toContain("…");
  });

  it("is no draft as read, though the rule holds what its kind does not show", async () => {
    vi.mocked(api.getRules).mockResolvedValue(rulesOf({ rules: [ruleOf({ kind: "completion", max_share: 0.3, option_texts: [" A "] })] }));
    const dirty: boolean[] = [];

    await opened(0, (open) => dirty.push(open));

    expect(dirty).not.toContain(true);
  });
});

describe("the rows a rule names", () => {
  const many = Array.from({ length: 300 }, (_, at) => ({ id: `n${at}`, kind: "node" as const, label: `LF ${at} Thema` }));

  it("offer a bounded number of what the rule may name, say how many more match, and narrow by a search", async () => {
    vi.mocked(api.getRules).mockResolvedValue(rulesOf({ targets: many }));
    const wrapper = await opened();
    const applies = control(wrapper, words("applies_to")) as HTMLElement;

    expect(applies.querySelectorAll("[data-test=targets-offered] input[type=checkbox]")).toHaveLength(20);
    expect(applies.textContent).toContain(t("documents.page.rules.moreMatch", { count: 280 }));
    expect(wrapper.findAll("input[type=checkbox]").length).toBeLessThan(50);

    const search = applies.querySelector<HTMLInputElement>("input[type=search]")!;
    search.value = "LF 29";
    search.dispatchEvent(new Event("input"));
    await flushPromises();
    // LF 29 and LF 290 to LF 299
    expect(applies.querySelectorAll("[data-test=targets-offered] label")).toHaveLength(11);
    expect(applies.textContent).not.toContain("weitere passen");
    expect(await violations(wrapper.element)).toEqual([]);
  });

  it("hold an Enter in their search, so it saves nothing", async () => {
    vi.spyOn(api, "editRule");
    const wrapper = await opened();
    const search = (control(wrapper, words("applies_to")) as HTMLElement).querySelector<HTMLInputElement>("input[type=search]")!;
    search.value = "LF";
    search.dispatchEvent(new Event("input"));
    const enter = new KeyboardEvent("keydown", { key: "Enter", bubbles: true, cancelable: true });

    search.dispatchEvent(enter);
    await flushPromises();

    // the browser submits a form on an Enter it is let have: here it is held
    expect(enter.defaultPrevented).toBe(true);
    expect(api.editRule).not.toHaveBeenCalled();
  });

  it("say what was chosen and what let go", async () => {
    const wrapper = await opened();
    const applies = control(wrapper, words("applies_to")) as HTMLElement;
    const said = () => applies.querySelector("[role=status]")?.textContent?.trim();

    const offered = [...applies.querySelectorAll("[data-test=targets-offered] label")].find((one) => one.textContent === "Physik");
    (document.getElementById(offered!.getAttribute("for")!) as HTMLInputElement).click();
    await flushPromises();
    expect(said()).toBe(t("documents.page.rules.chosenSaid", { label: "Physik" }));

    applies.querySelector<HTMLInputElement>("[data-test=targets-chosen] input")!.click();
    await flushPromises();
    expect(said()).toBe(t("documents.page.rules.releasedSaid", { label: "Physik" }));
  });

  it("keep a row chosen that no list offers, under its own words, and let it go", async () => {
    const said = { id: "x", kind: "statement" as const, label: "Sie messen." };
    vi.mocked(api.getRules).mockResolvedValue(rulesOf({ rules: [ruleOf({ kind: "prerequisite", requires: [said] })] }));
    vi.spyOn(api, "editRule").mockResolvedValue(ruleOf({ kind: "prerequisite", revision: 2 }));
    const wrapper = await opened();
    const requires = control(wrapper, words("requires")) as HTMLElement;
    expect(requires.querySelector("[data-test=targets-chosen]")?.textContent).toContain("Sie messen.");

    requires.querySelector<HTMLInputElement>("[data-test=targets-chosen] input")!.click();
    await flushPromises();
    expect(document.activeElement).toBe(requires.querySelector("input[type=search]"));
    await wrapper.get("form").trigger("submit");
    await flushPromises();

    expect(api.editRule).toHaveBeenCalledWith("r1", 1, { requires: [] });
  });
});
