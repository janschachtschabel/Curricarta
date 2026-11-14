// What the register shows (RegisterFilter.vue), what that asks of the server, and how the
// page's address holds it (?kandidaten=1&stand=unreachable&suche=Physik&land=DE-TH): a reload,
// a bookmark and the way back from an entry's page find the register filtered as it was.
import type { LocationQuery, LocationQueryRaw } from "vue-router";

import type { RegisterStatus, SourceFilters } from "@/api";
import { messages, t } from "@/i18n/de";

export interface RegisterFilters {
  candidates: boolean;
  /** Empty for every status. */
  status: RegisterStatus | "";
  /** In the title or the address; blank for no search. */
  q: string;
  /** A code of ISO 3166-2:DE the register names; empty for every Land. */
  country: string;
}

/** The statuses the filter offers, in the order an entry passes through them. */
export const STATUSES: readonly RegisterStatus[] = ["unchecked", "reachable", "unreachable", "acquired"];

type CountryCode = keyof typeof messages.sources.countries;

/** The Länder the filter offers - those the register's seeds name - by their name. */
export const COUNTRIES: readonly CountryCode[] = (Object.keys(messages.sources.countries) as CountryCode[]).sort(
  (a, b) => messages.sources.countries[a].localeCompare(messages.sources.countries[b], "de"),
);

/** The longest search the server reads (backend SearchText). */
export const MAX_SEARCH_SIGNS = 200;

function single(value: LocationQuery[string]): string {
  return typeof value === "string" ? value : "";
}

/** The filter the address holds; what it holds that the filter does not know is left out. */
export function filtersFromQuery(query: LocationQuery): RegisterFilters {
  const status = STATUSES.find((value) => value === query.stand);
  const country = COUNTRIES.find((value) => value === query.land);
  return {
    candidates: query.kandidaten === "1",
    status: status ?? "",
    q: single(query.suche).slice(0, MAX_SEARCH_SIGNS),
    country: country ?? "",
  };
}

/** The filter as the address holds it: only what it sets. */
export function queryOf(filters: RegisterFilters): LocationQueryRaw {
  const query: LocationQueryRaw = {};
  if (filters.candidates) query.kandidaten = "1";
  if (filters.status) query.stand = filters.status;
  if (filters.q.trim()) query.suche = filters.q.trim();
  if (filters.country) query.land = filters.country;
  return query;
}

export function sameFilters(a: RegisterFilters, b: RegisterFilters): boolean {
  return a.candidates === b.candidates && a.status === b.status && a.q === b.q && a.country === b.country;
}

/** What the filter asks of the server: only what it sets. */
export function askedOf(filters: RegisterFilters): SourceFilters {
  const query: SourceFilters = {};
  if (filters.candidates) query.candidates = true;
  if (filters.status) query.status = filters.status;
  if (filters.q.trim()) query.q = filters.q.trim();
  if (filters.country) query.country = filters.country;
  return query;
}

/** What to do where `asked` let no entry through: take back what it set. */
export function emptyAdvice(asked: SourceFilters): string {
  const label = t("sources.filter.candidates");
  if (asked.q || asked.country) return t("sources.filter.emptyBody.search");
  if (asked.candidates && asked.status) return t("sources.filter.emptyBody.both", { label });
  if (asked.candidates) return t("sources.filter.emptyBody.candidates", { label });
  return t("sources.filter.emptyBody.status", { any: t("sources.filter.anyStatus") });
}

/** Whether two questions to the server ask for the same entries. */
export function sameAsked(a: SourceFilters, b: SourceFilters): boolean {
  const names = new Set([...Object.keys(a), ...Object.keys(b)]) as Set<keyof SourceFilters>;
  return [...names].every((name) => a[name] === b[name]);
}
