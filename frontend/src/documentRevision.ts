// A document frozen and copied (plan M1 9.10, Paket 9d1 N6, N7; backend app/api/freeze.py): frozen, it is given
// back with its IRI; its violations are taken only when asked about first, by their count; what is missing for its
// IRI is named; a check owed is said so the tree can be checked; a document closed meanwhile (frozen, a job) is to
// be read again. Copied, the draft is given back; a draft open already is named where the server names it.
import { ApiError, copyDocument, freezeDocument, type CurriculumDocument } from "@/api";
import { t } from "@/i18n/de";
import { failureNotice, type Notice } from "@/notice";

export type FreezeOutcome =
  | { outcome: "frozen"; document: CurriculumDocument }
  | { outcome: "violations"; count: number }
  | { outcome: "incomplete"; missing: string[] }
  | { outcome: "owed" }
  /** The document closed meanwhile: read it again. */
  | { outcome: "closed"; code: string }
  | { outcome: "refused"; code: string }
  | { outcome: "failed"; problem: Notice };

export type CopyOutcome =
  | { outcome: "copied"; document: CurriculumDocument }
  /** A draft of it is open already, named where the server could. */
  | { outcome: "open"; documentId: string | null }
  /** Not frozen (any more): read it again. */
  | { outcome: "stale" }
  | { outcome: "refused"; code: string }
  | { outcome: "failed"; problem: Notice };

const CLOSING: ReadonlySet<string> = new Set(["frozen", "job_open"]);
const FREEZE_REFUSED: ReadonlySet<string> = new Set([
  "not_extracted",
  "no_iri_base",
  "iri_taken",
  "not_editor",
  // one naming no count of its violations: said by its code, there being nothing to ask about
  "has_violations",
]);
const COPY_REFUSED: ReadonlySet<string> = new Set(["not_latest", "vocabulary_changed", "not_editor"]);

// each by its own key: the catalogue's guard reads the keys the code asks for
const MISSING: Readonly<Record<string, () => string>> = {
  work: () => t("documents.page.freeze.missing.work"),
  region: () => t("documents.page.freeze.missing.region"),
  short_title: () => t("documents.page.freeze.missing.short_title"),
  issuer: () => t("documents.page.freeze.missing.issuer"),
  edition: () => t("documents.page.freeze.missing.edition"),
};

/** What the server says is missing for the document's IRI, item by item; an item it may add later left out. */
export function missingWords(missing: readonly string[]): string[] {
  return missing.flatMap((item) => (Object.hasOwn(MISSING, item) ? [MISSING[item]()] : []));
}

/**
 * What the document's IRI is made of, as the page can tell from the document it holds, each with whether it is
 * set - in the server's order and on its terms (backend app/db/freezing.py: the work's land and short title asked
 * for only once there is a work). A value the server finds names no part of an IRI (a Greek letter alone) reads as
 * set here; the server says so on freezing, as it says a check owed and violations, which the document does not show.
 */
export function freezeParts(document: CurriculumDocument): { part: IriPart; set: boolean }[] {
  const named = (text: string | null | undefined) => Boolean(text?.trim());
  const { work } = document;
  const parts: { part: IriPart; set: boolean }[] = [{ part: "work", set: work !== null }];
  if (work) parts.push({ part: "region", set: named(work.region) }, { part: "short_title", set: named(work.short_title) });
  parts.push({ part: "issuer", set: named(document.issuer) }, { part: "edition", set: named(document.edition) });
  return parts;
}

export type IriPart = "work" | "region" | "short_title" | "issuer" | "edition";

// each by its own key, as MISSING
const PART: Readonly<Record<IriPart, () => string>> = {
  work: () => t("documents.page.freeze.part.work"),
  region: () => t("documents.page.freeze.part.region"),
  short_title: () => t("documents.page.freeze.part.short_title"),
  issuer: () => t("documents.page.freeze.part.issuer"),
  edition: () => t("documents.page.freeze.part.edition"),
};

/** A part of the IRI with its state, as the freeze section lists it. */
export function partState({ part, set }: { part: IriPart; set: boolean }): string {
  const what = PART[part]();
  return set ? t("documents.page.freeze.check.set", { what }) : t("documents.page.freeze.check.missing", { what });
}

export async function freeze(documentId: string, acceptViolations: boolean): Promise<FreezeOutcome> {
  try {
    return { outcome: "frozen", document: await freezeDocument(documentId, acceptViolations) };
  } catch (error) {
    if (!(error instanceof ApiError) || !error.code) {
      return { outcome: "failed", problem: failureNotice(error, t("documents.page.freeze.failed")) };
    }
    const { code, details } = error;
    if (code === "has_violations" && typeof details.violations === "number") {
      return { outcome: "violations", count: details.violations };
    }
    if (code === "incomplete") {
      const missing = Array.isArray(details.missing) ? details.missing : [];
      return { outcome: "incomplete", missing: missing.filter((item): item is string => typeof item === "string") };
    }
    if (code === "check_owed") return { outcome: "owed" };
    if (CLOSING.has(code)) return { outcome: "closed", code };
    if (FREEZE_REFUSED.has(code)) return { outcome: "refused", code };
    return { outcome: "failed", problem: failureNotice(error, t("documents.page.freeze.failed")) };
  }
}

export async function copy(documentId: string): Promise<CopyOutcome> {
  try {
    return { outcome: "copied", document: await copyDocument(documentId) };
  } catch (error) {
    const code = error instanceof ApiError ? error.code : undefined;
    if (code === "draft_open") {
      const open = (error as ApiError).details.document_id;
      return { outcome: "open", documentId: typeof open === "string" ? open : null };
    }
    if (code === "not_frozen") return { outcome: "stale" };
    if (code && COPY_REFUSED.has(code)) return { outcome: "refused", code };
    return { outcome: "failed", problem: failureNotice(error, t("documents.page.revision.copyFailed")) };
  }
}

/** The revisions of `document`'s IRI among `documents` - an entry's, its draft copies among them -, the latest
 * first. */
export function revisionsOf(
  documents: readonly CurriculumDocument[],
  document: CurriculumDocument,
): CurriculumDocument[] {
  if (document.iri === null) return [];
  return documents.filter((one) => one.iri === document.iri).sort((one, other) => other.revision - one.revision);
}
