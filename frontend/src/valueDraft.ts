// A holder's levels, time spans and workloads as their form edits them (plan M3a G; backend app/api/values.py): each
// value an entry of its kind - kept by its `id`, a new one without -, its fields by the keys of its kind's form, a
// list's value as an IRI or "", a number as written (the German way: "7,5", "12.000" - the comma its only decimal
// sign, a dot only where it groups thousands, as the panel's own words write them), a yes or no as such. A set is sent
// whole: what it leaves out goes. A workload's periods are kept as they are stored; this form does not edit them.
// Compared as the server stores them, a number by its value, so that nothing changed is nothing to save; each kind
// is one field where a set meets another stored meanwhile (rowConflict.rebase): a kind only the other changed is
// taken in, a kind both changed put before the user. A specification's applicability contexts (plan M3a H) are
// one more kind of it: each an entry of its fields, its levels and time spans entries of their own within it, sent
// with the specification's values and compared, checked and named so - a problem under the context's path,
// `contexts[0].time_spans[1].time_kind`. What the lists offer: valueOffers.ts.
import type {
  ApplicabilityContext,
  ContextIn,
  Form,
  FormField,
  HeldTimeSpan,
  HeldValues,
  HolderKind,
  TimeSpanIn,
  ValueKind,
  ValuesIn,
} from "@/api";
import { LOCALE, t } from "@/i18n/de";
import { rebase } from "@/rowConflict";

export const VALUE_KINDS: readonly ValueKind[] = ["level_assignments", "time_spans", "workloads"];
/** A kind of a draft: a kind of value, or a specification's applicability contexts. */
export type DraftKind = ValueKind | "contexts";
export const DRAFT_KINDS: readonly DraftKind[] = [...VALUE_KINDS, "contexts"];
/** The most values of a kind at a holder, and periods of a workload, the server takes (backend MOST_VALUES). */
export const MOST_VALUES = 20;

export interface Entry {
  /** The entry's own in the form, through every change: its fields' ids and the keyboard's way to them. */
  key: string;
  /** The value the holder keeps; none for a new one. */
  id: string | null;
  fields: Record<string, string | boolean>;
  /** A workload's, as stored. */
  periods: TimeSpanIn[];
  /** A context's levels and time spans, as entries of their own. */
  inner?: ValuesDraft;
}

export type ValuesDraft = Record<DraftKind, Entry[]>;

/** A holder's values as stored - a specification's applicability contexts with them. */
export type HeldSet = HeldValues & { contexts?: readonly ApplicabilityContext[] };

/**
 * A field and the words of its problem: by its path in a set (`workloads[1].unit`), or by its entry's key and its
 * field (`value-7:unit`), where it stands however the entries move.
 */
export type ValueFault = readonly [field: string, problem: string];

const PATH = /^(level_assignments|time_spans|workloads|contexts)\[(\d+)\]\.(\w+)$/;
// a context's path: the context alone, one of its fields or kinds, or a path within that kind
const CONTEXT_PATH = /^contexts\[(\d+)\](?:\.(\w+)(.*))?$/;

const MOST_DIGITS = 15; // the store's (backend app/api/values.py, Number)
const MOST_WHOLE = 2 ** 31 - 1; // a whole number's, the store's integer
// a whole number, as the document says it: minutes per unit
const WHOLE: ReadonlySet<string> = new Set(["minutes_per_unit"]);
// digits, or thousands grouped by dots - the first group no zero, as "0.500" is no grouped number -, then the
// decimals after a comma
const NUMBER = /^(?:\d+|[1-9]\d{0,2}(?:\.\d{3})+)(?:,\d+)?$/;

let made = 0;
function nextKey(): string {
  made += 1;
  return `value-${made}`;
}

export function fieldsOf(form: Form, kind: DraftKind): FormField[] {
  return kind === "contexts" ? form.context.fields : form.values[kind].fields;
}

function emptyDraft(): ValuesDraft {
  return Object.fromEntries(DRAFT_KINDS.map((kind) => [kind, []])) as unknown as ValuesDraft;
}

/** The kinds the form offers a holder of the kind `holder`, in their order. */
export function kindsOf(form: Form, holder: HolderKind): ValueKind[] {
  return VALUE_KINDS.filter((kind) => form.values[kind].holders.includes(holder));
}

const WRITTEN = new Intl.NumberFormat(LOCALE, { maximumFractionDigits: 20, useGrouping: false });

/** A number as an entry writes it: the German way, ungrouped. */
function written(value: number | null): string {
  return value === null ? "" : WRITTEN.format(value);
}

type Stored = Record<string, unknown> & { id: string };

