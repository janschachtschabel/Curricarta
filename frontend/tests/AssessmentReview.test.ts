import { flushPromises, mount, type VueWrapper } from "@vue/test-utils";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import * as api from "@/api";
import { ApiError } from "@/api";
import DocumentAssessments from "@/components/DocumentAssessments.vue";
import { t } from "@/i18n/de";
import { clearSession, setSession } from "@/session";

import { ASSESSMENT_FORM, assessmentsOf, examWithPart } from "./assessmentFixtures";
import { violations } from "./axe";

// The editors' review of an assessment and of the levels at it, on the document's section of them (plan M3a L): the
// three statuses in a group named for it, set at its revision, said in words that name it, the list read again.
let shown: VueWrapper | null = null;

async function open(): Promise<VueWrapper> {
  shown = mount(DocumentAssessments, { props: { documentId: "d1", sector: "vocational" }, attachTo: document.body });
  await flushPromises();
  return shown;
}

function group(wrapper: VueWrapper, name: string) {
  const found = wrapper.findAll("[role=group]").find((one) => document.getElementById(one.attributes("aria-labelledby") ?? "")?.textContent === name);
  if (!found) throw new Error(name);
  return found;
}

function toggle(within: ReturnType<VueWrapper["get"]>, label: string) {
  const found = within.findAll("button").find((one) => one.text() === label);
  if (!found) throw new Error(label);
  return found;
}

beforeEach(() => {
  vi.restoreAllMocks();
  setSession({ id: "e1", name: "Redaktion", roles: ["redaktion"] });
  vi.spyOn(api, "getAssessments").mockResolvedValue(assessmentsOf({ assessments: examWithPart() }));
  vi.spyOn(api, "getForm").mockResolvedValue(ASSESSMENT_FORM);
});

afterEach(() => {
  shown?.unmount();
  shown = null;
  clearSession();
  document.body.innerHTML = "";
});

describe("an assessment's review on the page", () => {
  it("offers the editors its statuses in a group named for it, its own pressed", async () => {
    const wrapper = await open();

    const toggles = group(wrapper, "Prüfstand von „Abschlussprüfung“");
    expect(toggles.findAll("button").map((one) => [one.text(), one.attributes("aria-pressed")])).toEqual([
      ["Vorgeschlagen", "true"],
      ["Bestätigt", "false"],
      ["Verworfen", "false"],
    ]);
    // the levels at a part are reviewed so too
    expect(group(wrapper, "Prüfstand von „Note 2“").exists()).toBe(true);
    expect(await violations(wrapper.element)).toEqual([]);
  });

  it("sets it at its revision, says so by its name and reads the list again", async () => {
    const sent = vi.spyOn(api, "setReview").mockResolvedValue({ revisions: [{ id: "a1", revision: 2 }], nodes: [] });
    const wrapper = await open();
    const reads = vi.mocked(api.getAssessments).mock.calls.length;

    await toggle(group(wrapper, "Prüfstand von „Abschlussprüfung“"), "Verworfen").trigger("click");
    await flushPromises();

    expect(sent).toHaveBeenCalledWith("d1", "rejected", [{ kind: "assessment", id: "a1", revision: 1 }]);
    expect(wrapper.get(".assessments__status").text()).toBe("Prüfstand von „Abschlussprüfung“: Verworfen.");
    expect(vi.mocked(api.getAssessments).mock.calls.length).toBe(reads + 1);
  });

  it("says one changed meanwhile by its name, and reads the list again", async () => {
    vi.spyOn(api, "setReview").mockRejectedValue(
      new ApiError("server", 409, "stale_revision", "Changed.", { stale: [{ kind: "assessment", id: "a1", current: 2 }] }),
    );
    const wrapper = await open();

    await toggle(group(wrapper, "Prüfstand von „Abschlussprüfung“"), "Bestätigt").trigger("click");
    await flushPromises();

    expect(wrapper.get(".assessments__status").text()).toBe(t("documents.page.assessments.reviewStale", { title: "Abschlussprüfung" }));
  });

  it("offers no review to one who is no editor", async () => {
    setSession({ id: "o1", name: "Lehrkraft", roles: ["nutzer"] });
    const wrapper = await open();

    expect(wrapper.find("[role=group]").exists()).toBe(false);
  });
});
