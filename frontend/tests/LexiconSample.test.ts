import { flushPromises, mount, type VueWrapper } from "@vue/test-utils";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import * as api from "@/api";
import { ApiError, type ReviewCue, type ReviewList } from "@/api";
import LexiconSample from "@/components/LexiconSample.vue";
import { t } from "@/i18n/de";
import { EVERYWHERE, SAMPLE_PAGE } from "@/lexiconStrata";

import { violations } from "./axe";
import { LABELS, REGION, SCHOOL, cueDecision, reviewCue } from "./lexiconFixtures";

const OTHER = SCHOOL + "re-DE-BY-ba9876543210";
const GONE = SCHOOL + "re-DE-NW-000000000000";
let shown: VueWrapper | null = null;

function review(changes: Partial<ReviewList> = {}): ReviewList {
  return {
    strata: [
      { sector: "school", regions: [REGION + "DE-BY"], cues: 30, sampled: 3, decided: 1 },
      { sector: "school", regions: [REGION + "DE-NW"], cues: 20, sampled: 2, decided: 0 },
    ],
    items: [
      reviewCue(),
      reviewCue({ iri: OTHER, surface_form: "Lernfeld", regions: [REGION + "DE-BY"], decision: cueDecision({ cue: OTHER }) }),
    ],
    retired: [],
    labels: LABELS,
    ...changes,
  };
}

async function section(): Promise<VueWrapper> {
  shown = mount(LexiconSample, { attachTo: document.body });
  await flushPromises();
  return shown;
}

const headings = (wrapper: VueWrapper) => wrapper.findAll("article h3").map((one) => one.text());
const filter = (wrapper: VueWrapper) => wrapper.get("[data-test=open-only]");

beforeEach(() => {
  vi.restoreAllMocks();
  // a fresh copy each time: a list read again is another object
  vi.spyOn(api, "getReview").mockImplementation(() => Promise.resolve(review()));
});

afterEach(() => {
  shown?.unmount();
  shown = null;
  document.body.innerHTML = "";
});

