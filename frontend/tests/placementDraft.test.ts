import { describe, expect, it } from "vitest";

import type { Placement, Tree } from "@/api";
import { t } from "@/i18n/de";
import {
  changed,
  entriesOf,
  inSpecification,
  newEntry,
  obligationChoices,
  placeChoices,
  placementName,
  placementsOf,
  placementWords,
  variantChoices,
} from "@/placementDraft";

import { CV, field, form_, node_, noValues, value_ } from "./treeFixtures";

const BINDING = CV + "obl_binding";
const SPECIFICATIONS: Tree["specifications"] = [
  { id: "ba", title: "Bachelor", variants: [{ id: "v1", label: "Statistik" }] },
  { id: "ma", title: "Master", variants: [{ id: "v2", label: "Algebra" }] },
];
const NODES = [
  node_("m1", { fields: { original_title: "Analysis", code: "M 1" } }),
  node_("b1", { position: 2, fields: { original_title: "Pflichtbereich", code: "B" }, children: [node_("c1", { fields: { original_title: null, code: null } })] }),
];

function placement(changes: Partial<Placement> = {}): Placement {
  return {
    id: "p1", node_id: "m1", position: 1, specification_id: "ba", variant_id: null, in_node_id: null, obligation: BINDING,
    grade_weight: 1.5, iri: null, origin: CV + "orig_human", review_status: CV + "rev_proposed", revision: 1, values: noValues(),
    ...changes,
  };
}

function obligations() {
  const form = form_();
  form.node.push(field("obligation", "concept", [value_(BINDING, "verbindlich")]));
  return form;
}

describe("a node's placements as entries", () => {
  it("write a stored placement the German way and send it back as it was", () => {
    const [entry] = entriesOf([placement()]);

    expect(entry?.grade_weight).toBe("1,5");
    const [set, problems] = placementsOf(entry ? [entry] : []);
    expect(problems).toEqual([]);
    expect(set).toEqual([{ id: "p1", specification_id: "ba", variant_id: null, in_node_id: null, obligation: BINDING, grade_weight: 1.5 }]);
  });

  it("name what the server would refuse at the entry's fields", () => {
    const entry = { ...newEntry(SPECIFICATIONS), grade_weight: "viel" };

    const [, problems] = placementsOf([entry]);

    expect(problems).toEqual([
      [`${entry.key}:specification_id`, t("documents.tree.placements.problems.nowhere")],
      [`${entry.key}:obligation`, t("documents.tree.problems.required")],
      [`${entry.key}:grade_weight`, t("documents.tree.values.problems.not_number")],
    ]);
  });

  it("begin a new one in the document's one specification, where it has one alone", () => {
    expect(newEntry(SPECIFICATIONS.slice(1)).specification_id).toBe("ma");
    expect(newEntry(SPECIFICATIONS).specification_id).toBe("");
  });

  it("differ from where they began by a field or by their order, never by their keys", () => {
    const start = entriesOf([placement(), placement({ id: "p2", position: 2 })]);

    expect(changed(entriesOf([placement(), placement({ id: "p2", position: 2 })]), start)).toBe(false);
    expect(changed([...start].reverse(), start)).toBe(true);
    expect(changed([{ ...start[0], obligation: "" }, start[1]], start)).toBe(true);
  });
});

describe("what an entry may name", () => {
  it("offers the chosen specification's variants, every one's named with it where none is chosen", () => {
    expect(variantChoices(SPECIFICATIONS, "ma").map((one) => one.label)).toEqual(["Master – Algebra"]);
    expect(variantChoices(SPECIFICATIONS, "").map((one) => one.id)).toEqual(["v1", "v2"]);
  });

  it("lets go of a variant another specification does not hold", () => {
    const [entry] = entriesOf([placement({ variant_id: "v1" })]);
    if (!entry) throw new Error("no entry");

    expect(inSpecification(entry, "ma", SPECIFICATIONS).variant_id).toBe("");
    expect(inSpecification(entry, "ba", SPECIFICATIONS).variant_id).toBe("v1");
  });

  it("offers every node of the outline but the placed one, by its path", () => {
    expect(placeChoices(NODES, "m1").map((one) => one.label)).toEqual(["B Pflichtbereich", "B Pflichtbereich › ohne Titel (Stelle 1)"]);
  });

  it("keeps an obligation the list no longer offers, said so", () => {
    const offered = obligationChoices(obligations(), [BINDING, CV + "obl_gone"]);

    expect(offered).toEqual([
      { id: BINDING, label: "verbindlich" },
      { id: CV + "obl_gone", label: t("documents.tree.placements.retired", { value: "obl_gone" }) },
    ]);
  });
});

describe("a placement in words", () => {
  it("says where it is, at which node, how binding and its weight; its values by its place", () => {
    const at = placement({ in_node_id: "b1", variant_id: "v1" });

    expect(placementWords(at, SPECIFICATIONS, NODES, obligations())).toBe("Bachelor – Statistik · an B Pflichtbereich · verbindlich · Notengewicht 1,5");
    expect(placementName({ ...at, position: 2 }, SPECIFICATIONS, NODES)).toBe("Verwendung 2: Bachelor – Statistik · an B Pflichtbereich");
  });
});
