import { flushPromises, mount, type VueWrapper } from "@vue/test-utils";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import * as api from "@/api";
import { ApiError, type CurriculumDocument, type DocumentWork, type Me } from "@/api";
import DocumentEdition from "@/components/DocumentEdition.vue";
import DocumentMetaForm from "@/components/DocumentMetaForm.vue";
import RevisionList from "@/components/RevisionList.vue";
import SupersedesForm from "@/components/SupersedesForm.vue";
import WorkForm from "@/components/WorkForm.vue";
import { t } from "@/i18n/de";
import { clearSession, setSession } from "@/session";

import { violations } from "./axe";
import { documentOf } from "./documentFixtures";

let shown: VueWrapper | null = null;

const KLP: DocumentWork = {
  id: "w1",
  title: "Kernlehrplan Physik",
  region: "DE-NW",
  short_title: "klp-physik",
  iri: "https://example.org/kk/work/de-nw/klp-physik",
};
const OWNER: Me = { id: "a1", name: "Eigentümerin", roles: ["nutzer"] };
const EDITOR: Me = { id: "a2", name: "Redakteurin", roles: ["redaktion"] };

async function edition(document: CurriculumDocument, me: Me = OWNER): Promise<VueWrapper> {
  setSession(me);
  shown = mount(DocumentEdition, { props: { document }, attachTo: globalThis.document.body });
  await flushPromises();
  return shown;
}

const facts = (wrapper: VueWrapper) =>
  Object.fromEntries(
    wrapper.findAll("dt").map((term) => [term.text(), (term.element.nextElementSibling as HTMLElement).textContent?.trim()]),
  );

beforeEach(() => {
  vi.restoreAllMocks();
  vi.spyOn(api, "listDocuments").mockResolvedValue([]);
  vi.spyOn(api, "listWorkDocuments").mockResolvedValue([]);
});

afterEach(() => {
  shown?.unmount();
  shown = null;
  globalThis.document.body.innerHTML = "";
  clearSession();
});

describe("a document's work and edition", () => {
  it("say its issuer, edition, work, IRI and revision, what is not there said as such", async () => {
    const named = await edition(
      documentOf({
        issuer: "MSB NRW",
        edition: "2019",
        work: KLP,
        iri: "https://example.org/kk/doc/x",
        revision: 2,
        supersedes: { id: "d0", iri: "https://example.org/kk/doc/w", edition: "2008" },
      }),
    );

    expect(named.get("h2").text()).toBe(t("documents.page.edition.heading"));
    expect(facts(named)).toEqual({
      [t("documents.page.edition.issuer")]: "MSB NRW",
      [t("documents.page.edition.edition")]: "2019",
      [t("documents.page.edition.workHeading")]: "Kernlehrplan Physik (Nordrhein-Westfalen, klp-physik)",
      [t("documents.page.edition.iri")]: "https://example.org/kk/doc/x",
      [t("documents.page.edition.revision")]: "2",
      [t("documents.page.edition.supersedes")]: "2008 (https://example.org/kk/doc/w)",
    });
    expect(await violations(named.html())).toEqual([]);
    named.unmount();

    const bare = await edition(documentOf());
    const none = t("documents.page.edition.none");
    expect(facts(bare)).toMatchObject({
      [t("documents.page.edition.issuer")]: none,
      [t("documents.page.edition.edition")]: none,
      [t("documents.page.edition.workHeading")]: none,
      [t("documents.page.edition.iri")]: t("documents.page.edition.noIri"),
      [t("documents.page.edition.supersedes")]: none,
    });
  });

  it("list the revisions of its IRI where it has one", async () => {
    const named = await edition(documentOf({ iri: "https://example.org/kk/doc/x", revision: 2 }));
    expect(named.findComponent(RevisionList).exists()).toBe(true);
    named.unmount();

    expect((await edition(documentOf())).findComponent(RevisionList).exists()).toBe(false);
  });

  it("offer the owner its title, issuer and edition to change, the work being the editors'", async () => {
    const wrapper = await edition(documentOf({ own: true }));

    expect(wrapper.findComponent(DocumentMetaForm).exists()).toBe(true);
    expect(wrapper.findComponent(WorkForm).exists()).toBe(false);
  });

  it("offer an editor the work too, while the document has none and no IRI", async () => {
    const editing = await edition(documentOf({ own: false }), EDITOR);
    expect([editing.findComponent(DocumentMetaForm).exists(), editing.findComponent(WorkForm).exists()]).toEqual([
      true,
      true,
    ]);
    shown?.unmount();
    expect((await edition(documentOf({ own: false, work: KLP }), EDITOR)).findComponent(WorkForm).exists()).toBe(false);
    shown?.unmount();
    const copied = documentOf({ own: false, iri: "https://example.org/kk/doc/x", copy_of: "d0" });
    expect((await edition(copied, EDITOR)).findComponent(WorkForm).exists()).toBe(false);
  });

  it("offer nothing to change once the document is frozen", async () => {
    const wrapper = await edition(documentOf({ frozen_at: "2026-10-31T10:00:00Z", iri: "x", work: KLP }), EDITOR);

    expect(wrapper.find("form").exists()).toBe(false);
  });

  it("say a work set, and take the keyboard to their heading once the work form goes with it", async () => {
    const wrapper = await edition(documentOf(), EDITOR);
    (wrapper.findComponent(WorkForm).get("button[type=submit]").element as HTMLElement).focus();

    wrapper.findComponent(WorkForm).vm.$emit("saved");
    await flushPromises();
    expect(wrapper.get(".edition__status").text()).toBe(t("documents.page.edition.workSaved"));
    expect(wrapper.emitted("changed")).toHaveLength(1);
    await wrapper.setProps({ document: documentOf({ work: KLP }) });
    await flushPromises();

    expect(wrapper.findComponent(WorkForm).exists()).toBe(false);
    expect(globalThis.document.activeElement).toBe(wrapper.get("h2").element);
    expect(await violations(wrapper.html())).toEqual([]);
  });

  it("leave the keyboard where it rests when a reading finds a work set by another, out of the work form", async () => {
    const held = await edition(documentOf(), EDITOR);
    const button = held.findComponent(DocumentMetaForm).get("button[type=submit]");
    (button.element as HTMLElement).focus();
    await held.setProps({ document: documentOf({ work: KLP }) });
    await flushPromises();
    expect(globalThis.document.activeElement).toBe(button.element);
    held.unmount();

    const free = await edition(documentOf(), EDITOR);
    (globalThis.document.activeElement as HTMLElement | null)?.blur();
    await free.setProps({ document: documentOf({ work: KLP }) });
    await flushPromises();
    expect(globalThis.document.activeElement).not.toBe(free.get("h2").element);
  });

  it("have the page read the document again for a change saved below", async () => {
    const wrapper = await edition(documentOf(), EDITOR);

    wrapper.findComponent(DocumentMetaForm).vm.$emit("changed");
    wrapper.findComponent(WorkForm).vm.$emit("changed");

    expect(wrapper.emitted("changed")).toHaveLength(2);
  });
});

