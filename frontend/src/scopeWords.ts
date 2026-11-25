// A specification's values and applicability contexts in words (plan M3a H1; DocumentScope.vue): each concept by the
// label the values' form gives it - one no list holds, a retired one, by the last part of its IRI -, numbers as the
// page writes them, a context as the list of all it states.
import type { ApplicabilityContext, ScopeForm, ScopeLevel, ScopeTimeSpan, ScopeWorkload } from "@/api";
import { t } from "@/i18n/de";

/** A concept's label by its IRI. */
export type Labels = ReadonlyMap<string, string>;

const NUMBER = new Intl.NumberFormat("de-DE", { maximumFractionDigits: 15 });

/** The labels of every list of the values' form and of a context's form. */
export function labelsOf(form: ScopeForm | null): Labels {
  const labels = new Map<string, string>();
  const fields = form ? [...Object.values(form.values).flatMap((kind) => kind.fields), ...form.context.fields] : [];
  for (const field of fields) for (const value of field.values ?? []) labels.set(value.iri, value.label);
  return labels;
}

/** The concept's label; one no list holds by the last part of its IRI. */
export function conceptLabel(iri: string, labels: Labels): string {
  return labels.get(iri) ?? iri.slice(Math.max(iri.lastIndexOf("#"), iri.lastIndexOf("/")) + 1);
}

export function levelWords(level: ScopeLevel, labels: Labels): string {
  const from = conceptLabel(level.level, labels);
  return level.level_to ? t("documents.page.scope.range", { from, to: conceptLabel(level.level_to, labels) }) : from;
}

export function spanWords(span: ScopeTimeSpan, labels: Labels): string {
  const kind = conceptLabel(span.time_kind, labels);
  const [from, to] = [span.span_from, span.span_to].map((end) => (end === null ? null : NUMBER.format(end)));
  if (from !== null && to !== null) return t("documents.page.scope.span", { kind, from, to });
  if (from !== null) return t("documents.page.scope.spanFrom", { kind, from });
  if (to !== null) return t("documents.page.scope.spanTo", { kind, to });
  return kind;
}

export function workloadWords(workload: ScopeWorkload, labels: Labels): string {
  const unit = conceptLabel(workload.unit, labels);
  let words =
    workload.amount_to === null
      ? t("documents.page.scope.amount", { amount: NUMBER.format(workload.amount), unit })
      : t("documents.page.scope.amountRange", {
          from: NUMBER.format(workload.amount),
          to: NUMBER.format(workload.amount_to),
          unit,
        });
  if (workload.total) words = t("documents.page.scope.whole", { value: words });
  if (workload.is_recommendation) words = t("documents.page.scope.recommended", { value: words });
  return words;
}

/** All a context states, each part in words: its sector, formality, institution, target group, levels, time spans. */
export function contextWords(context: ApplicabilityContext, labels: Labels): string[] {
  return [
    ...[context.sector, context.formality].filter((iri) => iri !== null).map((iri) => conceptLabel(iri, labels)),
    ...(context.institution_text ? [t("documents.page.scope.institution", { text: context.institution_text })] : []),
    ...(context.target_group_text ? [t("documents.page.scope.targetGroup", { text: context.target_group_text })] : []),
    ...context.level_assignments.map((level) => levelWords(level, labels)),
    ...context.time_spans.map((span) => spanWords(span, labels)),
  ];
}
