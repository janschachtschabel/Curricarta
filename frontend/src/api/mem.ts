// MEM-Schule's catalogue and the import of its plans (backend app/api/mem.py, plan M2-8).
import type { CurriculumDocument } from "./documents";
import { apiFetch } from "./http";
import type { Job } from "./jobs";

/** The job kind of an import of a MEM plan (backend app/sources/mem/import_kind.py). */
export const IMPORT_KIND = "extract.mem_import";

/** A plan of the catalogue, as the catalogue read it from MEM-Schule. */
export interface MemPlan {
  iri: string;
  graph: string;
  land_iri: string | null;
  title: string;
  class_iri: string;
  subjects: string[];
  school_types: string[];
  /** The licence of MEM-Schule's data the operators checked; null while none is. */
  licence: string | null;
  attribution: string | null;
  /** When the catalogue last read the plan. */
  read_at: string;
  /** Its Land's region ("DE-SN"), "DE" for the KMK's standards; null where none matches. */
  region: string | null;
}

export interface MemPlanPage {
  plans: MemPlan[];
  total: number;
  /** When the catalogue last read a plan; null: it was never read. */
  catalog_read_at: string | null;
}

/** The plan an imported document was made of (CurriculumDocument.mem). */
export interface MemOrigin {
  plan_iri: string;
  attribution: string | null;
  licence: string | null;
}

export interface MemSearch {
  region?: string;
  title?: string;
  limit?: number;
  offset?: number;
}

export interface MemImportStarted {
  document: CurriculumDocument;
  job: Job;
}

/** A page of the catalogue's plans of a region whose title holds `title`; empty filters are left out. */
export function findMemPlans(search: MemSearch): Promise<MemPlanPage> {
  const query = new URLSearchParams();
  if (search.region) query.set("region", search.region);
  if (search.title) query.set("title", search.title);
  if (search.limit !== undefined) query.set("limit", String(search.limit));
  if (search.offset) query.set("offset", String(search.offset));
  const asked = query.toString();
  return apiFetch<MemPlanPage>(`/api/v1/mem/plans${asked ? `?${asked}` : ""}`);
}

/** Starts the catalogue's reading (admins); 409 catalog_running names the reading to follow. */
export function startMemCatalog(): Promise<{ job_id: string }> {
  return apiFetch<{ job_id: string }>("/api/v1/mem/catalog", { method: "POST" });
}

/** Imports a plan into a new document of the entry's finished conversion, or starts its import again. */
export function startMemImport(
  sourceId: string,
  asked: { plan_iri: string; conversion_id: string },
): Promise<MemImportStarted> {
  return apiFetch<MemImportStarted>(`/api/v1/sources/${encodeURIComponent(sourceId)}/mem-import`, {
    method: "POST",
    body: JSON.stringify(asked),
  });
}
