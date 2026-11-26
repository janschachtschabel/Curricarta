// A document's findings in words (DocumentFindings.vue): what a rule found, in German where the page
// knows the rule - X5's checks and the reading of the model's answers, named alike at every stage that
// reads one (tests/findingWords.test.ts) -, a message the server says is German (SHACL's, where the
// shape gives one) as it is, any other as the server's English, to be quoted; and the row it is about, with the
// tree's row where it has one (plan M1 9.10, Paket 9d2 P3) - a value's its holder's (plan M3a F2).
import type { DocumentFinding, FindingSeverity } from "@/api";
import { isolate } from "@/bidi";
import type { RowKey } from "@/documentTree";
import { messages, t } from "@/i18n/de";
import { word } from "@/registerWords";

/** A finding's pill by what its severity means (style.css, .status-badge). */
export const SEVERITY_TONES: Readonly<Record<FindingSeverity, string>> = {
  violation: "error",
  warning: "warning",
  info: "neutral",
};

/** In the gravest-first order the server lists them. */
export const SEVERITIES: readonly FindingSeverity[] = ["violation", "warning", "info"];

const RULES: Readonly<Record<string, string>> = messages.documents.findings.rules;
const KINDS: Readonly<Record<string, string>> = messages.documents.findings.kinds;
/** The second layer's values: a finding keeps one as its focus and names the row that holds it. */
const VALUE_KINDS: ReadonlySet<string> = new Set(["level_assignment", "time_span", "workload"]);

/** What the finding says, and `lang` "en" where it is the server's English. */
export function findingText(finding: DocumentFinding): { text: string; lang?: "en" } {
  const [stage, name] = finding.rule.split(".", 2);
  if (/^x\d$/.test(stage) && name && Object.hasOwn(RULES, name)) {
    return { text: t(`documents.findings.rules.${name}`) };
  }
  if (finding.message_lang === "de") return { text: finding.message };
  return { text: finding.message, lang: "en" };
}

// A statement always has its wording: without one it is gone - a repair of its package dropped it before X6
// took the findings on it along (Paket 9d3), or the list was read while it went.
function goneStatement(finding: DocumentFinding): boolean {
  return finding.focus.kind === "statement" && finding.focus.label === null;
}

/** A row by its kind and its wording or title, set apart, where it has one. */
function rowText(kind: string, label: string | null): string {
  return label ? t("documents.findings.about", { kind, label: isolate(label) }) : kind;
}

/** The row a finding is about: its kind, its wording or title set apart, the work package it names; a
 * statement no longer there said so; a value by its kind and its holder - gone where it has none. */
export function focusText(finding: DocumentFinding): string {
  const { kind, label, holder_kind: holder } = finding.focus;
  let what: string;
  if (VALUE_KINDS.has(kind)) {
    what = holder === null
      ? t("documents.findings.valueGone")
      : t("documents.findings.valueAt", { value: word(KINDS, kind), holder: rowText(word(KINDS, holder), label) });
  } else {
    what = rowText(goneStatement(finding) ? t("documents.findings.statementGone") : word(KINDS, kind), label);
  }
  return finding.unit ? t("documents.findings.inUnit", { what, unit: finding.unit }) : what;
}

/** The tree's row a finding is about: a node's or a statement's - a value's holder's -; none for what has no
 * row (an anchor, the document, a specification's value, a value gone …). */
export function findingRow(finding: DocumentFinding): RowKey | null {
  const { kind, id, holder_kind: holderKind, holder_id: holderId, placed_node_id: placed } = finding.focus;
  if (goneStatement(finding)) return null; // no row to lead to
  if (placed) return `node:${placed}`; // a placement's, or a value's at one: its node's (plan M3a K)
  const [rowKind, rowId] = VALUE_KINDS.has(kind) ? [holderKind, holderId] : [kind, id];
  return (rowKind === "node" || rowKind === "statement") && rowId !== null ? `${rowKind}:${rowId}` : null;
}
