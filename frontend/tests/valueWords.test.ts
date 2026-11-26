import { readFileSync } from "node:fs";
import { join } from "node:path";

import { describe, expect, it } from "vitest";

import type { HeldLevel, HeldTimeSpan, HeldWorkload } from "@/api";
import { messages, t } from "@/i18n/de";
import { contextWords, levelInWay, levelWords, shownContexts, timeSpanWords, valueWords, workloadWords } from "@/valueWords";

import { CV, LVL, form_, noValues, value_ } from "./treeFixtures";

const STATED = { id: "v1", origin: CV + "orig_human", review_status: CV + "rev_proposed", revision: 1 };

function level(changes: Partial<HeldLevel> = {}): HeldLevel {
  return { ...STATED, level: LVL + "B1", level_to: null, relation: null, dimension: null, competence_dimension: null, ...changes };
}

function span(changes: Partial<HeldTimeSpan> = {}): HeldTimeSpan {
  return { ...STATED, time_kind: CV + "time_gradeLevel", span_from: null, span_to: null, time_relation: null, ...changes };
}

function workload(changes: Partial<HeldWorkload> = {}): HeldWorkload {
  return {
    ...STATED,
    amount: 80,
    amount_to: null,
    unit: CV + "unit_lesson",
    workload_kind: null,
    is_recommendation: false,
    minutes_per_unit: null,
    total: false,
    periods: [],
    ...changes,
  };
}

const FORM = form_();

describe("a level in words", () => {
  it("names its level by its label, then what else it says", () => {
    expect(levelWords(level({ relation: CV + "lrel_minimum", competence_dimension: LVL + "listening" }), FORM)).toBe(
      "GER B1, Mindestniveau, Hören",
    );
    expect(levelWords(level({ dimension: CV + "dim_proficiency" }), FORM)).toBe("GER B1, Kompetenzstufe");
  });

  it("names a range by its start and its end", () => {
    expect(levelWords(level({ level_to: LVL + "B2" }), FORM)).toBe("GER B1 bis GER B2");
  });

  it("keeps a level the form no longer offers as its IRI rather than as nothing", () => {
    expect(levelWords(level({ level: "https://example.org/levels#gone" }), FORM)).toBe("https://example.org/levels#gone");
  });
});

describe("a time span in words", () => {
  it("names its kind and its span", () => {
    expect(timeSpanWords(span({ span_from: 7, span_to: 8 }), FORM)).toBe("Jahrgangsstufe 7–8");
    expect(timeSpanWords(span({ span_from: 7, span_to: 7 }), FORM)).toBe("Jahrgangsstufe 7");
  });

  it("names an open span by the end it has, and a kind without a span alone", () => {
    expect(timeSpanWords(span({ span_from: 7 }), FORM)).toBe("Jahrgangsstufe ab 7");
    expect(timeSpanWords(span({ span_to: 8 }), FORM)).toBe("Jahrgangsstufe bis 8");
    expect(timeSpanWords(span(), FORM)).toBe("Jahrgangsstufe");
  });

  it("adds its relation, a fraction with the decimal comma", () => {
    expect(timeSpanWords(span({ time_kind: CV + "time_semester", span_from: 1.5, time_relation: CV + "trel_during" }), FORM)).toBe(
      "Fachsemester ab 1,5, während",
    );
  });
});

