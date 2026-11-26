// What the lists of a value's form offer at a holder (plan M3a G): no level a rule of the form keeps from it (its
// `rules`, the core's shapes) - a node's, a statement's of its kind, a specification's of its class, or a level in
// one of a specification's applicability contexts -, a range's end of its start's system alone.
import type { Form, FormValue, RuleHolder, ValueKind } from "@/api";
import { fieldsOf, type Entry } from "@/valueDraft";

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
  holder: RuleHolder,
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
