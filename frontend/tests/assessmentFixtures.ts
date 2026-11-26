// Synthetic assessments of a document (plan M3a J), as the backend answers them, and the values' form that names the
// levels at them.
import type { Assessment, Assessments, Form } from "@/api";

import { SCOPE_FORM } from "./scopeFixtures";
import { field, value_ } from "./treeFixtures";

export const CV = "https://w3id.org/wlo/curriculum/vocab#";
export const LVL = "https://w3id.org/wlo/curriculum/level/";
const STATED = { origin: CV + "orig_human", review_status: CV + "rev_proposed", revision: 1 };

/** The values' form, its levels held at an assessment too - a grade among them. */
export const ASSESSMENT_FORM: Form = {
  ...SCOPE_FORM,
  values: {
    ...SCOPE_FORM.values,
    level_assignments: {
      ...SCOPE_FORM.values.level_assignments,
      holders: ["node", "statement", "specification", "assessment"],
      fields: [field("level", "concept", [value_(LVL + "grade-2", "Note 2", { group: LVL + "grade", dimension: CV + "dim_grading" })], true)],
    },
  },
};

export function assessmentOf(more: Partial<Assessment> = {}): Assessment {
  return {
    id: "a1",
    ...STATED,
    parent_kind: "specification",
    parent_id: "s1",
    position: 1,
    assessment_kind: CV + "ak_exam",
    label: "Abschlussprüfung",
    duration_minutes: 240,
    weight_percent: null,
    graded: true,
    iri: null,
    targets: [],
    values: { level_assignments: [], time_spans: [], workloads: [] },
    ...more,
  };
}

/** An examination with a part that assesses a node and is graded in a level. */
export function examWithPart(): Assessment[] {
  return [
    assessmentOf(),
    assessmentOf({
      id: "a2",
      parent_kind: "assessment",
      parent_id: "a1",
      assessment_kind: CV + "ak_examPart",
      label: "Teil 1",
      duration_minutes: null,
      weight_percent: 37.5,
      graded: null,
      targets: [{ kind: "node", id: "n1", label: "LF 1 Optik" }],
      values: {
        level_assignments: [{ id: "l1", ...STATED, level: LVL + "grade-2", level_to: null, relation: null, dimension: null, competence_dimension: null }],
        time_spans: [],
        workloads: [],
      },
    }),
  ];
}

export function assessmentsOf(more: Partial<Assessments> = {}): Assessments {
  return {
    editable: true,
    closed: null,
    assessments: [],
    choices: [
      { kind: "specification", id: "s1", label: "Physik" },
      { kind: "node", id: "n1", label: "LF 1 Optik" },
      { kind: "node", id: "n2", label: "LF 2 Mechanik" },
    ],
    kinds: [
      { iri: CV + "ak_exam", label: "Prüfung" },
      { iri: CV + "ak_examPart", label: "Prüfungsteil" },
    ],
    ...more,
  };
}