describe("a workload in words", () => {
  it("counts its unit and says when it is a recommendation", () => {
    expect(workloadWords(workload({ is_recommendation: true }), FORM)).toBe("80 Unterrichtsstunden, Richtwert");
    expect(workloadWords(workload({ amount: 1 }), FORM)).toBe("1 Unterrichtsstunde");
  });

  it("counts a range by its end, a fraction with the decimal comma", () => {
    expect(workloadWords(workload({ amount: 70, amount_to: 80 }), FORM)).toBe("70–80 Unterrichtsstunden");
    expect(workloadWords(workload({ amount: 7.5, unit: CV + "unit_hour" }), FORM)).toBe("7,5 Zeitstunden");
    // four digits as a year reads, five grouped
    expect(workloadWords(workload({ amount: 1800, amount_to: 12000, unit: CV + "unit_hour" }), FORM)).toBe("1800–12.000 Zeitstunden");
  });

  it("leaves out what it does not say, and says all it does", () => {
    const full = workload({
      workload_kind: CV + "wl_guidanceValue",
      is_recommendation: true,
      minutes_per_unit: 45,
      total: true,
      periods: [span({ span_from: 7, span_to: 8 })],
    });

    expect(workloadWords(full, FORM)).toBe(
      "80 Unterrichtsstunden, Zeitrichtwert, Richtwert, je 45 Minuten, Gesamtumfang, in Jahrgangsstufe 7–8",
    );
  });

  it("names a unit it has no counted word for by its label", () => {
    const form = form_();
    const unit = form.values.workloads.fields.find((field) => field.key === "unit");
    unit?.values?.push(value_("urn:double", "Doppelstunde", { notation: "double" }));

    expect(workloadWords(workload({ amount: 3, unit: "urn:double" }), form)).toBe("Doppelstunde: 3");
    expect(workloadWords(workload({ amount: 3, unit: "urn:unknown" }), form)).toBe("urn:unknown: 3");
  });
});

describe("a value of any kind in words", () => {
  it("is worded by its kind", () => {
    expect(valueWords("level_assignments", level(), FORM)).toBe("GER B1");
    expect(valueWords("time_spans", span({ span_from: 7 }), FORM)).toBe("Jahrgangsstufe ab 7");
    expect(valueWords("workloads", workload(), FORM)).toBe("80 Unterrichtsstunden");
  });
});

describe("an applicability context in words", () => {
  const context = {
    sector: CV + "sec_school",
    formality: null,
    institution_text: "Gymnasium",
    target_group_text: "Lernende mit Förderbedarf",
    level_assignments: [level()],
    time_spans: [span({ span_from: 5, span_to: 6 })],
  };

  it("names all it states, its values as they read", () => {
    expect(contextWords(context, FORM)).toBe("Schulbildung · Einrichtung: Gymnasium · Zielgruppe: Lernende mit Förderbedarf · GER B1 · Jahrgangsstufe 5–6");
    expect(valueWords("contexts", context, FORM)).toBe(contextWords(context, FORM));
  });

  it("says a context that states nothing as such", () => {
    const nothing = { sector: null, formality: null, institution_text: null, target_group_text: null, level_assignments: [], time_spans: [] };

    expect(contextWords(nothing, FORM)).toBe(t("documents.page.scope.emptyContext"));
  });

  it("shows each stored context and each of its values, with who stated it and a review by its table", () => {
    const stored = { ...STATED, id: "c1", ...context, level_assignments: [level({ id: "cl1" })], time_spans: [] };

    const shown = shownContexts(FORM, [stored]);

    expect(shown.map((one) => [one.id, one.words, one.review.table])).toEqual([
      ["c1", "Schulbildung · Einrichtung: Gymnasium · Zielgruppe: Lernende mit Förderbedarf · GER B1", "applicability_context"],
      ["cl1", "GER B1", "level_assignment"],
    ]);
    expect(shown[0]?.stated).toBe("redaktionell · Vorgeschlagen");
  });
});

describe("a level that stands in the way of a change of its holder", () => {
  it("is named by its place in the holder's values, another place not", () => {
    const values = { ...noValues(), level_assignments: [level(), level({ level: LVL + "B2" })] };

    expect(levelInWay(values, FORM, "level_assignments[1].level", "Nein.")).toBe(
      t("documents.tree.values.heldInWay", { value: "GER B2", problem: "Nein." }),
    );
    expect(levelInWay(values, FORM, "level_assignments[2].level", "Nein.")).toBeNull();
    expect(levelInWay(values, FORM, "statement_kind", "Nein.")).toBeNull();
  });
});

describe("the counted words of the units", () => {
  // a key that missed its notation would fall back to "Einheit: 3" without a word
  it("are one for each unit of cv:WorkloadUnits, by its notation", () => {
    const source = readFileSync(join(process.cwd(), "..", "ontology", "ontologie", "cur-vokabular.ttl"), "utf8");
    const notations = [...source.matchAll(/skos:inScheme cv:WorkloadUnits[^.]*?skos:notation "([A-Za-z]+)"/gs)].map(([, notation]) => notation);

    expect(notations.length).toBeGreaterThan(0);
    expect(Object.keys(messages.documents.tree.values.units).sort()).toEqual(notations.sort());
  });
});

