// What holds a set of values (plan M3a G and H): a row of a document's tree - a node, a statement - or one of the
// document's specifications, as a row of its own on the page's applicability section, or one of its assessments, on
// the page's section of them (plan M3a J: its levels). Each is read at its revision, holds its values - a specification
// its applicability contexts too - and has them set as a whole on its own route, which answers it as it then stands.
import {
  setAssessmentValues,
  setNodeValues,
  setSpecificationValues,
  setStatementValues,
  type ApplicabilityContext,
  type Assessment,
  type Form,
  type HeldValues,
  type Specification,
} from "@/api";
import type { Row } from "@/documentTree";
import { contextsOf, requestOf, type HeldSet, type ValuesDraft } from "@/valueDraft";

/** A specification as a holder of values. */
export interface SpecificationRow {
  kind: "specification";
  key: `specification:${string}`;
  specification: Specification;
}

/** An assessment as a holder of values: its levels. */
export interface AssessmentHolderRow {
  kind: "assessment";
  key: `assessment:${string}`;
  assessment: Assessment;
}

export type HolderRow = Row | SpecificationRow | AssessmentHolderRow;
export type HolderKey = HolderRow["key"];

/** A holder as stored - as a set's answer gives it, and a stale set's `details.current`. */
export interface Holder {
  values: HeldValues;
  revision: number;
  contexts?: ApplicabilityContext[];
}

// one row for each specification or assessment read: a render of the section is no reading anew
const ROWS = new WeakMap<Specification, SpecificationRow>();
const ASSESSMENT_ROWS = new WeakMap<Assessment, AssessmentHolderRow>();
// an assessment's class in the core, as a level rule's `unless` would name it (backend app/api/values.py)
const CUR = "https://w3id.org/wlo/curriculum/core#";
const ASSESSMENT_TYPE = CUR + "Assessment";

/** The specification `specification` as a holder's row. */
export function specificationRow(specification: Specification): SpecificationRow {
  let row = ROWS.get(specification);
  if (!row) {
    row = { kind: "specification", key: `specification:${specification.id}`, specification };
    ROWS.set(specification, row);
  }
  return row;
}

/** The assessment `assessment` as a holder's row. */
export function assessmentRow(assessment: Assessment): AssessmentHolderRow {
  let row = ASSESSMENT_ROWS.get(assessment);
  if (!row) {
    row = { kind: "assessment", key: `assessment:${assessment.id}`, assessment };
    ASSESSMENT_ROWS.set(assessment, row);
  }
  return row;
}

export function holderOf(row: HolderRow): Holder {
  if (row.kind === "node") return row.node;
  if (row.kind === "assessment") return row.assessment;
  return row.kind === "statement" ? row.statement : row.specification;
}

/** What the holder holds: its values, a specification's contexts with them. */
export function heldOf(holder: Holder): HeldSet {
  return holder.contexts ? { ...holder.values, contexts: holder.contexts } : holder.values;
}

/** A statement's kind, a specification's or an assessment's class: what a level rule's `unless` names; none for a node. */
export function holderTypeOf(row: HolderRow): string | null {
  if (row.kind === "specification") return row.specification.type;
  if (row.kind === "assessment") return ASSESSMENT_TYPE;
  const kind = row.kind === "statement" ? row.statement.fields.statement_kind : null;
  return typeof kind === "string" ? kind : null;
}

/** Set the holder's values to the draft `draft`, on its revision `revision`; the holder as it then stands. */
export function sendValues(row: HolderRow, revision: number, form: Form, draft: ValuesDraft): Promise<Holder> {
  const set = requestOf(form, draft);
  if (row.kind === "node") return setNodeValues(row.node.id, revision, set);
  if (row.kind === "statement") return setStatementValues(row.statement.id, revision, set);
  if (row.kind === "assessment") return setAssessmentValues(row.assessment.id, revision, set);
  return setSpecificationValues(row.specification.id, revision, { ...set, contexts: contextsOf(form, draft) });
}
