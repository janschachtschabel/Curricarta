// A rule in words on the document's page (plan M3a I; DocumentRules.vue): its kind, its parsed values - counts,
// amount with its unit, kind of requirement, share -, the rows it names by what the editors know them by, its
// anchors' pages. A unit or a kind of requirement the lists no longer name stands as the last part of its IRI.
import type { Rule, RuleChoice, RuleLink } from "@/api";
import { pagesText } from "@/anchorWords";
import { messages, t } from "@/i18n/de";
import { written } from "@/valueNumbers";

const lastPart = (iri: string): string => iri.slice(Math.max(iri.lastIndexOf("#"), iri.lastIndexOf("/")) + 1);

const NAMED = 80; // signs of a rule's wording a button's name carries

/** What a button names a rule by: its kind and the start of its wording. */
export function ruleName(rule: Pick<Rule, "kind" | "verbatim">): string {
  const wording = rule.verbatim.length > NAMED ? `${rule.verbatim.slice(0, NAMED - 1)}…` : rule.verbatim;
  return t("documents.page.rules.named", { kind: kindWord(rule.kind), wording });
}

/** The rule's kind in words; a kind the page has no words for as the server names it. */
export function kindWord(kind: string): string {
  const words: Record<string, string> = messages.documents.page.rules.kinds;
  return Object.hasOwn(words, kind) ? words[kind] : kind;
}

function labelOf(iri: string | null, choices: readonly RuleChoice[]): string | null {
  if (iri === null) return null;
  return choices.find((choice) => choice.iri === iri)?.label ?? lastPart(iri);
}

function bounds(least: number | null, most: number | null): string | null {
  if (least !== null && most !== null) return t("documents.page.rules.between", { least: written(least), most: written(most) });
  if (least !== null) return t("documents.page.rules.atLeast", { value: written(least) });
  if (most !== null) return t("documents.page.rules.atMost", { value: written(most) });
  return null;
}

/** The rule's parsed values, each in words; none where it has none. */
export function valueWords(rule: Rule, units: readonly RuleChoice[], requirementKinds: readonly RuleChoice[]): string[] {
  const found: string[] = [];
  const counted = bounds(rule.min_count, rule.max_count);
  if (counted) found.push(t("documents.page.rules.count", { bounds: counted }));
  const amount = bounds(rule.min_amount, rule.max_amount);
  const unit = labelOf(rule.amount_unit, units);
  if (amount) found.push(t("documents.page.rules.amount", { bounds: amount, unit: unit ?? "" }).trim());
  const requirement = labelOf(rule.requirement_kind, requirementKinds);
  if (requirement) found.push(t("documents.page.rules.requirement", { kind: requirement }));
  if (rule.max_share !== null) found.push(t("documents.page.rules.share", { share: written(rule.max_share * 100) }));
  return found;
}

/** The rows a role names, each by what the editors know it by. */
export function linkWords(links: readonly RuleLink[]): string[] {
  return links.map((link) => link.label ?? t("documents.page.rules.unnamed", { kind: messages.documents.findings.kinds[link.kind] }));
}

/** Where the rule stands: the pages of its anchors. */
export function anchorWords(rule: Rule): string {
  return rule.anchors.map((anchor) => pagesText({ ...anchor, printed_page: null })).join(t("documents.page.rules.separator"));
}
