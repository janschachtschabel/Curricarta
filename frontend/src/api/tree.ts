// A document's nodes and statements as the editor reads them (backend app/api/document_tree.py) and changes
// them (app/api/node_editing.py, statement_editing.py), the form their fields follow (app/api/profiles.py),
// and the pages of the conversion the document was read off - the blocks its anchors name
// (app/api/document_blocks.py). A node's levels, time spans and workloads and a statement's levels - the second
// layer's values (app/api/value_answers.py) - are set as a whole (app/api/values.py).
import type { BlockPage } from "./conversions";
import type { FindingSeverity } from "./documents";
import { apiFetch } from "./http";

/** A field's value: a text, a value's IRI, the IRIs of a field of many; none where it is unset. */
export type FieldValue = string | string[] | null;

/** Where a node's title or a statement stands in the document (backend AnchorOut). */
export interface TreeAnchor {
  id: string;
  /** Physical pages, from 1. */
  page_start: number | null;
  page_end: number | null;
  /** As the document prints it. */
  printed_page: string | null;
  /** The passage found. */
  quote: string | null;
  /** How it was found (cv:MatchKinds); none before X5 looked. */
  match_kind: string | null;
  match_score: number | null;
  /** In the document's order. */
  blocks: string[];
}

export interface TreeStatement {
  id: string;
  position: number;
  /** By the keys of the form's statement fields, each of them. */
  fields: Record<string, FieldValue>;
  origin: string;
  review_status: string;
  /** The change of the statement an edit of it names. */
  revision: number;
  /** Given when its document was frozen; a draft copy's rows bring theirs. */
  iri: string | null;
  text_hash: string;
  /** An editor's own from the first: taking it away deletes it; a run's is rejected and kept. */
  by_hand: boolean;
  anchors: TreeAnchor[];
  /** Its levels; set by `setStatementValues`. */
  values: HeldValues;
}

/** A node as a change of it answers: without its statements and children (backend NodeRowOut). */
export interface NodeRow {
  id: string;
  position: number;
  /** By the keys of the form's node fields, each of them. */
  fields: Record<string, FieldValue>;
  /** Its code is its position: the source names none. */
  code_assigned: boolean;
  origin: string;
  review_status: string;
  revision: number;
  iri: string | null;
  /** On the node and its anchors, its statements and theirs - not its children's. */
  findings: Record<FindingSeverity, number>;
  anchors: TreeAnchor[];
  /** Its levels, time spans and workloads; set by `setNodeValues`. */
  values: HeldValues;
}

export interface TreeNode extends NodeRow {
  statements: TreeStatement[];
  children: TreeNode[];
}

/** A kind of the second layer's values, by its key in a set of them (backend ValueKind). */
export type ValueKind = "level_assignments" | "time_spans" | "workloads";

/** What may hold a kind of value (backend HolderKind); a specification's values follow with its editing. */
export type HolderKind = "node" | "statement" | "specification";

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

/** Why nobody may change the tree now, whoever reads it: the reason that lasts longest. */
export type TreeClosed = "frozen" | "job_open" | "not_extracted";

export interface Tree {
  /** The caller may edit the nodes and statements now. */
  editable: boolean;
  /** The caller may set their review status now. */
  reviewable: boolean;
  /** Why nobody may change it now; none while it is open. */
  closed: TreeClosed | null;
  /** By review status (cv:ReviewStatuses), each of them. */
  counts: { nodes: Record<string, number>; statements: Record<string, number> };
  /** From the top, in their order. */
  nodes: TreeNode[];
}

/** A value of a list field: a concept of the core vocabulary or the sector's profile (backend ValueOut). */
export interface FormValue {
  iri: string;
  notation: string | null;
  label: string;
  alt_labels: string[];
  definition: string | null;
  /** skos:scopeNote. */
  note: string | null;
  /** What it is not for. */
  delimitation: string | null;
  examples: string[];
  /** The core values it refines: a node type's function, a subkind's kind. */
  broader: string[];
  /** A level's system, a competence dimension's model (`Form.groups`); none for others. */
  group: string | null;
  /** A level's system's dimension (cv:LevelDimensions), which a value kind's `rules` name. */
  dimension: string | null;
}

/** A number and a yes or no: fields of the second layer's values alone. */
export type FieldKind = "text" | "longtext" | "concept" | "concepts" | "number" | "boolean";

export interface FormField {
  key: string;
  kind: FieldKind;
  required: boolean;
  many: boolean;
  /** Signs, for a text. */
  most: number | null;
  /** A list's, active ones in the order of their labels; none for a text. */
  values: FormValue[] | null;
}

/**
 * Levels of these dimensions - their system's or the assignment's own - the holder never holds, but where its
 * type (a statement's kind) is `unless` (backend LevelRuleOut).
 */