// The editions of the work KLP an edition may supersede, as listDocuments gives them, the newest first
const FROZEN = { work: KLP, frozen_at: "2026-10-01T10:00:00Z" };
const A1 = documentOf({ ...FROZEN, id: "a1", edition: "2008", iri: "https://example.org/kk/doc/a", revision: 1 });
const A2 = documentOf({ ...FROZEN, id: "a2", edition: "2008", iri: "https://example.org/kk/doc/a", revision: 2 });
const B1 = documentOf({ ...FROZEN, id: "b1", edition: "2014", iri: "https://example.org/kk/doc/b", revision: 1 });
const OTHER: DocumentWork = { ...KLP, id: "w2", title: "Kernlehrplan Chemie" };

const choice = (wrapper: VueWrapper) => wrapper.findComponent(SupersedesForm).get("select");
const offered = (wrapper: VueWrapper) =>
  choice(wrapper)
    .findAll("option")
    .map((option) => [option.attributes("value"), option.text()]);

describe("what an edition supersedes", () => {
  it("offers the frozen editions of its work, each IRI once as its latest revision, none of its own IRI", async () => {
    // all the caller sees; the revisions of its own IRI, asked of its entry, stay out of this
    const seen = [
      A2,
      documentOf({ id: "draft", work: KLP, edition: "2020" }), // a draft is none to supersede
      documentOf({ ...FROZEN, id: "c1", work: OTHER, edition: "2001", iri: "https://example.org/kk/doc/c" }),
      documentOf({ ...FROZEN, id: "own1", edition: "2024", iri: "https://example.org/kk/doc/own" }),
      B1,
      A1,
    ];
    const asked = vi.spyOn(api, "listWorkDocuments").mockResolvedValue(seen);
    const copy = documentOf({ id: "own2", work: KLP, iri: "https://example.org/kk/doc/own", revision: 2 });

    const wrapper = await edition(copy, EDITOR);

    // asked of the work, all its documents the caller reads: none cut by the cap of the whole list
    expect(asked).toHaveBeenCalledWith("w1");
    expect(offered(wrapper)).toEqual([
      ["", t("documents.page.edition.supersedesNothing")],
      ["a2", "2008 (https://example.org/kk/doc/a)"],
      ["b1", "2014 (https://example.org/kk/doc/b)"],
    ]);
    expect(await violations(wrapper.html())).toEqual([]);
  });

  it("explains where its work has no frozen edition, and where it has no work yet", async () => {
    vi.spyOn(api, "listWorkDocuments").mockResolvedValue([documentOf({ id: "draft", work: KLP })]);
    const empty = await edition(documentOf({ work: KLP }), EDITOR);
    expect(empty.findComponent(SupersedesForm).text()).toContain(t("documents.page.edition.supersedesNone"));
    expect(empty.findComponent(SupersedesForm).find("select").exists()).toBe(false);
    empty.unmount();

    const workless = await edition(documentOf(), OWNER);
    expect(workless.findComponent(SupersedesForm).text()).toContain(t("documents.page.edition.supersedesNoWork"));
    expect(workless.findComponent(SupersedesForm).find("select").exists()).toBe(false);
  });

  it("asks the work anew once a work is set on the page, and offers its editions", async () => {
    // the page reads the document again and stays: the form, there before the work, is not made anew
    const asked = vi.spyOn(api, "listWorkDocuments").mockResolvedValue([B1]);
    const wrapper = await edition(documentOf(), EDITOR);
    expect(asked).not.toHaveBeenCalled();

    await wrapper.setProps({ document: documentOf({ work: KLP }) });
    await flushPromises();

    expect(asked).toHaveBeenCalledWith("w1");
    expect(offered(wrapper).map(([value]) => value)).toEqual(["", "b1"]);
    await wrapper.setProps({ document: documentOf({ work: OTHER }) });
    await flushPromises();
    expect(asked).toHaveBeenLastCalledWith("w2");
    // the other work's answer holds none of its editions: the first work's are gone with it
    expect(wrapper.findComponent(SupersedesForm).text()).toContain(t("documents.page.edition.supersedesNone"));
  });

  it("says where the editions were not read", async () => {
    vi.spyOn(api, "listWorkDocuments").mockRejectedValue(new ApiError("network", 0));

    const wrapper = await edition(documentOf({ work: KLP }), EDITOR);

    expect(wrapper.findComponent(SupersedesForm).text()).toContain(t("documents.page.edition.supersedesLoadFailed"));
  });

  it("saves the edition chosen, and no longer one, and has the page read the document again", async () => {
    vi.spyOn(api, "listWorkDocuments").mockResolvedValue([B1]);
    const saved = vi
      .spyOn(api, "editDocument")
      .mockResolvedValue(documentOf({ work: KLP, supersedes: { id: "b1", iri: B1.iri ?? "", edition: "2014" } }));
    const wrapper = await edition(documentOf({ work: KLP }), EDITOR);

    await choice(wrapper).setValue("b1");
    await wrapper.findComponent(SupersedesForm).get("form").trigger("submit");
    await flushPromises();

    expect(saved).toHaveBeenCalledWith("d1", { supersedes: "b1" });
    expect(wrapper.findComponent(SupersedesForm).get("[role=status]").text()).toBe(
      t("documents.page.edition.supersedesSaved"),
    );
    expect(wrapper.emitted("changed")).toHaveLength(1);

    await wrapper.setProps({ document: documentOf({ work: KLP, supersedes: { id: "b1", iri: B1.iri ?? "", edition: "2014" } }) });
    await choice(wrapper).setValue("");
    await wrapper.findComponent(SupersedesForm).get("form").trigger("submit");
    await flushPromises();
    expect(saved).toHaveBeenLastCalledWith("d1", { supersedes: null });
  });

  it("holds the edition it supersedes chosen, and saves nothing unchanged", async () => {
    vi.spyOn(api, "listWorkDocuments").mockResolvedValue([B1]);
    const saved = vi.spyOn(api, "editDocument");
    const wrapper = await edition(
      documentOf({ work: KLP, supersedes: { id: "b1", iri: B1.iri ?? "", edition: "2014" } }),
      EDITOR,
    );

    expect((choice(wrapper).element as HTMLSelectElement).value).toBe("b1");
    await wrapper.findComponent(SupersedesForm).get("form").trigger("submit");
    await flushPromises();

    expect(saved).not.toHaveBeenCalled();
    expect(wrapper.findComponent(SupersedesForm).get("[role=status]").text()).toBe(
      t("documents.page.edition.unchanged"),
    );
  });

  it("says the server's problem with the choice at the field, the keyboard taken there", async () => {
    vi.spyOn(api, "listWorkDocuments").mockResolvedValue([B1]);
    vi.spyOn(api, "editDocument").mockRejectedValue(
      new ApiError("server", 422, "invalid_field", "Bad.", { field: "supersedes", problem: "not_offered" }),
    );
    const wrapper = await edition(documentOf({ work: KLP }), EDITOR);
    const form = wrapper.findComponent(SupersedesForm);

    await choice(wrapper).setValue("b1");
    (form.get("button[type=submit]").element as HTMLElement).focus();
    await form.get("form").trigger("submit");
    await flushPromises();

    const select = choice(wrapper);
    expect(select.attributes("aria-invalid")).toBe("true");
    expect(form.get(`#${select.attributes("id")}-error`).text()).toContain(t("documents.tree.problems.not_offered"));
    expect(globalThis.document.activeElement).toBe(select.element);
    expect(await violations(wrapper.html())).toEqual([]);
  });

  it("offers no choice once the document is frozen, saying what it supersedes", async () => {
    const frozen = documentOf({
      ...FROZEN,
      iri: "https://example.org/kk/doc/own",
      supersedes: { id: "b1", iri: "https://example.org/kk/doc/b", edition: null },
    });

    const wrapper = await edition(frozen, EDITOR);

    expect(wrapper.findComponent(SupersedesForm).exists()).toBe(false);
    expect(facts(wrapper)[t("documents.page.edition.supersedes")]).toBe(
      `${t("documents.page.edition.none")} (https://example.org/kk/doc/b)`,
    );
  });
});
