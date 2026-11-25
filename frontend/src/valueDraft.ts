// A holder's levels, time spans and workloads as their form edits them (plan M3a G; backend app/api/values.py): each
// value an entry of its kind - kept by its `id`, a new one without -, its fields by the keys of its kind's form, a
// list's value as an IRI or "", a number as written (the German way: "7,5", "12.000" - the comma its only decimal
// sign, a dot only where it groups thousands, as the panel's own words write them), a yes or no as such. A set is sent
// whole: what it leaves out goes. A workload's periods are kept as they are stored; this form does not edit them.
// Compared as the server stores them, a number by its value, so that nothing changed is nothing to save; each kind
// is one field where a set meets another stored meanwhile (rowConflict.rebase): a kind only the other changed is
// taken in, a kind both changed put before the user. The lists offer what the holder may hold: no level a rule
// of the form keeps from it (its `rules`, the core's shapes), a range's end of its start's system alone.
import type {
  Form,
  FormField,
  FormValue,
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
}

export type ValuesDraft = Record<ValueKind, Entry[]>;

/**
 * A field and the words of its problem: by its path in a set (`workloads[1].unit`), or by its entry's key and its
 * field (`value-7:unit`), where it stands however the entries move.
 */
export type ValueFault = readonly [field: string, problem: string];

const PATH = /^(level_assignments|time_spans|workloads)\[(\d+)\]\.(\w+)$/;

const MOST_DIGITS = 15; // the store's (backend app/api/values.py, Number)
const MOST_WHOLE = 2 ** 31 - 1; // a whole number's, the store's integer
// a whole number, as the document says it: minutes per unit
const WHOLE: ReadonlySet<string> = new Set(["minutes_per_unit"]);
// digits, or thousands grouped by dots, then the decimals after a comma
const NUMBER = /^(?:\d+|\d{1,3}(?:\.\d{3})+)(?:,\d+)?$/;

let made = 0;
function nextKey(): string {
  made += 1;
  return `value-${made}`;
}

