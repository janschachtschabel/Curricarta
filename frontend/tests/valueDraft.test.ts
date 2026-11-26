import { readFileSync } from "node:fs";
import { join } from "node:path";

import { describe, expect, it } from "vitest";

import type { ApplicabilityContext, HeldValues } from "@/api";
import {
  checkDraft,
  contextsOf,
  draftOfValues,
  entryField,
  holdsEntry,
  isFull,
  kindsOf,
  MOST_VALUES,
  rebaseValues,
  requestOf,
  sameValues,
  withEntry,
  withoutEntry,
  type ValuesDraft,
} from "@/valueDraft";
import { t } from "@/i18n/de";
import { offeredFor } from "@/valueOffers";

import { CV, LVL, form_, noValues } from "./treeFixtures";

const FORM = form_();
const STATED = { origin: CV + "orig_human", review_status: CV + "rev_proposed", revision: 1 };

function held(): HeldValues {
  return {
    level_assignments: [
      { id: "l1", ...STATED, level: LVL + "B1", level_to: null, relation: CV + "lrel_minimum", dimension: null, competence_dimension: null },
    ],
    time_spans: [{ id: "t1", ...STATED, time_kind: CV + "time_gradeLevel", span_from: 7, span_to: 8, time_relation: null }],
    workloads: [
      {
        id: "w1",
        ...STATED,
        amount: 7.5,
        amount_to: null,
        unit: CV + "unit_hour",
        workload_kind: null,
        is_recommendation: true,
        minutes_per_unit: null,
        total: false,
        periods: [{ id: "p1", ...STATED, time_kind: CV + "time_gradeLevel", span_from: 7, span_to: null, time_relation: null }],
      },
    ],
  };
}

function edited(draft: ValuesDraft, kind: keyof ValuesDraft, at: number, key: string, value: string | boolean): ValuesDraft {
  const entries = draft[kind].map((entry, index) => (index === at ? { ...entry, fields: { ...entry.fields, [key]: value } } : entry));
  return { ...draft, [kind]: entries };
}

