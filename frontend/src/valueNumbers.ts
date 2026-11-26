// A value's number as its form writes it (plan M3a G): the German way, "7,5", "12.000" - the comma its only decimal
// sign, a dot only where it groups thousands, as the panel's own words write them -, and the problems of a field's
// entry the server would refuse: a required field empty, no number, too many digits, no whole number.
import type { FormField } from "@/api";
import { LOCALE, t } from "@/i18n/de";

const MOST_DIGITS = 15; // the store's (backend app/api/values.py, Number)
const MOST_WHOLE = 2 ** 31 - 1; // a whole number's, the store's integer
// a whole number, as the document says it: minutes per unit
const WHOLE: ReadonlySet<string> = new Set(["minutes_per_unit"]);
// digits, or thousands grouped by dots - the first group no zero, as "0.500" is no grouped number -, then the
// decimals after a comma
const NUMBER = /^(?:\d+|[1-9]\d{0,2}(?:\.\d{3})+)(?:,\d+)?$/;

const WRITTEN = new Intl.NumberFormat(LOCALE, { maximumFractionDigits: 20, useGrouping: false });

/** A number as an entry writes it: the German way, ungrouped. */
export function written(value: number | null): string {
  return value === null ? "" : WRITTEN.format(value);
}

/** A number as written, as a number; none where it is empty or no number. */
export function numberOf(text: string): number | null {
  const trimmed = text.trim();
  return NUMBER.test(trimmed) ? Number(trimmed.replaceAll(".", "").replace(",", ".")) : null;
}

/** The problem of a field's entry, in words; none where the server takes it. */
export function problemOf(field: FormField, value: string | boolean | undefined): string | null {
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
