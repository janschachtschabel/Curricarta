// The lexicon's values in the page's words (LexiconReviewView): a concept by the label the server sends with
// the list, a sector and regions by the catalogue, a strength as a German reader writes it - and the rules of
// the research's importer the page says before a decision: a word under four signs gives no cue, and a new
// cue the own lexicon holds already is left out (backend app/lexicon/held.py, recherche_cues.own_holds).
import type { HeldCue, Labels } from "@/api";
import { LOCALE, messages } from "@/i18n/de";
import { word } from "@/registerWords";

/** The signs a word needs to give a cue (backend app/lexicon/new_terms.py MIN_SIGNS). */
export const MIN_SIGNS = 4;

/** The strengths a confirmation may give, as the server takes them: 0.50 to 0.90 in steps of 0.05. */
export const STRENGTHS: readonly string[] = Array.from({ length: 9 }, (_, step) => (0.5 + step * 0.05).toFixed(2));

const listFormat = new Intl.ListFormat(LOCALE, { type: "conjunction" });
const strengthFormat = new Intl.NumberFormat(LOCALE, { minimumFractionDigits: 2, maximumFractionDigits: 2 });

/** A concept by its label; one without - a class or property of the core - by the IRI's last part. */
export function labelOf(labels: Labels, iri: string): string {
  return labels[iri] ?? (/[^#/]+$/.exec(iri)?.[0] || iri);
}

/** Several concepts by their labels, as one phrase in their order. */
export function labelList(labels: Labels, iris: readonly string[]): string {
  return listFormat.format(iris.map((iri) => labelOf(labels, iri)));
}

export function sectorWord(notation: string): string {
  return word(messages.documents.sectors, notation);
}

/** Regions by their codes ("DE-NW"), as one phrase. */
export function regionWords(codes: readonly string[]): string {
  return listFormat.format(codes.map((code) => word(messages.sources.countries, code)));
}

/** A strength the server writes as a decimal text ("0.9"), as a German reader reads it: "0,90". */
export function strengthText(value: string): string {
  return strengthFormat.format(Number(value));
}

/** Whether a word is too short for a cue: counted by its signs, as the server counts them. */
export function tooShort(term: string): boolean {
  return [...term].length < MIN_SIGNS;
}

/** Why the import would leave a new cue out: the own lexicon holds its word, or one of its own patterns. */
export type SkipReason = "word" | "pattern";

/**
 * Why the import would leave a new cue to `target` out, as the research's importer decides (own_holds): the own
 * lexicon holds the word, whatever the target, or an own pattern matches it for that target; null where it takes
 * it. A research cue of the same word stands beside the new one.
 */
export function skipReason(held: readonly HeldCue[], target: string | null): SkipReason | null {
  const own = held.filter((cue) => cue.own);
  if (own.some((cue) => cue.by_word)) return "word";
  return target !== null && own.some((cue) => cue.maps_to.includes(target)) ? "pattern" : null;
}
