import { flushPromises, mount, type VueWrapper } from "@vue/test-utils";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import * as api from "@/api";
import { ApiError, type CurriculumDocument } from "@/api";
import RevisionList from "@/components/RevisionList.vue";
import { momentFormat, t } from "@/i18n/de";
import { router } from "@/router";

import { violations } from "./axe";
import { documentOf } from "./documentFixtures";

let shown: VueWrapper | null = null;

const IRI = "https://example.org/kk/doc/de-rp/msb/klp/2019";
const ONE = documentOf({ id: "d1", iri: IRI, revision: 1, frozen_at: "2026-10-01T10:00:00Z" });
const TWO = documentOf({ id: "d2", iri: IRI, revision: 2, frozen_at: "2026-10-20T10:00:00Z", copy_of: "d1" });
const THREE = documentOf({ id: "d3", iri: IRI, revision: 3, copy_of: "d2" });
const ELSEWHERE = documentOf({ id: "d9", iri: null });

async function list(document: CurriculumDocument): Promise<VueWrapper> {
  shown = mount(RevisionList, { props: { document }, global: { plugins: [router] }, attachTo: globalThis.document.body });
  await flushPromises();
  return shown;
}

const moment = (value: string | null) => momentFormat.format(new Date(value as string));

beforeEach(() => {
  vi.restoreAllMocks();
});

afterEach(() => {
  shown?.unmount();
  shown = null;
  globalThis.document.body.innerHTML = "";
});

describe("the revisions of a document's IRI", () => {
  it("are listed the latest first, each frozen or a draft, the others a way to their page", async () => {
    const asked = vi.spyOn(api, "listDocuments").mockResolvedValue([ONE, ELSEWHERE, THREE, TWO]);
    const wrapper = await list(TWO);

    expect(asked).toHaveBeenCalledWith("s1");
    expect(wrapper.get("h3").text()).toBe(t("documents.page.revisions.heading"));
    // not numbered: a list's 1, 2, 3 beside "Revision 3, 2, 1" would read as another count
    expect(wrapper.find("ol").exists()).toBe(false);
    const items = wrapper.findAll("li");
    expect(items.map((item) => item.text())).toEqual([
      t("documents.page.revisions.draft", { revision: 3 }),
      t("documents.page.revisions.frozen", { revision: 2, date: moment(TWO.frozen_at) }),
      t("documents.page.revisions.frozen", { revision: 1, date: moment(ONE.frozen_at) }),
    ]);
    expect(items[0].get("a").attributes("href")).toBe("/dokumente/d3");
    expect(items[1].find("a").exists()).toBe(false);
    expect(items[1].get("[aria-current=page]").text()).toBe(items[1].text());
    expect(items[2].get("a").attributes("href")).toBe("/dokumente/d1");
    expect(await violations(wrapper.html())).toEqual([]);
  });

  it("say the document's own revision as the server reads it now: frozen since it was listed", async () => {
    vi.spyOn(api, "listDocuments").mockResolvedValue([ONE, THREE]);
    const wrapper = await list({ ...THREE, frozen_at: "2026-10-31T10:00:00Z" });

    expect(wrapper.findAll("li")[0].text()).toBe(
      t("documents.page.revisions.frozen", { revision: 3, date: moment("2026-10-31T10:00:00Z") }),
    );
  });

  it("list the document's own revision where the list read does not hold it", async () => {
    vi.spyOn(api, "listDocuments").mockResolvedValue([ONE]);
    const items = (await list(TWO)).findAll("li");

    expect(items.map((item) => item.text())).toEqual([
      t("documents.page.revisions.frozen", { revision: 2, date: moment(TWO.frozen_at) }),
      t("documents.page.revisions.frozen", { revision: 1, date: moment(ONE.frozen_at) }),
    ]);
    expect(items[0].find("[aria-current=page]").exists()).toBe(true);
  });

  it("are not listed where the document is its IRI's only revision", async () => {
    vi.spyOn(api, "listDocuments").mockResolvedValue([ONE, ELSEWHERE]);

    expect((await list(ONE)).find("li").exists()).toBe(false);
  });

  it("say they were not read where the list fails", async () => {
    vi.spyOn(api, "listDocuments").mockRejectedValue(new ApiError("network", 0));

    expect((await list(TWO)).text()).toContain(t("documents.page.revisions.failed"));
  });

  it("are read again once the document is frozen, a failure before said no more", async () => {
    const asked = vi
      .spyOn(api, "listDocuments")
      .mockRejectedValueOnce(new ApiError("network", 0))
      .mockResolvedValue([THREE]);
    const wrapper = await list(THREE);
    expect(wrapper.text()).toContain(t("documents.page.revisions.failed"));

    await wrapper.setProps({ document: { ...THREE, frozen_at: "2026-10-31T10:00:00Z" } });
    await flushPromises();

    expect(asked).toHaveBeenCalledTimes(2);
    expect(wrapper.text()).not.toContain(t("documents.page.revisions.failed"));
  });
});
