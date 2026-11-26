// The second layer's values of a document's rows (plan M3a G): a node's levels, time spans and workloads and a
// statement's levels as the tree answers them (backend app/api/value_answers.py), the form of each kind
// (app/api/profiles.py, FormOut.values), and a holder's set of them, set as a whole (app/api/values.py).
import { apiFetch } from "./http";
import type { FormField, NodeRow, TreeStatement } from "./tree";

/** A kind of the second layer's values, by its key in a set of them (backend ValueKind). */
export type ValueKind = "level_assignments" | "time_spans" | "workloads";

/** What may hold a kind of value (backend HolderKind); a specification's values follow with its editing. */
export type HolderKind = "node" | "statement" | "specification";

/** What a level rule is of: a holder of a set, or an applicability context within a specification's (backend RuleHolder). */
export type RuleHolder = HolderKind | "applicability_context";

/** A value as the tree answers it: who stated it, how far it is reviewed (backend StatedOut). */
interface StatedValue {
  /** Names it in a set that keeps it and in a review. */
  id: string;
  origin: string;
  review_status: string;
  /** The value's own, as a review names it. */
  revision: number;
}

/** A level, or a range of levels of one system (backend LevelOut); its fields' IRIs by the values' form. */
export interface HeldLevel extends StatedValue {
  level: string;
  level_to: string | null;
  relation: string | null;
  dimension: string | null;
  competence_dimension: string | null;
}

export interface HeldTimeSpan extends StatedValue {
  time_kind: string;
  span_from: number | null;
  span_to: number | null;
  time_relation: string | null;
}

export interface HeldWorkload extends StatedValue {
  amount: number;
  amount_to: number | null;
  unit: string;
  workload_kind: string | null;
  is_recommendation: boolean;
  /** A whole number. */
  minutes_per_unit: number | null;
  /** The holder's whole. */
  total: boolean;
  /** The time spans it is given in, in order. */
  periods: HeldTimeSpan[];
}

/** A holder's values, each kind in order (backend ValuesOut). */
export interface HeldValues {
  level_assignments: HeldLevel[];
  time_spans: HeldTimeSpan[];
  workloads: HeldWorkload[];
}

/**
 * Levels of these dimensions - their system's or the assignment's own - the holder never holds, but where its
 * type (a statement's kind) is `unless` (backend LevelRuleOut).
 */
export interface LevelRule {
  holder: RuleHolder;
  dimensions: string[];
  unless: string | null;
}

/** A kind of value: who is offered it, and its fields (backend ValueKindOut). */
export interface ValueKindForm {
  holders: HolderKind[];
  fields: FormField[];
  /** The kind a workload's periods are, with that kind's fields. */
  periods: ValueKind | null;
  rules: LevelRule[];
}

/** A value as a review names it: by its table - a specification's applicability context too (backend ReviewKind). */
export type ValueTable = "level_assignment" | "time_span" | "workload" | "applicability_context";

/**
 * A specification's applicability context in the values' form (backend ContextFormOut): its own fields, and the
 * kinds of value it holds, with those kinds' fields (`Form.values`).
 */
export interface ContextForm {
  fields: FormField[];
  values: ValueKind[];
}

/** A level as a set names it: by its `id` one the holder keeps, without a new one (backend LevelIn). */
export interface LevelIn {
  id: string | null;
  level: string;
  level_to: string | null;
  relation: string | null;
  dimension: string | null;
  competence_dimension: string | null;
}

export interface TimeSpanIn {
  id: string | null;
  time_kind: string;
  span_from: number | null;
  span_to: number | null;
  time_relation: string | null;
}

export interface WorkloadIn {
  id: string | null;
  amount: number;
  amount_to: number | null;
  unit: string;
  workload_kind: string | null;
  is_recommendation: boolean;
  minutes_per_unit: number | null;
  total: boolean;
  periods: TimeSpanIn[];
}

/** A holder's values, every kind named: what the set leaves out goes (backend ValuesIn, without the revision). */
export interface ValuesIn {
  level_assignments: LevelIn[];
  time_spans: TimeSpanIn[];
  workloads: WorkloadIn[];
}

/**
 * Set a node's levels, time spans and workloads as a whole, read at the node's revision `revision`; the node as it
 * then stands. 409 `stale_revision` (details.current: the node as stored), `job_open`, `frozen`, `not_extracted`;
 * 422 `invalid_field` (details.field: the path in the set, `workloads[1].unit`; details.problem).
 */
export function setNodeValues(id: string, revision: number, values: ValuesIn): Promise<NodeRow> {
  return apiFetch<NodeRow>(`/api/v1/nodes/${encodeURIComponent(id)}/values`, {
    method: "PUT",
    body: JSON.stringify({ expected_revision: revision, ...values }),
  });
}

/** Set a statement's levels as `setNodeValues` a node's values; the statement as it then stands. */
export function setStatementValues(id: string, revision: number, values: ValuesIn): Promise<TreeStatement> {
  return apiFetch<TreeStatement>(`/api/v1/statements/${encodeURIComponent(id)}/values`, {
    method: "PUT",
    body: JSON.stringify({ expected_revision: revision, ...values }),
  });
}