describe("a holder's values as a draft", () => {
  it("holds each value with its id, its lists' IRIs, its numbers as written the German way, and its yes or no", () => {
    const draft = draftOfValues(FORM, held());

    expect(draft.level_assignments[0]).toMatchObject({
      id: "l1",
      fields: { level: LVL + "B1", level_to: "", relation: CV + "lrel_minimum", dimension: "", competence_dimension: "" },
    });
    expect(draft.time_spans[0]?.fields).toMatchObject({ span_from: "7", span_to: "8", time_relation: "" });
    expect(draft.workloads[0]?.fields).toMatchObject({ amount: "7,5", amount_to: "", is_recommendation: true, total: false });
    // every entry its own key, which the form keys its fields by
    const keys = [...draft.level_assignments, ...draft.time_spans, ...draft.workloads].map((entry) => entry.key);
    expect(new Set(keys).size).toBe(3);
  });

  it("sees nothing to save where nothing changed, nor where a number is written another way", () => {
    const before = draftOfValues(FORM, held());

    expect(sameValues(before, draftOfValues(FORM, held()))).toBe(true);
    expect(sameValues(before, edited(before, "workloads", 0, "amount", "7,50"))).toBe(true);
    expect(sameValues(before, edited(before, "workloads", 0, "amount", "8"))).toBe(false);
  });

  it("takes the comma alone as the decimal sign, a dot only as it groups thousands", () => {
    const at = (amount: string, minutes = "") => {
      let draft = withEntry(FORM, draftOfValues(FORM, noValues()), "workloads").draft;
      draft = edited(edited(edited(draft, "workloads", 0, "amount", amount), "workloads", 0, "unit", CV + "unit_hour"), "workloads", 0, "minutes_per_unit", minutes);
      return { faults: checkDraft(FORM, draft), set: requestOf(FORM, draft).workloads[0] };
    };

    // as the panel's own words write them: never a thousandth of it
    expect(at("12.000").set?.amount).toBe(12000);
    expect(at("1.800,5").set?.amount).toBe(1800.5);
    expect(at("1.234.567").set?.amount).toBe(1234567);
    expect(at("12.000").faults).toEqual([]);
    expect(at("45", "1.000").set?.minutes_per_unit).toBe(1000);
    for (const written of ["7.50", "1.8", "12.00", "1.8000", ".5", "1,", "1.000.0", "0.500", "00.123"]) {
      expect(at(written).faults, written).toEqual([["workloads[0].amount", t("documents.tree.values.problems.not_number")]]);
      expect(at(written).set?.amount, written).toBeNull();
    }
  });

  it("adds an empty entry of a kind after the others, and takes one away by its key", () => {
    const before = draftOfValues(FORM, held());

    const added = withEntry(FORM, before, "time_spans");
    expect(added.draft.time_spans).toHaveLength(2);
    expect(added.entry).toMatchObject({ id: null, fields: { time_kind: "", span_from: "", span_to: "", time_relation: "" } });
    expect(sameValues(before, added.draft)).toBe(false);

    const removed = withoutEntry(added.draft, "time_spans", added.entry.key);
    expect(sameValues(before, removed)).toBe(true);
    expect(withoutEntry(before, "level_assignments", before.level_assignments[0]?.key ?? "").level_assignments).toEqual([]);
  });

  it("finds each problem before anything is asked, by its path in the set", () => {
    let draft = withEntry(FORM, draftOfValues(FORM, noValues()), "workloads").draft;
    draft = edited(draft, "workloads", 0, "amount_to", "zehn");
    draft = edited(draft, "workloads", 0, "minutes_per_unit", "45,5");
    draft = withEntry(FORM, draft, "level_assignments").draft;

    expect(checkDraft(FORM, draft)).toEqual([
      ["level_assignments[0].level", "Dieses Feld braucht einen Wert."],
      ["workloads[0].amount", "Dieses Feld braucht einen Wert."],
      ["workloads[0].amount_to", "Hier gehört eine Zahl ab 0 hin, etwa 7,5."],
      ["workloads[0].unit", "Dieses Feld braucht einen Wert."],
      ["workloads[0].minutes_per_unit", "Hier gehört eine ganze Zahl von 1 bis 2.147.483.647 hin."],
    ]);
    expect(checkDraft(FORM, edited(draft, "workloads", 0, "amount", "1234567890123456"))).toContainEqual([
      "workloads[0].amount",
      "Diese Zahl hat mehr als 15 Ziffern.",
    ]);
  });

  it("sends the whole set: the values kept by their ids, the new without, numbers as numbers, empty as none", () => {
    let draft = withEntry(FORM, draftOfValues(FORM, held()), "level_assignments").draft;
    draft = edited(draft, "level_assignments", 1, "level", LVL + "B2");

    expect(requestOf(FORM, draft)).toEqual({
      level_assignments: [
        { id: "l1", level: LVL + "B1", level_to: null, relation: CV + "lrel_minimum", dimension: null, competence_dimension: null },
        { id: null, level: LVL + "B2", level_to: null, relation: null, dimension: null, competence_dimension: null },
      ],
      time_spans: [{ id: "t1", time_kind: CV + "time_gradeLevel", span_from: 7, span_to: 8, time_relation: null }],
      workloads: [
        {
          id: "w1",
          amount: 7.5,
          amount_to: null,
          unit: CV + "unit_hour",
          workload_kind: null,
          is_recommendation: true,
          minutes_per_unit: null,
          total: false,
          // kept as they are: the form does not edit them
          periods: [{ id: "p1", time_kind: CV + "time_gradeLevel", span_from: 7, span_to: null, time_relation: null }],
        },
      ],
    });
  });
});

describe("a problem's field in a set", () => {
  it("is named by its entry's key and its field, none where the set holds no such entry or field", () => {
    const set = draftOfValues(FORM, held());
    const key = set.workloads[0]?.key ?? "";

    expect(entryField(FORM, set, "workloads[0].unit")).toBe(`${key}:unit`);
    expect(entryField(FORM, set, "workloads[1].unit")).toBeNull();
    expect(entryField(FORM, set, "workloads[0].periods[0].time_kind")).toBeNull();
    expect(entryField(FORM, set, "workloads[0].id")).toBeNull();
  });
});

