// A rule's draft in its form (plan M3a I; RuleForm.vue): every field as its control holds it - numbers as written the
// German way (valueNumbers.ts), the option texts one a line, the links by their targets' ids -, and the changes it
// makes to the rule as read, each checked as the server would: a count a whole number from 0, an amount a number,
// a share one from 0 to 1, a wording there. What a kind does not hold its form does not show: a selection alone
// has options, a prerequisite alone a kind of requirement and required items, a recognition alone a share - so a
// kind changed away from one empties these, as the server takes them of that kind alone.
import type { FormValue, Rule, RuleFields, RuleKind } from "@/api";
import { t } from "@/i18n/de";
import { numberOf, written } from "@/valueNumbers";

export const RULE_KINDS: readonly RuleKind[] = ["selection", "prerequisite", "completion", "recognition", "progression"];
const MOST_COUNT = 2 ** 31 - 1; // as the server takes a count (backend app/api/rule_answers.py)
const MOST_DIGITS = 15;
const MOST_OPTION = 2000; // signs of an option as written
export const MOST_VERBATIM = 20000; // signs of a rule's wording, as a statement's
const COUNT = /^\d{1,10}$/;

export interface RuleDraft {
  kind: string;
  verbatim: string;
  min_count: string;
  max_count: string;
  min_amount: string;
  max_amount: string;
  amount_unit: string;
  requirement_kind: string;
  max_share: string;
  /** One a line. */
  option_texts: string;
  applies_to: string[];
  options: string[];
  requires: string[];
}

export type RuleField = keyof RuleDraft;
export type RuleFault = readonly [field: RuleField, problem: string];

/** A choice of a rule's form as a form's value: what it sets and its words. */
export function choice(iri: string, label: string): FormValue {
  return {
    iri,
    label,
    notation: null,
    alt_labels: [],
    definition: null,
    note: null,
    delimitation: null,
    examples: [],
    broader: [],
    group: null,
    dimension: null,
  };
}

/** Whether a rule of the kind holds the field: options a selection's, a share a recognition's … */
export function holds(kind: string, field: RuleField): boolean {
  if (field === "options") return kind === "selection";
  if (field === "requirement_kind" || field === "requires") return kind === "prerequisite";
  if (field === "max_share") return kind === "recognition";
  return true;
}

export function draftOf(rule: Rule): RuleDraft {
  return {
    kind: rule.kind,
    verbatim: rule.verbatim,
    min_count: written(rule.min_count),
    max_count: written(rule.max_count),
    min_amount: written(rule.min_amount),
    max_amount: written(rule.max_amount),
    amount_unit: rule.amount_unit ?? "",
    requirement_kind: rule.requirement_kind ?? "",
    max_share: written(rule.max_share),
    option_texts: rule.option_texts.join("\n"),
    applies_to: rule.applies_to.map((link) => link.id),
    options: rule.options.map((link) => link.id),
    requires: rule.requires.map((link) => link.id),
  };
}

/** The draft read anew: a field the user left as it was takes the value now read, an entry made meanwhile stays. */
export function rebased(draft: RuleDraft, was: Rule, now: Rule): RuleDraft {
  const before = draftOf(was);
  const after = draftOf(now);
  const next = { ...draft };
  for (const key of Object.keys(draft) as RuleField[]) {
    if (same(draft[key], before[key])) (next as Record<RuleField, string | string[]>)[key] = after[key];
  }
  return next;
}

function same(one: string | string[], other: string | string[]): boolean {
  return Array.isArray(one) && Array.isArray(other) ? one.join("\n") === other.join("\n") : one === other;
}

/** What the draft changes of the rule as read, and the problems of its entries the server would refuse. */
export function changesOf(rule: Rule, draft: RuleDraft): { fields: RuleFields; faults: RuleFault[] } {
  const fields: RuleFields = {};
  const faults: RuleFault[] = [];
  const kind = draft.kind as RuleKind;
  if (kind !== rule.kind) fields.kind = kind;
  if (!draft.verbatim.trim()) faults.push(["verbatim", t("documents.tree.problems.required")]);
  else if (draft.verbatim !== rule.verbatim) fields.verbatim = draft.verbatim;
  for (const key of ["min_count", "max_count"] as const) {
    const text = draft[key].trim();
    const count = text === "" ? null : COUNT.test(text) && Number(text) <= MOST_COUNT ? Number(text) : undefined;
    if (count === undefined) faults.push([key, t("documents.page.rules.problems.not_count")]);
    else if (count !== rule[key]) fields[key] = count;
  }
  for (const key of ["min_amount", "max_amount", "max_share"] as const) {
    const held = holds(kind, key);
    const text = held ? draft[key].trim() : "";
    const number = text === "" ? null : numberOf(text);
    if (number === null && text !== "") faults.push([key, t("documents.tree.values.problems.not_number")]);
    else if (text.replace(/[.,]/g, "").replace(/^0+(?=\d)/, "").length > MOST_DIGITS) {
      faults.push([key, t("documents.tree.values.problems.too_many_digits")]);
    } else if (key === "max_share" && number !== null && number > 1) {
      faults.push([key, t("documents.page.rules.problems.not_share")]);
    } else if (number !== rule[key]) fields[key] = number;
  }
  for (const key of ["amount_unit", "requirement_kind"] as const) {
    const value = holds(kind, key) ? draft[key] || null : null;
    if (value !== rule[key]) fields[key] = value;
  }
  const texts = draft.option_texts.split("\n").map((text) => text.trim()).filter(Boolean);
  if (texts.some((text) => text.length > MOST_OPTION)) faults.push(["option_texts", t("documents.tree.problems.too_long")]);
  else if (!same(texts, rule.option_texts)) fields.option_texts = texts;
  for (const key of ["applies_to", "options", "requires"] as const) {
    const ids = holds(kind, key) ? draft[key] : [];
    if (!same(ids, rule[key].map((link) => link.id))) fields[key] = ids;
  }
  return { fields, faults };
}