function fieldsOf(form: Form, kind: ValueKind): FormField[] {
  return form.values[kind].fields;
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

function entryOf(form: Form, kind: ValueKind, stored: Record<string, unknown> & { id: string }, key: string): Entry {
  const fields = Object.fromEntries(
    fieldsOf(form, kind).map((field) => {
      const value = stored[field.key];
      if (field.kind === "boolean") return [field.key, value === true];
      if (field.kind === "number") return [field.key, typeof value === "number" ? written(value) : ""];
      return [field.key, typeof value === "string" ? value : ""];
    }),
  );
  const periods = Array.isArray(stored.periods) ? (stored.periods as HeldTimeSpan[]).map(periodOf) : [];
  return { key, id: stored.id, fields, periods };
}

function periodOf(span: HeldTimeSpan): TimeSpanIn {
  const { id, time_kind, span_from, span_to, time_relation } = span;
  return { id, time_kind, span_from, span_to, time_relation };
}

/**
 * The holder's values as a draft, each kind the form knows - an entry of `previous` keeping its key where it holds
 * the same value, so that its controls stay as the row is read again.
 */
export function draftOfValues(form: Form, values: HeldValues, previous?: ValuesDraft): ValuesDraft {
  const draft = {} as ValuesDraft;
  for (const kind of VALUE_KINDS) {
    const keys = new Map((previous?.[kind] ?? []).filter((entry) => entry.id !== null).map((entry) => [entry.id, entry.key]));
    draft[kind] = (values[kind] as unknown as (Record<string, unknown> & { id: string })[]).map((one) =>
      entryOf(form, kind, one, keys.get(one.id) ?? nextKey()),
    );
  }
  return draft;
}

/** The draft with an empty entry of the kind `kind` after the others, and that entry. */
export function withEntry(form: Form, draft: ValuesDraft, kind: ValueKind): { draft: ValuesDraft; entry: Entry } {
  const fields = Object.fromEntries(fieldsOf(form, kind).map((field) => [field.key, field.kind === "boolean" ? false : ""]));
  const entry: Entry = { key: nextKey(), id: null, fields, periods: [] };
  return { draft: { ...draft, [kind]: [...draft[kind], entry] }, entry };
}

/** Whether the draft holds as many entries of the kind `kind` as a holder takes. */
export function isFull(draft: ValuesDraft, kind: ValueKind): boolean {
  return draft[kind].length >= MOST_VALUES;
}

/**
 * The field the path `path` names in the set `set`, by its entry's key (`value-7:unit`); none where the set holds
 * no such entry or its kind's form no such field.
 */
export function entryField(form: Form, set: ValuesDraft, path: string): string | null {
  const at = PATH.exec(path);
  if (!at) return null;
  const kind = at[1] as ValueKind;
  const entry = set[kind][Number(at[2])];
  const shown = fieldsOf(form, kind).some((field) => field.key === at[3]);
  return entry && shown ? `${entry.key}:${at[3]}` : null;
}

/** The draft without the entry `key` of the kind `kind`. */
export function withoutEntry(draft: ValuesDraft, kind: ValueKind, key: string): ValuesDraft {
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
  return { id: entry.id, fields, periods: entry.periods };
}

/** Each kind as one comparable value: the field a conflict lays beside another. */
function asFields(draft: ValuesDraft): Record<ValueKind, string> {
  return Object.fromEntries(VALUE_KINDS.map((kind) => [kind, JSON.stringify(draft[kind].map(stored))])) as Record<ValueKind, string>;
}

/** Whether the two drafts set the same values. */
export function sameValues(a: ValuesDraft, b: ValuesDraft): boolean {
  return changedKinds(a, b).length === 0;
}

/** The kinds whose values `draft` changes from `before`, in their order. */
export function changedKinds(before: ValuesDraft, draft: ValuesDraft): ValueKind[] {
  const [left, right] = [asFields(before), asFields(draft)];
  return VALUE_KINDS.filter((kind) => left[kind] !== right[kind]);
}

/** The draft's problems the server would refuse, in the order of the set; none where it may be sent. */
export function checkDraft(form: Form, draft: ValuesDraft): ValueFault[] {
  const faults: ValueFault[] = [];
  for (const kind of VALUE_KINDS) {
    draft[kind].forEach((entry, at) => {
      for (const field of fieldsOf(form, kind)) {
        const problem = problemOf(field, entry.fields[field.key]);
        if (problem) faults.push([`${kind}[${at}].${field.key}`, problem]);
      }
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
export function valueOf(form: Form, kind: ValueKind, entry: Entry): Record<string, unknown> {
  const value: Record<string, unknown> = { id: entry.id };
  for (const field of fieldsOf(form, kind)) {
    const held = entry.fields[field.key];
    if (typeof held === "boolean") value[field.key] = held;
    else if (field.kind === "number") value[field.key] = numberOf(held ?? "");
    else value[field.key] = held?.trim() ? held : null;
  }
  if (kind === "workloads") value.periods = entry.periods;
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

/**
 * The values the field `key` of an entry of the kind `kind` offers at a holder of the kind `holder` - a statement
 * of the kind `holderType` -: a level or a dimension no rule keeps from it, a range's end of its start's system.
 * The value the entry holds stays among them, though it no longer fits: the server says why it refuses it.
 */
export function offeredFor(
  form: Form,
  kind: ValueKind,
  key: string,
  entry: Entry,
  holder: HolderKind,
  holderType: string | null,
): FormValue[] {
  const values = fieldsOf(form, kind).find((field) => field.key === key)?.values ?? [];
  if (kind !== "level_assignments") return values;
  const held = entry.fields[key];
  const barred = new Set(
    form.values.level_assignments.rules
      .filter((rule) => rule.holder === holder && (rule.unless === null || rule.unless !== holderType))
      .flatMap((rule) => rule.dimensions),
  );
  const start = values.length && key === "level_to" ? groupOf(form, entry.fields.level) : null;
  return values.filter((value) => {
    if (value.iri === held) return true;
    if (key === "level") return !barred.has(value.dimension ?? "");
    if (key === "dimension") return !barred.has(value.iri);
    if (key === "level_to") return start === null || value.group === start;
    return true;
  });
}

function groupOf(form: Form, level: string | boolean | undefined): string | null {
  if (typeof level !== "string" || !level) return null;
  const found = fieldsOf(form, "level_assignments")
    .find((field) => field.key === "level")
    ?.values?.find((value) => value.iri === level);
  return found?.group ?? null;
}

// each kind a field of rowConflict's, compared by its value as one
const KIND_FIELDS: FormField[] = VALUE_KINDS.map((key) => ({ key, kind: "text", required: false, many: false, most: null, values: null }));

export interface RebasedValues {
  /** The user's draft with the kinds only the other changed taken in; a clash keeps the user's until decided. */
  draft: ValuesDraft;
  /** The kinds both changed, in their order. */
  clashes: ValueKind[];
  /** The kinds only the other changed, in their order. */
  taken: ValueKind[];
}

/** Lay `draft` - begun from `before` - beside `stored`, the holder's values as the server holds them now. */
export function rebaseValues(before: ValuesDraft, draft: ValuesDraft, stored: ValuesDraft): RebasedValues {
  const laid = rebase(KIND_FIELDS, asFields(before), asFields(draft), asFields(stored));
  const taken = laid.taken as ValueKind[];
  const merged = { ...draft };
  for (const kind of taken) merged[kind] = stored[kind];
  return { draft: merged, clashes: laid.clashes.map((clash) => clash.key as ValueKind), taken };
}
