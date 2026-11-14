import { flushPromises, mount, RouterLinkStub, type VueWrapper } from "@vue/test-utils";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import * as api from "@/api";
import type { FormValue, NewTerm } from "@/api";
import { isolate } from "@/bidi";
import LexiconTermItem from "@/components/LexiconTermItem.vue";
import { momentFormat, t } from "@/i18n/de";
import { goneTerm } from "@/lexiconReview";
import type { Targets } from "@/lexiconTargets";

import { violations } from "./axe";
import { CV, DOCUMENT, LABELS, REGION, SCHOOL, heldCue, newTerm, nodeType, termDecision } from "./lexiconFixtures";

const AREA = nodeType("Inhaltsbereich", [CV + "fn_area"]);
const WITH_FUNCTIONS = { ...LABELS, [CV + "fn_area"]: "Bereich" };
let shown: VueWrapper | null = null;
let targets = vi.fn<Targets>();

function item(term: NewTerm = newTerm(), gone = false): VueWrapper {
  shown = mount(LexiconTermItem, {
    props: { term, labels: WITH_FUNCTIONS, gone, targets },
    global: { stubs: { RouterLink: RouterLinkStub } },
    attachTo: document.body,
  });
  return shown;
}

const toggle = (wrapper: VueWrapper) => wrapper.get("[data-test=decide]");
const row = (wrapper: VueWrapper, name: string) => {
  const found = wrapper.findAll("dl > div").find((one) => one.get("dt").text() === name);
  if (!found) throw new Error(name);
  return found.get("dd");
};

beforeEach(() => {
  vi.restoreAllMocks();
  targets = vi.fn<Targets>(() => Promise.resolve<FormValue[]>([AREA]));
});

afterEach(() => {
  shown?.unmount();
  shown = null;
  document.body.innerHTML = "";
});