describe("the sample of the research's cues", () => {
  it("shows its strata in a table and each cue of the list", async () => {
    const wrapper = await section();

    expect(wrapper.get("h2").text()).toBe(t("lexicon.sample.heading"));
    expect(wrapper.get("caption").text()).toBe(t("lexicon.sample.strata"));
    // the scroll region named by the caption itself, not said twice
    expect(wrapper.get("[role=region]").attributes("aria-labelledby")).toBe(wrapper.get("caption").attributes("id"));
    expect(wrapper.get("[role=region]").attributes("aria-label")).toBeUndefined();
    const rows = wrapper.findAll("tbody tr").map((row) => row.findAll("th, td").map((cell) => cell.text()));
    expect(rows).toEqual([
      ["Schulbildung", "Bayern", "30", "3", "1"],
      ["Schulbildung", "Nordrhein-Westfalen", "20", "2", "0"],
    ]);
    // no row header: a sector stands in several rows, a row is told by its sector and regions together
    expect(wrapper.find("tbody th").exists()).toBe(false);
    expect(headings(wrapper)).toEqual(["„Inhaltsfeld“", "„Lernfeld“"]);
    expect(wrapper.find("[data-test=retired]").exists()).toBe(false);
    expect(await violations(wrapper.html())).toEqual([]);
  });

  it("says that it waits until the list comes", async () => {
    let answer: (list: ReviewList) => void = () => undefined;
    vi.spyOn(api, "getReview").mockReturnValueOnce(new Promise((resolve) => (answer = resolve)));
    shown = mount(LexiconSample, { attachTo: document.body });
    await flushPromises();
    expect(shown.get("[role=status]").text()).toBe(t("lexicon.sample.loading"));

    answer(review());
    await flushPromises();
    expect(headings(shown)).toHaveLength(2);
  });

  it("says a failed reading, and reads again on the reader's word", async () => {
    vi.spyOn(api, "getReview")
      .mockRejectedValueOnce(new ApiError("server", 503, "service_unavailable"))
      .mockResolvedValueOnce(review());
    const wrapper = await section();

    expect(wrapper.get("[role=alert]").text()).toContain(t("lexicon.sample.loadFailed"));
    await wrapper.get("[role=alert] button").trigger("click");
    await flushPromises();

    expect(headings(wrapper)).toHaveLength(2);
  });

  it("says where there is nothing to review", async () => {
    vi.spyOn(api, "getReview").mockResolvedValue(review({ strata: [], items: [] }));
    const wrapper = await section();

    expect(wrapper.text()).toContain(t("lexicon.sample.noneTitle"));
    expect(wrapper.find("table").exists()).toBe(false);
    expect(wrapper.find("[data-test=open-only]").exists()).toBe(false);
  });

  it("shows the decisions on retired cues where no stratum is left, with nothing to filter", async () => {
    const retired = cueDecision({ cue: GONE, retired: true, decision: "rejected", strength: null, applied: true });
    vi.spyOn(api, "getReview").mockResolvedValue(review({ strata: [], items: [], retired: [retired] }));
    const wrapper = await section();

    expect(wrapper.text()).not.toContain(t("lexicon.sample.noneTitle"));
    expect(wrapper.find("[data-test=retired] article").exists()).toBe(true);
    expect(wrapper.find("[data-test=open-only]").exists()).toBe(false);
  });

  it("names a stratum of no region as holding everywhere", async () => {
    const strata = [{ sector: "school", regions: [], cues: 4, sampled: 1, decided: 0 }];
    vi.spyOn(api, "getReview").mockResolvedValue(review({ strata }));
    const wrapper = await section();

    expect(wrapper.findAll("tbody td")[1].text()).toBe(t("lexicon.cue.everywhere"));
  });

  it("shows the open cues alone on the reader's word, and how many are open", async () => {
    const wrapper = await section();

    expect(filter(wrapper).attributes("aria-pressed")).toBe("false");
    expect(wrapper.get("[data-test=open-count]").text()).toBe("1 von 2 offen");
    await filter(wrapper).trigger("click");

    expect(filter(wrapper).attributes("aria-pressed")).toBe("true");
    expect(headings(wrapper)).toEqual(["„Inhaltsfeld“"]);
  });

  it("takes a decision made into the list and its stratum, and keeps the cue in sight while only open ones show", async () => {
    const made = cueDecision({ decision: "rejected", strength: null, evidence: null });
    vi.spyOn(api, "decideCue").mockResolvedValue(made);
    const wrapper = await section();
    await filter(wrapper).trigger("click");

    await wrapper.get("[data-test=decide]").trigger("click");
    await wrapper.get("input[value=rejected]").setValue(true);
    await wrapper.get("form").trigger("submit");
    await flushPromises();

    expect(headings(wrapper)).toEqual(["„Inhaltsfeld“"]);
    expect(wrapper.get("[data-test=decision]").text()).toContain(t("lexicon.cue.rejected"));
    expect(document.activeElement).toBe(wrapper.get("[data-test=decision]").element);
    expect(wrapper.findAll("tbody tr")[1].findAll("td").at(-1)?.text()).toBe("1");
    expect(wrapper.get("[data-test=open-count]").text()).toBe("0 von 2 offen");
  });

  it("lists the decisions on retired cues apart, as each was judged, decided again in place", async () => {
    const retired = cueDecision({ cue: GONE, retired: true, decision: "rejected", strength: null, applied: true });
    vi.spyOn(api, "getReview").mockImplementation(() => Promise.resolve(review({ retired: [retired] })));
    const made = { ...retired, decision: "confirmed" as const, strength: "0.8", applied: false };
    vi.spyOn(api, "decideCue").mockResolvedValue(made);
    const wrapper = await section();

    const part = wrapper.get("[data-test=retired]");
    expect(part.get("h3").text()).toBe(t("lexicon.sample.retiredHeading"));
    // its entries a level below its heading
    expect(part.findAll("article h4").map((one) => one.text())).toEqual(["„Inhaltsfeld“"]);
    await part.get("[data-test=decide]").trigger("click");
    await part.get("input[value=confirmed]").setValue(true);
    await part.get("select").setValue("0.80");
    await part.get("input[type=text]").setValue("KLP S. 3");
    await part.get("form").trigger("submit");
    await flushPromises();

    expect(part.get("[data-test=decision]").text()).toContain(t("lexicon.cue.retiredSince"));
    expect(await violations(wrapper.html())).toEqual([]);
  });

  it("reads the list again where a cue went meanwhile", async () => {
    vi.spyOn(api, "decideCue").mockRejectedValue(new ApiError("server", 404, "no_cue"));
    const wrapper = await section();
    await wrapper.get("[data-test=decide]").trigger("click");
    await wrapper.get("input[value=rejected]").setValue(true);
    await wrapper.get("form").trigger("submit");
    await flushPromises();

    await wrapper.get("[data-test=decision-reload]").trigger("click");
    await flushPromises();

    expect(api.getReview).toHaveBeenCalledTimes(2);
  });

  it("keeps a cue whose form holds what is not saved in sight when only the open ones show", async () => {
    const wrapper = await section();
    const decided = wrapper.findAll("article")[1]; // decided before, "Neu entscheiden"
    await decided.get("[data-test=decide]").trigger("click");
    await decided.get("textarea").setValue("doch prüfen");

    await filter(wrapper).trigger("click");

    expect(headings(wrapper)).toEqual(["„Inhaltsfeld“", "„Lernfeld“"]);
    expect(wrapper.get("textarea").element.value).toBe("doch prüfen");

    // left, the entry stays until the filter is set again: the keyboard back on its button
    await wrapper.get("[data-test=decision-cancel]").trigger("click");
    await flushPromises();
    expect(headings(wrapper)).toEqual(["„Inhaltsfeld“", "„Lernfeld“"]);
    expect(document.activeElement).toBe(wrapper.findAll("[data-test=decide]")[1].element);
    await filter(wrapper).trigger("click");
    await filter(wrapper).trigger("click");
    expect(headings(wrapper)).toEqual(["„Inhaltsfeld“"]);
  });

  it("keeps a cue in sight whose form holds input when the list read again says another decided it", async () => {
    // only the open ones shown, both open: one form holds a note, the other's cue went, so the list is read again
    const open = review({ items: [reviewCue(), reviewCue({ iri: OTHER, surface_form: "Lernfeld", regions: [REGION + "DE-BY"] })] });
    const later = review({ items: [reviewCue({ decision: cueDecision({ decided_by: "Andere Redaktion" }) })] });
    vi.spyOn(api, "getReview").mockResolvedValueOnce(open).mockResolvedValueOnce(later);
    vi.spyOn(api, "decideCue").mockRejectedValue(new ApiError("server", 404, "no_cue"));
    const wrapper = await section();
    await filter(wrapper).trigger("click");
    const [first, second] = wrapper.findAll("article");
    await first.get("[data-test=decide]").trigger("click");
    await first.get("textarea").setValue("noch zu klären");
    await second.get("[data-test=decide]").trigger("click");
    await second.get("input[value=rejected]").setValue(true);
    await second.get("form").trigger("submit");
    await flushPromises();

    await wrapper.get("[data-test=decision-reload]").trigger("click");
    await flushPromises();

    expect(headings(wrapper)).toEqual(["„Inhaltsfeld“"]);
    expect(wrapper.get("textarea").element.value).toBe("noch zu klären");
  });

  it("tells the page the form went when its cue left the list read again", async () => {
    vi.spyOn(api, "decideCue").mockRejectedValue(new ApiError("server", 404, "no_cue"));
    vi.spyOn(api, "getReview")
      .mockResolvedValueOnce(review())
      .mockResolvedValueOnce(review({ items: [review().items[1]] }));
    const wrapper = await section();
    await wrapper.get("[data-test=decide]").trigger("click");
    await wrapper.get("textarea").setValue("noch offen");
    await wrapper.get("input[value=rejected]").setValue(true);
    await wrapper.get("form").trigger("submit");
    await flushPromises();

    await wrapper.get("[data-test=decision-reload]").trigger("click");
    await flushPromises();

    expect(headings(wrapper)).toEqual(["„Lernfeld“"]);
    expect(wrapper.emitted("dirty")?.at(-1)).toEqual([false]);
  });

  it("tells the page while a form holds what is not saved", async () => {
    const wrapper = await section();
    await wrapper.get("[data-test=decide]").trigger("click");

    await wrapper.get("textarea").setValue("noch offen");
    await wrapper.get("[data-test=decision-cancel]").trigger("click");

    expect(wrapper.emitted("dirty")).toEqual([[true], [false]]);
  });
});

