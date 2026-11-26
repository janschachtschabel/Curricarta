// What holds a set of values (plan M3a G and H): a row of a document's tree - a node, a statement - or one of the
// document's specifications, as a row of its own on the page's applicability section. Each is read at its revision,
// holds its values - a specification its applicability contexts too - and has them set as a whole on its own route,
// which answers it as it then stands.
import {
  setNodeValues,
  setSpecificationValues,
  setStatementValues,
  type ApplicabilityContext,
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

export type HolderRow = Row | SpecificationRow;
export type HolderKey = HolderRow["key"];

/** A holder as stored - as a set's answer gives it, and a stale set's `details.current`. */
export interface Holder {
  values: HeldValues;
  revision: number;
  contexts?: ApplicabilityContext[];
}

// one row for each specification read: a render of the section is no reading anew
const ROWS = new WeakMap<Specification, SpecificationRow>();

/** The specification `specification` as a holder's row. */
export function specificationRow(specification: Specification): SpecificationRow {
  let row = ROWS.get(specification);
  if (!row) {
    row = { kind: "specification", key: `specification:${specification.id}`, specification };
    ROWS.set(specification, row);
  }
  return row;
}

export function holderOf(row: HolderRow): Holder {
  if (row.kind === "node") return row.node;
  return row.kind === "statement" ? row.statement : row.specification;
}

/** What the holder holds: its values, a specification's contexts with them. */
export function heldOf(holder: Holder): HeldSet {
  return holder.contexts ? { ...holder.values, contexts: holder.contexts } : holder.values;
}

/** A statement's kind, a specification's class: what a level rule's `unless` names; none for a node. */
export function holderTypeOf(row: HolderRow): string | null {
  if (row.kind === "specification") return row.specification.type;
  const kind = row.kind === "statement" ? row.statement.fields.statement_kind : null;
  return typeof kind === "string" ? kind : null;
}

/** Set the holder's values to the draft `draft`, on its revision `revision`; the holder as it then stands. */
export function sendValues(row: HolderRow, revision: number, form: Form, draft: ValuesDraft): Promise<Holder> {
  const set = requestOf(form, draft);
  if (row.kind === "node") return setNodeValues(row.node.id, revision, set);
  if (row.kind === "statement") return setStatementValues(row.statement.id, revision, set);
  return setSpecificationValues(row.specification.id, revision, { ...set, contexts: contextsOf(form, draft) });
}
