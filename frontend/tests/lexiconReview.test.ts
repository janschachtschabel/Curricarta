import { describe, expect, it } from "vitest";

import type { ReviewList, TermsList } from "@/api";
import { decidedIn, goneTerm, judgedCue, termDecidedIn, termKey } from "@/lexiconReview";

import { CUE, CV, REGION, SCHOOL, cueDecision, newTerm, reviewCue, termDecision } from "./lexiconFixtures";

const OTHER = SCHOOL + "re-DE-BY-ba9876543210";

function list(changes: Partial<ReviewList> = {}): ReviewList {
  return {
    strata: [
      { sector: "school", regions: [REGION + "DE-BY"], cues: 30, sampled: 3, decided: 0 },
      { sector: "school", regions: [REGION + "DE-NW"], cues: 20, sampled: 2, decided: 1 },
      // what a cue of DE-BY is not counted in: another sector's, and none's
      { sector: "vocational", regions: [REGION + "DE-BY"], cues: 10, sampled: 1, decided: 0 },
      { sector: "school", regions: [], cues: 10, sampled: 1, decided: 0 },
    ],
    items: [reviewCue(), reviewCue({ iri: OTHER, regions: [REGION + "DE-BY"] })],
    retired: [],
    labels: {},
    ...changes,
  };
}

describe("a retired cue's decision as an entry of the list", () => {
  it("is the cue as it was judged", () => {
    const decision = cueDecision({ retired: true, decision: "rejected", strength: null });

    const cue = judgedCue(decision);

    expect(cue).toMatchObject({
      iri: CUE,
      surface_form: "Inhaltsfeld",
      pattern: null,
      regions: [REGION + "DE-NW"],
      role: CV + "role_alt",
      kind: CV + "ck_term",
      maps_to: [SCHOOL + "Inhaltsbereich"],
      sampled: false,
      decision,
    });
    expect([cue.sources, cue.notes, cue.recognition_hints, cue.examples]).toEqual([[], [], [], []]);
  });

  it("takes nothing it cannot read as what was judged", () => {
    const cue = judgedCue(cueDecision({ content: { surface_form: 7, maps_to: ["a", 3], scope_regions: "DE" } }));

    expect([cue.surface_form, cue.maps_to, cue.regions, cue.role, cue.kind]).toEqual([null, ["a"], [], "", ""]);
  });
});

describe("a decision taken into the list", () => {
  it("replaces the cue's decision and counts a first one in its stratum", () => {
    const made = cueDecision({ cue: OTHER });

    const after = decidedIn(list(), made);

    expect(after.items[1].decision).toEqual(made);
    expect(after.items[0].decision).toBeNull();
    expect(after.strata.map((stratum) => stratum.decided)).toEqual([1, 1, 0, 0]);
  });

  it("counts a decision made again once", () => {
    const before = list();
    before.items[1].decision = cueDecision({ cue: OTHER, decision: "rejected" });

    const after = decidedIn(before, cueDecision({ cue: OTHER }));

    expect(after.strata.map((stratum) => stratum.decided)).toEqual([0, 1, 0, 0]);
    expect(after.items[1].decision?.decision).toBe("confirmed");
  });

  it("replaces a retired cue's decision where it stands", () => {
    const gone = SCHOOL + "re-DE-NW-000000000000";
    const made = cueDecision({ cue: gone, retired: true, decision: "confirmed" });

    const after = decidedIn(list({ retired: [cueDecision({ cue: gone, retired: true, decision: "rejected" })] }), made);

    expect(after.retired).toEqual([made]);
    expect(after.strata.map((stratum) => stratum.decided)).toEqual([0, 1, 0, 0]);
  });

  it("leaves the list it was given as it was", () => {
    const before = list();

    decidedIn(before, cueDecision({ cue: OTHER }));

    expect(before.items[1].decision).toBeNull();
    expect(before.strata[0].decided).toBe(0);
  });
});

function terms(changes: Partial<TermsList> = {}): TermsList {
  return {
    terms: [newTerm(), newTerm({ regions: ["DE-BY"] }), newTerm({ term: "Lernfeld" })],
    gone: [],
    labels: {},
    ...changes,
  };
}

describe("a decision on a term no document names any more, as an entry of the list", () => {
  it("is the term as it was judged, named by no document now", () => {
    const decision = termDecision({ content: { functions: [CV + "fn_unit"], documents: 3 } });

    expect(goneTerm(decision)).toEqual({
      sector: "school",
      regions: ["DE-NW"],
      term: "Lernbereich",
      documents: 0,
      functions: [CV + "fn_unit"],
      occurrences: [],
      held: [],
      decision,
    });
  });

  it("takes no functions it cannot read as what was judged", () => {
    expect(goneTerm(termDecision({ content: { functions: "fn_unit" } })).functions).toEqual([]);
  });
});

describe("a decision on a term taken into the list", () => {
  it("replaces the decision of the term of its sector, regions and word alone", () => {
    const made = termDecision({ regions: ["DE-BY"] });

    const after = termDecidedIn(terms(), termKey(newTerm({ regions: ["DE-BY"] })), made);

    expect(after.terms.map((term) => term.decision)).toEqual([null, made, null]);
  });

  it("replaces a decision on a term gone where it stands", () => {
    const made = termDecision({ term: "Leitidee", decision: "error", maps_to: null, role: null });

    const after = termDecidedIn(terms({ gone: [termDecision({ term: "Leitidee" })] }), termKey(made), made);

    expect(after.gone).toEqual([made]);
    expect(after.terms.every((term) => term.decision === null)).toBe(true);
  });

  it("leaves the list it was given as it was", () => {
    const before = terms();

    termDecidedIn(before, termKey(newTerm()), termDecision());

    expect(before.terms[0].decision).toBeNull();
  });

  it("replaces the decision of the term it was made for, however the server writes the term now", () => {
    // the documents write it otherwise most by now: the decision is the entry's all the same
    const made = termDecision({ term: "LERNBEREICH" });

    const after = termDecidedIn(terms(), termKey(newTerm()), made);

    expect(after.terms[0].decision).toEqual(made);
  });

  it("takes the label of the target chosen into the list's labels", () => {
    const made = termDecision({ maps_to: SCHOOL + "Verzeichnis" });

    const after = termDecidedIn(terms({ labels: { a: "A" } }), termKey(newTerm()), made, { [SCHOOL + "Verzeichnis"]: "Verzeichnis/Vorwort" });

    expect(after.labels).toEqual({ a: "A", [SCHOOL + "Verzeichnis"]: "Verzeichnis/Vorwort" });
  });

  it("tells terms apart by sector, regions and word", () => {
    const keys = [newTerm(), newTerm({ regions: ["DE-BY"] }), newTerm({ sector: "vocational" }), newTerm({ term: "Lernfeld" })];

    expect(new Set(keys.map(termKey)).size).toBe(4);
    expect(termKey(termDecision())).toBe(termKey(newTerm()));
  });
});