describe("the kinds and values a holder is offered", () => {
  it("offers a node every kind, a statement its levels alone", () => {
    expect(kindsOf(FORM, "node")).toEqual(["level_assignments", "time_spans", "workloads"]);
    expect(kindsOf(FORM, "statement")).toEqual(["level_assignments"]);
  });

  it("leaves out the levels a holder never holds, and a range's end of another system than its start", () => {
    const draft = withEntry(FORM, draftOfValues(FORM, noValues()), "level_assignments").draft;
    const entry = draft.level_assignments[0];
    if (!entry) throw new Error("an entry");
    const iris = (key: string, holder: "node" | "statement", at = entry) =>
      offeredFor(FORM, "level_assignments", key, at, holder, null).map((value) => value.iri);

    expect(iris("level", "node")).toContain(LVL + "Q4");
    expect(iris("level", "statement")).toEqual([LVL + "B1", LVL + "B2"]);
    expect(iris("dimension", "statement")).toEqual([CV + "dim_proficiency"]);
    const chosen = { ...entry, fields: { ...entry.fields, level: LVL + "B1" } };
    expect(iris("level_to", "node", chosen)).toEqual([LVL + "B1", LVL + "B2"]);
    // the value held stays offered, though no longer fitting: the server says why it refuses it
    const holding = { ...entry, fields: { ...entry.fields, level: LVL + "Q4" } };
    expect(iris("level", "statement", holding)).toContain(LVL + "Q4");
  });

  it("offers a statement of the kind a rule excepts every level", () => {
    const form = form_();
    form.values.level_assignments.rules = [{ holder: "statement", dimensions: [CV + "dim_qualification"], unless: CV + "kind_standard" }];
    const entry = withEntry(form, draftOfValues(form, noValues()), "level_assignments").entry;

    const offered = offeredFor(form, "level_assignments", "level", entry, "statement", CV + "kind_standard");

    expect(offered.map((value) => value.iri)).toContain(LVL + "Q4");
  });
});

describe("a set laid beside the holder's values as another stored them meanwhile", () => {
  it("takes in a kind only the other changed and puts a kind both changed before the user", () => {
    const before = draftOfValues(FORM, held());
    const mine = edited(edited(before, "level_assignments", 0, "relation", ""), "time_spans", 0, "span_to", "9");
    const theirs = held();
    theirs.level_assignments[0] = { ...theirs.level_assignments[0], relation: CV + "lrel_target" };
    theirs.workloads = [];
    const stored = draftOfValues(FORM, theirs);

    const laid = rebaseValues(before, mine, stored);

    expect(laid.clashes).toEqual(["level_assignments"]);
    expect(laid.taken).toEqual(["workloads"]);
    expect(laid.draft.workloads).toEqual([]);
    // the user's until decided, and their change the other did not make
    expect(laid.draft.level_assignments[0]?.fields.relation).toBe("");
    expect(laid.draft.time_spans[0]?.fields.span_to).toBe("9");
  });
});

describe("the most values of a kind", () => {
  it("are as many as the server takes of a kind at a holder", () => {
    const api = readFileSync(join(process.cwd(), "..", "backend", "app", "api", "values.py"), "utf8");

    expect(Number(/^MOST_VALUES: Final = (\d+)/m.exec(api)?.[1])).toBe(MOST_VALUES);
  });
});


