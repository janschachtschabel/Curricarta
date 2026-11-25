import { describe, expect, it } from "vitest";

import type { ApplicabilityContext, ScopeForm, ScopeLevel, ScopeTimeSpan, ScopeWorkload } from "@/api";
import { t } from "@/i18n/de";
import { contextWords, joined, labelsOf, levelWords, spanWords, stated, workloadWords } from "@/scopeWords";

const CV = "https://w3id.org/wlo/curriculum/vocab#";
const LVL = "https://w3id.org/wlo/curriculum/level/";
const STATED = { id: "v1", origin: CV + "orig_human", review_status: CV + "rev_proposed", revision: 1 };

const FORM: ScopeForm = {
  values: {
    level_assignments: {
      fields: [{ key: "level", values: [{ iri: LVL + "EQF-4", label: "EQR 4" }, { iri: LVL + "EQF-5", label: "EQR 5" }] }],
    },
    time_spans: { fields: [{ key: "time_kind", values: [{ iri: CV + "time_gradeLevel", label: "Jahrgangsstufe" }] }] },
    workloads: { fields: [{ key: "unit", values: [{ iri: CV + "unit_lesson", label: "Unterrichtsstunden" }] }, { key: "amount", values: null }] },
  },
  context: {
    fields: [
      { key: "sector", values: [{ iri: CV + "sec_school", label: "Schulbildung" }] },
      { key: "formality", values: [{ iri: CV + "form_formal", label: "formal" }] },
    ],
  },
};
const labels = labelsOf(FORM);

function level(more: Partial<ScopeLevel> = {}): ScopeLevel {
  return { ...STATED, level: LVL + "EQF-4", level_to: null, relation: null, dimension: null, competence_dimension: null, ...more };
}

function span(more: Partial<ScopeTimeSpan> = {}): ScopeTimeSpan {
  return { ...STATED, time_kind: CV + "time_gradeLevel", span_from: 5, span_to: 6, time_relation: null, ...more };
}

describe("the words of a specification's values and contexts", () => {
  it("name a level by its label, a range by both ends", () => {
    expect(levelWords(level(), labels)).toBe("EQR 4");
    expect(levelWords(level({ level_to: LVL + "EQF-5" }), labels)).toBe("EQR 4 bis EQR 5");
  });

  it("name a time span by its kind and its ends, an open end as such", () => {
    expect(spanWords(span(), labels)).toBe("Jahrgangsstufe 5–6");
    expect(spanWords(span({ span_to: null }), labels)).toBe("Jahrgangsstufe ab 5");
    expect(spanWords(span({ span_from: null }), labels)).toBe("Jahrgangsstufe bis 6");
    expect(spanWords(span({ span_from: null, span_to: null }), labels)).toBe("Jahrgangsstufe");
  });

  it("name a workload by its amount and unit, a recommendation and a whole as such", () => {
    const workload: ScopeWorkload = {
      ...STATED, amount: 40, amount_to: 50, unit: CV + "unit_lesson", workload_kind: null, is_recommendation: true,
      minutes_per_unit: null, total: true, periods: [],
    };
    expect(workloadWords(workload, labels)).toBe("40–50 Unterrichtsstunden insgesamt, Empfehlung");
    expect(workloadWords({ ...workload, amount_to: null, is_recommendation: false, total: false }, labels)).toBe(
      "40 Unterrichtsstunden",
    );
  });

  it("name a context by all it states, the texts as written", () => {
    const context: ApplicabilityContext = {
      ...STATED, sector: CV + "sec_school", formality: CV + "form_formal", institution_text: "Gymnasium",
      target_group_text: "Erwachsene", level_assignments: [level()], time_spans: [span()],
    };
    expect(contextWords(context, labels)).toEqual([
      "Schulbildung", "formal", "Einrichtung: Gymnasium", "Zielgruppe: Erwachsene", "EQR 4 (Vorgeschlagen)",
      "Jahrgangsstufe 5–6 (Vorgeschlagen)",
    ]);
  });

  it("say a context's value's review status, and a context that states nothing as such", () => {
    const rejected = level({ review_status: CV + "rev_rejected" });
    const empty: ApplicabilityContext = {
      ...STATED, sector: null, formality: null, institution_text: null, target_group_text: null,
      level_assignments: [], time_spans: [],
    };

    expect(contextWords({ ...empty, level_assignments: [rejected] }, labels)).toEqual(["EQR 4 (Verworfen)"]);
    expect(contextWords(empty, labels)).toEqual([t("documents.page.scope.emptyContext")]);
    expect(stated("EQR 4", CV + "rev_confirmed")).toBe("EQR 4 (Bestätigt)");
    expect(joined(["a", "b"])).toBe(`a${t("documents.page.scope.separator")}b`);
  });

  it("name a concept no list holds by the last part of its IRI", () => {
    expect(levelWords(level({ level: LVL + "DQR-3" }), labels)).toBe("DQR-3");
    expect(levelWords(level({ level: CV + "sec_x" }), new Map())).toBe("sec_x");
  });
});
