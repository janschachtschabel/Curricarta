import { flushPromises, mount, type VueWrapper } from "@vue/test-utils";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import * as api from "@/api";
import type { ReviewCue } from "@/api";
import LexiconCueItem from "@/components/LexiconCueItem.vue";
import { isolate } from "@/bidi";
import { momentFormat, t } from "@/i18n/de";
import { judgedCue } from "@/lexiconReview";

import { violations } from "./axe";
import { CV, LABELS, REGION, SCHOOL, cueDecision, reviewCue } from "./lexiconFixtures";

let shown: VueWrapper | null = null;

function item(cue: ReviewCue = reviewCue(), retired = false): VueWrapper {
  shown = mount(LexiconCueItem, { props: { item: cue, labels: LABELS, retired }, attachTo: document.body });
  return shown;
}

const toggle = (wrapper: VueWrapper) => wrapper.get("[data-test=decide]");
const facts = (wrapper: VueWrapper) =>
  Object.fromEntries(wrapper.findAll("dl > div").map((row) => [row.get("dt").text(), row.get("dd").text()]));

beforeEach(() => {
  vi.restoreAllMocks();
});

afterEach(() => {
  shown?.unmount();
  shown = null;
  document.body.innerHTML = "";
});

describe("a cue of the sample", () => {
  it("names its word, where it holds and what it says, by the labels of its concepts", () => {
    const wrapper = item(reviewCue({ maps_to: [SCHOOL + "Inhaltsbereich", "https://w3id.org/wlo/curriculum/core#Node"] }));

    expect(wrapper.get("h3").text()).toBe("„Inhaltsfeld“");
    expect(wrapper.get("[data-test=where]").text()).toBe("Schulbildung · Nordrhein-Westfalen · in der Stichprobe");
    expect(facts(wrapper)).toEqual({
      [t("lexicon.cue.role")]: "echtes Synonym",
      [t("lexicon.cue.kind")]: "Wort",
      // a class of the core has no label: its IRI's last part
      [t("lexicon.cue.targets")]: "Inhaltsbereich und Node",
      [t("lexicon.cue.strength")]: "0,70 · ungeprüft",
      [t("lexicon.cue.notes")]: "Beleg E: Kernlehrplan Physik, S. 14",
      [t("lexicon.cue.examples")]: "Inhaltsfeld 1: Energie",
      [t("lexicon.cue.sources")]: "recherche-ergebnisse/schule-nw.md",
    });
    expect(wrapper.get("[data-test=decision]").text()).toBe(t("lexicon.item.undecided"));
    expect(toggle(wrapper).text()).toBe(t("lexicon.item.decide"));
  });

  it("names a pattern as one, and a cue of no region as holding everywhere", () => {
    const wrapper = item(
      reviewCue({ surface_form: null, pattern: "^Inhaltsfeld\\s+\\d+", regions: [], sampled: false, kind: CV + "ck_headingPattern" }),
    );

    expect(wrapper.get("h3").text()).toBe(`${t("lexicon.cue.pattern")} ^Inhaltsfeld\\s+\\d+`);
    expect(wrapper.find("h3 code").exists()).toBe(true);
    expect(wrapper.get("[data-test=where]").text()).toBe("Schulbildung · bundesweit · entschieden, außerhalb der Stichprobe");
  });

  it("says its decision: who made it, when, and whether the files hold it yet", () => {
    const wrapper = item(reviewCue({ decision: cueDecision({ note: "auch in HE", applied: true }) }));

    const said = wrapper.get("[data-test=decision]").text();
    // what a reader wrote, set apart from the sentence it stands in
    expect(said).toContain(t("lexicon.cue.confirmed", { strength: "0,90", evidence: isolate("KLP S. 14") }));
    const date = momentFormat.format(new Date("2026-11-01T10:00:00Z"));
    expect(said).toContain(t("lexicon.item.by", { name: isolate("Redaktion"), date }));
    expect(said).toContain(t("lexicon.item.note", { note: isolate("auch in HE") }));
    expect(said).toContain(t("lexicon.cue.appliedConfirmed"));
    expect(toggle(wrapper).text()).toBe(t("lexicon.item.decideAgain"));
  });

  it("says a rejection, and that it waits for the export until the files drop the cue", () => {
    const decision = cueDecision({ decision: "rejected", strength: null, evidence: null });

    expect(item(reviewCue({ decision })).get("[data-test=decision]").text()).toContain(
      `${t("lexicon.cue.rejected")} `,
    );
    expect(shown?.get("[data-test=decision]").text()).toContain(t("lexicon.item.waiting"));
  });

  it("opens its form on the reader's word, and closes it again with the keyboard back on the button", async () => {
    const wrapper = item();

    expect(toggle(wrapper).attributes("aria-expanded")).toBe("false");
    expect(wrapper.find("form").exists()).toBe(false);
    await toggle(wrapper).trigger("click");
    expect(toggle(wrapper).attributes("aria-expanded")).toBe("true");
    expect(wrapper.get(`#${toggle(wrapper).attributes("aria-controls")}`).find("form").exists()).toBe(true);
    expect(await violations(wrapper.html())).toEqual([]);

    await wrapper.get("[data-test=decision-cancel]").trigger("click");
    await flushPromises();

    expect(wrapper.find("form").exists()).toBe(false);
    expect(document.activeElement).toBe(toggle(wrapper).element);
    expect(wrapper.emitted("dirty")?.at(-1)).toEqual([false]);
  });

  it("says the form holds nothing any more once its button closes it", async () => {
    const wrapper = item();
    await toggle(wrapper).trigger("click");
    await wrapper.get("textarea").setValue("noch offen");

    await toggle(wrapper).trigger("click");

    expect(wrapper.find("form").exists()).toBe(false);
    expect(wrapper.emitted("dirty")).toEqual([[true], [false]]);
  });

  it("says the form holds nothing any more when the entry goes with it", async () => {
    // test-utils drops a wrapper's event history on unmount: a listener hears what the unmount says
    const dirty = vi.fn();
    const wrapper = item();
    await wrapper.setProps({ onDirty: dirty });
    await toggle(wrapper).trigger("click");
    await wrapper.get("textarea").setValue("noch offen");
    expect(wrapper.emitted("dirty")).toEqual([[true]]);

    wrapper.unmount();
    shown = null;

    expect(dirty).toHaveBeenLastCalledWith(false);
  });

  it("hands a decision made on, and once it shows, takes the keyboard to it", async () => {
    const made = cueDecision({ decision: "rejected", strength: null, evidence: null });
    vi.spyOn(api, "decideCue").mockResolvedValue(made);
    const wrapper = item();
    await toggle(wrapper).trigger("click");
    await wrapper.get("input[value=rejected]").setValue(true);

    await wrapper.get("form").trigger("submit");
    await flushPromises();
    expect(wrapper.emitted("decided")).toEqual([[made]]);
    await wrapper.setProps({ item: reviewCue({ decision: made }) });
    await flushPromises();

    expect(wrapper.find("form").exists()).toBe(false);
    expect(wrapper.emitted("dirty")?.at(-1)).toEqual([false]); // the form went with what it held
    expect(document.activeElement).toBe(wrapper.get("[data-test=decision]").element);
    expect(wrapper.get("[data-test=decision]").text()).toContain(t("lexicon.cue.rejected"));
  });

  it("leaves the keyboard where the reader took it while the decision was saved", async () => {
    const made = cueDecision({ decision: "rejected", strength: null, evidence: null });
    vi.spyOn(api, "decideCue").mockResolvedValue(made);
    const wrapper = item();
    const elsewhere = document.body.appendChild(document.createElement("button"));
    await toggle(wrapper).trigger("click");
    await wrapper.get("input[value=rejected]").setValue(true);
    await wrapper.get("form").trigger("submit");
    await flushPromises();

    elsewhere.focus(); // on to the next entry meanwhile
    await wrapper.setProps({ item: reviewCue({ decision: made }) });
    await flushPromises();

    expect(document.activeElement).toBe(elsewhere);
  });

  it("leaves the keyboard where it is when a decision it did not make shows", async () => {
    vi.spyOn(api, "decideCue").mockResolvedValue(cueDecision());
    const wrapper = item();
    // a decision made here, shown, the keyboard back on the button
    await toggle(wrapper).trigger("click");
    await wrapper.get("input[value=rejected]").setValue(true);
    await wrapper.get("form").trigger("submit");
    await flushPromises();
    await wrapper.setProps({ item: reviewCue({ decision: cueDecision() }) });
    await flushPromises();
    (toggle(wrapper).element as HTMLElement).focus();

    // the list read again: another's decision since
    await wrapper.setProps({ item: reviewCue({ decision: cueDecision({ decided_by: "Andere Redaktion" }) }) });
    await flushPromises();

    expect(document.activeElement).toBe(toggle(wrapper).element);
  });

  it("leaves the keyboard where it is when its first decision comes from the list", async () => {
    const wrapper = item();
    (toggle(wrapper).element as HTMLElement).focus();

    await wrapper.setProps({ item: reviewCue({ decision: cueDecision() }) });
    await flushPromises();

    expect(document.activeElement).toBe(toggle(wrapper).element);
  });

  it("hands on a wish to read the list again", async () => {
    const wrapper = item();
    await toggle(wrapper).trigger("click");

    wrapper.getComponent({ name: "CueDecisionForm" }).vm.$emit("reload");

    expect(wrapper.emitted("reload")).toHaveLength(1);
  });

  it("shows a retired cue as it was judged, and that it is retired", () => {
    const decision = cueDecision({ retired: true, applied: false });

    const wrapper = item(judgedCue(decision), true);

    expect(wrapper.get("h3").text()).toBe("„Inhaltsfeld“");
    expect(wrapper.get("[data-test=where]").text()).toBe(`Nordrhein-Westfalen · ${t("lexicon.cue.retired")}`);
    expect(Object.keys(facts(wrapper))).toEqual([t("lexicon.cue.role"), t("lexicon.cue.kind"), t("lexicon.cue.targets")]);
    expect(wrapper.get("[data-test=decision]").text()).toContain(t("lexicon.cue.retiredSince"));
  });

  it("stands a level below a heading of its list where it is told to", () => {
    shown = mount(LexiconCueItem, { props: { item: reviewCue(), labels: LABELS, level: 4 }, attachTo: document.body });

    expect(shown.get("article h4").text()).toBe("„Inhaltsfeld“");
    expect(shown.find("h3").exists()).toBe(false);
  });

  it("names its regions together, in their order", () => {
    const wrapper = item(reviewCue({ regions: [REGION + "DE-BY", REGION + "DE-NW"] }));

    expect(wrapper.get("[data-test=where]").text()).toContain("Bayern und Nordrhein-Westfalen");
  });
});
