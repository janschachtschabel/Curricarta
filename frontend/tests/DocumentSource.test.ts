import { flushPromises, mount, type VueWrapper } from "@vue/test-utils";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import * as api from "@/api";
import { ApiError, type SourceDetail } from "@/api";
import AcquisitionList from "@/components/AcquisitionList.vue";
import DocumentSource from "@/components/DocumentSource.vue";
import { messages, t } from "@/i18n/de";
import { word } from "@/registerWords";

import { violations } from "./axe";
import { documentOf } from "./documentFixtures";
import { detail } from "./registerEntries";

let shown: VueWrapper | null = null;

const FETCHED: SourceDetail = detail({
  rights_status: "offen_lizenziert",
  license: "CC BY 4.0",
  rights_evidence: "Impressum des Ministeriums",
  acquisitions: [
    {
      method: "url",
      acquired_at: "2026-10-30T10:00:00Z",
      chain: ["https://example.org/lp.pdf", "https://cdn.example.org/lp.pdf"],
      received_name: "lp.pdf",
    },
  ],
});

async function source(): Promise<VueWrapper> {
  shown = mount(DocumentSource, { props: { document: documentOf() }, attachTo: document.body });
  await flushPromises();
  return shown;
}

const facts = (wrapper: VueWrapper) =>
  Object.fromEntries(
    wrapper.findAll("section > dl > dt").map((term) => [term.text(), (term.element.nextElementSibling as HTMLElement).textContent?.trim()]),
  );

beforeEach(() => {
  vi.restoreAllMocks();
});

afterEach(() => {
  shown?.unmount();
  shown = null;
  document.body.innerHTML = "";
});

describe("where a document comes from", () => {
  it("says its entry's provenance, rights, license and kind of source, and how its file was fetched", async () => {
    const asked = vi.spyOn(api, "getSource").mockResolvedValue(FETCHED);
    const wrapper = await source();

    expect(asked).toHaveBeenCalledWith("s1");
    expect(wrapper.get("h2").text()).toBe(t("documents.page.source.heading"));
    expect(facts(wrapper)).toEqual({
      [t("entryPage.facts.provenance")]: word(messages.sources.provenance, FETCHED.provenance),
      [t("entryPage.facts.rights")]: word(messages.sources.rights, "offen_lizenziert"),
      [t("entryPage.facts.license")]: "CC BY 4.0",
      [t("entryPage.facts.rightsEvidence")]: "Impressum des Ministeriums",
      [t("entryPage.facts.sourceType")]: word(messages.entryPage.sourceType, "amtlich"),
    });
    expect(wrapper.getComponent(AcquisitionList).props("acquisitions")).toEqual(FETCHED.acquisitions);
    expect(await violations(wrapper.html())).toEqual([]);
  });

  it("leaves out what the entry does not say, and the fetching where its file was never fetched", async () => {
    vi.spyOn(api, "getSource").mockResolvedValue(detail({ license: null, rights_evidence: null, source_type: null }));
    const wrapper = await source();

    expect(Object.keys(facts(wrapper))).toEqual([t("entryPage.facts.provenance"), t("entryPage.facts.rights")]);
    expect(wrapper.findComponent(AcquisitionList).exists()).toBe(false);
  });

  it("says while it reads the entry, in words of its own beside the other sections' waiting", async () => {
    vi.spyOn(api, "getSource").mockReturnValue(new Promise(() => {}));

    expect((await source()).get(".loading").text()).toBe(t("documents.page.source.loading"));
  });

  it("says an entry the account does not see, offering nothing to try again, and tells the page", async () => {
    vi.spyOn(api, "getSource").mockRejectedValue(new ApiError("server", 404, "not_found"));
    const wrapper = await source();

    expect(wrapper.text()).toContain(t("documents.page.source.hidden"));
    expect(wrapper.find("button").exists()).toBe(false);
    expect(wrapper.emitted("hidden")).toHaveLength(1);
  });

  it("tells the page nothing of a reading that failed otherwise", async () => {
    vi.spyOn(api, "getSource").mockRejectedValue(new ApiError("network", 0));

    expect((await source()).emitted("hidden")).toBeUndefined();
  });

  it("says a reading that failed, and reads again on request: waiting meanwhile, the keyboard to its heading", async () => {
    let answer: (value: SourceDetail) => void = () => {};
    const asked = vi
      .spyOn(api, "getSource")
      .mockRejectedValueOnce(new ApiError("network", 0))
      .mockReturnValueOnce(new Promise((resolve) => (answer = resolve)));
    const wrapper = await source();

    expect(wrapper.get("[role=alert]").text()).toContain(t("documents.page.source.failed"));
    const button = wrapper.get("button");
    (button.element as HTMLElement).focus();
    await button.trigger("click");
    await flushPromises();

    expect(wrapper.find("[role=alert]").exists()).toBe(false);
    expect(wrapper.find(".loading").exists()).toBe(true);
    answer(FETCHED);
    await flushPromises();

    expect(asked).toHaveBeenCalledTimes(2);
    expect(wrapper.findComponent(AcquisitionList).exists()).toBe(true);
    expect(document.activeElement).toBe(wrapper.get("h2").element);
    expect(await violations(wrapper.html())).toEqual([]);
  });

  it("leaves the keyboard where the reader took it meanwhile", async () => {
    let answer: (value: SourceDetail) => void = () => {};
    vi.spyOn(api, "getSource")
      .mockRejectedValueOnce(new ApiError("network", 0))
      .mockReturnValueOnce(new Promise((resolve) => (answer = resolve)));
    const elsewhere = document.body.appendChild(document.createElement("button"));
    const wrapper = await source();

    (wrapper.get("button").element as HTMLElement).focus();
    await wrapper.get("button").trigger("click");
    elsewhere.focus();
    answer(FETCHED);
    await flushPromises();

    expect(document.activeElement).toBe(elsewhere);
  });

  it("says again a reading that failed again: a new alert, not the one before", async () => {
    vi.spyOn(api, "getSource").mockRejectedValue(new ApiError("network", 0));
    const wrapper = await source();
    const before = wrapper.get("[role=alert]").element;

    await wrapper.get("button").trigger("click");
    await flushPromises();

    const again = wrapper.get("[role=alert]");
    expect(again.element).not.toBe(before);
    expect(again.text()).toContain(t("documents.page.source.failed"));
  });
});
