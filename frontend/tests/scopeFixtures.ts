// Synthetic specifications and the lists that name their values (plan M3a H1), as the backend answers them.
import type { ScopeForm, Specification, Specifications } from "@/api";

const CV = "https://w3id.org/wlo/curriculum/vocab#";
const CUR = "https://w3id.org/wlo/curriculum/core#";
const LVL = "https://w3id.org/wlo/curriculum/level/";
const STATED = { origin: CV + "orig_human", review_status: CV + "rev_proposed", revision: 1 };

export const SCOPE_FORM: ScopeForm = {
  values: {
    level_assignments: { fields: [{ key: "level", values: [{ iri: LVL + "EQF-4", label: "EQR 4" }] }] },
    time_spans: { fields: [{ key: "time_kind", values: [{ iri: CV + "time_gradeLevel", label: "Jahrgangsstufe" }] }] },
    workloads: { fields: [{ key: "unit", values: [{ iri: CV + "unit_lesson", label: "Unterrichtsstunden" }] }] },
  },
  context: {
    fields: [
      { key: "sector", values: [{ iri: CV + "sec_school", label: "Schulbildung" }] },
      { key: "formality", values: [{ iri: CV + "form_formal", label: "formal" }] },
    ],
  },
};

export function specificationOf(more: Partial<Specification> = {}): Specification {
  return {
    id: "s1",
    key: "lp",
    spec_kind: "curriculum",
    type: CUR + "Curriculum",
    title: "Physik",
    field_text: null,
    revision: 1,
    variants: [{ id: "v1", key: "g8", label: "G8", variant_kind: CV + "var_track" }],
    values: { level_assignments: [], time_spans: [], workloads: [] },
    contexts: [],
    ...more,
  };
}

/** A specification with a value of each kind and a context. */
export function valuedSpecification(): Specification {
  return specificationOf({
    field_text: "Naturwissenschaften",
    values: {
      level_assignments: [
        { ...STATED, id: "l1", level: LVL + "EQF-4", level_to: null, relation: null, dimension: null, competence_dimension: null },
      ],
      time_spans: [],
      workloads: [
        {
          ...STATED, id: "w1", amount: 80, amount_to: null, unit: CV + "unit_lesson", workload_kind: null,
          is_recommendation: false, minutes_per_unit: null, total: true, periods: [],
        },
      ],
    },
    contexts: [
      {
        ...STATED, id: "c1", sector: CV + "sec_school", formality: CV + "form_formal", institution_text: "Gymnasium",
        target_group_text: null, level_assignments: [],
        time_spans: [{ ...STATED, id: "t1", time_kind: CV + "time_gradeLevel", span_from: 5, span_to: 6, time_relation: null }],
      },
    ],
  });
}

export function specificationsOf(more: Partial<Specifications> = {}): Specifications {
  return { editable: true, closed: null, specifications: [specificationOf()], ...more };
}
