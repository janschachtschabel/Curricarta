// The four states a data view has besides "all here": loading, empty, failed,
// and partly there.
import { flushPromises, mount } from "@vue/test-utils";
import { describe, expect, it, vi } from "vitest";

import * as api from "@/api";

import EmptyState from "@/components/EmptyState.vue";
import ErrorState from "@/components/ErrorState.vue";
import LoadingState from "@/components/LoadingState.vue";
import PartialState from "@/components/PartialState.vue";
import ValueSection from "@/components/ValueSection.vue";
import { rowsOf, type Row } from "@/documentTree";
import { t } from "@/i18n/de";

import { CV, form_, node_, noValues } from "./treeFixtures";

describe("the loading state", () => {
  it("says so politely, in its own words or the general ones", () => {
    const general = mount(LoadingState);
    const own = mount(LoadingState, { props: { label: "Lehrpläne werden geladen …" } });

    expect(general.attributes("role")).toBe("status");
    expect(general.attributes("aria-live")).toBe("polite");
    expect(general.text()).toBe(t("states.loading"));
    expect(own.text()).toBe("Lehrpläne werden geladen …");
  });

  it("says nothing aloud where it is quiet: what it marks is said elsewhere", () => {
    const quiet = mount(LoadingState, { props: { label: "Wird neu gelesen …", quiet: true } });

    expect(quiet.attributes("role")).toBeUndefined();
    expect(quiet.attributes("aria-live")).toBeUndefined();
    expect(quiet.text()).toBe("Wird neu gelesen …");
  });
});

describe("the empty state", () => {
  it("says what would be here at the heading level it is given", () => {
    const wrapper = mount(EmptyState, { props: { title: "Noch nichts da", body: "Leg den ersten an.", level: 3 } });

    expect(wrapper.get("h3").text()).toBe("Noch nichts da");
    expect(wrapper.text()).toContain("Leg den ersten an.");
  });
});

describe("the error state", () => {
  it("alerts with the sentence and the reason, and offers to try again", async () => {
    const wrapper = mount(ErrorState, { props: { message: "Nicht geladen.", reason: "database away" } });

    expect(wrapper.attributes("role")).toBe("alert");
    expect(wrapper.get("q").attributes("lang")).toBe("en");
    await wrapper.get("button").trigger("click");
    expect(wrapper.emitted("retry")).toHaveLength(1);
  });
});

describe("the partial state", () => {
  it("says what is missing beside what is shown, without interrupting", () => {
    // Part of the page is there; a status, not an alert: nothing stopped working.
    const wrapper = mount(PartialState, {
      props: { notice: { text: "Ein Teil fehlt.", explanation: "Die Suche antwortet gerade nicht." } },
    });

    expect(wrapper.attributes("role")).toBe("status");
    expect(wrapper.text()).toContain("Ein Teil fehlt. Die Suche antwortet gerade nicht.");
    expect(wrapper.find("button").exists()).toBe(false);
  });

  it("is in the page before it has anything to say, so its first word is read out", () => {
    // a live region inserted together with its text is often not read
    const wrapper = mount(PartialState, { props: { notice: null, retry: true } });

    expect(wrapper.attributes("role")).toBe("status");
    expect(wrapper.text()).toBe("");
    expect(wrapper.find("button").exists()).toBe(false);
    expect(wrapper.classes()).not.toContain("page-notice");
  });

  it("offers to fetch the rest where the page can", async () => {
    const wrapper = mount(PartialState, { props: { notice: { text: "Ein Teil fehlt." }, retry: true } });

    await wrapper.get("button").trigger("click");

    expect(wrapper.get("button").text()).toBe(t("states.retry"));
    expect(wrapper.emitted("retry")).toHaveLength(1);
  });
});

describe("a row's values", () => {
  const ROW = rowsOf([node_("a", { values: noValues() })]).get("node:a") as Row;
  const props = { row: ROW, form: form_(), documentId: "d1", reviewable: false, closedBy: null };

  it("say while they are saved that they are, quietly, the button keeping the keyboard", async () => {
    let answer: (row: api.NodeRow) => void = () => undefined;
    vi.spyOn(api, "setNodeValues").mockImplementation(() => new Promise((done) => (answer = done)));
    const wrapper = mount(ValueSection, { props: { ...props, editable: true }, attachTo: document.body });
    await wrapper.findAll(".value-section__add")[1]?.trigger("click");
    await wrapper.get("fieldset select").setValue(form_().values.time_spans.fields[0]?.values?.[0]?.iri);
    const save = wrapper.get("form button[type=submit]");
    (save.element as HTMLElement).focus();

    await wrapper.get("form").trigger("submit");

    expect(wrapper.get(".loading").text()).toBe(t("documents.tree.values.saving"));
    expect(wrapper.get(".loading").attributes("role")).toBeUndefined();
    expect(save.attributes("aria-disabled")).toBe("true");
    expect(document.activeElement).toBe(save.element);
    const { statements, children, ...row } = node_("a", { revision: 2 });
    void [statements, children];
    answer(row);
    await flushPromises();
    expect(wrapper.find(".loading").exists()).toBe(false);
    wrapper.unmount();
  });

  it("say where none is entered yet, to a reader who may not change them", () => {
    const wrapper = mount(ValueSection, { props: { ...props, editable: false } });

    expect(wrapper.get(".value-list__none").text()).toBe(t("documents.tree.values.none"));
    expect(wrapper.find("form").exists()).toBe(false);
  });

  // a job open on the document: read as they are, with nothing to change - the panel's line says why. Its form
  // stays only where a draft of the row's own fields was open as the tree closed (`editable` kept), not for the values
  it.each([
    ["closed to everyone", false],
    ["closed under a draft of the row's fields", true],
  ])("only read where a job keeps the tree closed: %s", (_case, editable) => {
    const workload = {
      id: "w1", origin: CV + "orig_human", review_status: CV + "rev_proposed", revision: 1, amount: 80, amount_to: null,
      unit: CV + "unit_lesson", workload_kind: null, is_recommendation: false, minutes_per_unit: null, total: false, periods: [],
    };
    const row = rowsOf([node_("a", { values: { ...noValues(), workloads: [workload] } })]).get("node:a") as Row;
    const wrapper = mount(ValueSection, { props: { ...props, row, editable, closedBy: "job_open" } });

    expect(wrapper.get(".value-list__words").text()).toBe("80 Unterrichtsstunden");
    expect(wrapper.find("form").exists()).toBe(false);
    expect(wrapper.find("button").exists()).toBe(false);
    expect(wrapper.find("[role=alert]").exists()).toBe(false);
  });
});