function entryOf(form: Form, kind: DraftKind, stored: Stored, previous: Entry | undefined): Entry {
  const fields = Object.fromEntries(
    fieldsOf(form, kind).map((field) => {
      const value = stored[field.key];
      if (field.kind === "boolean") return [field.key, value === true];
      if (field.kind === "number") return [field.key, typeof value === "number" ? written(value) : ""];
      return [field.key, typeof value === "string" ? value : ""];
    }),
  );
  const periods = Array.isArray(stored.periods) ? (stored.periods as HeldTimeSpan[]).map(periodOf) : [];
  const entry: Entry = { key: previous?.key ?? nextKey(), id: stored.id, fields, periods };
  if (kind === "contexts") entry.inner = draftOfValues(form, stored as unknown as HeldSet, previous?.inner);
  return entry;
}

function periodOf(span: HeldTimeSpan): TimeSpanIn {
  const { id, time_kind, span_from, span_to, time_relation } = span;
  return { id, time_kind, span_from, span_to, time_relation };
}

/**
 * The holder's values as a draft, each kind the form knows - an entry of `previous` keeping its key where it holds
 * the same value, so that its controls stay as the row is read again.
 */
export function draftOfValues(form: Form, values: HeldSet, previous?: ValuesDraft): ValuesDraft {
  const draft = emptyDraft();
  for (const kind of DRAFT_KINDS) {
    const kept = new Map((previous?.[kind] ?? []).filter((entry) => entry.id !== null).map((entry) => [entry.id, entry]));
    const held = ((values as Partial<Record<DraftKind, unknown>>)[kind] ?? []) as Stored[];
    draft[kind] = held.map((one) => entryOf(form, kind, one, kept.get(one.id)));
  }
  return draft;
}

/** The draft with an empty entry of the kind `kind` after the others, and that entry. */
export function withEntry(form: Form, draft: ValuesDraft, kind: DraftKind): { draft: ValuesDraft; entry: Entry } {
  const fields = Object.fromEntries(fieldsOf(form, kind).map((field) => [field.key, field.kind === "boolean" ? false : ""]));
  const entry: Entry = { key: nextKey(), id: null, fields, periods: [] };
  if (kind === "contexts") entry.inner = emptyDraft();
  return { draft: { ...draft, [kind]: [...draft[kind], entry] }, entry };
}

/** Whether the draft holds as many entries of the kind `kind` as a holder takes. */
export function isFull(draft: ValuesDraft, kind: DraftKind): boolean {
  return draft[kind].length >= MOST_VALUES;
}

/**
 * The field the path `path` names in the set `set`, by its entry's key (`value-7:unit`); none where the set holds
 * no such entry or its kind's form no such field. Within a context its values' fields so too; what the store
 * refuses in a context - named by the context (`contexts[0]`) or one of its kinds (`contexts[0].time_spans`) - by
 * the context's key and `context` or that kind.
 */
export function entryField(form: Form, set: ValuesDraft, path: string): string | null {
  const within = CONTEXT_PATH.exec(path);
  if (within) {
    const [, place, key, rest] = within;
    const context = set.contexts[Number(place)];
    if (!context) return null;
    if (key === undefined) return `${context.key}:context`;
    if (rest) return context.inner ? entryField(form, context.inner, key + rest) : null;
    if (form.context.values.includes(key as ValueKind)) return `${context.key}:${key}`;
  }
  const at = PATH.exec(path);
  if (!at) return null;
  const kind = at[1] as DraftKind;
  const entry = set[kind][Number(at[2])];
  const shown = fieldsOf(form, kind).some((field) => field.key === at[3]);
  return entry && shown ? `${entry.key}:${at[3]}` : null;
}

/** Whether the draft holds the entry `key`, within a context too. */
export function holdsEntry(draft: ValuesDraft, key: string): boolean {
  return DRAFT_KINDS.some((kind) => draft[kind].some((entry) => entry.key === key || (!!entry.inner && holdsEntry(entry.inner, key))));
}

/** The draft without the entry `key` of the kind `kind`. */
export function withoutEntry(draft: ValuesDraft, kind: DraftKind, key: string): ValuesDraft {
  return { ...draft, [kind]: draft[kind].filter((entry) => entry.key !== key) };
}

/** A number as written, as a number; none where it is empty or no number. */
function numberOf(text: string): number | null {
  const trimmed = text.trim();
  return NUMBER.test(trimmed) ? Number(trimmed.replaceAll(".", "").replace(",", ".")) : null;
}

// an entry as the server stores it: a number by its value, nothing as none
function stored(entry: Entry): unknown {
  const fields = Object.fromEntries(
    Object.entries(entry.fields).map(([key, value]) => {
      if (typeof value === "boolean") return [key, value];
      const trimmed = value.trim();
      return [key, trimmed === "" ? null : (numberOf(trimmed) ?? trimmed)];
    }),
  );
  return { id: entry.id, fields, periods: entry.periods, inner: entry.inner && asFields(entry.inner) };
}

