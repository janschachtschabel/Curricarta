// The refusals the server names by a code (`code` in its error body,
// app/api/errors.py) that the page says in its own German words instead of
// quoting the server's English. A code not listed here gets the caller's
// sentence and the English reason; tests/refusals.test.ts checks that every code
// listed is one the backend sends.
import { t, type MessageParams } from "@/i18n/de";

export const REFUSAL_CODES = [
  "forbidden",
  "service_unavailable",
  "validation_failed",
  // an upload or an import (backend app/api/sources.py), and a body cut at its limit
  "file_too_large",
  "content_too_large",
  "archive_too_large",
  "unsupported_type",
  "file_missing",
  "title_invalid",
  "title_too_long",
  "url_invalid",
  "too_many_uploads",
  "too_many_imports",
  "uploads_busy",
  "upload_too_slow",
  // an entry's content and its conversion (backend app/api/source_content.py, conversions.py)
  "file_hidden",
  "no_file",
  "not_pdf",
  "too_many_conversions",
  "no_pages",
  "no_conversion",
  "not_converted",
  "no_such_page",
  // a document and its extraction (backend app/api/documents.py), a model job's admission (limits.py)
  "no_document",
  "not_owner",
  "unknown_sector",
  "unknown_region",
  "no_budget",
  "too_many_jobs",
  "too_many_starts",
  // a document's repair (backend app/api/documents.py)
  "not_checked",
  "nothing_to_repair",
  // an editor's change to a document's nodes and statements (backend app/api/node_editing.py,
  // statement_editing.py, edit_answers.py)
  "no_node",
  "no_statement",
  // a specification's title, field, values and contexts (backend app/api/specifications.py)
  "no_specification",
  // a rule's change (backend app/api/rules.py)
  "no_rule",
  "stale_revision",
  "invalid_field",
  "anchor_missing",
  "job_open",
  "frozen",
  "no_form",
  "not_extracted",
  // the editors' review (backend app/api/review.py)
  "not_editor",
  // a document's work and metadata, frozen and copied (backend app/api/document_meta.py, freeze.py,
  // documents.py)
  "named",
  "no_work",
  "incomplete",
  "no_iri_base",
  "check_owed",
  "has_violations",
  "iri_taken",
  "not_frozen",
  "not_latest",
  "draft_open",
  "vocabulary_changed",
  "not_extractable",
  // an import from MEM-Schule (backend app/api/mem.py)
  "mem_no_conversion",
  "mem_unknown_plan",
  "mem_plan_taken",
  "catalog_running",
  // the exports of a frozen document (backend app/api/exports.py, kern_export.py)
  "export_not_frozen",
  "not_mem_import",
  "export_invalid",
  "export_unavailable",
  "too_many_exports",
  "export_unnamed",
  // the editors' review of the lexicon (backend app/api/lexicon_review.py, lexicon_terms.py)
  "no_cue",
  "no_term",
  "not_a_node_type",
  "too_short",
] as const;

export type RefusalCode = (typeof REFUSAL_CODES)[number];

function isRefusalCode(code: unknown): code is RefusalCode {
  return (REFUSAL_CODES as readonly unknown[]).includes(code);
}

/** The page's words for a refusal the server named by its code; null for any other code. */
export function refusalText(code: unknown, params: MessageParams = {}): string | null {
  return isRefusalCode(code) ? t(`refusals.${code}`, params) : null;
}
