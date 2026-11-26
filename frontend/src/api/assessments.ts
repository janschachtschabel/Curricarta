// A document's assessments (plan M3a J; backend app/api/assessments.py): read with what they assess, the levels at
// them and what an assessment may be a part of or assess; one added under its parent, one's fields set on its
// revision, one taken away with its parts, the levels at one set as a whole on its revision.
import { apiFetch } from "./http";
import type { HeldValues, ValuesIn } from "./values";

/** What an assessment assesses: a node by its code and title, a statement by its wording, cut. */
export interface AssessmentTarget {
  kind: "node" | "statement";
  id: string;
  label: string | null;
}

export interface Assessment {
  id: string;
  origin: string;
  review_status: string;
  /** The token of an edit and of a set of its levels. */
  revision: number;
  parent_kind: "assessment" | "specification" | "node";
  parent_id: string;
  /** Among the parts of its parent, from 1. */
  position: number;
  /** A concept of cv:AssessmentKinds. */
  assessment_kind: string;
  label: string | null;
  duration_minutes: number | null;
  weight_percent: number | null;
  graded: boolean | null;
  /** Given when the document is frozen. */
  iri: string | null;
  targets: AssessmentTarget[];
  /** The levels at it; it holds no time spans or workloads. */
  values: HeldValues;
}

/** A specification or a node an assessment may be a part of or assess. */
export interface AssessmentChoice {
  kind: "specification" | "node";
  id: string;
  label: string | null;
}

/** A kind of assessment the list offers (cv:AssessmentKinds, active), by its label. */
export interface AssessmentKind {
  iri: string;
  label: string;
}

export type AssessmentsClosed = "frozen" | "job_open" | "not_extracted";

export interface Assessments {
  /** The caller may edit them now. */
  editable: boolean;
  /** Why nobody may now, whoever reads. */
  closed: AssessmentsClosed | null;
  /** Each part after the assessment it is a part of. */
  assessments: Assessment[];
  choices: AssessmentChoice[];
  kinds: AssessmentKind[];
}

/** An assessment's fields as a new one or an edit sends them; `targets` the whole list. */
export interface AssessmentFields {
  parent_id: string;
  assessment_kind: string;
  label: string | null;
  duration_minutes: number | null;
  weight_percent: number | null;
  graded: boolean | null;
  targets: string[];
}

const assessmentPath = (id: string) => `/api/v1/assessments/${encodeURIComponent(id)}`;

/** The document's assessments; 404 `no_document`, 403 `file_hidden`. */
export function getAssessments(documentId: string): Promise<Assessments> {
  return apiFetch<Assessments>(`/api/v1/documents/${encodeURIComponent(documentId)}/assessments`);
}

/**
 * Add an assessment after the parts of its parent, by the document's owner or an editor. 422 `invalid_field`
 * (`details.field`, `problem`); 409 `frozen`, `job_open`, `not_extracted`; 404 `no_document`.
 */
export function addAssessment(documentId: string, fields: AssessmentFields): Promise<Assessment> {
  return apiFetch<Assessment>(`/api/v1/documents/${encodeURIComponent(documentId)}/assessments`, {
    method: "POST",
    body: JSON.stringify(fields),
  });
}

/**
 * Set an assessment's fields on its revision: 422 `invalid_field` (`parent_id` `cycle` for a parent among its own
 * parts); 409 `stale_revision` (`details.current`: the assessment as it stands), `frozen`, `job_open`,
 * `not_extracted`; 404 `no_assessment`.
 */
export function editAssessment(id: string, expectedRevision: number, fields: Partial<AssessmentFields>): Promise<Assessment> {
  return apiFetch<Assessment>(assessmentPath(id), {
    method: "PATCH",
    body: JSON.stringify({ expected_revision: expectedRevision, ...fields }),
  });
}

/** Take an assessment away with its parts, on its revision; how many went. Refused as an edit, without a field. */
export function dropAssessment(id: string, expectedRevision: number): Promise<{ assessments: number }> {
  return apiFetch<{ assessments: number }>(`${assessmentPath(id)}?expected_revision=${expectedRevision}`, {
    method: "DELETE",
  });
}

/** Set the levels at an assessment as a whole, as a node's values (setNodeValues); the assessment as it then stands. */
export function setAssessmentValues(id: string, revision: number, values: ValuesIn): Promise<Assessment> {
  return apiFetch<Assessment>(`${assessmentPath(id)}/values`, {
    method: "PUT",
    body: JSON.stringify({ expected_revision: revision, ...values }),
  });
}
