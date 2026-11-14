// The sample's cues by the strata it is drawn from (LexiconSample.vue): a Bildungsbereich and a Land to show the
// cues of, and how many at a time. A sample of some 200 cues on one page was read as one long scroll, with no way
// to the cues of one Land and the second section of the page behind all of them (UI review M3).
import type { Labels, ReviewCue } from "@/api";
import { LOCALE } from "@/i18n/de";
import { labelOf, sectorWord } from "@/lexiconWords";

/** The choice of a cue that names no region: one that holds everywhere. */
export const EVERYWHERE = "everywhere";

/** How many cues a page of the sample shows, and each "Weitere zeigen" adds. */
export const SAMPLE_PAGE = 20;

export interface CueChoice {
  /** A sector's notation; empty for every one. */
  sector: string;
  /** A region's IRI, or EVERYWHERE; empty for every one. */
  region: string;
}

export const ANY_CUE: CueChoice = { sector: "", region: "" };

/** The sectors the cues stand in, by their words. */
export function sectorsOf(items: readonly ReviewCue[]): string[] {
  return [...new Set(items.map((item) => item.sector))].sort((a, b) => sectorWord(a).localeCompare(sectorWord(b), LOCALE));
}

/** The regions the cues name, by their labels; EVERYWHERE last, where a cue names none. */
export function regionsOf(items: readonly ReviewCue[], labels: Labels): string[] {
  const named = [...new Set(items.flatMap((item) => item.regions))].sort((a, b) =>
    labelOf(labels, a).localeCompare(labelOf(labels, b), LOCALE),
  );
  return items.some((item) => item.regions.length === 0) ? [...named, EVERYWHERE] : named;
}

export function chosen(item: ReviewCue, choice: CueChoice): boolean {
  if (choice.sector && item.sector !== choice.sector) return false;
  if (choice.region === EVERYWHERE) return item.regions.length === 0;
  return !choice.region || item.regions.includes(choice.region);
}
