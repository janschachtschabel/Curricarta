// Synthetic rules of a document (plan M3a I), as the backend answers them.
import type { Rule, Rules } from "@/api";

const CV = "https://w3id.org/wlo/curriculum/vocab#";

export const RULE_UNITS = [{ iri: CV + "unit_ectsCredit", label: "ECTS-Leistungspunkt" }];
export const REQUIREMENT_KINDS = [{ iri: CV + "req_formal", label: "formal (zwingend)" }];

export function ruleOf(more: Partial<Rule> = {}): Rule {
  return {
    id: "r1",
    iri: null,
    kind: "selection",
    verbatim: "Zwei aus vier Wahlmodulen.",
    min_count: 2,
    max_count: 2,
    min_amount: 10,
    max_amount: null,
    amount_unit: CV + "unit_ectsCredit",
    requirement_kind: null,
    max_share: null,
    option_texts: ["Modul A", "Modul B"],
    applies_to: [],
    options: [],
    requires: [],
    origin: CV + "orig_model",
    review_status: CV + "rev_proposed",
    revision: 1,
    by_hand: false,
    anchors: [{ page_start: 3, page_end: null, blocks: ["p3-b1"] }],
    ...more,
  };
}

export function rulesOf(more: Partial<Rules> = {}): Rules {
  return {
    editable: true,
    closed: null,
    rules: [ruleOf()],
    targets: [
      { id: "s1", kind: "specification", label: "Physik" },
      { id: "n1", kind: "node", label: "LF 1 Optik" },
      { id: "n2", kind: "node", label: "LF 2 Mechanik" },
    ],
    units: RULE_UNITS,
    requirement_kinds: REQUIREMENT_KINDS,
    ...more,
  };
}
