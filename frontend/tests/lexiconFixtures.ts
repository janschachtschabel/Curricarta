// What the lexicon's review answers with (backend app/api/lexicon_review.py, lexicon_terms.py), for the tests
// of its page.
import type { CueDecision, FormValue, HeldCue, NewTerm, ReviewCue, TermDecision } from "@/api";

export const CV = "https://w3id.org/wlo/curriculum/vocab#";
export const SCHOOL = "https://w3id.org/wlo/curriculum/profile/school#";
export const REGION = "https://w3id.org/wlo/curriculum/region/";
export const CUE = SCHOOL + "re-DE-NW-0123456789ab";

export const LABELS: Record<string, string> = {
  [CV + "role_alt"]: "echtes Synonym",
  [CV + "role_cue"]: "Hinweis (kein Synonym)",
  [CV + "ck_term"]: "Wort",
  [CV + "ck_headingPattern"]: "Überschriftenmuster",
  [SCHOOL + "Inhaltsbereich"]: "Inhaltsbereich",
  [SCHOOL + "Lernfeld"]: "Lernfeld",
  [REGION + "DE-NW"]: "Nordrhein-Westfalen",
  [REGION + "DE-BY"]: "Bayern",
};

export function cueDecision(changes: Partial<CueDecision> = {}): CueDecision {
  return {
    cue: CUE,
    decision: "confirmed",
    strength: "0.9",
    evidence: "KLP S. 14",
    note: null,
    content: {
      surface_form: "Inhaltsfeld",
      pattern: null,
      maps_to: [SCHOOL + "Inhaltsbereich"],
      scope_regions: [REGION + "DE-NW"],
      role: CV + "role_alt",
      kind: CV + "ck_term",
      profile: SCHOOL + "Terminology",
    },
    decided_by: "Redaktion",
    decided_at: "2026-11-01T10:00:00Z",
    retired: false,
    applied: false,
    ...changes,
  };
}

export function reviewCue(changes: Partial<ReviewCue> = {}): ReviewCue {
  return {
    iri: CUE,
    sector: "school",
    regions: [REGION + "DE-NW"],
    surface_form: "Inhaltsfeld",
    pattern: null,
    role: CV + "role_alt",
    kind: CV + "ck_term",
    maps_to: [SCHOOL + "Inhaltsbereich"],
    strength: "0.7",
    verified: false,
    sources: ["recherche-ergebnisse/schule-nw.md"],
    notes: ["Beleg E: Kernlehrplan Physik, S. 14"],
    recognition_hints: [],
    examples: ["Inhaltsfeld 1: Energie"],
    sampled: true,
    decision: null,
    ...changes,
  };
}

export const DOCUMENT = "0190-0000-0000-7000-8000-000000000001";

export function termDecision(changes: Partial<TermDecision> = {}): TermDecision {
  return {
    sector: "school",
    regions: ["DE-NW"],
    term: "Lernbereich",
    decision: "cue",
    maps_to: SCHOOL + "Inhaltsbereich",
    role: "alt",
    note: null,
    content: { functions: [CV + "fn_area"], documents: 2 },
    decided_by: "Redaktion",
    decided_at: "2026-11-01T10:00:00Z",
    applied: false,
    ...changes,
  };
}

export function heldCue(changes: Partial<HeldCue> = {}): HeldCue {
  return {
    iri: SCHOOL + "cue-ib-lernbereich",
    own: true,
    by_word: true,
    surface_form: "Lernbereich",
    pattern: null,
    maps_to: [SCHOOL + "Inhaltsbereich"],
    role: CV + "role_cue",
    regions: [],
    ...changes,
  };
}

export function newTerm(changes: Partial<NewTerm> = {}): NewTerm {
  return {
    sector: "school",
    regions: ["DE-NW"],
    term: "Lernbereich",
    documents: 2,
    functions: [CV + "fn_area"],
    occurrences: [
      { document: DOCUMENT, title: "Kernlehrplan Physik", block: "p3-b2", function: CV + "fn_area" },
      { document: "0190-0000-0000-7000-8000-000000000002", title: null, block: null, function: null },
    ],
    held: [],
    decision: null,
    ...changes,
  };
}

export function nodeType(name: string, functions: string[]): FormValue {
  return {
    iri: SCHOOL + name,
    notation: null,
    label: name,
    alt_labels: [],
    definition: null,
    note: null,
    delimitation: null,
    examples: [],
    broader: functions,
  };
}