describe("a specification's applicability contexts in its draft", () => {
  function context(changes: Partial<ApplicabilityContext> = {}): ApplicabilityContext {
    return {
      id: "c1",
      ...STATED,
      sector: CV + "sec_school",
      formality: null,
      institution_text: "Gymnasium",
      target_group_text: null,
      level_assignments: [{ id: "cl1", ...STATED, level: LVL + "B1", level_to: null, relation: null, dimension: null, competence_dimension: null }],
      time_spans: [],
      ...changes,
    };
  }
  const specification = (contexts = [context()]) => ({ ...noValues(), contexts });

  it("holds each context with its fields and, as entries of their own, its levels and time spans", () => {
    const draft = draftOfValues(FORM, specification());

    expect(draft.contexts[0]).toMatchObject({
      id: "c1",
      fields: { sector: CV + "sec_school", formality: "", institution_text: "Gymnasium", target_group_text: "" },
    });
    expect(draft.contexts[0]?.inner?.level_assignments[0]).toMatchObject({ id: "cl1", fields: { level: LVL + "B1" } });
    expect(draft.contexts[0]?.inner?.time_spans).toEqual([]);
    // a holder of no context holds none
    expect(draftOfValues(FORM, held()).contexts).toEqual([]);
  });

  it("keeps a context's and its values' keys as the specification is read again", () => {
    const before = draftOfValues(FORM, specification());
    const again = draftOfValues(FORM, specification(), before);

    expect(again.contexts[0]?.key).toBe(before.contexts[0]?.key);
    expect(again.contexts[0]?.inner?.level_assignments[0]?.key).toBe(before.contexts[0]?.inner?.level_assignments[0]?.key);
    expect(holdsEntry(again, before.contexts[0]?.inner?.level_assignments[0]?.key ?? "")).toBe(true);
    expect(holdsEntry(again, "value-0")).toBe(false);
  });

  it("adds an empty context, which holds no value, and takes no more than the server does", () => {
    let draft = draftOfValues(FORM, noValues());
    const added = withEntry(FORM, draft, "contexts");

    expect(added.entry).toMatchObject({ id: null, fields: { sector: "", formality: "", institution_text: "", target_group_text: "" } });
    expect(added.entry.inner).toEqual({ level_assignments: [], time_spans: [], workloads: [], contexts: [] });
    for (let more = 0; more < MOST_VALUES; more += 1) draft = withEntry(FORM, draft, "contexts").draft;
    expect(isFull(draft.contexts)).toBe(true);
  });

  it("sees a changed value of a context as a change of the contexts", () => {
    const before = draftOfValues(FORM, specification());
    const [first] = before.contexts;
    if (!first?.inner) throw new Error("a context");
    const inner = edited(first.inner, "level_assignments", 0, "level", LVL + "B2");
    const changed = { ...before, contexts: [{ ...first, inner }] };

    expect(sameValues(before, draftOfValues(FORM, specification()))).toBe(true);
    expect(rebaseValues(before, before, draftOfValues(FORM, specification([context({ institution_text: "Realschule" })]))).taken).toEqual([
      "contexts",
    ]);
    expect(rebaseValues(before, changed, draftOfValues(FORM, specification([]))).clashes).toEqual(["contexts"]);
  });

  it("finds a problem of a context's value by its path under the context", () => {
    let draft = withEntry(FORM, draftOfValues(FORM, noValues()), "contexts").draft;
    const [first] = draft.contexts;
    if (!first?.inner) throw new Error("a context");
    draft = { ...draft, contexts: [{ ...first, inner: withEntry(FORM, first.inner, "time_spans").draft }] };

    expect(checkDraft(FORM, draft)).toEqual([["contexts[0].time_spans[0].time_kind", "Dieses Feld braucht einen Wert."]]);
  });

  it("sends each context with its fields and values, the kept by their ids, an empty text as none", () => {
    let draft = withEntry(FORM, draftOfValues(FORM, specification()), "contexts").draft;
    draft = edited(draft, "contexts", 1, "institution_text", "  ");

    expect(contextsOf(FORM, draft)).toEqual([
      {
        id: "c1", sector: CV + "sec_school", formality: null, institution_text: "Gymnasium", target_group_text: null,
        level_assignments: [{ id: "cl1", level: LVL + "B1", level_to: null, relation: null, dimension: null, competence_dimension: null }],
        time_spans: [],
      },
      { id: null, sector: null, formality: null, institution_text: null, target_group_text: null, level_assignments: [], time_spans: [] },
    ]);
    // a node's set names no context: the node's route takes none
    expect(requestOf(FORM, draft)).not.toHaveProperty("contexts");
  });

  it("names a problem's field in a context: the form's paths, and the store's at the context or one of its kinds", () => {
    const set = draftOfValues(FORM, specification());
    const at = set.contexts[0];
    const level = at?.inner?.level_assignments[0];

    expect(entryField(FORM, set, "contexts[0].sector")).toBe(`${at?.key}:sector`);
    expect(entryField(FORM, set, "contexts[0].level_assignments[0].level")).toBe(`${level?.key}:level`);
    expect(entryField(FORM, set, "contexts[0].level_assignments")).toBe(`${at?.key}:level_assignments`);
    expect(entryField(FORM, set, "contexts[0].time_spans")).toBe(`${at?.key}:time_spans`);
    expect(entryField(FORM, set, "contexts[0]")).toBe(`${at?.key}:context`);
    // none the set or the form does not hold
    expect(entryField(FORM, set, "contexts[1].sector")).toBeNull();
    expect(entryField(FORM, set, "contexts[0].id")).toBeNull();
    expect(entryField(FORM, set, "contexts[0].level_assignments[0].id")).toBeNull();
    expect(entryField(FORM, set, "contexts")).toBeNull();
  });
});
