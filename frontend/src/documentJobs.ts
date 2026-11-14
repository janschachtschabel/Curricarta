// A document's latest job by its kind (backend app/api/documents.py, extraction.kind): an extraction, a
// repair (X6, then X5 again), a check (X5 again) or an import of a MEM plan, which share the document's
// one job at a time.
import { CHECK_KIND, IMPORT_KIND, REPAIR_KIND, type JobStatus } from "@/api";
import { t } from "@/i18n/de";

/** What the job is called where it is followed and cancelled. */
export function jobLabel(kind: string): string {
  if (kind === REPAIR_KIND) return t("documents.page.repairLabel");
  if (kind === IMPORT_KIND) return t("documents.page.importLabel");
  return kind === CHECK_KIND ? t("documents.page.checkLabel") : t("documents.page.jobLabel");
}

/** What a start of the extraction set going, said by its kind: a start meets the document's job of any kind. */
export function startedWords(kind: string): string {
  if (kind === REPAIR_KIND) return t("documents.page.repairRunning");
  if (kind === IMPORT_KIND) return t("documents.page.importStarted");
  return kind === CHECK_KIND ? t("documents.page.checkRunning") : t("documents.page.started");
}

/** How the latest job of the document stands, by its kind. */
export function lastStatus(latest: { kind: string; status: JobStatus }): string {
  const status = t(`jobs.status.${latest.status}`);
  if (latest.kind === REPAIR_KIND) return t("documents.page.lastRepairStatus", { status });
  if (latest.kind === IMPORT_KIND) return t("documents.page.lastImportStatus", { status });
  return latest.kind === CHECK_KIND
    ? t("documents.page.lastCheckStatus", { status })
    : t("documents.page.lastStatus", { status });
}
