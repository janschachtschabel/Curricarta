// A node's placements (plan M3a K; backend app/api/placements.py): where the node - a module, a learning field - is
// placed, in which of the document's specifications or variants, at which node, how binding and with what weight in
// the grade; read with the tree at each node, set as the node's whole on its revision, and the time spans and
// workloads of one set as a whole on its revision.
import { apiFetch } from "./http";
import type { NodeRow } from "./tree";
import type { HeldValues, ValuesIn } from "./values";

export interface Placement {
  id: string;
  /** The node it places. */
  node_id: string;
  /** Among the node's placements, from 1. */
  position: number;
  specification_id: string | null;
  variant_id: string | null;
  /** Where in the specification or variant. */
  in_node_id: string | null;
  /** A concept of cv:Obligations. */
  obligation: string;
  grade_weight: number | null;
  /** Given when the document is frozen. */
  iri: string | null;
  origin: string;
  review_status: string;
  /** The token of a set of its values. */
  revision: number;
  /** Its time spans and workloads; it holds no levels. */
  values: HeldValues;
}

/** A placement as a set names it: by its `id` one the node keeps, without a new one (backend PlacementIn). */
export interface PlacementIn {
  id: string | null;
  specification_id: string | null;
  variant_id: string | null;
  in_node_id: string | null;
  obligation: string;
  grade_weight: number | null;
}

/**
 * Set the node's placements as a whole, read at the node's revision `revision`; the node as it then stands. 409
 * `stale_revision` (details.current: the node as stored), `job_open`, `frozen`, `not_extracted`; 422 `invalid_field`
 * (details.field: the path in the set, `placements[1].variant_id`; details.problem); 404 `no_node`.
 */
export function setNodePlacements(id: string, revision: number, placements: PlacementIn[]): Promise<NodeRow> {
  return apiFetch<NodeRow>(`/api/v1/nodes/${encodeURIComponent(id)}/placements`, {
    method: "PUT",
    body: JSON.stringify({ expected_revision: revision, placements }),
  });
}

/** Set a placement's time spans and workloads as a node's values (setNodeValues); the placement as it then stands. */
export function setPlacementValues(id: string, revision: number, values: ValuesIn): Promise<Placement> {
  return apiFetch<Placement>(`/api/v1/placements/${encodeURIComponent(id)}/values`, {
    method: "PUT",
    body: JSON.stringify({ expected_revision: revision, ...values }),
  });
}
