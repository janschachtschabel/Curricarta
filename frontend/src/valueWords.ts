// A row's levels, time spans and workloads in words (plan M3a G): each list's value by the label the values' form
// gives it - one the form no longer offers by its IRI, as formWords.ts does -, then what else the value says, the
// parts it leaves out left out. A range reads by its two ends, a number the German way; a workload counts its unit
// in the catalogue's word for it, where it has one, else names it by its label. A workload's periods follow it.
import type { Form, HeldLevel, HeldTimeSpan, HeldValues, HeldWorkload, ValueKind } from "@/api";
import { valueLabel } from "@/formWords";
import { LOCALE, messages, t } from "@/i18n/de";

/** A level as a set or a holder names it. */
export type LevelValue = Pick<HeldLevel, "level" | "level_to" | "relation" | "dimension" | "competence_dimension">;
export type TimeSpanValue = Pick<HeldTimeSpan, "time_kind" | "span_from" | "span_to" | "time_relation">;
export type WorkloadValue = Omit<HeldWorkload, "id" | "origin" | "review_status" | "revision" | "periods"> & {
  periods: readonly TimeSpanValue[];
};

const UNITS: Readonly<Record<string, string>> = messages.documents.tree.values.units;
// four digits ungrouped, as a year reads and as the catalogue's numbers show (i18n/de.ts)
const GROUPED = new Intl.NumberFormat(LOCALE, { maximumFractionDigits: 20 });
const UNGROUPED = new Intl.NumberFormat(LOCALE, { maximumFractionDigits: 20, useGrouping: false });

/** A number of a value, the German way. */
export function numberText(value: number): string {
  return (Math.abs(value) >= 10000 ? GROUPED : UNGROUPED).format(value);
}

function label(form: Form, kind: ValueKind, key: string, iri: string | null): string | null {
  return iri === null ? null : valueLabel(form.values[kind].fields, key, iri);
}

function joined(parts: readonly (string | null | false)[]): string {
  return parts.filter((part): part is string => typeof part === "string" && part !== "").join(", ");
}

export function levelWords(value: LevelValue, form: Form): string {
  const from = label(form, "level_assignments", "level", value.level) ?? "";
  const to = label(form, "level_assignments", "level_to", value.level_to);
  return joined([
    to === null ? from : t("documents.tree.values.words.levelRange", { from, to }),
    label(form, "level_assignments", "relation", value.relation),
    label(form, "level_assignments", "dimension", value.dimension),
    label(form, "level_assignments", "competence_dimension", value.competence_dimension),
  ]);
}

/** Two ends of a span, one where they are alike. */
function range(from: number, to: number | null): string {
  if (to === null || to === from) return numberText(from);
  return t("documents.tree.values.words.numberRange", { from: numberText(from), to: numberText(to) });
}

export function timeSpanWords(value: TimeSpanValue, form: Form): string {
  const kind = label(form, "time_spans", "time_kind", value.time_kind) ?? "";
  const { span_from: from, span_to: to } = value;
  let span = kind;
  if (from !== null) {
    span = to === null ? t("documents.tree.values.words.spanFrom", { kind, from: numberText(from) }) : t("documents.tree.values.words.span", { kind, span: range(from, to) });
  } else if (to !== null) span = t("documents.tree.values.words.spanTo", { kind, to: numberText(to) });
  return joined([span, label(form, "time_spans", "time_relation", value.time_relation)]);
}

function amountWords(value: WorkloadValue, form: Form): string {
  const amount = range(value.amount, value.amount_to);
  const unit = form.values.workloads.fields.find((field) => field.key === "unit")?.values?.find((one) => one.iri === value.unit);
  const notation = unit?.notation ?? "";
  if (Object.hasOwn(UNITS, notation)) {
    const counted = t(`documents.tree.values.units.${notation}`, { count: value.amount_to ?? value.amount });
    return t("documents.tree.values.words.amount", { amount, unit: counted });
  }
  return t("documents.tree.values.words.amountLabelled", { amount, unit: unit?.label ?? value.unit });
}

export function workloadWords(value: WorkloadValue, form: Form): string {
  const periods = value.periods.map((period) => timeSpanWords(period, form)).join("; ");
  return joined([
    amountWords(value, form),
    label(form, "workloads", "workload_kind", value.workload_kind),
    value.is_recommendation && t("documents.tree.values.words.recommendation"),
    value.minutes_per_unit !== null && t("documents.tree.values.words.minutes", { minutes: value.minutes_per_unit }),
    value.total && t("documents.tree.values.words.total"),
    periods && t("documents.tree.values.words.periods", { spans: periods }),
  ]);
}

const LEVEL_AT = /^level_assignments\[(\d+)\]\./;

/**
 * Words for a change of the holder refused at one of its levels (`level_assignments[0].level`: a statement's kind
 * its level does not allow), naming that level and the problem's words; none for another place.
 */
export function levelInWay(values: HeldValues, form: Form, field: string, problem: string): string | null {
  const at = LEVEL_AT.exec(field);
  const level = at ? values.level_assignments[Number(at[1])] : undefined;
  return level ? t("documents.tree.values.heldInWay", { value: levelWords(level, form), problem }) : null;
}

/** A value of the kind `kind` in words. */
export function valueWords(kind: ValueKind, value: LevelValue | TimeSpanValue | WorkloadValue, form: Form): string {
  if (kind === "level_assignments") return levelWords(value as LevelValue, form);
  if (kind === "time_spans") return timeSpanWords(value as TimeSpanValue, form);
  return workloadWords(value as WorkloadValue, form);
}
