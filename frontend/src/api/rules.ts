// A document's rules (plan M3a I; backend app/api/rules.py): read with what they may name and the units and kinds
// of requirement to choose from; a rule's values and links set on its revision, a rule added on its anchors, a rule
// taken away - rejected where a run read it, deleted where an editor made it.
import { apiFetch } from "./http";
import type { AnchorIn, Taken } from "./tree";

export type RuleKind = "selection" | "prerequisite" | "completion" | "recognition" | "progression";
export type RuleTargetKind = "node" | "statement" | "specification" | "variant";

/** A row a rule names: what the editors know it by, none for a row no list names. */
export interface RuleLink {
  id: string;
  kind: RuleTargetKind;
  label: string | null;
}

export interface RuleAnchor {
  page_start: number | null;
  page_end: number | null;
  blocks: string[];
}

export interface Rule {
  id: string;
  /** Given when the document is frozen. */
  iri: string | null;
  kind: string;
  verbatim: string;
  min_count: number | null;
  max_count: number | null;
  min_amount: number | null;
  max_amount: number | null;
  /** A concept of cv:WorkloadUnits. */
  amount_unit: string | null;
  /** A concept of cv:RequirementKinds: a prerequisite's. */
  requirement_kind: string | null;
  /** A recognition's, from 0 to 1. */
  max_share: number | null;
  /** The options as written, where no link names them. */
  option_texts: string[];
  applies_to: RuleLink[];
  /** A selection's. */
  options: RuleLink[];
  /** A prerequisite's. */
  requires: RuleLink[];
  origin: string;
  review_status: string;
  /** The token of an edit and of taking it away. */
  revision: number;
  /** An editor's: taken away, it is deleted. */
  by_hand: boolean;
  anchors: RuleAnchor[];
}

/** What a rule may name: a specification, a variant, a node. */
export interface RuleTarget {
  id: string;
  kind: RuleTargetKind;
  label: string;
}

export interface RuleChoice {
  iri: string;
  label: string;
}

export type RulesClosed = "frozen" | "job_open" | "not_extracted";

export interface Rules {
  /** The caller may edit them now. */
  editable: boolean;
  /** Why nobody may now, whoever reads. */
  closed: RulesClosed | null;
  /** In the document's order. */
  rules: Rule[];
  /** Specifications, their variants, the nodes from the top. */
  targets: RuleTarget[];
  /** Active ones, by their labels. */
  units: RuleChoice[];
  requirement_kinds: RuleChoice[];
}

/** The fields an edit sets: one left out stays, null empties it; a link field names all its targets. */
export interface RuleFields {
  kind?: RuleKind;
  verbatim?: string;
  min_count?: number | null;
  max_count?: number | null;
  min_amount?: number | null;
  max_amount?: number | null;
  amount_unit?: string | null;
  requirement_kind?: string | null;
  max_share?: number | null;
  option_texts?: string[];
  applies_to?: string[];
  options?: string[];
  requires?: string[];
}

export interface NewRule {
  kind: RuleKind;
  verbatim: string;
  anchors: AnchorIn[];
}

const rulePath = (id: string) => `/api/v1/rules/${encodeURIComponent(id)}`;
const documentRules = (documentId: string) => `/api/v1/documents/${encodeURIComponent(documentId)}/rules`;

/** The document's rules; 404 `no_document`, 403 `file_hidden`. */
export function getRules(documentId: string): Promise<Rules> {
  return apiFetch<Rules>(documentRules(documentId));
}

/**
 * Set a rule's fields on its revision, by the document's owner or an editor. 422 `invalid_field` (`details.field`,
 * `problem`); 409 `stale_revision` (`details.current`: the rule as it stands), `frozen`, `job_open`,
 * `not_extracted`; 404 `no_rule`.
 */
export function editRule(id: string, expectedRevision: number, fields: RuleFields): Promise<Rule> {
  return apiFetch<Rule>(rulePath(id), { method: "PATCH", body: JSON.stringify({ expected_revision: expectedRevision, ...fields }) });
}

/** Add a rule after the document's others on its anchors; 422 `anchor_missing`, `invalid_field`, as an edit else. */
export function addRule(documentId: string, rule: NewRule): Promise<Rule> {
  return apiFetch<Rule>(documentRules(documentId), { method: "POST", body: JSON.stringify(rule) });
}

/** Take a rule away read at revision `revision`: an editor's own is deleted, a run's rejected and kept. */
export function takeRule(id: string, revision: number): Promise<Taken> {
  return apiFetch<Taken>(`${rulePath(id)}?expected_revision=${revision}`, { method: "DELETE" });
}
