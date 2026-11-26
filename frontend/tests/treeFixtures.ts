// The rows of a document's tree and its form, as the backend answers them (app/api/document_tree.py,
// app/api/profiles.py), for the tests of the tree's view.
import type { Form, FormField, FormValue, HeldValues, Tree, TreeNode, TreeStatement, ValueKindForm } from "@/api";

export const CV = "https://w3id.org/wlo/curriculum/vocab#";
export const SCHOOL = "https://w3id.org/wlo/curriculum/profile/school#";
/** Level systems and a competency model of the tests' own, as a vocabulary's values (synthetic). */
export const LVL = "https://example.org/levels#";

/** A holder without values. */
export function noValues(): HeldValues {
  return { level_assignments: [], time_spans: [], workloads: [] };
}

export function statement_(id: string, changes: Partial<TreeStatement> = {}): TreeStatement {
  return {
    id,
    position: 1,
    fields: { verbatim: `Aussage ${id}` },
    origin: CV + "orig_model",
    review_status: CV + "rev_proposed",
    revision: 1,
    iri: null,
    text_hash: "h",
    by_hand: false,
    anchors: [],
    values: noValues(),
    ...changes,
  };
}

export function node_(id: string, changes: Partial<TreeNode> = {}): TreeNode {
  return {
    id,
    position: 1,
    fields: { original_title: `Knoten ${id}`, code: null },
    code_assigned: false,
    origin: CV + "orig_model",
    review_status: CV + "rev_proposed",
    revision: 1,
    iri: null,
    findings: { violation: 0, warning: 0, info: 0 },
    anchors: [],
    values: noValues(),
    statements: [],
    children: [],
    ...changes,
  };
}

export function tree_(nodes: TreeNode[], changes: Partial<Tree> = {}): Tree {
  return { editable: true, reviewable: true, closed: null, counts: { nodes: {}, statements: {} }, nodes, ...changes };
}

export function value_(iri: string, label: string, changes: Partial<FormValue> = {}): FormValue {
  return {
    iri,
    notation: null,
    label,
    alt_labels: [],
    definition: null,
    note: null,
    delimitation: null,
    examples: [],
    broader: [],
    group: null,
    dimension: null,
    ...changes,
  };
}

export function field(key: string, kind: FormField["kind"], values: FormValue[] | null = null, required = false): FormField {
  return { key, kind, required, many: kind === "concepts", most: kind === "text" ? 2000 : null, values };
}

function kind(holders: ValueKindForm["holders"], fields: FormField[], changes: Partial<ValueKindForm> = {}): ValueKindForm {
  return { holders, fields, periods: null, rules: [], ...changes };
}

const LEVEL = { group: LVL + "language", dimension: CV + "dim_proficiency" };
const QUALIFICATION = { group: LVL + "qualification", dimension: CV + "dim_qualification" };

/** The values' form, one for every sector, as far as the tests ask it (backend app/vocab/value_forms.py). */
export function valuesForm_(): Pick<Form, "values" | "context" | "groups"> {
  return {
    values: {
      level_assignments: kind(
        ["node", "statement", "specification"],
        [
          field("level", "concept", [value_(LVL + "B1", "GER B1", LEVEL), value_(LVL + "B2", "GER B2", LEVEL), value_(LVL + "Q4", "Stufe Q4", QUALIFICATION)], true),
          field("level_to", "concept", [value_(LVL + "B1", "GER B1", LEVEL), value_(LVL + "B2", "GER B2", LEVEL), value_(LVL + "Q4", "Stufe Q4", QUALIFICATION)]),
          field("relation", "concept", [value_(CV + "lrel_minimum", "Mindestniveau"), value_(CV + "lrel_target", "Zielniveau")]),
          field("dimension", "concept", [value_(CV + "dim_proficiency", "Kompetenzstufe"), value_(CV + "dim_qualification", "Qualifikation")]),
          field("competence_dimension", "concept", [value_(LVL + "listening", "Hören", { group: LVL + "skills" })]),
        ],
        { rules: [{ holder: "statement", dimensions: [CV + "dim_qualification"], unless: null }] },
      ),
      time_spans: kind(["node", "specification"], [
        field("time_kind", "concept", [value_(CV + "time_gradeLevel", "Jahrgangsstufe"), value_(CV + "time_semester", "Fachsemester")], true),
        field("span_from", "number"),
        field("span_to", "number"),
        field("time_relation", "concept", [value_(CV + "trel_during", "während")]),
      ]),
      workloads: kind(
        ["node", "specification"],
        [
          field("amount", "number", null, true),
          field("amount_to", "number"),
          field("unit", "concept", [value_(CV + "unit_lesson", "Unterrichtsstunde", { notation: "lesson" }), value_(CV + "unit_hour", "Zeitstunde", { notation: "hour" })], true),
          field("workload_kind", "concept", [value_(CV + "wl_guidanceValue", "Zeitrichtwert")]),
          field("is_recommendation", "boolean"),
          field("minutes_per_unit", "number"),
          field("total", "boolean"),
        ],
        { periods: "time_spans" },
      ),
    },
    context: {
      fields: [
        field("sector", "concept", [value_(CV + "sec_school", "Schulbildung"), value_(CV + "sec_vet", "Berufsbildung")]),
        field("formality", "concept", [value_(CV + "form_formal", "formal")]),
        field("institution_text", "text"),
        field("target_group_text", "text"),
      ],
      values: ["level_assignments", "time_spans"],
    },
    groups: { [LVL + "language"]: "Sprachniveaus", [LVL + "qualification"]: "Qualifikationsstufen", [LVL + "skills"]: "Fertigkeiten" },
  };
}

/** A form that offers no kind of value: for the pages that ask the node and statement fields alone. */
export const NO_VALUES_FORM: Pick<Form, "values" | "context" | "groups"> = {
  values: { level_assignments: kind([], []), time_spans: kind([], []), workloads: kind([], [], { periods: "time_spans" }) },
  context: { fields: [], values: [] },
  groups: {},
};

/** The school's form, as far as the tests of the tree ask it. */
export function form_(sector = "school"): Form {
  return {
    sector,
    profile: "schule",
    node: [
      field("original_title", "text", null, true),
      field("function", "concept", [value_(CV + "fn_area", "Bereich"), value_(CV + "fn_unit", "Einheit")], true),
      field("node_type", "concept", [value_(SCHOOL + "Inhaltsbereich", "Inhaltsbereich", { broader: [CV + "fn_area"] })]),
      field("code", "text"),
    ],
    statement: [
      field("verbatim", "longtext", null, true),
      field("statement_kind", "concept", [value_(CV + "kind_learningOutcome", "Lernergebnis")], true),
      field("addressees", "concepts", [value_(CV + "addr_learner", "Lernende"), value_(CV + "addr_educator", "Lehrkräfte")], true),
      field("levelText", "text"),
    ],
    ...valuesForm_(),
  };
}
