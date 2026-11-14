import { flushPromises, mount, type VueWrapper } from "@vue/test-utils";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import * as api from "@/api";
import { ApiError, type MemPlan, type MemPlanPage } from "@/api";
import MemImportPanel from "@/components/MemImportPanel.vue";
import { t } from "@/i18n/de";
import { router } from "@/router";
import { clearSession, setSession } from "@/session";

import { violations } from "./axe";
import { documentOf } from "./documentFixtures";

let shown: VueWrapper | null = null;

function plan(name: string, changes: Partial<MemPlan> = {}): MemPlan {
  return {
    iri: `https://w3id.org/p/${name}`,
    graph: "https://w3id.org/lehrplan/sn",
    land_iri: "https://w3id.org/lehrplan/ontology/LP_3000047",
    title: `Informatik ${name}`,
    class_iri: "https://w3id.org/lehrplan/ontology/LP_0000438",
    subjects: [],
    school_types: [],
    licence: null,
    attribution: "MEM-Schule (https://sparql.example/sparql), Lehrplan-Ontologie",
    read_at: "2026-11-10T10:00:00Z",
    region: "DE-SN",
    ...changes,
  };
}

function page(plans: MemPlan[], total = plans.length, readAt: string | null = "2026-11-10T10:00:00Z"): MemPlanPage {
  return { plans, total, catalog_read_at: readAt };
}

function mountPanel(conversionId: string | null = "c1", country: string | null = "DE-SN"): VueWrapper {
  shown = mount(MemImportPanel, {
    props: { sourceId: "s1", conversionId, country },
    attachTo: document.body,
    global: { plugins: [router] },
  });
  return shown;
}

beforeEach(() => {
  vi.restoreAllMocks();
  setSession({ id: "r", name: "Redaktion", roles: ["redaktion"] });
});

afterEach(() => {
  shown?.unmount();
  shown = null;
  clearSession();
});

