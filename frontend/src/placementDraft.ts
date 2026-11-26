// A node's placements as their form writes them (plan M3a K; NodePlacements.vue): each entry's specification, variant,
// the node it is at, its obligation and its grade weight written the German way (valueNumbers.ts), as the server
// takes them with the problems it would refuse; whether the entries differ from where they began; what an entry may
// name - the document's specifications and their variants, the outline's nodes but the placed one, the obligations
// the node's form offers - and a placement in words.
import type { Form, Placement, PlacementIn, TreeNode, TreeSpecification } from "@/api";
import { messages, t } from "@/i18n/de";
import { conceptWord } from "@/registerWords";
import { CV, statusWord } from "@/reviewStatus";
import { numberOf, written } from "@/valueNumbers";

export type PlacementField = "specification_id" | "variant_id" | "in_node_id" | "obligation" | "grade_weight";
export const PLACEMENT_FIELDS: readonly PlacementField[] = ["specification_id", "variant_id", "in_node_id", "obligation", "grade_weight"];
export const MOST_PLACEMENTS = 50; // of one node, as the server takes them (backend app/domain/placements.py)

/** One placement's entry: its fields as written, `id` the placement it keeps (none for a new one), `key` its own. */
export interface PlacementEntry {
  key: string;
  id: string | null;
  specification_id: string;
  variant_id: string;
  in_node_id: string;
  obligation: string;
  grade_weight: string;
}

/** What a placement says of where it is: what its words are made of. */
export type PlacementPlace = Pick<Placement, "specification_id" | "variant_id" | "in_node_id" | "obligation" | "grade_weight">;

export interface Choice {
  id: string;
  label: string;
}

let made = 0;

/** A new entry's key: its fields' ids and its problems' places stand by it. */
export function entryKey(): string {
  made += 1;
  return `placement-${made}`;
}

/** The entries of the node's placements, in their order. */
export function entriesOf(placements: readonly Placement[]): PlacementEntry[] {
  return placements.map((placement) => ({
    key: entryKey(),
    id: placement.id,
    specification_id: placement.specification_id ?? "",
    variant_id: placement.variant_id ?? "",
    in_node_id: placement.in_node_id ?? "",
    obligation: placement.obligation,
    grade_weight: written(placement.grade_weight),
  }));
}

/** A new entry: in the document's one specification where it has one alone. */
export function newEntry(specifications: readonly TreeSpecification[]): PlacementEntry {
  const [only] = specifications.length === 1 ? specifications : [];
  return { key: entryKey(), id: null, specification_id: only?.id ?? "", variant_id: "", in_node_id: "", obligation: "", grade_weight: "" };
}

/** Whether the entries say other than those `start` began as: their fields and their order. */
export function changed(entries: readonly PlacementEntry[], start: readonly PlacementEntry[]): boolean {
  const said = (list: readonly PlacementEntry[]) => JSON.stringify(list.map(({ key, ...fields }) => (void key, fields)));
  return said(entries) !== said(start);
}

/** The entries as the server takes them; the problems of their fields, by entry key, where it would refuse them. */
export function placementsOf(entries: readonly PlacementEntry[]): [PlacementIn[], [string, string][]] {
  const problems: [string, string][] = [];
  const set = entries.map((entry) => {
    if (!entry.specification_id && !entry.variant_id) {
      problems.push([`${entry.key}:specification_id`, t("documents.tree.placements.problems.nowhere")]);
    }
    if (!entry.obligation) problems.push([`${entry.key}:obligation`, t("documents.tree.problems.required")]);
    const weight = entry.grade_weight.trim() ? numberOf(entry.grade_weight) : null;
    if (entry.grade_weight.trim() && weight === null) {
      problems.push([`${entry.key}:grade_weight`, t("documents.tree.values.problems.not_number")]);
    }
    return {
      id: entry.id,
      specification_id: entry.specification_id || null,
      variant_id: entry.variant_id || null,
      in_node_id: entry.in_node_id || null,
      obligation: entry.obligation,
      grade_weight: weight,
    };
  });
  return [set, problems];
}

/** The document's specifications, by title. */
export function specificationChoices(specifications: readonly TreeSpecification[]): Choice[] {
  return specifications.map((one) => ({ id: one.id, label: one.title }));
}

/** The variants an entry may name: those of its specification, else every specification's, named with it. */
export function variantChoices(specifications: readonly TreeSpecification[], specificationId: string): Choice[] {
  return specifications
    .filter((one) => !specificationId || one.id === specificationId)
    .flatMap((one) => one.variants.map((variant) => ({ id: variant.id, label: t("documents.tree.placements.variantOf", { variant: variant.label, specification: one.title }) })));
}

