/**
 * axe over the pages as they are shown: the shell with its routed page, mounted
 * in the document as the app is, for a visitor and for an account, and the
 * sign-in with a refusal on screen. The whole document is checked, so the rules
 * about the page itself fire too (tests/axe.ts, pageViolations).
 */
import { flushPromises, mount, type VueWrapper } from "@vue/test-utils";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import * as api from "@/api";
import App from "@/App.vue";
import { t } from "@/i18n/de";
import { router } from "@/router";
import { clearSession, setSession } from "@/session";

import { ASSESSMENT_FORM, assessmentsOf, examWithPart } from "./assessmentFixtures";
import { describeViolations, pageViolations } from "./axe";
import { block, blockPage, conversion, table } from "./conversions";
import { CV, LABELS, REGION, cueDecision, newTerm, nodeType, reviewCue, termDecision } from "./lexiconFixtures";
import { documentOf } from "./documentFixtures";
import { detail } from "./registerEntries";
import { ruleOf, rulesOf } from "./ruleFixtures";
import { SCOPE_FORM, specificationsOf, valuedSpecification } from "./scopeFixtures";
import { CV as TREE_CV, LVL, NO_VALUES_FORM, form_, node_, noValues, tree_ } from "./treeFixtures";

let shown: VueWrapper | null = null;

const ENTRY: api.SourceEntry = {
  id: "s1",
  title: "Lehrplan Physik",
  provenance: "url",
  rights_status: "unklar",
  source_type: null,
  register_status: "acquired",
  country: "DE-BY",
  sector: null,
  url: "https://example.org/lehrplan.pdf",
  file: { name: "lehrplan.pdf", mime: "application/pdf", size: 8, sha256: "ab" },
  mine: true,
  created_at: "2026-10-22T10:00:00Z",
  updated_at: "2026-10-22T10:00:00Z",
};

const FAILED_JOB: api.Job = {
  id: "j1",
  kind: "source.fetch",
  status: "failed",
  progress: null,
  error_code: "download_refused",
  cancel_requested: false,
  attempts: 1,
  max_attempts: 3,
  created_at: "2026-10-22T10:00:00Z",
  started_at: null,
  finished_at: null,
};

async function show(path: string): Promise<VueWrapper> {
  document.body.innerHTML = '<div id="app"></div>';
  await router.push(path);
  shown = mount(App, { global: { plugins: [router] }, attachTo: "#app" });
  await flushPromises();
  return shown;
}

beforeEach(() => {
  vi.restoreAllMocks();
  api.clearToken();
  clearSession();
  // as index.html says it
  document.documentElement.lang = "de";
  vi.spyOn(api, "getInfo").mockResolvedValue({ name: "Curricarta", version: "0.1.0", public_access: "lookup", max_upload_mb: 50 });
});

afterEach(() => {
  // a test that faked the clock and failed early must not leave it to the next one's axe
  vi.useRealTimers();
  shown?.unmount();
  shown = null;
  document.body.innerHTML = "";
});

describe("the page harness", () => {
  it("reports a page whose content is in no landmark", async () => {
    // the guard on the checks below: inside a div these rules never fire
    document.body.innerHTML = '<div id="app"><p>Nur ein Absatz.</p></div>';

    const found = describeViolations(await pageViolations());

    expect(found).toMatch(/landmark-one-main|region/);
  });
});

