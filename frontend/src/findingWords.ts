// A document's findings in words (DocumentFindings.vue): what a rule found, in German where the page
// knows the rule - X5's checks and the reading of the model's answers, named alike at every stage that
// reads one (tests/findingWords.test.ts) -, a message the server says is German (SHACL's, where the
// shape gives one) as it is, any other as the server's English, to be quoted; and the row it is about, with the
// tree's row where it has one (plan M1 9.10, Paket 9d2 P3).
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

/** The row a finding is about: its kind, its wording or title set apart, the work package it names; a
 * statement no longer there said so. */
export function focusText(finding: DocumentFinding): string {
  const { kind, label } = finding.focus;
  const named = goneStatement(finding)
    ? t("documents.findings.statementGone")
    : word(messages.documents.findings.kinds, kind);
  const what = label ? t("documents.findings.about", { kind: named, label: isolate(label) }) : named;
  return finding.unit ? t("documents.findings.inUnit", { what, unit: finding.unit }) : what;
}

/** The tree's row a finding is about: a node's or a statement's; none for what has no row (an anchor, the
 * document …). */
export function findingRow(finding: DocumentFinding): RowKey | null {
  const { kind, id } = finding.focus;
  if (goneStatement(finding)) return null; // no row to lead to
  return kind === "node" || kind === "statement" ? `${kind}:${id}` : null;
}
