// The exports of a frozen document: a MEM import's as MEM-Schule's RDF (backend app/api/exports.py, plan
// M2-6/M2-8b), any one's as Curriculum-Kern RDF (app/api/kern_export.py, plan M3a C2).
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
  const { blob, filename } = await fetchExport(documentId, "export.ttl", "mem");
  return { blob, filename };
}

/** The frozen document's Curriculum-Kern Turtle (backend app/api/kern_export.py, plan M3a C2), its name and
 * the violations the editors accepted when they froze it; ApiError where it is refused (409 export_unnamed …). */
export async function exportKern(documentId: string): Promise<{ blob: Blob; filename: string; accepted: number }> {
  const { blob, filename, response } = await fetchExport(documentId, "kern.ttl", "kern");
  const accepted = Number.parseInt(response.headers.get("Curricarta-Accepted-Violations") ?? "", 10);
  return { blob, filename, accepted: Number.isNaN(accepted) || accepted < 0 ? 0 : accepted };
}

async function fetchExport(
  documentId: string,
  file: string,
  kind: string,
): Promise<{ blob: Blob; filename: string; response: Response }> {
  const response = await send(`/api/v1/documents/${encodeURIComponent(documentId)}/${file}`);
  const named = SAFE_NAME.exec(response.headers.get("Content-Disposition") ?? "")?.[1];
  const filename = named && !named.startsWith(".") ? named : `${kind}-${documentId.replace(/[^A-Za-z0-9-]/g, "")}.ttl`;
  try {
    return { blob: await response.blob(), filename, response };
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
