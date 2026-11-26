// A document's specifications and their applicability (plan M3a H1; backend app/api/specifications.py): read with
// their variants, own values and applicability contexts - each context with its time spans and levels -; a
// specification's title and field set on its revision; its values and contexts set as a whole on it.
import { apiFetch } from "./http";
import type { LevelIn, TimeSpanIn, ValuesIn } from "./values";

/** Where a stored value or context came from, how far it is reviewed, and its revision (backend StatedOut). */
export interface ScopeStated {
  id: string;
  origin: string;
  review_status: string;
  revision: number;
}

export interface ScopeLevel extends ScopeStated {
  level: string;
  level_to: string | null;
  relation: string | null;
  dimension: string | null;
  competence_dimension: string | null;
}

export interface ScopeTimeSpan extends ScopeStated {
  time_kind: string;
  span_from: number | null;
  span_to: number | null;
  time_relation: string | null;
}

export interface ScopeWorkload extends ScopeStated {
  amount: number;
  amount_to: number | null;
  unit: string;
  workload_kind: string | null;
  is_recommendation: boolean;
  minutes_per_unit: number | null;
  total: boolean;
  periods: ScopeTimeSpan[];
}

/** A specification's own values (backend ValuesOut). */
export interface ScopeValues {
  level_assignments: ScopeLevel[];
  time_spans: ScopeTimeSpan[];
  workloads: ScopeWorkload[];
}

/** An applicability context (cur:ApplicabilityContext): an AND of what it states and of its values. */
export interface ApplicabilityContext extends ScopeStated {
  /** A concept of cv:EducationSectors. */
  sector: string | null;
  /** A concept of cv:Formalities. */
  formality: string | null;
  institution_text: string | null;
  target_group_text: string | null;
  level_assignments: ScopeLevel[];
  time_spans: ScopeTimeSpan[];
}

export interface SpecificationVariant {
  id: string;
  key: string;
  label: string;
  /** A concept of cv:VariantKinds. */
  variant_kind: string;
}

export type SpecificationKind = "curriculum" | "competencyFramework" | "qualificationSpecification" | "assessmentSpecification";

export interface Specification {
  id: string;
  /** What its IRI is made of: it stays. */
  key: string;
  spec_kind: SpecificationKind;
  /** Its class in the core (cur:Curriculum …), as a level rule's `unless` names it. */
  type: string;
  title: string;
  field_text: string | null;
  /** The token of an edit and of a set of its values. */
  revision: number;
  /** X1's, read only. */
  variants: SpecificationVariant[];
  values: ScopeValues;
  contexts: ApplicabilityContext[];
}

export type SpecificationsClosed = "frozen" | "job_open" | "not_extracted";

export interface Specifications {
  /** The caller may edit them now. */
  editable: boolean;
  /** Why nobody may now, whoever reads. */
  closed: SpecificationsClosed | null;
  /** By key. */
  specifications: Specification[];
}

/** The fields an edit sets: one left out stays, an emptied field text none. */
export interface SpecificationFields {
  title?: string;
  field_text?: string | null;
}

/** A concept a list of the values' form offers (backend ValueOut): what a value's IRI is called. */
export interface ScopeFormValue {
  iri: string;
  label: string;
}

export interface ScopeFormField {
  key: string;
  values: ScopeFormValue[] | null;
}

/** What the page names the values and contexts by: the lists of the values' form and of a context (backend FormOut). */
export interface ScopeForm {
  values: Record<string, { fields: ScopeFormField[] }>;
  context: { fields: ScopeFormField[] };
}

const specificationPath = (id: string) => `/api/v1/specifications/${encodeURIComponent(id)}`;

/** The document's specifications; 404 `no_document`, 403 `file_hidden`. */
export function getSpecifications(documentId: string): Promise<Specifications> {
  return apiFetch<Specifications>(`/api/v1/documents/${encodeURIComponent(documentId)}/specifications`);
}

/**
 * Sets a specification's title or field on its revision, by the document's owner or an editor. 422 `invalid_field`
 * (`details.field`, `problem`); 409 `stale_revision` (`details.current`: the specification as it stands), `frozen`,
 * `job_open`, `not_extracted`; 404 `no_specification`.
 */
export function editSpecification(id: string, expectedRevision: number, fields: SpecificationFields): Promise<Specification> {
  return apiFetch<Specification>(specificationPath(id), {
    method: "PATCH",
    body: JSON.stringify({ expected_revision: expectedRevision, ...fields }),
  });
}

/** An applicability context as a set names it: by its `id` one the specification keeps, without a new one (backend ContextIn). */
export interface ContextIn {
  id: string | null;
  sector: string | null;
  formality: string | null;
  institution_text: string | null;
  target_group_text: string | null;
  level_assignments: LevelIn[];
  time_spans: TimeSpanIn[];
}

/** A specification's values and contexts, every kind named: what the set leaves out goes (backend SpecificationValuesIn). */
export interface SpecificationValuesIn extends ValuesIn {
  contexts: ContextIn[];
}

/**
 * Set a specification's levels, time spans, workloads and applicability contexts as a whole, read at its revision
 * `revision`; the specification as it then stands. Refused as a node's values (setNodeValues), 404
 * `no_specification`; a context's problem at its path (`contexts[0].sector`), one the store refuses in a context at
 * the context (`contexts[0]`) or its kind (`contexts[0].level_assignments`).
 */
export function setSpecificationValues(id: string, revision: number, values: SpecificationValuesIn): Promise<Specification> {
  return apiFetch<Specification>(`${specificationPath(id)}/values`, {
    method: "PUT",
    body: JSON.stringify({ expected_revision: revision, ...values }),
  });
}