describe("a term X1 found no type for", () => {
  it("names its word, where and in how many documents, and the functions suggested", () => {
    const wrapper = item();

    expect(wrapper.get("h3").text()).toBe("„Lernbereich“");
    expect(wrapper.get("[data-test=where]").text()).toBe("Schulbildung · Nordrhein-Westfalen · in 2 Dokumenten");
    expect(row(wrapper, t("lexicon.term.functions")).text()).toBe("Bereich");
    expect(wrapper.get("[data-test=decision]").text()).toBe(t("lexicon.item.undecided"));
  });

  it("leads to the documents that name it, with what X1 suggested there, and counts the others", () => {
    const wrapper = item(newTerm({ documents: 4 }));

    const links = wrapper.findAllComponents(RouterLinkStub);
    expect(links.map((link) => [link.text(), link.props("to")])).toEqual([
      ["Kernlehrplan Physik", { name: "document", params: { id: DOCUMENT } }],
      [t("documents.untitled"), { name: "document", params: { id: "0190-0000-0000-7000-8000-000000000002" } }],
    ]);
    const places = row(wrapper, t("lexicon.term.places")).findAll("li").map((one) => one.text());
    expect(places[0]).toContain(t("lexicon.term.placeFunction", { function: "Bereich" }));
    expect(places.at(-1)).toBe("und 2 weitere Dokumente");
  });

  it("counts a document named twice among its places once", () => {
    const twice = { document: DOCUMENT, title: "Kernlehrplan Physik", block: "p9-b1", function: null };

    const wrapper = item(newTerm({ documents: 2, occurrences: [newTerm().occurrences[0], twice] }));

    expect(row(wrapper, t("lexicon.term.places")).findAll("li").at(-1)?.text()).toBe("und 1 weiteres Dokument");
  });

  it("names the cues that hold its word already, the own lexicon's and the research's", () => {
    const research = heldCue({
      iri: SCHOOL + "re-DE-BY-1",
      own: false,
      regions: [REGION + "DE-BY"],
      role: CV + "role_alt",
    });
    const pattern = heldCue({ by_word: false, surface_form: null, pattern: "^Lernbereich\\s+\\d+" });

    const wrapper = item(newTerm({ held: [heldCue(), pattern, research] }));

    const held = row(wrapper, t("lexicon.term.held")).findAll("li").map((one) => one.text());
    expect(held[0]).toBe("„Lernbereich“ → Inhaltsbereich · Hinweis (kein Synonym) · eigenes Lexikon · bundesweit");
    expect(held[1]).toContain(`${t("lexicon.cue.pattern")} ^Lernbereich\\s+\\d+`);
    expect(held[2]).toBe("„Lernbereich“ → Inhaltsbereich · echtes Synonym · Länderrecherche · Bayern");
  });

  it("says its decision, and whether the files hold the new cue, or the import leaves it out", () => {
    const decision = termDecision({ note: "wie in BY" });
    const date = momentFormat.format(new Date("2026-11-01T10:00:00Z"));

    const said = item(newTerm({ decision })).get("[data-test=decision]").text();
    expect(said).toContain(t("lexicon.term.cue", { target: "Inhaltsbereich", role: t("lexicon.termForm.roles.alt") }));
    expect(said).toContain(t("lexicon.item.by", { name: isolate("Redaktion"), date }));
    expect(said).toContain(t("lexicon.item.note", { note: isolate("wie in BY") }));
    expect(said).toContain(t("lexicon.item.waiting"));
    shown?.unmount();

    expect(item(newTerm({ decision: termDecision({ applied: true }) })).get("[data-test=decision]").text()).toContain(t("lexicon.term.applied"));
    shown?.unmount();
    const held = [heldCue()];
    expect(item(newTerm({ decision, held })).get("[data-test=decision]").text()).toContain(t("lexicon.term.skipped.word"));
    shown?.unmount();
    const pattern = [heldCue({ by_word: false, surface_form: null, pattern: "^Lernbereich", maps_to: [decision.maps_to ?? ""] })];
    expect(item(newTerm({ decision, held: pattern })).get("[data-test=decision]").text()).toContain(
      t("lexicon.term.skipped.pattern"),
    );
  });

  it("says a term peculiar to its document, or misread, with nothing to take into the files", () => {
    const said = item(newTerm({ decision: termDecision({ decision: "error", maps_to: null, role: null, applied: null }) }))
      .get("[data-test=decision]")
      .text();

    expect(said).toContain(t("lexicon.term.error"));
    expect(said).not.toContain(t("lexicon.item.waiting"));
  });

  it("opens its form on the reader's word, a decision made taking the keyboard once it shows", async () => {
    const made = termDecision({ decision: "document", maps_to: null, role: null, applied: null });
    vi.spyOn(api, "decideTerm").mockResolvedValue(made);
    const wrapper = item();

    await toggle(wrapper).trigger("click");
    expect(toggle(wrapper).attributes("aria-expanded")).toBe("true");
    expect(await violations(wrapper.html())).toEqual([]);
    await wrapper.get("input[value=document]").setValue(true);
    await wrapper.get("form").trigger("submit");
    await flushPromises();
    expect(wrapper.emitted("decided")).toEqual([[made, {}]]); // no target, no label to bring
    await wrapper.setProps({ term: newTerm({ decision: made }) });
    await flushPromises();

    expect(wrapper.find("form").exists()).toBe(false);
    expect(wrapper.emitted("dirty")?.at(-1)).toEqual([false]);
    expect(document.activeElement).toBe(wrapper.get("[data-test=decision]").element);
  });

  it("sends the term by its sector, regions and word alone, as the server takes a decision", async () => {
    const sent = vi.spyOn(api, "decideTerm").mockResolvedValue(termDecision());
    const wrapper = item(newTerm({ held: [heldCue()], decision: termDecision({ decision: "error" }) }));
    await toggle(wrapper).trigger("click");
    await wrapper.get("input[value=cue]").setValue(true);
    await flushPromises();
    await wrapper.findAll("select")[0].setValue(AREA.iri);
    await wrapper.findAll("select")[1].setValue("alt");

    await wrapper.get("form").trigger("submit");
    await flushPromises();

    // the list's term carries its places, counts and decision: none of that is the body (extra forbid)
    expect(sent.mock.calls).toEqual([
      [{ sector: "school", regions: ["DE-NW"], term: "Lernbereich", decision: "cue", maps_to: AREA.iri, role: "alt", note: null }],
    ]);
  });

  it("takes the keyboard back to its button when the form is left", async () => {
    const wrapper = item();
    await toggle(wrapper).trigger("click");

    await wrapper.get("[data-test=decision-cancel]").trigger("click");
    await flushPromises();

    expect(document.activeElement).toBe(toggle(wrapper).element);
  });

  it("hands on a wish to read the list again", async () => {
    const wrapper = item();
    await toggle(wrapper).trigger("click");

    wrapper.getComponent({ name: "TermDecisionForm" }).vm.$emit("reload");

    expect(wrapper.emitted("reload")).toHaveLength(1);
  });

  it("shows a term gone as it was judged, named by no document now", () => {
    const wrapper = item(goneTerm(termDecision()), true);

    expect(wrapper.get("[data-test=where]").text()).toBe(`Schulbildung · Nordrhein-Westfalen · ${t("lexicon.term.gone")}`);
    expect(wrapper.findAll("dl > div").map((one) => one.get("dt").text())).toEqual([t("lexicon.term.functions")]);
  });
});
