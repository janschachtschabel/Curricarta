import { flushPromises, mount, RouterLinkStub, type VueWrapper } from "@vue/test-utils";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import * as api from "@/api";
import { ApiError, type Form, type TermsList } from "@/api";
import LexiconTerms from "@/components/LexiconTerms.vue";
import { t } from "@/i18n/de";

import { violations } from "./axe";
import { CV, LABELS, SCHOOL, newTerm, nodeType, termDecision } from "./lexiconFixtures";
import { NO_VALUES_FORM } from "./treeFixtures";

const AREA = nodeType("Inhaltsbereich", [CV + "fn_area"]);
let shown: VueWrapper | null = null;

function list(changes: Partial<TermsList> = {}): TermsList {
  return {
    terms: [newTerm(), newTerm({ term: "Leitidee", decision: termDecision({ term: "Leitidee", decision: "error", maps_to: null, role: null }) })],
    gone: [],
    labels: LABELS,
    ...changes,
  };
}

const FORM: Form = {
  sector: "school",
  profile: SCHOOL + "Terminology",
  node: [{ key: "node_type", kind: "concept", required: false, many: false, most: null, values: [AREA] }],
  statement: [],
  ...NO_VALUES_FORM,
};

async function section(): Promise<VueWrapper> {
  shown = mount(LexiconTerms, { global: { stubs: { RouterLink: RouterLinkStub } }, attachTo: document.body });
  await flushPromises();
  return shown;
}

const headings = (wrapper: VueWrapper) => wrapper.findAll("article h3").map((one) => one.text());
const filter = (wrapper: VueWrapper) => wrapper.get("[data-test=open-only]");

async function decideFirst(wrapper: VueWrapper, decision = "document"): Promise<void> {
  await wrapper.get("[data-test=decide]").trigger("click");
  await wrapper.get(`input[value=${decision}]`).setValue(true);
  await wrapper.get("form").trigger("submit");
  await flushPromises();
}

beforeEach(() => {
  vi.restoreAllMocks();
  // a fresh copy each time: a list read again is another object
  vi.spyOn(api, "getTerms").mockImplementation(() => Promise.resolve(list()));
  vi.spyOn(api, "getForm").mockResolvedValue(FORM);
});

afterEach(() => {
  shown?.unmount();
  shown = null;
  document.body.innerHTML = "";
});

