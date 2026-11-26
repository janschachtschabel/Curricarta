// A document's assessments in words (plan M3a J; DocumentAssessments.vue): an assessment by its name, or said to have
// none; what it states - its kind by the label of its list, the parent it is a part of by that one's name, its
// duration, weight and grading as the page writes numbers, what it assesses, the levels at it by the values' form
// (scopeWords.ts) - each fact with the word for it; and the parts of each assessment, in their order.
import type { Assessment, Assessments } from "@/api";
import { t } from "@/i18n/de";
import { conceptLabel, joined, levelWords, stated, type Labels } from "@/scopeWords";
import type { Holder } from "@/valueHolder";

const NUMBER = new Intl.NumberFormat("de-DE", { maximumFractionDigits: 15 });

/** What an item of the section (AssessmentItem.vue) asks of the section (DocumentAssessments.vue). */
export interface ItemActions {
  open: (mode: "edit" | "part", id: string) => void;
  drop: (assessment: Assessment) => void;
  saved: (assessment: Assessment, added: boolean) => void;
  changed: () => void;
  cancel: () => void;
  dirty: (form: string, open: boolean) => void;
  valuesSaved: (holder: Holder) => void;
  gone: () => void;
}

/** What an assessment states, one fact a line. */
export interface Fact {
  key: string;
  term: string;
  words: string;
}

/** The assessment's name; one without said to have none. */
export function assessmentTitle(assessment: Assessment): string {
  return assessment.label ?? t("documents.page.assessments.unnamed");
}

/** The name of each row an assessment may be a part of or assess - its specifications, nodes, assessments - by id. */
export function namesOf(read: Assessments): ReadonlyMap<string, string> {
  const names = new Map<string, string>();
  for (const choice of read.choices) names.set(choice.id, choice.label ?? t("documents.page.assessments.none"));
  for (const assessment of read.assessments) names.set(assessment.id, assessmentTitle(assessment));
  return names;
}

/** The labels of the kinds of assessment the list offers, by IRI. */
export function kindLabels(read: Assessments): Labels {
  return new Map(read.kinds.map((kind) => [kind.iri, kind.label]));
}

/** Each assessment's parts by its id, in their order; the tops under the empty key. */
export function partsOf(assessments: readonly Assessment[]): ReadonlyMap<string, Assessment[]> {
  const parts = new Map<string, Assessment[]>();
  for (const assessment of assessments) {
    const parent = assessment.parent_kind === "assessment" ? assessment.parent_id : "";
    parts.set(parent, [...(parts.get(parent) ?? []), assessment]);
  }
  for (const each of parts.values()) each.sort((one, other) => one.position - other.position);
  return parts;
}

/** The ids of the assessment and of every part under it: none of them may become its parent. */
export function subtreeOf(id: string, parts: ReadonlyMap<string, Assessment[]>): Set<string> {
  const found = new Set([id]);
  const pending = [id];
  while (pending.length) for (const part of parts.get(pending.pop() ?? "") ?? []) if (!found.has(part.id)) {
    found.add(part.id);
    pending.push(part.id);
  }
  return found;
}

/** What the assessment states, in words: its kind, parent, duration, weight, grading, targets and levels. */
export function factsOf(
  assessment: Assessment,
  names: ReadonlyMap<string, string>,
  kinds: Labels,
  levels: Labels,
): Fact[] {
  const none = t("documents.page.assessments.none");
  const separator = t("documents.page.assessments.separator");
  const { duration_minutes: minutes, weight_percent: weight, graded } = assessment;
  const targets = assessment.targets.map((target) => target.label ?? none);
  const held = assessment.values.level_assignments.map((level) => stated(levelWords(level, levels), level.review_status));
  return [
    { key: "kind", term: t("documents.page.assessments.kind"), words: conceptLabel(assessment.assessment_kind, kinds) },
    { key: "parent", term: t("documents.page.assessments.parent"), words: names.get(assessment.parent_id) ?? none },
    {
      key: "duration",
      term: t("documents.page.assessments.duration"),
      words: minutes === null ? none : t("documents.page.assessments.minutes", { minutes }),
    },
    {
      key: "weight",
      term: t("documents.page.assessments.weight"),
      words: weight === null ? none : t("documents.page.assessments.percent", { weight: NUMBER.format(weight) }),
    },
    {
      key: "graded",
      term: t("documents.page.assessments.graded"),
      words: graded === null ? none : graded ? t("documents.page.assessments.yes") : t("documents.page.assessments.no"),
    },
    {
      key: "targets",
      term: t("documents.page.assessments.targets"),
      words: joined(targets, separator) || t("documents.page.assessments.noTargets"),
    },
    {
      key: "levels",
      term: t("documents.page.assessments.levels"),
      words: joined(held, separator) || t("documents.page.assessments.noLevels"),
    },
  ];
}
