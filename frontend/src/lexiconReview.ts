// The two lists as the page keeps them (LexiconSample.vue, LexiconTerms.vue): a decision on a cue retired or a
// term gone shown as an entry of its own, built from what was judged - the cue or term itself is no longer
// listed -, and a decision just made taken into its list without reading it again.
import type { CueDecision, Labels, NewTerm, ReviewCue, ReviewList, TermDecision, TermsList } from "@/api";

function text(value: unknown): string | null {
  return typeof value === "string" ? value : null;
}

function texts(value: unknown): string[] {
  return Array.isArray(value) ? value.filter((one): one is string => typeof one === "string") : [];
}

/** A retired cue's decision as an entry: the cue as it was judged then, outside the sample. */
export function judgedCue(decision: CueDecision): ReviewCue {
  const judged = decision.content;
  return {
    iri: decision.cue,
    sector: "",
    regions: texts(judged.scope_regions),
    surface_form: text(judged.surface_form),
    pattern: text(judged.pattern),
    role: text(judged.role) ?? "",
    kind: text(judged.kind) ?? "",
    maps_to: texts(judged.maps_to),
    strength: null,
    verified: false,
    sources: [],
    notes: [],
    recognition_hints: [],
    examples: [],
    sampled: false,
    decision,
  };
}

function sameRegions(one: readonly string[], other: readonly string[]): boolean {
  return one.length === other.length && one.every((region, index) => region === other[index]);
}

/** The list with `made` in place of the cue's decision before; a first decision counted in the cue's stratum. */
export function decidedIn(list: ReviewList, made: CueDecision): ReviewList {
  const cue = list.items.find((item) => item.iri === made.cue);
  if (!cue) {
    return { ...list, retired: list.retired.map((decision) => (decision.cue === made.cue ? made : decision)) };
  }
  const first = cue.decision === null;
  return {
    ...list,
    items: list.items.map((item) => (item.iri === made.cue ? { ...item, decision: made } : item)),
    strata: list.strata.map((stratum) =>
      first && stratum.sector === cue.sector && sameRegions(stratum.regions, cue.regions)
        ? { ...stratum, decided: stratum.decided + 1 }
        : stratum,
    ),
  };
}

/** A term's key, as the list tells one from another: its sector, its regions and its word. */
export function termKey(term: { sector: string; regions: readonly string[]; term: string }): string {
  return [term.sector, term.regions.join(" "), term.term].join("\n");
}

/** A decision on a term no document names any more as an entry: the term as it was judged. */
export function goneTerm(decision: TermDecision): NewTerm {
  return {
    sector: decision.sector,
    regions: decision.regions,
    term: decision.term,
    documents: 0,
    functions: texts(decision.content.functions),
    occurrences: [],
    held: [],
    decision,
  };
}

/**
 * The list with `made` in place of the decision before of the term `key` names - the entry it was made for: the
 * server writes the term as the documents write it most at that moment, which may be otherwise by then -, listed
 * or gone, and `labels` - the target's, as it was chosen - among the list's.
 */
export function termDecidedIn(list: TermsList, key: string, made: TermDecision, labels: Labels = {}): TermsList {
  return {
    ...list,
    labels: { ...list.labels, ...labels },
    terms: list.terms.map((term) => (termKey(term) === key ? { ...term, decision: made } : term)),
    gone: list.gone.map((decision) => (termKey(decision) === key ? made : decision)),
  };
}
