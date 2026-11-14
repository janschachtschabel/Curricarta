// The editors' review of the lexicon (plan M1 10.3-10.5; backend app/api/lexicon_review.py, lexicon_terms.py):
// the sample of the research's cues and the terms X1 found no type for, each with its decision, and a
// decision made again over the last. The editors alone (403 `not_editor` for any other account).
import { apiFetch } from "./http";

/** Every concept an answer names, by its German label; a class or property of the core has none. */
export type Labels = Record<string, string>;

// --- the sample of the research's cues ---

export type CueDecisionKind = "confirmed" | "rejected";

export interface CueDecision {
  cue: string;
  decision: CueDecisionKind;
  /** A decimal text, "0.90"; none for a rejection. */
  strength: string | null;
  /** Where the editors found the cue; none for a rejection. */
  evidence: string | null;
  note: string | null;
  /** What was judged, as the cue said it then: surface_form, pattern, maps_to, scope_regions, role, kind, profile. */
  content: Record<string, unknown>;
  /** The account's name. */
  decided_by: string;
  decided_at: string;
  /** The cue retired since. */
  retired: boolean;
  /** The files' release holds it: confirmed - verified at its strength; rejected - retired. */
  applied: boolean;
}

export interface Stratum {
  /** The notation of its sector, "school". */
  sector: string;
  /** The IRIs of its regions. */
  regions: string[];
  cues: number;
  sampled: number;
  decided: number;
}

export interface ReviewCue {
  iri: string;
  sector: string;
  /** IRIs. */
  regions: string[];
  surface_form: string | null;
  pattern: string | null;
  /** IRIs, as are kind and maps_to. */
  role: string;
  kind: string;
  maps_to: string[];
  strength: string | null;
  verified: boolean;
  sources: string[];
  /** Where the research found it, and what it proposed. */
  notes: string[];
  recognition_hints: string[];
  examples: string[];
  /** In the sample; else listed for its decision. */
  sampled: boolean;
  decision: CueDecision | null;
}

export interface ReviewList {
  strata: Stratum[];
  /** The sample, stratum by stratum; then the other cues decided. */
  items: ReviewCue[];
  /** Decisions on cues retired since. */
  retired: CueDecision[];
  labels: Labels;
}

export interface CueDecisionIn {
  cue: string;
  decision: CueDecisionKind;
  /** 0.50 to 0.90, two places, with `evidence`, for a confirmation alone. */
  strength?: string | null;
  evidence?: string | null;
  note?: string | null;
}

// --- the terms X1 found no type for ---

export type TermDecisionKind = "cue" | "document" | "error";
export type NewCueRole = "pref" | "alt" | "cue";

export interface TermDecision {
  sector: string;
  regions: string[];
  /** The term as judged. */
  term: string;
  decision: TermDecisionKind;
  maps_to: string | null;
  role: NewCueRole | null;
  note: string | null;
  /** What else was judged: the functions suggested, how many documents named it. */
  content: Record<string, unknown>;
  decided_by: string;
  decided_at: string;
  /** A new cue: whether an active cue of the profile says it yet; null, nothing to apply. */
  applied: boolean | null;
}

export interface Place {
  document: string;
  title: string | null;
  block: string | null;
  /** The function X1 suggested, an IRI. */
  function: string | null;
}

export interface HeldCue {
  iri: string;
  /** The sector's own lexicon; else the research's. The importer takes no new cue of an own word. */
  own: boolean;
  /** Its word holds the term; else its pattern alone, which the importer counts only for its targets. */
  by_word: boolean;
  surface_form: string | null;
  pattern: string | null;
  maps_to: string[];
  /** Its IRI. */
  role: string;
  /** IRIs; none, everywhere. */
  regions: string[];
}

export interface NewTerm {
  sector: string;
  /** Codes, "DE-NW"; "DE" for a document of none. */
  regions: string[];
  /** In the form the documents write most. */
  term: string;
  documents: number;
  functions: string[];
  /** The first places; `documents` counts them all. */
  occurrences: Place[];
  /** The active cues that hold the word already, the own lexicon's first. */
  held: HeldCue[];
  decision: TermDecision | null;
}

export interface TermsList {
  terms: NewTerm[];
  /** Decisions on terms no document names any more. */
  gone: TermDecision[];
  labels: Labels;
}

export interface TermDecisionIn {
  sector: string;
  regions: string[];
  term: string;
  decision: TermDecisionKind;
  /** A node type of the sector's profile, with `role`, for a new cue alone. */
  maps_to?: string | null;
  role?: NewCueRole | null;
  note?: string | null;
}

export function getReview(): Promise<ReviewList> {
  return apiFetch<ReviewList>("/api/v1/lexicon/review");
}

/** 404 `no_cue`: no active research cue, nor one decided before. */
export function decideCue(body: CueDecisionIn): Promise<CueDecision> {
  return apiFetch<CueDecision>("/api/v1/lexicon/review", { method: "POST", body: JSON.stringify(body) });
}

export function getTerms(): Promise<TermsList> {
  return apiFetch<TermsList>("/api/v1/lexicon/terms");
}

/**
 * 404 `no_term`: no document names it, nor was it decided before; 422 `too_short` (a word under four signs gives
 * no cue), `not_a_node_type`.
 */
export function decideTerm(body: TermDecisionIn): Promise<TermDecision> {
  return apiFetch<TermDecision>("/api/v1/lexicon/terms", { method: "POST", body: JSON.stringify(body) });
}