/** Each kind as one comparable value: the field a conflict lays beside another. */
function asFields(draft: ValuesDraft): Record<DraftKind, string> {
  return Object.fromEntries(DRAFT_KINDS.map((kind) => [kind, JSON.stringify(draft[kind].map(stored))])) as Record<DraftKind, string>;
}

/** Whether the two drafts set the same values. */
export function sameValues(a: ValuesDraft, b: ValuesDraft): boolean {
  return changedKinds(a, b).length === 0;
}

/** The kinds whose values `draft` changes from `before`, in their order. */
export function changedKinds(before: ValuesDraft, draft: ValuesDraft): DraftKind[] {
  const [left, right] = [asFields(before), asFields(draft)];
  return DRAFT_KINDS.filter((kind) => left[kind] !== right[kind]);
}

/** The draft's problems the server would refuse, in the order of the set; none where it may be sent. */
export function checkDraft(form: Form, draft: ValuesDraft, within = ""): ValueFault[] {
  const faults: ValueFault[] = [];
  for (const kind of DRAFT_KINDS) {
    draft[kind].forEach((entry, at) => {
      for (const field of fieldsOf(form, kind)) {
        const problem = problemOf(field, entry.fields[field.key]);
        if (problem) faults.push([`${within}${kind}[${at}].${field.key}`, problem]);
      }
      if (entry.inner) faults.push(...checkDraft(form, entry.inner, `${within}${kind}[${at}].`));
    });
  }
  return faults;
}

function problemOf(field: FormField, value: string | boolean | undefined): string | null {
  if (typeof value === "boolean") return null;
  const text = (value ?? "").trim();
  if (text === "") return field.required ? t("documents.tree.problems.required") : null;
  if (field.kind !== "number") return null;
  const number = numberOf(text);
  if (WHOLE.has(field.key)) {
    return number !== null && Number.isInteger(number) && number >= 1 && number <= MOST_WHOLE && !text.includes(",")
      ? null
      : t("documents.tree.values.problems.not_whole");
  }
  if (number === null) return t("documents.tree.values.problems.not_number");
  // leading zeros are no digits of the value; trailing ones after the comma are
  const digits = text.replace(/[.,]/g, "").replace(/^0+(?=\d)/, "").length;
  return digits > MOST_DIGITS ? t("documents.tree.values.problems.too_many_digits") : null;
}

/** An entry of the kind `kind` as a set names it: a number none where it is empty or no number. */
export function valueOf(form: Form, kind: DraftKind, entry: Entry): Record<string, unknown> {
  const value: Record<string, unknown> = { id: entry.id };
  for (const field of fieldsOf(form, kind)) {
    const held = entry.fields[field.key];
    if (typeof held === "boolean") value[field.key] = held;
    else if (field.kind === "number") value[field.key] = numberOf(held ?? "");
    else value[field.key] = held?.trim() ? held : null;
  }
  if (kind === "workloads") value.periods = entry.periods;
  if (kind === "contexts") {
    const set = requestOf(form, entry.inner ?? emptyDraft());
    for (const held of form.context.values) value[held] = set[held];
  }
  return value;
}

/** The draft as a set sends it - checked first (`checkDraft`). */
export function requestOf(form: Form, draft: ValuesDraft): ValuesIn {
  const set = (kind: ValueKind) => draft[kind].map((entry) => valueOf(form, kind, entry));
  return {
    level_assignments: set("level_assignments") as unknown as ValuesIn["level_assignments"],
    time_spans: set("time_spans") as unknown as ValuesIn["time_spans"],
    workloads: set("workloads") as unknown as ValuesIn["workloads"],
  };
}

/** A specification's applicability contexts as its set sends them, with its values (`requestOf`). */
export function contextsOf(form: Form, draft: ValuesDraft): ContextIn[] {
  return draft.contexts.map((entry) => valueOf(form, "contexts", entry)) as unknown as ContextIn[];
}

// each kind a field of rowConflict's, compared by its value as one
const KIND_FIELDS: FormField[] = DRAFT_KINDS.map((key) => ({ key, kind: "text", required: false, many: false, most: null, values: null }));

export interface RebasedValues {
  /** The user's draft with the kinds only the other changed taken in; a clash keeps the user's until decided. */
  draft: ValuesDraft;
  /** The kinds both changed, in their order. */
  clashes: DraftKind[];
  /** The kinds only the other changed, in their order. */
  taken: DraftKind[];
}

/** Lay `draft` - begun from `before` - beside `stored`, the holder's values as the server holds them now. */
export function rebaseValues(before: ValuesDraft, draft: ValuesDraft, stored: ValuesDraft): RebasedValues {
  const laid = rebase(KIND_FIELDS, asFields(before), asFields(draft), asFields(stored));
  const taken = laid.taken as DraftKind[];
  const merged = { ...draft };
  for (const kind of taken) merged[kind] = stored[kind];
  return { draft: merged, clashes: laid.clashes.map((clash) => clash.key as DraftKind), taken };
}