/** The nodes of the outline a placement may be at, in the tree's order: every one but the placed node. */
export function placeChoices(nodes: readonly TreeNode[], placed: string): Choice[] {
  const found: Choice[] = [];
  // each by its path in the outline: its depth seen, an untitled one told apart by its position
  const walk = (level: readonly TreeNode[], above: readonly string[]): void => {
    for (const node of level) {
      const path = [...above, nodeLabel(node)];
      if (node.id !== placed) found.push({ id: node.id, label: path.join(" › ") });
      walk(node.children, path);
    }
  };
  walk(nodes, []);
  return found;
}

/** The entry with its specification `specificationId`: a variant that specification does not hold let go. */
export function inSpecification(entry: PlacementEntry, specificationId: string, specifications: readonly TreeSpecification[]): PlacementEntry {
  const held = variantChoices(specifications, specificationId).some((one) => one.id === entry.variant_id);
  return { ...entry, specification_id: specificationId, variant_id: held ? entry.variant_id : "" };
}

/** What a placement's values are named by: its place among the node's and where it is, at which node. */
export function placementName(
  placement: PlacementPlace & { position: number },
  specifications: readonly TreeSpecification[],
  nodes: readonly TreeNode[],
): string {
  const at = placement.in_node_id ? findNode(nodes, placement.in_node_id) : undefined;
  const where = [placementTitle(placement, specifications), ...(at ? [t("documents.tree.placements.at", { node: nodeLabel(at) })] : [])];
  return t("documents.tree.placements.named", { place: placement.position, where: where.join(" · ") });
}

/** The obligations the node's form offers; one an entry keeps though the list offers it no more, said so. */
export function obligationChoices(form: Form, kept: readonly string[]): Choice[] {
  const offered = (form.node.find((field) => field.key === "obligation")?.values ?? []).map((value) => ({ id: value.iri, label: value.label }));
  const retired = kept.filter((iri) => iri && !offered.some((one) => one.id === iri));
  return [...offered, ...retired.map((iri) => ({ id: iri, label: t("documents.tree.placements.retired", { value: localName(iri) }) }))];
}

/** A placement in words: where it is, at which node, how binding, with what weight. */
export function placementWords(placement: PlacementPlace, specifications: readonly TreeSpecification[], nodes: readonly TreeNode[], form: Form): string {
  const where = placementTitle(placement, specifications);
  const at = placement.in_node_id ? findNode(nodes, placement.in_node_id) : undefined;
  const obligation = obligationChoices(form, [placement.obligation]).find((one) => one.id === placement.obligation)?.label ?? placement.obligation;
  const parts = [where];
  if (at) parts.push(t("documents.tree.placements.at", { node: nodeLabel(at) }));
  parts.push(obligation);
  if (placement.grade_weight !== null) parts.push(t("documents.tree.placements.weight", { weight: written(placement.grade_weight) }));
  return parts.join(" · ");
}

/** Where a placement is: its specification's title, its variant named with it. */
export function placementTitle(placement: PlacementPlace, specifications: readonly TreeSpecification[]): string {
  const specification = specifications.find((one) => one.id === placement.specification_id);
  for (const one of specifications) {
    const variant = one.variants.find((each) => each.id === placement.variant_id);
    if (variant) return t("documents.tree.placements.variantOf", { variant: variant.label, specification: one.title });
  }
  return specification?.title ?? t("documents.tree.placements.unknownPlace");
}

/** An entry in words, as it would be stored: what a closed form keeps to copy. */
export function entryPlace(entry: PlacementEntry): PlacementPlace {
  return {
    specification_id: entry.specification_id || null,
    variant_id: entry.variant_id || null,
    in_node_id: entry.in_node_id || null,
    obligation: entry.obligation,
    grade_weight: numberOf(entry.grade_weight),
  };
}

/** Who stated a stored placement, and how far it is reviewed. */
export function placementStated(placement: Placement): string {
  return t("documents.tree.values.stated", {
    origin: conceptWord(messages.documents.tree.origins, `${CV}orig_`, placement.origin),
    status: statusWord(placement.review_status),
  });
}

function findNode(nodes: readonly TreeNode[], id: string): TreeNode | undefined {
  for (const node of nodes) {
    if (node.id === id) return node;
    const found = findNode(node.children, id);
    if (found) return found;
  }
  return undefined;
}

function nodeLabel(node: TreeNode): string {
  const code = node.fields.code;
  const title = node.fields.original_title;
  const words = [typeof code === "string" ? code : "", typeof title === "string" ? title : ""].filter(Boolean).join(" ");
  return words || t("documents.tree.placements.untitledAt", { position: node.position });
}

function localName(iri: string): string {
  return iri.slice(Math.max(iri.lastIndexOf("#"), iri.lastIndexOf("/")) + 1);
}
