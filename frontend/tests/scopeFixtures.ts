// Synthetic specifications and the lists that name their values (plan M3a H1), as the backend answers them.
import type { Form, Specification, Specifications } from "@/api";

import { field, form_, value_ } from "./treeFixtures";

const CV = "https://w3id.org/wlo/curriculum/vocab#";
const CUR = "https://w3id.org/wlo/curriculum/core#";
const LVL = "https://w3id.org/wlo/curriculum/level/";
const STATED = { origin: CV + "orig_human", review_status: CV + "rev_proposed", revision: 1 };

/** The values' form, as far as the specifications' tests ask it: its labels name their values and contexts. */
export const SCOPE_FORM: Form = {
  ...form_(),
  values: {
    ...form_().values,
    level_assignments: {
      ...form_().values.level_assignments,
      fields: [field("level", "concept", [value_(LVL + "EQF-4", "EQR 4", { group: LVL + "eqf", dimension: CV + "dim_qualification" })], true)],
    },
    time_spans: {
      ...form_().values.time_spans,
      fields: [field("time_kind", "concept", [value_(CV + "time_gradeLevel", "Jahrgangsstufe")], true), field("span_from", "number"), field("span_to", "number")],
    },
    workloads: {
      ...form_().values.workloads,
      fields: [field("amount", "number", null, true), field("unit", "concept", [value_(CV + "unit_lesson", "Unterrichtsstunden")], true)],
    },
  },
  context: {
    fields: [
      field("sector", "concept", [value_(CV + "sec_school", "Schulbildung")]),
      field("formality", "concept", [value_(CV + "form_formal", "formal")]),
      field("institution_text", "text"),
      field("target_group_text", "text"),
    ],
    values: ["level_assignments", "time_spans"],
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