describe("the terms X1 found no type for", () => {
  it("lists each term with its decision", async () => {
    const wrapper = await section();

    expect(wrapper.get("h2").text()).toBe(t("lexicon.terms.heading"));
    expect(headings(wrapper)).toEqual(["„Lernbereich“", "„Leitidee“"]);
    expect(wrapper.get("[data-test=open-count]").text()).toBe("1 von 2 offen");
    expect(wrapper.find("[data-test=gone]").exists()).toBe(false);
    expect(await violations(wrapper.html())).toEqual([]);
  });

  it("says that it waits until the list comes", async () => {
    let answer: (found: TermsList) => void = () => undefined;
    vi.spyOn(api, "getTerms").mockReturnValueOnce(new Promise((resolve) => (answer = resolve)));
    shown = mount(LexiconTerms, { global: { stubs: { RouterLink: RouterLinkStub } }, attachTo: document.body });
    await flushPromises();
    expect(shown.get("[role=status]").text()).toBe(t("lexicon.terms.loading"));

    answer(list());
    await flushPromises();
    expect(headings(shown)).toHaveLength(2);
  });

  it("says a failed reading, and reads again on the reader's word", async () => {
    vi.spyOn(api, "getTerms")
      .mockRejectedValueOnce(new ApiError("server", 503, "service_unavailable"))
      .mockResolvedValueOnce(list());
    const wrapper = await section();

    expect(wrapper.get("[role=alert]").text()).toContain(t("lexicon.terms.loadFailed"));
    await wrapper.get("[role=alert] button").trigger("click");
    await flushPromises();

    expect(headings(wrapper)).toHaveLength(2);
  });

  it("says where there is nothing to decide", async () => {
    vi.spyOn(api, "getTerms").mockResolvedValue(list({ terms: [] }));
    const wrapper = await section();

    expect(wrapper.text()).toContain(t("lexicon.terms.noneTitle"));
    expect(wrapper.find("[data-test=open-only]").exists()).toBe(false);
  });

  it("shows the open terms alone on the reader's word, a term decided meanwhile still in sight", async () => {
    vi.spyOn(api, "decideTerm").mockResolvedValue(termDecision({ decision: "document", maps_to: null, role: null }));
    const wrapper = await section();

    await filter(wrapper).trigger("click");
    expect(filter(wrapper).attributes("aria-pressed")).toBe("true");
    expect(headings(wrapper)).toEqual(["„Lernbereich“"]);
    await decideFirst(wrapper);

    expect(headings(wrapper)).toEqual(["„Lernbereich“"]);
    expect(wrapper.get("[data-test=decision]").text()).toContain(t("lexicon.term.document"));
    expect(document.activeElement).toBe(wrapper.get("[data-test=decision]").element);
    expect(wrapper.get("[data-test=open-count]").text()).toBe("0 von 2 offen");
  });

  it("lists the decisions on terms gone apart, a level below their heading, decided again in place", async () => {
    const gone = termDecision({ term: "Probebereich", decision: "error", maps_to: null, role: null, applied: null });
    vi.spyOn(api, "getTerms").mockImplementation(() => Promise.resolve(list({ terms: [], gone: [gone] })));
    vi.spyOn(api, "decideTerm").mockResolvedValue({ ...gone, decision: "document" });
    const wrapper = await section();

    const part = wrapper.get("[data-test=gone]");
    expect(part.get("h3").text()).toBe(t("lexicon.terms.goneHeading"));
    expect(part.findAll("article h4").map((one) => one.text())).toEqual(["„Probebereich“"]);
    expect(wrapper.text()).not.toContain(t("lexicon.terms.noneTitle"));
    expect(wrapper.find("[data-test=open-only]").exists()).toBe(false); // nothing listed to filter
    await decideFirst(wrapper);

    expect(part.get("[data-test=decision]").text()).toContain(t("lexicon.term.document"));
  });

  it("names the node type a new cue points to by the label it was chosen by", async () => {
    vi.spyOn(api, "getForm").mockResolvedValue({ ...FORM, node: [{ ...FORM.node[0], values: [nodeType("Verzeichnis/Vorwort", [])] }] });
    // the server writes the term as the documents write it most by now
    vi.spyOn(api, "decideTerm").mockResolvedValue(termDecision({ term: "LERNBEREICH", maps_to: SCHOOL + "Verzeichnis/Vorwort", role: "pref" }));
    const wrapper = await section();
    await wrapper.get("[data-test=decide]").trigger("click");
    await wrapper.get("input[value=cue]").setValue(true);
    await flushPromises();
    await wrapper.findAll("select")[0].setValue(SCHOOL + "Verzeichnis/Vorwort");
    await wrapper.findAll("select")[1].setValue("pref");

    await wrapper.get("form").trigger("submit");
    await flushPromises();

    expect(wrapper.get("[data-test=decision]").text()).toContain(
      t("lexicon.term.cue", { target: "Verzeichnis/Vorwort", role: t("lexicon.termForm.roles.pref") }),
    );
    expect(document.activeElement).toBe(wrapper.get("[data-test=decision]").element);
  });

  it("reads the node types of a sector once for all its terms", async () => {
    const wrapper = await section();

    for (const toggle of wrapper.findAll("[data-test=decide]")) await toggle.trigger("click");
    for (const choice of wrapper.findAll("input[value=cue]")) await choice.setValue(true);
    await flushPromises();

    expect(wrapper.findAll("select")).toHaveLength(4); // node type and role, in each of the two forms
    expect(api.getForm).toHaveBeenCalledTimes(1);
  });

  it("reads the list again where a term went meanwhile", async () => {
    vi.spyOn(api, "decideTerm").mockRejectedValue(new ApiError("server", 404, "no_term"));
    const wrapper = await section();
    await decideFirst(wrapper);

    await wrapper.get("[data-test=decision-reload]").trigger("click");
    await flushPromises();

    expect(api.getTerms).toHaveBeenCalledTimes(2);
  });

  it("keeps a term whose form holds what is not saved in sight when only the open ones show", async () => {
    const wrapper = await section();
    const decided = wrapper.findAll("article")[1];
    await decided.get("[data-test=decide]").trigger("click");
    await decided.get("textarea").setValue("doch ein Hinweis");

    await filter(wrapper).trigger("click");

    expect(headings(wrapper)).toEqual(["„Lernbereich“", "„Leitidee“"]);
    await decided.get("textarea").setValue(""); // the input taken back: the entry stays where it is typed in
    expect(headings(wrapper)).toEqual(["„Lernbereich“", "„Leitidee“"]);
  });

  it("tells the page while a form holds what is not saved", async () => {
    const wrapper = await section();
    await wrapper.get("[data-test=decide]").trigger("click");

    await wrapper.get("textarea").setValue("noch offen");
    await wrapper.get("[data-test=decision-cancel]").trigger("click");

    expect(wrapper.emitted("dirty")).toEqual([[true], [false]]);
  });
});
