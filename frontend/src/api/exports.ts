// The export of a frozen MEM import as MEM-Schule's RDF (backend app/api/exports.py, plan M2-6/M2-8b).
import { ApiError, send } from "./http";

/** A MEM shape a row of the export broke (backend app/exports/mem_gate.py, Violation). */
export interface ExportViolation {
  focus: string;
  row_kind: string | null;
  row_id: string | null;
  shape: string;
  path: string | null;
  /** pyshacl's sentence, in English. */
  message: string;
}

// a name a download may carry: the server's, as long as it is no path and needs no quoting
const SAFE_NAME = /filename="([A-Za-z0-9._-]+)"/;

/** The document's export as a file and its name; ApiError where it is refused (409 export_invalid …). */
export async function exportMem(documentId: string): Promise<{ blob: Blob; filename: string }> {
  const response = await send(`/api/v1/documents/${encodeURIComponent(documentId)}/export.ttl`);
  const named = SAFE_NAME.exec(response.headers.get("Content-Disposition") ?? "")?.[1];
  const filename = named && !named.startsWith(".") ? named : `mem-${documentId.replace(/[^A-Za-z0-9-]/g, "")}.ttl`;
  try {
    return { blob: await response.blob(), filename };
  } catch {
    throw new ApiError("network", 0); // the file broke off on its way
  }
}

/** The violations an export_invalid refusal lists, and how many there are in all; none where it lists
 * none of the form it should. */
export function exportViolations(error: ApiError): { total: number; violations: ExportViolation[] } {
  const listed = Array.isArray(error.details.violations) ? error.details.violations : [];
  const violations = listed.filter(isViolation);
  const total = typeof error.details.total === "number" ? error.details.total : violations.length;
  return { total, violations };
}

function isViolation(value: unknown): value is ExportViolation {
  if (typeof value !== "object" || value === null) return false;
  const found = value as Record<string, unknown>;
  const text = (key: string) => typeof found[key] === "string";
  const textOrNull = (key: string) => found[key] === null || text(key);
  return text("focus") && text("shape") && text("message") && textOrNull("row_kind") && textOrNull("row_id")
    && textOrNull("path");
}
