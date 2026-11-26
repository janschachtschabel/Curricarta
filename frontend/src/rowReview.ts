// Setting a row's review status (plan M1 9.8, Paket 9c2c M2, M3): the editors' alone, for the row chosen at the
// revision the tree shows - or the one a status just set left, until the tree is read again -, a node's or a
// statement's. Set, the revision it left is given. A row changed meanwhile is not set but said, the tree to be read
// again, as a row the document no longer holds; a tree closed meanwhile (a job, frozen, X4 not done) is said too,
// as a caller who is no editor; another failure is said where it was asked. A row's value - a level, a time span, a
// workload (plan M3a G) - is set alike, by its table at its own revision; set, its holder's revision moved too, and a
// node's so moved is given (an open draft of its placements goes on from it). An assessment and a placement (plan M3a
// L) are rows so too.
import { ApiError, setReview, type ReviewItem, type ReviewedRevision, type ValueTable } from "@/api";
import type { Row } from "@/documentTree";
import { t } from "@/i18n/de";
import { failureNotice, type Notice } from "@/notice";
import { refusalText } from "@/refusals";
import { statusIri, statusOf, statusWord, type ReviewStatus } from "@/reviewStatus";
import type { AssessmentHolderRow, PlacementHolderRow } from "@/valueHolder";

/** A row whose own review status is set: a node, a statement, an assessment, a placement. */
export type ReviewedRow = Row | AssessmentHolderRow | PlacementHolderRow;

export type ReviewOutcome =
  /** `nodes`: each node whose revision the review moved as a holder, at its revision after. */
  | { outcome: "set"; status: ReviewStatus; revision: number; nodes: ReviewedRevision[] }
  | { outcome: "stale" }
  /** The document holds the row no more. */
  | { outcome: "gone" }
  /** The tree closed to change: read it again. */
  | { outcome: "closed"; code: string }
  | { outcome: "refused"; code: string }
  | { outcome: "failed"; problem: Notice };

const CLOSING: ReadonlySet<string> = new Set(["job_open", "frozen", "not_extracted"]);

/** A row's value to review: by its table, at its own revision. */
export interface ReviewedValue {
  table: ValueTable;
  id: string;
  revision: number;
  review_status: string;
}

// the row as stored, by its kind
function storedOf(row: ReviewedRow): { id: string; revision: number; review_status: string } {
  if (row.kind === "node") return row.node;
  if (row.kind === "assessment") return row.assessment;
  return row.kind === "placement" ? row.placement : row.statement;
}

/** The status the row stands at; none for one the vocabulary does not hold. */
export function rowStatus(row: ReviewedRow): ReviewStatus | null {
  return statusOf(storedOf(row).review_status);
}

function itemOf(row: ReviewedRow, revision?: number): ReviewItem {
  const stored = storedOf(row);
  return { kind: row.kind, id: stored.id, revision: revision ?? stored.revision };
}

// the row as stored none (backend app/api/review.py: `details.stale`, its `current` null)
function goneIn(details: Record<string, unknown>, id: string): boolean {
  const stale = details.stale;
  return (
    Array.isArray(stale) &&
    stale.some((one: unknown) => {
      const entry = one as { id?: unknown; current?: unknown } | null;
      return entry?.id === id && entry.current === null;
    })
  );
}

export async function reviewRow(
  documentId: string,
  row: ReviewedRow,
  status: ReviewStatus,
  revision?: number,
): Promise<ReviewOutcome> {
  return reviewItem(documentId, itemOf(row, revision), status);
}

/** Set the review status of the value `value`, at `revision` where a status just set left it. */
export function reviewValue(
  documentId: string,
  value: ReviewedValue,
  status: ReviewStatus,
  revision?: number,
): Promise<ReviewOutcome> {
  return reviewItem(documentId, { kind: value.table, id: value.id, revision: revision ?? value.revision }, status);
}

async function reviewItem(documentId: string, item: ReviewItem, status: ReviewStatus): Promise<ReviewOutcome> {
  try {
    const { revisions, nodes } = await setReview(documentId, status, [item]);
    return { outcome: "set", status, revision: revisions.find((one) => one.id === item.id)?.revision ?? item.revision, nodes };
  } catch (error) {
    if (error instanceof ApiError && error.code === "stale_revision") {
      return goneIn(error.details, item.id) ? { outcome: "gone" } : { outcome: "stale" };
    }
    const code = error instanceof ApiError ? error.code : undefined;
    if (code && CLOSING.has(code)) return { outcome: "closed", code };
    if (code === "not_editor") return { outcome: "refused", code };
    return { outcome: "failed", problem: failureNotice(error, t("documents.tree.review.failed")) };
  }
}

/**
 * How the review of a row named `name` went, in words naming it - `stale` where it changed or went meanwhile -; none
 * where the panel's words say it (closed, refused).
 */
export function namedReviewWords(done: Exclude<ReviewOutcome, { outcome: "failed" }>, name: string, stale: string): string | undefined {
  if (done.outcome === "set") return t("documents.tree.values.reviewSet", { value: name, status: statusWord(statusIri(done.status)) });
  return done.outcome === "stale" || done.outcome === "gone" ? stale : undefined;
}

/** What the panel says of it; a failure is said where it was asked. */
export function reviewWords(done: Exclude<ReviewOutcome, { outcome: "failed" }>): string {
  switch (done.outcome) {
    case "set":
      return t("documents.tree.review.set", { status: statusWord(statusIri(done.status)) });
    case "stale":
      return t("documents.tree.review.stale");
    case "gone":
      return t("documents.tree.gone");
    default:
      return refusalText(done.code) ?? t("documents.tree.review.failed");
  }
}
