import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { decideCue, decideTerm, getReview, getTerms } from "@/api";

function answer(status: number, body: unknown): Response {
  return new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });
}

function call(index = 0): [string, RequestInit] {
  return vi.mocked(fetch).mock.calls[index] as [string, RequestInit];
}

beforeEach(() => {
  // a body is read once: one answer per request
  vi.stubGlobal("fetch", vi.fn(() => Promise.resolve(answer(200, { done: true }))));
});

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("the editors' review of the lexicon", () => {
  it("reads the sample and the new terms", async () => {
    const sample = await getReview();
    const terms = await getTerms();

    expect([call(0)[0], call(0)[1].method]).toEqual(["/api/v1/lexicon/review", undefined]);
    expect([call(1)[0], call(1)[1].method]).toEqual(["/api/v1/lexicon/terms", undefined]);
    expect([sample, terms]).toEqual([{ done: true }, { done: true }]);
  });

  it("decides on a research cue, its strength as a decimal text", async () => {
    const decided = await decideCue({
      cue: "https://example.org/re-1",
      decision: "confirmed",
      strength: "0.85",
      evidence: "KLP S. 14",
      note: null,
    });

    expect([call()[0], call()[1].method]).toEqual(["/api/v1/lexicon/review", "POST"]);
    expect(JSON.parse(call()[1].body as string)).toEqual({
      cue: "https://example.org/re-1",
      decision: "confirmed",
      strength: "0.85",
      evidence: "KLP S. 14",
      note: null,
    });
    expect(decided).toEqual({ done: true });
  });

  it("decides on a new term, by its sector, regions and word", async () => {
    await decideTerm({
      sector: "school",
      regions: ["DE-NW"],
      term: "Lernbereich",
      decision: "cue",
      maps_to: "https://example.org/Lernbereich",
      role: "alt",
      note: null,
    });

    expect([call()[0], call()[1].method]).toEqual(["/api/v1/lexicon/terms", "POST"]);
    expect(JSON.parse(call()[1].body as string)).toEqual({
      sector: "school",
      regions: ["DE-NW"],
      term: "Lernbereich",
      decision: "cue",
      maps_to: "https://example.org/Lernbereich",
      role: "alt",
      note: null,
    });
  });
});