describe("accessibility of the pages", () => {
  it("the start page for a visitor has none", async () => {
    const wrapper = await show("/");
    expect(wrapper.html().length).toBeGreaterThan(300);

    const found = await pageViolations();

    expect(found, describeViolations(found)).toEqual([]);
  });

  it("the start page for an account has none", async () => {
    api.setToken("curricarta_token");
    setSession({ id: "0190-a", name: "Erste Admin", roles: ["admin"] });
    await show("/");

    const found = await pageViolations();

    expect(found, describeViolations(found)).toEqual([]);
  });

  it("the start page for an account whose load failed has none", async () => {
    api.setToken("curricarta_token");
    vi.spyOn(api, "getMe").mockRejectedValue(new api.ApiError("server", 503, "service_unavailable"));
    const wrapper = await show("/");
    expect(wrapper.find("[role=alert]").exists()).toBe(true);

    const found = await pageViolations();

    expect(found, describeViolations(found)).toEqual([]);
  });

  it("the register with its entries, a failed fetch and a page that did not load has none", async () => {
    api.setToken("curricarta_token");
    setSession({ id: "0190-a", name: "Lehrkraft", roles: ["nutzer"] });
    vi.spyOn(api, "listSources")
      .mockResolvedValueOnce({ entries: [ENTRY], total: 2, limit: 50, offset: 0 })
      .mockResolvedValueOnce({ entries: [ENTRY], total: 2, limit: 50, offset: 0 })
      .mockRejectedValue(new api.ApiError("network", 0));
    vi.spyOn(api, "importSource").mockResolvedValue({ source: { ...ENTRY, file: null }, job_id: "j1" });
    vi.spyOn(api, "getJob").mockResolvedValue(FAILED_JOB);
    // the job's first question is a second away; flushPromises runs on setImmediate, left real
    vi.useFakeTimers({ toFake: ["setTimeout", "clearTimeout"] });
    const wrapper = await show("/quellen");
    await wrapper.get("#import-url").setValue("https://example.org/lehrplan.pdf");
    await wrapper.get("#import-url").trigger("submit");
    await flushPromises();
    await vi.advanceTimersByTimeAsync(1000);
    vi.useRealTimers(); // axe keeps its own time
    await wrapper.get("[data-test=more]").trigger("click");
    await flushPromises();
    expect(wrapper.find("tbody tr").exists()).toBe(true);
    expect(wrapper.text()).toContain(t("jobs.failures.download_refused"));
    expect(wrapper.get(".sources__partial").text()).toContain(t("sources.register.moreFailed"));

    const found = await pageViolations();

    expect(found, describeViolations(found)).toEqual([]);
  });

  it("the register with refusals in both forms and no entries has none", async () => {
    api.setToken("curricarta_token");
    setSession({ id: "0190-a", name: "Lehrkraft", roles: ["nutzer"] });
    vi.spyOn(api, "listSources").mockResolvedValue({ entries: [], total: 0, limit: 50, offset: 0 });
    const wrapper = await show("/quellen");
    await wrapper.get("#upload-file").trigger("submit");
    await wrapper.get("#import-url").trigger("submit");
    await flushPromises();
    expect(wrapper.find("#upload-error").exists()).toBe(true);
    expect(wrapper.find("#import-error").exists()).toBe(true);

    const found = await pageViolations();

    expect(found, describeViolations(found)).toEqual([]);
  });

  it("the register that did not load has none", async () => {
    api.setToken("curricarta_token");
    setSession({ id: "0190-a", name: "Lehrkraft", roles: ["nutzer"] });
    vi.spyOn(api, "listSources").mockRejectedValue(new api.ApiError("server", 503, "service_unavailable"));
    const wrapper = await show("/quellen");
    expect(wrapper.find("[role=alert]").exists()).toBe(true);

    const found = await pageViolations();

    expect(found, describeViolations(found)).toEqual([]);
  });

  it("the lexicon's review for the editors, a form of each section open, has none", async () => {
    api.setToken("curricarta_token");
    setSession({ id: "0190-r", name: "Redaktion", roles: ["redaktion"] });
    vi.spyOn(api, "getReview").mockResolvedValue({
      strata: [{ sector: "school", regions: [REGION + "DE-NW"], cues: 10, sampled: 1, decided: 1 }],
      items: [reviewCue({ decision: cueDecision() }), reviewCue({ iri: "https://example.org/re-2", surface_form: null, pattern: "^Lernfeld\\s+\\d+" })],
      retired: [cueDecision({ cue: "https://example.org/re-3", retired: true, decision: "rejected", strength: null })],
      labels: LABELS,
    });
    vi.spyOn(api, "getTerms").mockResolvedValue({
      terms: [newTerm(), newTerm({ term: "LF", decision: termDecision({ term: "LF", decision: "error", maps_to: null, role: null }) })],
      gone: [termDecision({ term: "Probebereich" })],
      labels: LABELS,
    });
    vi.spyOn(api, "getForm").mockResolvedValue({
      sector: "school",
      profile: "https://w3id.org/wlo/curriculum/profile/school#Terminology",
      node: [{ key: "node_type", kind: "concept", required: false, many: false, most: null, values: [nodeType("Inhaltsbereich", [CV + "fn_area"])] }],
      statement: [],
    ...NO_VALUES_FORM,
    });
    const wrapper = await show("/lexikon");
    const [sample, terms] = wrapper.findAll("section");
    await sample.get("[data-test=decide]").trigger("click");
    await sample.get("input[value=confirmed]").setValue(true);
    await terms.get("[data-test=decide]").trigger("click");
    await terms.get("input[value=cue]").setValue(true);
    await flushPromises();
    expect(wrapper.findAll("form")).toHaveLength(2);

    const found = await pageViolations();

    expect(found, describeViolations(found)).toEqual([]);
  });

  it("the register of an admin, filtered to nothing, with the check's question open, has none", async () => {
    api.setToken("curricarta_token");
    setSession({ id: "0190-a", name: "Erste Admin", roles: ["admin"] });
    vi.spyOn(api, "listSources")
      .mockResolvedValueOnce({ entries: [ENTRY], total: 1, limit: 50, offset: 0 })
      .mockResolvedValue({ entries: [], total: 0, limit: 50, offset: 0 });
    const wrapper = await show("/quellen");
    await wrapper.get("#register-candidates").setValue(true);
    await flushPromises();
    await wrapper.get("[data-test=check-start]").trigger("click");
    expect(wrapper.text()).toContain(t("sources.filter.emptyTitle"));
    expect(wrapper.find("[role=dialog]").exists()).toBe(true);

    const found = await pageViolations();

    expect(found, describeViolations(found)).toEqual([]);
  });

  it("an entry's page with its rights, its file's fetch, what the seed said, the check found and the notes tell has none", async () => {
    api.setToken("curricarta_token");
    setSession({ id: "0190-a", name: "Lehrkraft", roles: ["nutzer"] });
    const chain = ["https://lehrplaene.bildung-rp.de/physik", "https://lehrplaene.bildung-rp.de/dateien/physik.pdf"];
    vi.spyOn(api, "getSource").mockResolvedValue(
      detail({
        license: "CC BY 4.0",
        rights_evidence: "Lizenzhinweis auf der Portalseite",
        acquisitions: [{ method: "url", acquired_at: "2026-10-22T11:00:00Z", chain, received_name: "physik.pdf" }],
      }),
    );
    const wrapper = await show("/quellen/s1");
    expect(wrapper.find("#source-notes").exists()).toBe(true);
    expect(wrapper.find("#source-acquisitions").exists()).toBe(true);

    const found = await pageViolations();

    expect(found, describeViolations(found)).toEqual([]);
  });

  it("an entry's page for an entry that is not there has none", async () => {
    api.setToken("curricarta_token");
    setSession({ id: "0190-a", name: "Lehrkraft", roles: ["nutzer"] });
    vi.spyOn(api, "getSource").mockRejectedValue(new api.ApiError("server", 404, "not_found"));
    const wrapper = await show("/quellen/s1");
    expect(wrapper.text()).toContain(t("entryPage.notFoundTitle"));

    const found = await pageViolations();

    expect(found, describeViolations(found)).toEqual([]);
  });

  it("an entry's page with its conversion done and what it found has none", async () => {
    api.setToken("curricarta_token");
    setSession({ id: "0190-a", name: "Lehrkraft", roles: ["nutzer"] });
    vi.spyOn(api, "getSource").mockResolvedValue(detail({ file: ENTRY.file, mine: true }));
    const findings = [
      { code: "unmapped_symbol", params: { codepoint: "U+F0B7", count: 3, pages: [1, 2] } },
      { code: "encoding_suspect", params: { share: 0.034, count: 41, examples: ["Ã¤"] } },
    ];
    vi.spyOn(api, "getConversion").mockResolvedValue(conversion({ findings }));
    const wrapper = await show("/quellen/s1");
    expect(wrapper.find("[data-test=findings]").exists()).toBe(true);

    const found = await pageViolations();

    expect(found, describeViolations(found)).toEqual([]);
  });

  it("an entry's page for the redaktion, with the import of a MEM plan and a plan chosen, has none", async () => {
    api.setToken("curricarta_token");
    setSession({ id: "0190-r", name: "Redaktion", roles: ["redaktion"] });
    vi.spyOn(api, "getSource").mockResolvedValue(detail({ file: ENTRY.file, country: "DE-SN" }));
    vi.spyOn(api, "getConversion").mockResolvedValue(conversion());
    vi.spyOn(api, "findMemPlans").mockResolvedValue({
      plans: [
        {
          iri: "https://w3id.org/p/1", graph: "https://w3id.org/lehrplan/sn", land_iri: null, title: "Informatik",
          class_iri: "https://w3id.org/lehrplan/ontology/LP_0000438", subjects: [], school_types: [], licence: null,
          attribution: "MEM-Schule", read_at: "2026-11-10T10:00:00Z", region: "DE-SN",
        },
      ],
      total: 1,
      catalog_read_at: "2026-11-10T10:00:00Z",
    });
    const wrapper = await show("/quellen/s1");
    await wrapper.get("input[name=mem-import-plan]").setValue(true);

    const found = await pageViolations();

    expect(found, describeViolations(found)).toEqual([]);
  });

  it("an entry's page while its conversion runs has none", async () => {
    api.setToken("curricarta_token");
    setSession({ id: "0190-a", name: "Lehrkraft", roles: ["nutzer"] });
    vi.spyOn(api, "getSource").mockResolvedValue(detail({ file: ENTRY.file, mine: true }));
    vi.spyOn(api, "getConversion").mockResolvedValue(conversion({ status: "pending", pages: null, printed_pages: null }));
    vi.spyOn(api, "getJob").mockResolvedValue({ ...FAILED_JOB, kind: "source.convert", status: "running", error_code: null, progress: { code: "converting", params: {} } });
    vi.useFakeTimers({ toFake: ["setTimeout", "clearTimeout"] });
    const wrapper = await show("/quellen/s1");
    await vi.advanceTimersByTimeAsync(1000);
    vi.useRealTimers(); // axe keeps its own time
    expect(wrapper.text()).toContain(t("jobs.progress.converting"));

    const found = await pageViolations();

    expect(found, describeViolations(found)).toEqual([]);
  });

  it("an entry's page whose conversion failed, its start again refused, has none", async () => {
    api.setToken("curricarta_token");
    setSession({ id: "0190-a", name: "Lehrkraft", roles: ["nutzer"] });
    vi.spyOn(api, "getSource").mockResolvedValue(detail({ file: ENTRY.file, mine: true }));
    vi.spyOn(api, "getConversion").mockResolvedValue(conversion({ status: "failed", error_code: "needs_ocr", pages: null }));
    vi.spyOn(api, "askConversion").mockRejectedValue(new api.ApiError("server", 503, "service_unavailable"));
    const wrapper = await show("/quellen/s1");
    await wrapper.get("[data-test=conversion-start]").trigger("click");
    await flushPromises();
    expect(wrapper.text()).toContain(t("jobs.failures.needs_ocr"));
    expect(wrapper.find("[aria-labelledby=source-conversion] [role=alert]").exists()).toBe(true);

    const found = await pageViolations();

    expect(found, describeViolations(found)).toEqual([]);
  });

  it("an entry's blocks with a table, a running head and foot, and a page number refused has none", async () => {
    api.setToken("curricarta_token");
    setSession({ id: "0190-a", name: "Lehrkraft", roles: ["nutzer"] });
    vi.spyOn(api, "getSource").mockResolvedValue(detail({ file: ENTRY.file, mine: true }));
    vi.spyOn(api, "getConversion").mockResolvedValue(conversion());
    vi.spyOn(api, "getBlocks").mockResolvedValue(
      blockPage(2, [
        block("p2-b1", "Kerncurriculum Physik", { kind: "page_header" }),
        block("p2-b2", "Kompetenzen", { bold: true }),
        table(),
        block("p2-b4", "2", { kind: "page_footer" }),
      ], "1"),
    );
    const wrapper = await show("/quellen/s1/bloecke?seite=2");
    await wrapper.get("#pager-page").setValue("12");
    await wrapper.get("form.pager__jump").trigger("submit");
    expect(wrapper.find("table").exists()).toBe(true);
    expect(wrapper.find("#pager-error").exists()).toBe(true);

    const found = await pageViolations();

    expect(found, describeViolations(found)).toEqual([]);
  });

  it("an entry's blocks before its file is converted has none", async () => {
    api.setToken("curricarta_token");
    setSession({ id: "0190-a", name: "Lehrkraft", roles: ["nutzer"] });
    vi.spyOn(api, "getSource").mockResolvedValue(detail({ file: ENTRY.file, mine: true }));
    vi.spyOn(api, "getConversion").mockRejectedValue(new api.ApiError("server", 404, "no_conversion"));
    const wrapper = await show("/quellen/s1/bloecke");
    expect(wrapper.text()).toContain(t("conversionPage.notConvertedTitle"));

    const found = await pageViolations();

    expect(found, describeViolations(found)).toEqual([]);
  });

  it("the tree's page with a node's values in their form, an entry added and a problem at its field, has none", async () => {
    api.setToken("curricarta_token");
    setSession({ id: "0190-a", name: "Redaktion", roles: ["redaktion"] });
    const stated = { origin: TREE_CV + "orig_human", review_status: TREE_CV + "rev_proposed", revision: 1 };
    const values = {
      ...noValues(),
      level_assignments: [{ id: "l1", ...stated, level: LVL + "B1", level_to: null, relation: null, dimension: null, competence_dimension: null }],
      time_spans: [{ id: "t1", ...stated, time_kind: TREE_CV + "time_gradeLevel", span_from: 7, span_to: 8, time_relation: null }],
    };
    vi.spyOn(api, "getDocument").mockResolvedValue(documentOf());
    vi.spyOn(api, "getTree").mockResolvedValue(tree_([node_("a", { values })]));
    vi.spyOn(api, "getForm").mockResolvedValue(form_());
    vi.spyOn(api, "getDocumentBlocks").mockRejectedValue(new api.ApiError("server", 404, "no_such_page"));
    const wrapper = await show("/dokumente/d1/baum?zeile=node:a");
    const add = wrapper.findAll(".value-section__add").find((button) => button.text() === "Umfang hinzufügen");
    await add?.trigger("click");
    await wrapper.get(".value-section form").trigger("submit");
    await flushPromises();
    expect(wrapper.find(".value-section .field__error").exists()).toBe(true);

    const found = await pageViolations();

    expect(found, describeViolations(found)).toEqual([]);
  });

  it("the document's page with a specification's values and contexts in their form and a problem at a context's field, has none", async () => {
    api.setToken("curricarta_token");
    setSession({ id: "0190-a", name: "Redaktion", roles: ["redaktion"] });
    vi.spyOn(api, "getDocument").mockResolvedValue(documentOf());
    vi.spyOn(api, "getRuns").mockResolvedValue([]);
    vi.spyOn(api, "getUnits").mockResolvedValue([]);
    vi.spyOn(api, "getFindings").mockResolvedValue({ counts: { violation: 0, warning: 0, info: 0 }, findings: [], truncated: false, repairable: [] });
    vi.spyOn(api, "getSource").mockResolvedValue(detail());
    vi.spyOn(api, "listDocuments").mockResolvedValue([]);
    vi.spyOn(api, "getSpecifications").mockResolvedValue(specificationsOf({ specifications: [valuedSpecification()] }));
    vi.spyOn(api, "getAssessments").mockResolvedValue(assessmentsOf());
    vi.spyOn(api, "getForm").mockResolvedValue(SCOPE_FORM);
    vi.spyOn(api, "getRules").mockResolvedValue(rulesOf({ rules: [] }));
    vi.spyOn(api, "setSpecificationValues").mockRejectedValue(
      new api.ApiError("server", 422, "invalid_field", "No.", { field: "contexts[0].sector", problem: "not_offered" }),
    );
    const wrapper = await show("/dokumente/d1");
    const add = wrapper.findAll(".value-section__add").find((button) => button.text() === "Geltungskontext hinzufügen");
    await add?.trigger("click");
    await wrapper.get(".value-section form").trigger("submit");
    await flushPromises();
    expect(wrapper.find(".context-item .field__error").exists()).toBe(true);

    const found = await pageViolations();

    expect(found, describeViolations(found)).toEqual([]);
  });

  it("the document's page with a rule's form open, a new one's problems at its fields, has none", async () => {
    api.setToken("curricarta_token");
    setSession({ id: "0190-a", name: "Redaktion", roles: ["redaktion"] });
    vi.spyOn(api, "getDocument").mockResolvedValue(documentOf());
    vi.spyOn(api, "getRuns").mockResolvedValue([]);
    vi.spyOn(api, "getUnits").mockResolvedValue([]);
    vi.spyOn(api, "getFindings").mockResolvedValue({ counts: { violation: 0, warning: 0, info: 0 }, findings: [], truncated: false, repairable: [] });
    vi.spyOn(api, "getSource").mockResolvedValue(detail());
    vi.spyOn(api, "listDocuments").mockResolvedValue([]);
    vi.spyOn(api, "getSpecifications").mockResolvedValue(specificationsOf({ specifications: [] }));
    vi.spyOn(api, "getAssessments").mockResolvedValue(assessmentsOf());
    vi.spyOn(api, "getForm").mockResolvedValue(SCOPE_FORM);
    vi.spyOn(api, "getRules").mockResolvedValue(rulesOf({ rules: [ruleOf(), ruleOf({ id: "r2", kind: "prerequisite" })] }));
    const wrapper = await show("/dokumente/d1");
    await wrapper.findAll(".rules__edit")[1]?.trigger("click");
    await wrapper.get(".rules__add").trigger("click");
    await wrapper.get("form.rule-new").trigger("submit");
    await flushPromises();
    expect(wrapper.find("form.rule-new .field__error").exists()).toBe(true);

    const found = await pageViolations();

    expect(found, describeViolations(found)).toEqual([]);
  });

  it("the document's page with its assessments, one's form open with a problem at its parent, has none", async () => {
    api.setToken("curricarta_token");
    setSession({ id: "0190-a", name: "Redaktion", roles: ["redaktion"] });
    vi.spyOn(api, "getDocument").mockResolvedValue(documentOf());
    vi.spyOn(api, "getRuns").mockResolvedValue([]);
    vi.spyOn(api, "getUnits").mockResolvedValue([]);
    vi.spyOn(api, "getFindings").mockResolvedValue({ counts: { violation: 0, warning: 0, info: 0 }, findings: [], truncated: false, repairable: [] });
    vi.spyOn(api, "getSource").mockResolvedValue(detail());
    vi.spyOn(api, "listDocuments").mockResolvedValue([]);
    vi.spyOn(api, "getSpecifications").mockResolvedValue(specificationsOf());
    vi.spyOn(api, "getAssessments").mockResolvedValue(assessmentsOf({ assessments: examWithPart() }));
    vi.spyOn(api, "getForm").mockResolvedValue(ASSESSMENT_FORM);
    vi.spyOn(api, "getRules").mockResolvedValue(rulesOf({ rules: [] }));
    vi.spyOn(api, "editAssessment").mockRejectedValue(
      new api.ApiError("server", 422, "invalid_field", "No.", { field: "parent_id", problem: "cycle" }),
    );
    const wrapper = await show("/dokumente/d1");
    const edit = wrapper.findAll("button").find((button) => button.attributes("aria-label") === "Bearbeiten: Teil 1");
    await edit?.trigger("click");
    await wrapper.get(".assessment-form input[type=text]").setValue("Teil 1a");
    await wrapper.get(".assessment-form").trigger("submit");
    await flushPromises();
    expect(wrapper.find(".assessment-form .field__error").exists()).toBe(true);

    const found = await pageViolations();

    expect(found, describeViolations(found)).toEqual([]);
  });

  it("the tree's page of a frozen document, a node's values read in words, has none", async () => {
    api.setToken("curricarta_token");
    setSession({ id: "0190-a", name: "Lehrkraft", roles: ["nutzer"] });
    const values = {
      ...noValues(),
      workloads: [
        { id: "w1", origin: TREE_CV + "orig_human", review_status: TREE_CV + "rev_confirmed", revision: 1, amount: 80, amount_to: null,
          unit: TREE_CV + "unit_lesson", workload_kind: null, is_recommendation: true, minutes_per_unit: null, total: false, periods: [] },
      ],
    };
    vi.spyOn(api, "getDocument").mockResolvedValue(documentOf());
    vi.spyOn(api, "getTree").mockResolvedValue(tree_([node_("a", { values })], { editable: false, reviewable: false, closed: "frozen" }));
    vi.spyOn(api, "getForm").mockResolvedValue(form_());
    vi.spyOn(api, "getDocumentBlocks").mockRejectedValue(new api.ApiError("server", 404, "no_such_page"));
    const wrapper = await show("/dokumente/d1/baum?zeile=node:a");
    expect(wrapper.get(".value-list__words").text()).toBe("80 Unterrichtsstunden, Richtwert");

    const found = await pageViolations();

    expect(found, describeViolations(found)).toEqual([]);
  });

  it("the sign-in with a refused token on screen has none", async () => {
    vi.spyOn(api, "checkToken").mockResolvedValue(null);
    const wrapper = await show("/anmelden");
    await wrapper.get("form input").setValue("curricarta_" + "t".repeat(43));
    await wrapper.get("form").trigger("submit");
    await flushPromises();
    expect(wrapper.find("#login-error").exists()).toBe(true);

    const found = await pageViolations();

    expect(found, describeViolations(found)).toEqual([]);
  });
});
