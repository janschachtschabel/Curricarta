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

  it("says of a selection that the export names it none until two options are linked", async () => {
    const link = (id: string) => ({ id, kind: "node" as const, label: id });
    const one = ruleOf({ id: "r1", options: [link("n1")] });
    const two = ruleOf({ id: "r2", options: [link("n1"), link("n2")] });
    vi.mocked(api.getRules).mockResolvedValue(rulesOf({ rules: [one, two] }));
    const wrapper = await open();

    const [first, second] = wrapper.findAll("[data-test=rule]");
    expect(first.find("[data-test=rule-unlinked]").exists()).toBe(true);
    expect(second.find("[data-test=rule-unlinked]").exists()).toBe(false);
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