export interface LevelRule {
  holder: HolderKind;
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

export interface Form {
  sector: string;
  profile: string;
  node: FormField[];
  statement: FormField[];
  /** The second layer's values: one form for every sector. */
  values: Record<ValueKind, ValueKindForm>;
  /** The label of each group a value names. */
  groups: Record<string, string>;
}

/** The fields a change names, by the keys of the form: left out stays, none (or a blank text) clears. */
export type EditFields = Record<string, FieldValue>;

/**
 * Where a statement stands, as an edit names it (backend AnchorIn): blocks of the document's conversion - its
 * pages follow from them -, or the page it stands on where no block holds it.
 */
export type AnchorIn = { blocks: string[] } | { page: number };

/** What taking a node away took with it: the node and those under it, and their statements (backend DroppedOut). */
export interface Dropped {
  nodes: number;
  statements: number;
}

/** What taking a statement away did (backend TakenOut): an editor's own deleted, a run's rejected and kept. */
export interface Taken {
  outcome: "deleted" | "rejected";
  /** The rejected statement's after; none once deleted. */
  revision: number | null;
}

/** A review status by its cv:ReviewStatuses name without "rev_" (backend ReviewIn). */
export type ReviewStatus = "proposed" | "confirmed" | "rejected";

/** A value as a review names it: by its table (backend ReviewKind). */
export type ValueTable = "level_assignment" | "time_span" | "workload";

/** A row or a value a review names, at the revision it was read at (backend ReviewItemIn). */
export interface ReviewItem {
  kind: "node" | "statement" | ValueTable;
  id: string;
  revision: number;
}

/** Each row a review named, once, in the order asked, at its revision after (backend ReviewOut). */
export interface Reviewed {
  revisions: { id: string; revision: number }[];
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

/** A page of the document's own conversion, with the count of its pages (backend DocumentPageOut). */
export interface DocumentPage extends BlockPage {
  pages: number;
}

/**
 * The document's nodes and statements; 404 `no_document` to one who may not read it, 403 `file_hidden` where the
 * entry's content is no longer the caller's.
 */
export function getTree(documentId: string): Promise<Tree> {
  return apiFetch<Tree>(`${documentPath(documentId)}/tree`);
}

/** The fields of a node and of a statement in the sector's profile; 404 `unknown_sector`. */
export function getForm(sector: string): Promise<Form> {
  return apiFetch<Form>(`/api/v1/profiles/${encodeURIComponent(sector)}/form`);
}

/** Page `page` (from 1) of the conversion the document was read off; 403 `file_hidden`, 404 `no_such_page`. */
export function getDocumentBlocks(documentId: string, page: number): Promise<DocumentPage> {
  return apiFetch<DocumentPage>(`${documentPath(documentId)}/blocks?page=${page}`);
}

/**
 * Change a node's fields, the change read at revision `revision`; the node as it then stands. 409
 * `stale_revision` (details.current: the node as stored, none where it is gone), `job_open`, `frozen`,
 * `not_extracted`, `no_form`; 422 `invalid_field` (details.field, details.problem).
 */
export function editNode(id: string, revision: number, fields: EditFields): Promise<NodeRow> {
  return apiFetch<NodeRow>(`/api/v1/nodes/${encodeURIComponent(id)}`, {
    method: "PATCH",
    body: JSON.stringify({ expected_revision: revision, fields }),
  });
}

/**
 * Change a statement's fields as `editNode` a node's, and with `anchors` all its anchors in their place
 * (at most 20); left out, they stay as they are. 422 `invalid_field` with details.field `anchors` (problem
 * `unknown_block`, `no_page`), `anchor_missing`.
 */
export function editStatement(
  id: string,
  revision: number,
  fields: EditFields,
  anchors?: AnchorIn[],
): Promise<TreeStatement> {
  return apiFetch<TreeStatement>(`/api/v1/statements/${encodeURIComponent(id)}`, {
    method: "PATCH",
    // left out where undefined: the anchors stay
    body: JSON.stringify({ expected_revision: revision, fields, anchors }),
  });
}

/**
 * Add a node after its siblings: under `parentId`, or at the document's top where none; the node as it then
 * stands. 404 `no_document`, `no_node` (the parent); refusals as `editNode`'s.
 */
export function addNode(documentId: string, parentId: string | null, fields: EditFields): Promise<NodeRow> {
  return apiFetch<NodeRow>(`${documentPath(documentId)}/nodes`, {
    method: "POST",
    body: JSON.stringify({ parent_id: parentId, fields }),
  });
}

/**
 * Add a statement after the node's others, with one anchor at least (422 `anchor_missing` without); the
 * statement as it then stands. 404 `no_node`; refusals as `editStatement`'s.
 */
export function addStatement(nodeId: string, fields: EditFields, anchors: AnchorIn[]): Promise<TreeStatement> {
  return apiFetch<TreeStatement>(`/api/v1/nodes/${encodeURIComponent(nodeId)}/statements`, {
    method: "POST",
    body: JSON.stringify({ fields, anchors }),
  });
}

/**
 * Take a node away with its subtree and the findings on them, read at revision `revision`. 409
 * `stale_revision` as `editNode`'s, `job_open`, `frozen`, `not_extracted`.
 */
export function dropNode(id: string, revision: number): Promise<Dropped> {
  return apiFetch<Dropped>(`/api/v1/nodes/${encodeURIComponent(id)}?expected_revision=${revision}`, {
    method: "DELETE",
  });
}

/** Take a statement away as `dropNode` a node: an editor's own is deleted, a run's rejected and kept. */
export function dropStatement(id: string, revision: number): Promise<Taken> {
  return apiFetch<Taken>(`/api/v1/statements/${encodeURIComponent(id)}?expected_revision=${revision}`, {
    method: "DELETE",
  });
}

/**
 * Set the review status of the rows named, all or none - the editors alone (403 `not_editor`). 409
 * `stale_revision` (details.stale: each row changed or gone, its revision now or null), `job_open`, `frozen`,
 * `not_extracted`.
 */
export function setReview(documentId: string, status: ReviewStatus, items: ReviewItem[]): Promise<Reviewed> {
  return apiFetch<Reviewed>(`${documentPath(documentId)}/review`, {
    method: "POST",
    body: JSON.stringify({ status, items }),
  });
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

function documentPath(id: string): string {
  return `/api/v1/documents/${encodeURIComponent(id)}`;
}
