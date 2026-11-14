import { flushPromises, mount, type VueWrapper } from "@vue/test-utils";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { defineComponent, h } from "vue";
import { createMemoryHistory, createRouter, RouterView, type Router } from "vue-router";

import * as api from "@/api";
import { ApiError, type ReviewList, type TermsList } from "@/api";
import { t } from "@/i18n/de";
import { refusalText } from "@/refusals";
import LexiconReviewView from "@/views/LexiconReviewView.vue";

import { REGION, newTerm, reviewCue, LABELS } from "./lexiconFixtures";

let shown: VueWrapper | null = null;

const SAMPLE: ReviewList = {
  strata: [{ sector: "school", regions: [REGION + "DE-NW"], cues: 10, sampled: 1, decided: 0 }],
  items: [reviewCue()],
  retired: [],
  labels: LABELS,
};
const TERMS: TermsList = { terms: [newTerm()], gone: [], labels: LABELS };

async function page(): Promise<{ wrapper: VueWrapper; router: Router }> {
  const router = createRouter({
    history: createMemoryHistory(),
    routes: [
      { path: "/lexikon", name: "lexicon", component: LexiconReviewView },
      { path: "/elsewhere", name: "elsewhere", component: defineComponent({ render: () => h("p", "elsewhere") }) },
      // where an entry's place leads
      { path: "/dokumente/:id", name: "document", component: defineComponent({ render: () => h("p", "document") }) },
    ],
  });
  await router.push("/lexikon");
  shown = mount(RouterView, { global: { plugins: [router] }, attachTo: document.body });
  await flushPromises();
  return { wrapper: shown, router };
}

const sections = (wrapper: VueWrapper) => wrapper.findAll("h2").map((one) => one.text());

beforeEach(() => {
  vi.restoreAllMocks();
  vi.spyOn(api, "getReview").mockImplementation(() => Promise.resolve(structuredClone(SAMPLE)));
  vi.spyOn(api, "getTerms").mockImplementation(() => Promise.resolve(structuredClone(TERMS)));
});

afterEach(() => {
  shown?.unmount();
  shown = null;
  document.body.innerHTML = "";
});

describe("the editors' review of the lexicon", () => {
  it("names itself and shows the sample and the new terms, each in its section", async () => {
    const { wrapper } = await page();

    expect(wrapper.get("h1").text()).toBe(t("lexicon.page.heading"));
    expect(wrapper.text()).toContain(t("lexicon.page.intro"));
    expect(sections(wrapper)).toEqual([t("lexicon.sample.heading"), t("lexicon.terms.heading")]);
    expect(wrapper.findAll("article")).toHaveLength(2);
  });

  it("leads to each of its sections from its top, the second one far down a long sample", async () => {
    const { wrapper } = await page();

    const nav = wrapper.get("nav");
    expect(nav.attributes("aria-label")).toBe(t("lexicon.page.sections"));
    const links = nav.findAll("a").map((link) => [link.text(), link.attributes("href")]);
    expect(links).toEqual([
      [t("lexicon.sample.heading"), "#lexicon-sample"],
      [t("lexicon.terms.heading"), "#lexicon-terms"],
    ]);
    // each lands on its section's heading, which takes the keyboard
    for (const [, href] of links) expect(wrapper.get(String(href)).attributes("tabindex")).toBe("-1");
  });

  it("shows one section where the other did not come", async () => {
    vi.spyOn(api, "getReview").mockRejectedValue(new ApiError("server", 503, "service_unavailable"));
    const { wrapper } = await page();

    expect(wrapper.get("[role=alert]").text()).toContain(t("lexicon.sample.loadFailed"));
    expect(wrapper.findAll("article h3").map((one) => one.text())).toEqual(["„Lernbereich“"]);
  });

  it("says in its words that the lexicon is the editors' where the server refuses an account", async () => {
    vi.spyOn(api, "getReview").mockRejectedValue(new ApiError("forbidden", 403, "not_editor"));
    vi.spyOn(api, "getTerms").mockRejectedValue(new ApiError("forbidden", 403, "not_editor"));
    const { wrapper } = await page();

    const alerts = wrapper.findAll("[role=alert]").map((one) => one.text());
    expect(alerts).toHaveLength(2);
    for (const said of alerts) expect(said).toContain(refusalText("not_editor"));
  });

  it("lets the reader go while no form holds what is not saved", async () => {
    const { wrapper, router } = await page();
    await wrapper.get("[data-test=decide]").trigger("click");

    await router.push("/elsewhere");
    await flushPromises();

    expect(router.currentRoute.value.name).toBe("elsewhere");
  });

  it("asks before a decision not saved goes, in either section, and stays on the reader's word", async () => {
    const { wrapper, router } = await page();
    const terms = wrapper.findAll("section")[1];
    await terms.get("[data-test=decide]").trigger("click");
    await terms.get("textarea").setValue("noch zu klären");

    void router.push("/elsewhere");
    await flushPromises();
    const dialog = wrapper.get("[role=dialog]");
    expect(dialog.text()).toContain(t("lexicon.page.leave.message"));
    await dialog.findAll("button").find((one) => one.text() === t("lexicon.page.leave.cancel"))?.trigger("click");
    await flushPromises();
    expect(router.currentRoute.value.name).toBe("lexicon");
    expect(terms.get("textarea").element.value).toBe("noch zu klären");

    void router.push("/elsewhere");
    await flushPromises();
    await wrapper.get("[role=dialog]").findAll("button").find((one) => one.text() === t("lexicon.page.leave.confirm"))?.trigger("click");
    await flushPromises();
    expect(router.currentRoute.value.name).toBe("elsewhere");
  });

  it("asks of the sample's form as well", async () => {
    const { wrapper, router } = await page();
    const sample = wrapper.findAll("section")[0];
    await sample.get("[data-test=decide]").trigger("click");
    await sample.get("textarea").setValue("prüfen");

    void router.push("/elsewhere");
    await flushPromises();

    expect(wrapper.find("[role=dialog]").exists()).toBe(true);
    expect(router.currentRoute.value.name).toBe("lexicon");
  });
});