// 197 cues on one page, all of their buttons named alike (UI review M3)
describe("a long sample", () => {
  const many = (count: number, changes: (index: number) => Partial<ReviewCue> = () => ({})) =>
    Array.from({ length: count }, (_, index) =>
      reviewCue({ iri: `${SCHOOL}re-${index}`, surface_form: `Wort ${index + 1}`, ...changes(index) }),
    );
  const byLabel = (wrapper: VueWrapper, id: string) => wrapper.get(`[for=${id}]`).text();

  it("shows a page of cues at a time, the next one on the reader's word with the keyboard at its first cue", async () => {
    vi.spyOn(api, "getReview").mockImplementation(() => Promise.resolve(review({ items: many(SAMPLE_PAGE + 5) })));
    const wrapper = await section();
    expect(headings(wrapper)).toHaveLength(SAMPLE_PAGE);
    expect(wrapper.get("[data-test=shown-count]").text()).toBe(
      t("lexicon.sample.shownCount", { shown: SAMPLE_PAGE, total: SAMPLE_PAGE + 5 }),
    );

    await wrapper.get("[data-test=more-cues]").trigger("click");
    await flushPromises();

    expect(headings(wrapper)).toHaveLength(SAMPLE_PAGE + 5);
    expect(document.activeElement).toBe(wrapper.findAll("article h3")[SAMPLE_PAGE].element);
    expect(wrapper.find("[data-test=more-cues]").exists()).toBe(false);
  });

  it("shows the cues of one Bildungsbereich and one Land, a cue of no region under its own choice", async () => {
    const items = [
      reviewCue({ iri: `${SCHOOL}a`, surface_form: "Inhaltsfeld", regions: [REGION + "DE-NW"] }),
      reviewCue({ iri: `${SCHOOL}b`, surface_form: "Lernfeld", sector: "vocational", regions: [REGION + "DE-BY"] }),
      reviewCue({ iri: `${SCHOOL}c`, surface_form: "Kompetenz", regions: [] }),
    ];
    vi.spyOn(api, "getReview").mockImplementation(() => Promise.resolve(review({ items })));
    const wrapper = await section();
    expect(byLabel(wrapper, "lexicon-sector")).toBe(t("lexicon.sample.filter.sector"));
    expect(byLabel(wrapper, "lexicon-region")).toBe(t("lexicon.sample.filter.region"));
    const regionOptions = wrapper.findAll("#lexicon-region option").map((one) => one.text());
    expect(regionOptions).toEqual([t("lexicon.sample.filter.anyRegion"), "Bayern", "Nordrhein-Westfalen", t("lexicon.cue.everywhere")]);

    await wrapper.get("#lexicon-sector").setValue("school");
    expect(headings(wrapper)).toEqual(["„Inhaltsfeld“", "„Kompetenz“"]);
    await wrapper.get("#lexicon-region").setValue(EVERYWHERE);
    expect(headings(wrapper)).toEqual(["„Kompetenz“"]);
    await wrapper.get("#lexicon-region").setValue(REGION + "DE-BY");

    expect(headings(wrapper)).toEqual([]);
    expect(wrapper.text()).toContain(t("lexicon.sample.filter.none"));
    expect(await violations(wrapper.html())).toEqual([]);
  });

  it("starts again at the first page when the choice changes", async () => {
    vi.spyOn(api, "getReview").mockImplementation(() =>
      Promise.resolve(review({ items: many(SAMPLE_PAGE * 3, (index) => ({ sector: index % 2 ? "school" : "vocational" })) })),
    );
    const wrapper = await section();
    await wrapper.get("[data-test=more-cues]").trigger("click");
    await flushPromises();
    expect(headings(wrapper)).toHaveLength(SAMPLE_PAGE * 2);

    await wrapper.get("#lexicon-sector").setValue("school");

    expect(headings(wrapper)).toHaveLength(SAMPLE_PAGE);
  });

  // a form's input went without a question when the choice left its cue out (UI review 1, finding 1)
  it("keeps a cue whose form holds input in sight whatever the choice", async () => {
    const items = [
      reviewCue({ iri: `${SCHOOL}a`, surface_form: "Inhaltsfeld", regions: [REGION + "DE-NW"] }),
      reviewCue({ iri: `${SCHOOL}b`, surface_form: "Lernfeld", sector: "vocational", regions: [REGION + "DE-BY"] }),
    ];
    vi.spyOn(api, "getReview").mockImplementation(() => Promise.resolve(review({ items })));
    const wrapper = await section();
    const held = wrapper.findAll("article")[1];
    await held.get("[data-test=decide]").trigger("click");
    await held.get("textarea").setValue("noch prüfen");

    await wrapper.get("#lexicon-sector").setValue("school");

    expect(headings(wrapper)).toEqual(["„Inhaltsfeld“", "„Lernfeld“"]);
    expect(wrapper.get("textarea").element.value).toBe("noch prüfen");
    expect(wrapper.emitted("dirty")).toEqual([[true]]);

    // once left, the next choice takes it out
    await wrapper.get("[data-test=decision-cancel]").trigger("click");
    await wrapper.get("#lexicon-region").setValue(REGION + "DE-NW");
    expect(headings(wrapper)).toEqual(["„Inhaltsfeld“"]);
  });

  // kept only for its input, the cue went from under the keyboard once its form was left or saved (browser check 2,
  // defect 2): it stays until the choice changes again
  describe("a cue kept outside the choice for its input", () => {
    const items = () => [
      reviewCue({ iri: `${SCHOOL}a`, surface_form: "Inhaltsfeld", regions: [REGION + "DE-NW"] }),
      reviewCue({ iri: `${SCHOOL}b`, surface_form: "Lernfeld", sector: "vocational", regions: [REGION + "DE-BY"] }),
    ];

    async function heldOutside(): Promise<VueWrapper> {
      vi.spyOn(api, "getReview").mockImplementation(() => Promise.resolve(review({ items: items() })));
      const wrapper = await section();
      const held = wrapper.findAll("article")[1];
      await held.get("[data-test=decide]").trigger("click");
      await held.get("textarea").setValue("noch prüfen");
      await wrapper.get("#lexicon-sector").setValue("school");
      return wrapper;
    }

    it("stays when its form is left, the keyboard on its button, until the choice changes", async () => {
      const wrapper = await heldOutside();

      await wrapper.get("[data-test=decision-cancel]").trigger("click");
      await flushPromises();

      expect(headings(wrapper)).toEqual(["„Inhaltsfeld“", "„Lernfeld“"]);
      expect(document.activeElement).toBe(wrapper.findAll("article")[1].get("[data-test=decide]").element);
      await wrapper.get("#lexicon-region").setValue(REGION + "DE-NW");
      expect(headings(wrapper)).toEqual(["„Inhaltsfeld“"]);
    });

    it("stays when its decision is saved, the keyboard on the decision, and the status says it was saved", async () => {
      const made = cueDecision({ cue: `${SCHOOL}b`, decision: "rejected", strength: null, evidence: null });
      vi.spyOn(api, "decideCue").mockResolvedValue(made);
      const wrapper = await heldOutside();
      const held = wrapper.findAll("article")[1];

      await held.get("input[value=rejected]").setValue(true);
      await held.get("form").trigger("submit");
      await flushPromises();

      expect(headings(wrapper)).toEqual(["„Inhaltsfeld“", "„Lernfeld“"]);
      expect(document.activeElement).toBe(wrapper.findAll("article")[1].get("[data-test=decision]").element);
      expect(wrapper.get("[data-test=choice-status]").text()).toBe(
        `${t("lexicon.sample.saved")} ${t("lexicon.sample.keptOutside")}`,
      );
      await wrapper.get("#lexicon-sector").setValue("vocational");
      await wrapper.get("#lexicon-sector").setValue("school");
      expect(headings(wrapper)).toEqual(["„Inhaltsfeld“"]);
    });

    it("is counted with the cues it stands among", async () => {
      vi.spyOn(api, "getReview").mockImplementation(() =>
        Promise.resolve(review({ items: [...items(), ...many(SAMPLE_PAGE, () => ({ regions: [REGION + "DE-NW"] }))] })),
      );
      const wrapper = await section();
      const held = wrapper.findAll("article")[1];
      await held.get("[data-test=decide]").trigger("click");
      await held.get("textarea").setValue("noch prüfen");

      await wrapper.get("#lexicon-sector").setValue("school");

      // one open cue more among the shown than in the choice: both counts say the same total
      const total = SAMPLE_PAGE + 2;
      expect(wrapper.get("[data-test=open-count]").text()).toBe(t("lexicon.list.openCount", { open: total, total }));
      expect(wrapper.get("[data-test=shown-count]").text()).toBe(t("lexicon.sample.shownCount", { shown: SAMPLE_PAGE, total }));
    });
  });

  it("keeps the page down to a cue whose form holds input when only the open ones are asked for", async () => {
    vi.spyOn(api, "getReview").mockImplementation(() => Promise.resolve(review({ items: many(SAMPLE_PAGE * 2) })));
    const wrapper = await section();
    await wrapper.get("[data-test=more-cues]").trigger("click");
    await flushPromises();
    const held = wrapper.findAll("article")[SAMPLE_PAGE + 10];
    await held.get("[data-test=decide]").trigger("click");
    await held.get("textarea").setValue("noch prüfen");

    await filter(wrapper).trigger("click");

    expect(headings(wrapper)).toHaveLength(SAMPLE_PAGE + 11);
    expect(wrapper.get("textarea").element.value).toBe("noch prüfen");
    expect(wrapper.emitted("dirty")).toEqual([[true]]);
  });

  // a reader changing the choice heard nothing of what it left (UI review 1, finding 10)
  it("says what a choice leaves in a status region that is there from the start", async () => {
    const items = [
      reviewCue({ iri: `${SCHOOL}a`, surface_form: "Inhaltsfeld", regions: [REGION + "DE-NW"] }),
      reviewCue({ iri: `${SCHOOL}b`, surface_form: "Lernfeld", sector: "vocational", regions: [REGION + "DE-BY"] }),
    ];
    vi.spyOn(api, "getReview").mockImplementation(() => Promise.resolve(review({ items })));
    const wrapper = await section();
    const status = wrapper.get("[data-test=choice-status]");
    expect(status.attributes("role")).toBe("status");
    expect(status.text()).toBe("");

    await wrapper.get("#lexicon-sector").setValue("school");
    expect(status.text()).toBe(t("lexicon.list.openCount", { open: 1, total: 1 }));

    await wrapper.get("#lexicon-region").setValue(REGION + "DE-BY");
    expect(status.text()).toBe(t("lexicon.sample.filter.none"));
  });

  it("names each button to decide by its cue", async () => {
    const wrapper = await section();

    const named = wrapper.findAll("[data-test=decide]").map((button) =>
      (button.attributes("aria-labelledby") ?? "")
        .split(" ")
        .map((id) => document.getElementById(id)?.textContent?.trim())
        .join(" "),
    );
    expect(named).toEqual([
      `${t("lexicon.item.decide")} „Inhaltsfeld“ Schulbildung · Nordrhein-Westfalen · ${t("lexicon.cue.inSample")}`,
      `${t("lexicon.item.decideAgain")} „Lernfeld“ Schulbildung · Bayern · ${t("lexicon.cue.inSample")}`,
    ]);
  });

  // six pairs of cues shared one name: the word alone does not tell them apart (browser check 2, NIT 7)
  it("tells two buttons apart whose cues share a word, by where each holds", async () => {
    const items = [
      reviewCue({ iri: `${SCHOOL}a`, surface_form: "Grundkurs", regions: [REGION + "DE-NW"] }),
      reviewCue({ iri: `${SCHOOL}b`, surface_form: "Grundkurs", regions: [REGION + "DE-BY"] }),
      reviewCue({ iri: `${SCHOOL}c`, surface_form: "Grundkurs", sector: "vocational", regions: [REGION + "DE-BY"] }),
    ];
    vi.spyOn(api, "getReview").mockImplementation(() => Promise.resolve(review({ items })));
    const wrapper = await section();

    const named = wrapper.findAll("[data-test=decide]").map((button) =>
      (button.attributes("aria-labelledby") ?? "")
        .split(" ")
        .map((id) => document.getElementById(id)?.textContent?.trim())
        .join(" "),
    );
    expect(new Set(named).size).toBe(3);
  });
});