describe("the import of a MEM plan on an entry's page", () => {
  it("without a finished conversion says so and asks the catalogue nothing", async () => {
    const found = vi.spyOn(api, "findMemPlans");
    const wrapper = mountPanel(null);
    await flushPromises();

    expect(wrapper.text()).toContain(t("mem.import.needsConversion"));
    expect(wrapper.get("a[href='#source-conversion']").text()).toBe(t("mem.import.toConversion"));
    expect(found).not.toHaveBeenCalled();
    expect(await violations(wrapper.html())).toEqual([]);
  });

  it("looks the entry's Land up at first, and offers its plans to choose from", async () => {
    const found = vi.spyOn(api, "findMemPlans").mockResolvedValue(page([plan("a"), plan("b")]));
    const wrapper = mountPanel();
    await flushPromises();

    expect(found).toHaveBeenCalledWith({ region: "DE-SN", title: undefined, offset: 0 });
    expect(wrapper.get<HTMLSelectElement>("#mem-import-region").element.value).toBe("DE-SN");
    expect(wrapper.findAll("input[type=radio]")).toHaveLength(2);
    expect(wrapper.get("[data-test=mem-shown]").text()).toBe(t("mem.import.shown", { shown: 2, total: 2 }));
    expect(await violations(wrapper.html())).toEqual([]);
  });

  it("shows no search where the catalogue was never read", async () => {
    vi.spyOn(api, "findMemPlans").mockResolvedValue(page([], 0, null));
    const wrapper = mountPanel();
    await flushPromises();

    expect(wrapper.text()).toContain(t("mem.catalog.never"));
    expect(wrapper.find("form").exists()).toBe(false);
  });

  it("says a search that found nothing, telling it from a catalogue never read", async () => {
    vi.spyOn(api, "findMemPlans").mockResolvedValue(page([]));
    const wrapper = mountPanel();
    await flushPromises();

    expect(wrapper.text()).toContain(t("mem.import.noneFound"));
    expect(wrapper.find("form").exists()).toBe(true);
  });

  it("searches by the region and title asked, the KMK's standards as all of Germany", async () => {
    const found = vi.spyOn(api, "findMemPlans").mockResolvedValue(page([plan("a")]));
    const wrapper = mountPanel();
    await flushPromises();

    await wrapper.get("#mem-import-region").setValue("DE");
    await wrapper.get("#mem-import-title").setValue("Mathe");
    await wrapper.get("form").trigger("submit");
    await flushPromises();

    expect(found).toHaveBeenLastCalledWith({ region: "DE", title: "Mathe", offset: 0 });
    expect(wrapper.get("#mem-import-region option[value=DE]").text()).toBe(t("mem.import.regionKmk"));
  });

  it("loads more of a long list below what it shows", async () => {
    const found = vi
      .spyOn(api, "findMemPlans")
      .mockResolvedValueOnce(page([plan("a")], 2))
      .mockResolvedValueOnce(page([plan("b")], 2));
    const wrapper = mountPanel();
    await flushPromises();

    await wrapper.get("[data-test=mem-more]").trigger("click");
    await flushPromises();

    expect(found).toHaveBeenLastCalledWith({ region: "DE-SN", title: undefined, offset: 1 });
    expect(wrapper.findAll("input[type=radio]")).toHaveLength(2);
    expect(wrapper.find("[data-test=mem-more]").exists()).toBe(false);
  });

  it("names the chosen plan's attribution and licence, and that the wordings' rights are the entry's", async () => {
    vi.spyOn(api, "findMemPlans").mockResolvedValue(page([plan("a")]));
    const wrapper = mountPanel();
    await flushPromises();

    await wrapper.get("input[type=radio]").setValue(true);

    const facts = wrapper.get("[data-test=mem-chosen]").text();
    expect(facts).toContain(plan("a").attribution);
    expect(facts).toContain(t("mem.import.licenceNone"));
    expect(facts).toContain(t("mem.import.rightsNote"));
  });

  it("asks for a plan before it imports, and gives the choice the keyboard", async () => {
    const started = vi.spyOn(api, "startMemImport");
    vi.spyOn(api, "findMemPlans").mockResolvedValue(page([plan("a")]));
    const wrapper = mountPanel();
    await flushPromises();

    await wrapper.get("[data-test=mem-import]").trigger("click");
    await flushPromises();

    expect(started).not.toHaveBeenCalled();
    expect(wrapper.get("#mem-import-choice-error").text()).toContain(t("mem.import.chooseMissing"));
    expect(document.activeElement).toBe(wrapper.get("input[type=radio]").element);
  });

  it("imports the chosen plan into the entry's conversion and goes to the new document", async () => {
    vi.spyOn(api, "findMemPlans").mockResolvedValue(page([plan("a")]));
    const started = vi
      .spyOn(api, "startMemImport")
      .mockResolvedValue({ document: documentOf({ id: "d9" }), job: { id: "j9" } as api.Job });
    const push = vi.spyOn(router, "push").mockResolvedValue(undefined);
    const wrapper = mountPanel();
    await flushPromises();

    await wrapper.get("input[type=radio]").setValue(true);
    await wrapper.get("[data-test=mem-import]").trigger("click");
    await flushPromises();

    expect(started).toHaveBeenCalledWith("s1", { plan_iri: plan("a").iri, conversion_id: "c1" });
    expect(push).toHaveBeenCalledWith({ name: "document", params: { id: "d9" } });
  });

  it("leads to the document a plan was imported into before", async () => {
    vi.spyOn(api, "findMemPlans").mockResolvedValue(page([plan("a")]));
    vi.spyOn(api, "startMemImport").mockRejectedValue(
      new ApiError("server", 409, "mem_plan_taken", "taken", { document_id: "d0" }),
    );
    const wrapper = mountPanel();
    await flushPromises();

    await wrapper.get("input[type=radio]").setValue(true);
    await wrapper.get("[data-test=mem-import]").trigger("click");
    await flushPromises();

    const alert = wrapper.get("[role=alert]");
    expect(alert.text()).toContain(t("refusals.mem_plan_taken"));
    expect(alert.get("a").attributes("href")).toBe("/dokumente/d0");
    expect(alert.get("a").text()).toBe(t("mem.import.toDocument"));
    expect(await violations(wrapper.html())).toEqual([]);
  });

  it("looks the catalogue up anew when the chosen plan is gone from it", async () => {
    const found = vi.spyOn(api, "findMemPlans").mockResolvedValue(page([plan("a")]));
    vi.spyOn(api, "startMemImport").mockRejectedValue(new ApiError("server", 422, "mem_unknown_plan", "gone"));
    const wrapper = mountPanel();
    await flushPromises();

    await wrapper.get("input[type=radio]").setValue(true);
    await wrapper.get("[data-test=mem-import]").trigger("click");
    await flushPromises();

    expect(found).toHaveBeenCalledTimes(2);
    expect(wrapper.get("[role=alert]").text()).toContain(t("refusals.mem_unknown_plan"));
  });

  it("says the catalogue could not be read, and tries again on asking", async () => {
    const found = vi
      .spyOn(api, "findMemPlans")
      .mockRejectedValueOnce(new ApiError("network", 0))
      .mockResolvedValueOnce(page([plan("a")]));
    const wrapper = mountPanel();
    await flushPromises();

    expect(wrapper.text()).toContain(t("mem.import.loadFailed"));
    expect(await violations(wrapper.html())).toEqual([]);
    await wrapper.get(".error button").trigger("click");
    await flushPromises();

    expect(found).toHaveBeenCalledTimes(2);
    expect(wrapper.findAll("input[type=radio]")).toHaveLength(1);
  });

  it("drops an answer a newer search overtook", async () => {
    let slow: (page: MemPlanPage) => void = () => undefined;
    vi.spyOn(api, "findMemPlans")
      .mockResolvedValueOnce(page([plan("a")]))
      .mockReturnValueOnce(new Promise((resolve) => (slow = resolve)))
      .mockResolvedValueOnce(page([plan("new")]));
    const wrapper = mountPanel();
    await flushPromises();

    await wrapper.get("form").trigger("submit");
    await wrapper.get("form").trigger("submit");
    await flushPromises();
    slow(page([plan("old")]));
    await flushPromises();

    expect(wrapper.text()).toContain("Informatik new");
    expect(wrapper.text()).not.toContain("Informatik old");
  });

  it("loads no more while a new search runs: the list is never one of two searches", async () => {
    let slow: (page: MemPlanPage) => void = () => undefined;
    const found = vi
      .spyOn(api, "findMemPlans")
      .mockResolvedValueOnce(page([plan("a")], 2))
      .mockReturnValueOnce(new Promise((resolve) => (slow = resolve)));
    const wrapper = mountPanel();
    await flushPromises();

    await wrapper.get("#mem-import-region").setValue("DE-BY");
    await wrapper.get("form").trigger("submit");
    await wrapper.get("[data-test=mem-more]").trigger("click");
    await flushPromises();

    expect(found).toHaveBeenCalledTimes(2);
    expect(wrapper.get("[data-test=mem-more]").attributes("aria-disabled")).toBe("true");
    slow(page([plan("by1", { region: "DE-BY" })], 1));
    await flushPromises();
    expect(wrapper.findAll("input[type=radio]")).toHaveLength(1);
    expect(wrapper.text()).toContain("Informatik by1");
  });

  it("loads more of the search shown, though the form was changed meanwhile or a new search failed", async () => {
    const found = vi
      .spyOn(api, "findMemPlans")
      .mockResolvedValueOnce(page([plan("a")], 2))
      .mockRejectedValueOnce(new ApiError("network", 0))
      .mockResolvedValueOnce(page([plan("b")], 2));
    const wrapper = mountPanel();
    await flushPromises();
    await wrapper.get("#mem-import-region").setValue("DE-BY");
    await wrapper.get("form").trigger("submit");
    await flushPromises();

    await wrapper.get("[data-test=mem-more]").trigger("click");
    await flushPromises();

    expect(found).toHaveBeenLastCalledWith({ region: "DE-SN", title: undefined, offset: 1 });
    expect(wrapper.findAll("input[type=radio]")).toHaveLength(2);
  });

  it("gives the keyboard to the first plan loaded once the last page took the button away", async () => {
    vi.spyOn(api, "findMemPlans")
      .mockResolvedValueOnce(page([plan("a")], 2))
      .mockResolvedValueOnce(page([plan("b")], 2));
    const wrapper = mountPanel();
    await flushPromises();
    const more = wrapper.get<HTMLButtonElement>("[data-test=mem-more]");
    more.element.focus();

    await more.trigger("click");
    await flushPromises();

    expect(document.activeElement).toBe(wrapper.findAll("input[type=radio]")[1].element);
  });

  it("says when more could not be loaded, keeping what it shows", async () => {
    vi.spyOn(api, "findMemPlans")
      .mockResolvedValueOnce(page([plan("a")], 2))
      .mockRejectedValueOnce(new ApiError("network", 0));
    const wrapper = mountPanel();
    await flushPromises();

    await wrapper.get("[data-test=mem-more]").trigger("click");
    await flushPromises();

    expect(wrapper.get("[role=alert]").text()).toContain(t("mem.import.moreFailed"));
    expect(wrapper.findAll("input[type=radio]")).toHaveLength(1);
  });

  it("says the number found once asked for, not when the section first loads", async () => {
    vi.spyOn(api, "findMemPlans").mockResolvedValue(page([plan("a")]));
    const wrapper = mountPanel();
    await flushPromises();
    const status = () => wrapper.get(".mem-import__status").text();
    expect(status()).toBe("");

    await wrapper.get("form").trigger("submit");
    await flushPromises();

    expect(status()).toContain(t("mem.import.shown", { shown: 1, total: 1 }));
  });

  it("forgets the choice and its error with a new search, and ties the error to every choice", async () => {
    vi.spyOn(api, "findMemPlans").mockResolvedValue(page([plan("a")]));
    const wrapper = mountPanel();
    await flushPromises();
    await wrapper.get("[data-test=mem-import]").trigger("click");
    await flushPromises();
    expect(wrapper.get("input[type=radio]").attributes("aria-describedby")).toBe("mem-import-choice-error");
    expect(await violations(wrapper.html())).toEqual([]);

    await wrapper.get("form").trigger("submit");
    await flushPromises();

    expect(wrapper.find("#mem-import-choice-error").exists()).toBe(false);
  });

  it("names no region where a plan has none", async () => {
    vi.spyOn(api, "findMemPlans").mockResolvedValue(page([plan("a", { region: null })]));
    const wrapper = mountPanel();
    await flushPromises();

    expect(wrapper.get(".mem-import__meta").text()).toMatch(/^Stand/);
  });

  it("has nothing axe finds where the catalogue was never read or a search found nothing", async () => {
    vi.spyOn(api, "findMemPlans").mockResolvedValueOnce(page([], 0, null)).mockResolvedValueOnce(page([]));
    const never = mountPanel();
    await flushPromises();
    expect(await violations(never.html())).toEqual([]);
    never.unmount();

    const none = mountPanel();
    await flushPromises();
    expect(await violations(none.html())).toEqual([]);
  });

  it("drops more a new search overtook: the list is the search's alone", async () => {
    let slow: (page: MemPlanPage) => void = () => undefined;
    vi.spyOn(api, "findMemPlans")
      .mockResolvedValueOnce(page([plan("a")], 3))
      .mockReturnValueOnce(new Promise((resolve) => (slow = resolve)))
      .mockResolvedValueOnce(page([plan("new")], 1));
    const wrapper = mountPanel();
    await flushPromises();

    await wrapper.get("[data-test=mem-more]").trigger("click");
    await wrapper.get("form").trigger("submit");
    await flushPromises();
    slow(page([plan("b")], 3));
    await flushPromises();

    expect(wrapper.findAll("input[type=radio]")).toHaveLength(1);
    expect(wrapper.text()).toContain("Informatik new");
    expect(wrapper.text()).not.toContain("Informatik b");
  });

  it("leaves the keyboard on the button where more pages follow", async () => {
    vi.spyOn(api, "findMemPlans")
      .mockResolvedValueOnce(page([plan("a")], 3))
      .mockResolvedValueOnce(page([plan("b")], 3));
    const wrapper = mountPanel();
    await flushPromises();
    const more = wrapper.get<HTMLButtonElement>("[data-test=mem-more]");
    more.element.focus();

    await more.trigger("click");
    await flushPromises();

    expect(document.activeElement).toBe(wrapper.get("[data-test=mem-more]").element);
  });

  it("shows a search on its way at its button", async () => {
    vi.spyOn(api, "findMemPlans")
      .mockResolvedValueOnce(page([plan("a")]))
      .mockReturnValueOnce(new Promise(() => undefined));
    const wrapper = mountPanel();
    await flushPromises();

    await wrapper.get("form").trigger("submit");
    await flushPromises();

    expect(wrapper.get("[data-test=mem-search]").attributes("aria-disabled")).toBe("true");
    expect(wrapper.get("[data-test=mem-search]").text()).toBe(t("mem.import.searching"));
  });
});
