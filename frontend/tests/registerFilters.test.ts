import { describe, expect, it } from "vitest";

import { messages, t } from "@/i18n/de";
import {
  COUNTRIES,
  MAX_SEARCH_SIGNS,
  askedOf,
  emptyAdvice,
  filtersFromQuery,
  queryOf,
  sameFilters,
} from "@/registerFilters";

describe("the register's filter in the address", () => {
  it("is read from it", () => {
    expect(filtersFromQuery({ kandidaten: "1", stand: "unreachable" })).toEqual({ candidates: true, status: "unreachable", q: "", country: "" });
    expect(filtersFromQuery({})).toEqual({ candidates: false, status: "", q: "", country: "" });
  });

  it.each([
    ["a status the register does not know", { stand: "kaputt" }],
    ["a status twice", { stand: ["acquired", "reachable"] }],
    ["candidates by another word", { kandidaten: "ja" }],
    ["a parameter without its value", { kandidaten: null, stand: null }],
  ])("leaves out %s", (_what, query) => {
    expect(filtersFromQuery(query)).toEqual({ candidates: false, status: "", q: "", country: "" });
  });

  it("is written as it is read, and only with what is set", () => {
    expect(queryOf({ candidates: true, status: "acquired", q: "", country: "" })).toEqual({ kandidaten: "1", stand: "acquired" });
    expect(queryOf({ candidates: false, status: "reachable", q: "", country: "" })).toEqual({ stand: "reachable" });
    expect(queryOf({ candidates: false, status: "", q: "", country: "" })).toEqual({});
  });

  // the register's 1,499 entries need a search and a Land (UI review M2)
  it("holds a search and a Land as it holds the status", () => {
    const filters = { candidates: false, status: "" as const, q: "Physik", country: "DE-TH" };

    expect(queryOf(filters)).toEqual({ suche: "Physik", land: "DE-TH" });
    expect(filtersFromQuery({ suche: "Physik", land: "DE-TH" })).toEqual(filters);
  });

  it.each([
    ["a Land the register does not know", { land: "XX" }],
    ["a Land twice", { land: ["DE-BY", "DE-TH"] }],
    ["a search twice", { suche: ["a", "b"] }],
  ])("leaves out %s", (_what, query) => {
    expect(filtersFromQuery(query)).toEqual({ candidates: false, status: "", q: "", country: "" });
  });

  it("keeps a search no longer than the server reads", () => {
    expect(filtersFromQuery({ suche: "x".repeat(250) }).q).toHaveLength(MAX_SEARCH_SIGNS);
  });

  // the server counts signs as Python does, by code point; a cut inside a pair left half a sign (UI review 1, NIT 17)
  it("cuts a search by signs, never between the halves of one, and without its outer spaces", () => {
    const astral = "\u{1D53B}"; // one sign, two UTF-16 units
    const cut = filtersFromQuery({ suche: astral.repeat(250) }).q;
    expect([...cut]).toHaveLength(MAX_SEARCH_SIGNS);
    expect(cut).toBe(astral.repeat(MAX_SEARCH_SIGNS));
    expect(filtersFromQuery({ suche: "  Physik " }).q).toBe("Physik");
  });

  it("asks the server for the search without its outer spaces, and not for a blank one", () => {
    expect(askedOf({ candidates: false, status: "", q: "  Physik ", country: "DE-BY" })).toEqual({
      q: "Physik",
      country: "DE-BY",
    });
    expect(askedOf({ candidates: false, status: "", q: "   ", country: "" })).toEqual({});
    expect(queryOf({ candidates: false, status: "", q: "   ", country: "" })).toEqual({});
  });

  it("advises changing the search or the Land where they let nothing through", () => {
    expect(emptyAdvice({ q: "Physik" })).toBe(t("sources.filter.emptyBody.search"));
    expect(emptyAdvice({ country: "DE-BY", candidates: true })).toBe(t("sources.filter.emptyBody.search"));
  });

  it("offers every Land the register names, by name", () => {
    expect(COUNTRIES).toHaveLength(Object.keys(messages.sources.countries).length);
    const names = COUNTRIES.map((code) => messages.sources.countries[code]);
    expect(names).toEqual([...names].sort((a, b) => a.localeCompare(b, "de")));
  });

  it("tells one filter from another", () => {
    expect(sameFilters({ candidates: true, status: "", q: "", country: "" }, { candidates: true, status: "", q: "", country: "" })).toBe(true);
    expect(sameFilters({ candidates: true, status: "", q: "", country: "" }, { candidates: true, status: "acquired", q: "", country: "" })).toBe(false);
  });
});
