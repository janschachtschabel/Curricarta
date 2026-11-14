import { describe, expect, it } from "vitest";

import type { HeldCue } from "@/api";
import {
  STRENGTHS,
  labelList,
  labelOf,
  regionWords,
  sectorWord,
  skipReason,
  strengthText,
  tooShort,
} from "@/lexiconWords";

const SCHOOL = "https://w3id.org/wlo/curriculum/profile/school#";

function held(changes: Partial<HeldCue> = {}): HeldCue {
  return {
    iri: SCHOOL + "cue-1",
    own: true,
    by_word: true,
    surface_form: "Lernbereich",
    pattern: null,
    maps_to: [SCHOOL + "Inhaltsbereich"],
    role: "https://w3id.org/wlo/curriculum/vocab#role_alt",
    regions: [],
    ...changes,
  };
}

describe("the lexicon's values in words", () => {
  it("name a concept by its label, else by the IRI's last part", () => {
    const labels = { [SCHOOL + "Inhaltsbereich"]: "Inhaltsbereich (Fach)" };

    expect(labelOf(labels, SCHOOL + "Inhaltsbereich")).toBe("Inhaltsbereich (Fach)");
    // a class or property of the core has no label
    expect(labelOf(labels, "https://w3id.org/wlo/curriculum/core#hasLevel")).toBe("hasLevel");
    expect(labelOf(labels, "https://example.org/Ebene/Lernfeld")).toBe("Lernfeld");
    // an IRI that ends in its separator is shown whole rather than as nothing
    expect(labelOf(labels, "https://example.org/")).toBe("https://example.org/");
  });

  it("name several concepts as one phrase, in their order", () => {
    const labels = { [SCHOOL + "Inhaltsbereich"]: "Inhaltsbereich" };

    expect(labelList(labels, [SCHOOL + "Lernfeld", SCHOOL + "Inhaltsbereich"])).toBe("Lernfeld und Inhaltsbereich");
    expect(labelList(labels, [])).toBe("");
  });

  it("name a sector and regions by the catalogue, an unknown code as it is", () => {
    expect(sectorWord("school")).toBe("Schulbildung");
    expect(sectorWord("kindergarten")).toBe("kindergarten");
    expect(regionWords(["DE", "DE-NW", "DE-XX"])).toBe("Bund, Nordrhein-Westfalen und DE-XX");
  });

  it("offer the strengths a confirmation may give, and write them as a German reader reads them", () => {
    expect(STRENGTHS).toEqual(["0.50", "0.55", "0.60", "0.65", "0.70", "0.75", "0.80", "0.85", "0.90"]);
    expect(strengthText("0.9")).toBe("0,90");
    expect(strengthText("0.75")).toBe("0,75");
  });

  it("tell a word too short for a cue by its signs, not its code units", () => {
    expect(tooShort("LF")).toBe(true);
    expect(tooShort("Maß")).toBe(true);
    expect(tooShort("Feld")).toBe(false);
    // one sign each, two code units each
    expect(tooShort("𝔄𝔅𝔆")).toBe(true);
    expect(tooShort("𝔄𝔅𝔆𝔇")).toBe(false);
  });
});

describe("why the import would leave a new cue out", () => {
  it("is the own lexicon's word, whatever its target", () => {
    expect(skipReason([held()], SCHOOL + "Lernfeld")).toBe("word");
    expect(skipReason([held()], null)).toBe("word");
  });

  it("is an own pattern for one of the pattern's targets alone", () => {
    const pattern = held({ by_word: false, surface_form: null, pattern: "^Lernbereich\\s+\\d+" });

    expect(skipReason([pattern], SCHOOL + "Inhaltsbereich")).toBe("pattern");
    expect(skipReason([pattern], SCHOOL + "Lernfeld")).toBeNull();
    expect(skipReason([pattern], null)).toBeNull();
  });

  it("is the word before a pattern, where both hold it", () => {
    const pattern = held({ iri: SCHOOL + "cue-2", by_word: false, surface_form: null, pattern: "^Lernbereich" });

    expect(skipReason([pattern, held()], SCHOOL + "Inhaltsbereich")).toBe("word");
  });

  it("is none the research holds: the import puts the two side by side", () => {
    expect(skipReason([held({ own: false })], SCHOOL + "Inhaltsbereich")).toBeNull();
    expect(skipReason([], SCHOOL + "Inhaltsbereich")).toBeNull();
  });
});
