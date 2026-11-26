import { describe, expect, it } from "vitest";

import type { HeldValues } from "@/api";
import { t } from "@/i18n/de";
import { checkDraft, draftOfValues, entryField, newEntry, requestOf, sameValues, type Entry, type ValuesDraft } from "@/valueDraft";

import { CV, form_, noValues } from "./treeFixtures";

// A workload's periods (plan M3a G, carried to L): time spans of the workload alone, entries of their own within it,
// edited, checked and sent with it, and a problem the server finds at one (`workloads[0].periods[1].time_kind`) laid
// at that period's field.
const FORM = form_();
const STATED = { origin: CV + "orig_human", review_status: CV + "rev_proposed", revision: 1 };

function held(): HeldValues {
  return {
    ...noValues(),
    workloads: [
      {
        id: "w1",
        ...STATED,
        amount: 4,
        amount_to: null,
        unit: CV + "unit_lesson",
        workload_kind: null,
        is_recommendation: false,
        minutes_per_unit: null,
        total: false,
        periods: [{ id: "p1", ...STATED, time_kind: CV + "time_gradeLevel", span_from: 7, span_to: 8, time_relation: null }],
      },
    ],
  };
}

function periodsOf(draft: ValuesDraft, at = 0): Entry[] {
  return draft.workloads[at]?.inner?.time_spans ?? [];
}

function withPeriods(draft: ValuesDraft, periods: Entry[], at = 0): ValuesDraft {
  const workloads = draft.workloads.map((entry, place) =>
    place === at && entry.inner ? { ...entry, inner: { ...entry.inner, time_spans: periods } } : entry,
  );
  return { ...draft, workloads };
}

describe("a workload's periods in its draft", () => {
  it("are entries of their own within it, each with its id and its fields as written", () => {
    const [period] = periodsOf(draftOfValues(FORM, held()));

    expect(period).toMatchObject({ id: "p1", fields: { time_kind: CV + "time_gradeLevel", span_from: "7", span_to: "8", time_relation: "" } });
    expect(periodsOf({ ...draftOfValues(FORM, noValues()), workloads: [newEntry(FORM, "workloads")] })).toEqual([]);
  });

  it("are a change once one is added, changed or taken away, and sent with their workload", () => {
    const before = draftOfValues(FORM, held());
    const added = newEntry(FORM, "time_spans");
    const filled = { ...added, fields: { ...added.fields, time_kind: CV + "time_semester", span_from: "2" } };
    const [kept] = periodsOf(before);
    if (!kept) throw new Error("a period");

    const changed = withPeriods(before, [{ ...kept, fields: { ...kept.fields, span_to: "9" } }, filled]);

    expect(sameValues(before, changed)).toBe(false);
    expect(sameValues(before, withPeriods(before, []))).toBe(false);
    expect(requestOf(FORM, changed).workloads[0]?.periods).toEqual([
      { id: "p1", time_kind: CV + "time_gradeLevel", span_from: 7, span_to: 9, time_relation: null },
      { id: null, time_kind: CV + "time_semester", span_from: 2, span_to: null, time_relation: null },
    ]);
    expect(requestOf(FORM, withPeriods(before, [])).workloads[0]?.periods).toEqual([]);
  });

  it("have their problems found by their path in the set, laid at the period's field", () => {
    const before = draftOfValues(FORM, held());
    const empty = newEntry(FORM, "time_spans");
    const [kept] = periodsOf(before);
    if (!kept) throw new Error("a period");
    const draft = withPeriods(before, [{ ...kept, fields: { ...kept.fields, span_from: "sieben" } }, empty]);

    expect(checkDraft(FORM, draft)).toEqual([
      ["workloads[0].periods[0].span_from", t("documents.tree.values.problems.not_number")],
      ["workloads[0].periods[1].time_kind", "Dieses Feld braucht einen Wert."],
    ]);
    // the server's at the period as the set was sent, by its key
    expect(entryField(FORM, draft, "workloads[0].periods[1].time_kind")).toBe(`${empty.key}:time_kind`);
    expect(entryField(FORM, draft, "workloads[0].periods[2].time_kind")).toBeNull();
    expect(entryField(FORM, draft, "workloads[0].periods[0].id")).toBeNull();
  });
});
