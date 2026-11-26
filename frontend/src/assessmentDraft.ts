// One assessment's entry in its form (plan M3a J; AssessmentForm.vue): its fields as written - a duration in whole
// minutes, a weight the German way (valueNumbers.ts), grading as yes, no or not said -, the fields as the server takes
// them with the problems it would refuse, what an edit changed against where it began, and what it may be a part of
// or assess: the specifications, the outline's nodes, the assessments but itself and its own parts.
import type { Assessment, AssessmentFields, Assessments } from "@/api";
import { assessmentTitle, kindLabels, partsOf, subtreeOf } from "@/assessmentWords";
import { t } from "@/i18n/de";
import { conceptLabel } from "@/scopeWords";
import { numberOf, written } from "@/valueNumbers";

export type Field = keyof AssessmentFields;
export const FIELDS: readonly Field[] = ["parent_id", "assessment_kind", "label", "duration_minutes", "weight_percent", "graded", "targets"];
const WHOLE = /^\d{1,10}$/;
const MOST_WHOLE = 2 ** 31 - 1; // the store's integer
const MOST_TARGETS = 200; // of one assessment, as the server takes them (backend app/domain/assessments.py)

export interface Draft {
  parent_id: string;
  assessment_kind: string;
  label: string;
  duration_minutes: string;
  weight_percent: string;
  graded: "" | "yes" | "no";
  targets: string[];
}

export interface Option {
  id: string;
  label: string;
}

/** The entry of the assessment `assessment` - a new one under `parentId` where none. */
export function draftOf(assessment: Assessment | undefined, parentId?: string): Draft {
  return {
    parent_id: assessment?.parent_id ?? parentId ?? "",
    assessment_kind: assessment?.assessment_kind ?? "",
    label: assessment?.label ?? "",
    duration_minutes: assessment?.duration_minutes == null ? "" : String(assessment.duration_minutes),
    weight_percent: written(assessment?.weight_percent ?? null),
    graded: assessment?.graded == null ? "" : assessment.graded ? "yes" : "no",
    targets: assessment?.targets.map((target) => target.id) ?? [],
  };
}

/** The entry as the server takes it; the problems of its fields where it would refuse them. */
export function fieldsOf(value: Draft): [AssessmentFields, [Field, string][]] {
  const problems: [Field, string][] = [];
  if (!value.parent_id) problems.push(["parent_id", t("documents.tree.problems.required")]);
  if (!value.assessment_kind) problems.push(["assessment_kind", t("documents.tree.problems.required")]);
  const minutes = value.duration_minutes.trim();
  if (minutes && (!WHOLE.test(minutes) || Number(minutes) > MOST_WHOLE)) {
    problems.push(["duration_minutes", t("documents.page.assessments.problems.not_whole")]);
  }
  const weight = value.weight_percent.trim() ? numberOf(value.weight_percent) : null;
  if (value.weight_percent.trim() && (weight === null || weight > 100)) {
    problems.push(["weight_percent", t("documents.page.assessments.problems.not_weight")]);
  }
  if (value.targets.length > MOST_TARGETS) {
    problems.push(["targets", t("documents.page.assessments.problems.too_many_targets", { most: MOST_TARGETS })]);
  }
  const fields: AssessmentFields = {
    parent_id: value.parent_id,
    assessment_kind: value.assessment_kind,
    label: value.label.trim() ? value.label : null,
    duration_minutes: minutes ? Number(minutes) : null,
    weight_percent: weight,
    graded: value.graded === "" ? null : value.graded === "yes",
    targets: value.targets,
  };
  return [fields, problems];
}

/** The fields `fields` changes against the entry `start` began as: a second try after a change meanwhile sends them again. */
export function changedFields(fields: AssessmentFields, start: Draft): Partial<AssessmentFields> {
  const [before] = fieldsOf(start);
  return Object.fromEntries(
    FIELDS.filter((key) => JSON.stringify(fields[key]) !== JSON.stringify(before[key])).map((key) => [key, fields[key]]),
  );
}

/** What the assessment `kept` - a new one where none - may be a part of, by group: never itself nor one of its parts. */
export function parentsOf(read: Assessments, kept: Assessment | undefined): { group: string; options: Option[] }[] {
  const barred = kept ? subtreeOf(kept.id, partsOf(read.assessments)) : new Set<string>();
  const none = t("documents.page.assessments.none");
  const chosen = (kind: "specification" | "node") =>
    read.choices.filter((one) => one.kind === kind).map((one) => ({ id: one.id, label: one.label ?? none }));
  const assessments = read.assessments.filter((one) => !barred.has(one.id)).map((one) => ({ id: one.id, label: assessmentTitle(one) }));
  return [
    { group: "specification", options: chosen("specification") },
    { group: "node", options: chosen("node") },
    { group: "assessment", options: assessments },
  ].filter((one) => one.options.length);
}

/** The kinds the list offers; a kind the assessment `kept` keeps though the list offers it no more, said so. */
export function kindsOf(read: Assessments, kept: Assessment | undefined): Option[] {
  const offered = read.kinds.map((kind) => ({ id: kind.iri, label: kind.label }));
  if (!kept || offered.some((kind) => kind.id === kept.assessment_kind)) return offered;
  const kind = conceptLabel(kept.assessment_kind, kindLabels(read));
  return [...offered, { id: kept.assessment_kind, label: t("documents.page.assessments.retiredKind", { kind }) }];
}

/** What the assessment may assess: the outline's nodes, and a statement it assesses already, kept. */
export function targetsOf(read: Assessments, kept: Assessment | undefined): Option[] {
  const none = t("documents.page.assessments.none");
  const nodes = read.choices.filter((one) => one.kind === "node").map((one) => ({ id: one.id, label: one.label ?? none }));
  const statements = (kept?.targets ?? []).filter((one) => one.kind === "statement").map((one) => ({ id: one.id, label: one.label ?? none }));
  return [...nodes, ...statements];
}
