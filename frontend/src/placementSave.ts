// A node's placements in their form, saved (plan M3a K; NodePlacements.vue): the entries and where they began, the
// node as last read - its revision the token of a set -, and a save of the entries as the node's whole: problems found
// first at their fields, a set that met a change of the node kept and said to be, one the tree's closing refused kept
// to copy (`closed`), a node gone, any other failure said. The entries follow the node as the tree is read anew where
// none of them changed.
import { computed, ref, watch, type Ref } from "vue";

import { ApiError, setNodePlacements, type NodeRow } from "@/api";
import { t } from "@/i18n/de";
import { sayAnew } from "@/liveRegion";
import { failureNotice, type Notice } from "@/notice";
import { PLACEMENT_FIELDS, changed, entriesOf, placementsOf, type PlacementEntry, type PlacementField } from "@/placementDraft";
import { problemText } from "@/rowRefusals";

export type PlacementOutcome = "saved" | "unchanged" | "invalid" | "stale" | "closed" | "gone" | "failed";

// a refusal that closes the tree to the change: said where the form stood, the draft kept to copy
const CLOSING: ReadonlySet<string> = new Set(["frozen", "job_open", "not_extracted"]);
const AT = /^placements\[(\d+)\](?:\.(\w+))?$/;

export function usePlacementSave(node: Ref<NodeRow | null>) {
  const base = ref<NodeRow | null>(node.value);
  const start = ref<PlacementEntry[]>(entriesOf(node.value?.placements ?? []));
  const entries = ref<PlacementEntry[]>(entriesOf(node.value?.placements ?? []));
  const saving = ref(false);
  const failure = ref<Notice | null>(null);
  const closed = ref<string | null>(null);
  const dirty = computed(() => changed(entries.value, start.value));

  watch(node, (now) => {
    if (!now || dirty.value) return;
    base.value = now;
    start.value = entriesOf(now.placements);
    entries.value = entriesOf(now.placements);
  });

  /** Save the entries; how it went, the problems at their fields (`<entry key>:<field>`), the node as stored. */
  async function save(): Promise<{ outcome: PlacementOutcome; faults?: [string, string][]; answer?: NodeRow }> {
    failure.value = null;
    const [set, problems] = placementsOf(entries.value);
    if (problems.length) return { outcome: "invalid", faults: problems };
    if (!dirty.value || !base.value) return { outcome: "unchanged" };
    saving.value = true;
    try {
      const answer = await setNodePlacements(base.value.id, base.value.revision, set);
      base.value = answer;
      start.value = entriesOf(answer.placements);
      entries.value = entriesOf(answer.placements);
      return { outcome: "saved", answer };
    } catch (error) {
      return refused(error);
    } finally {
      saving.value = false;
    }
  }

  function refused(error: unknown): { outcome: PlacementOutcome; faults?: [string, string][] } {
    const code = error instanceof ApiError ? error.code : undefined;
    const details = error instanceof ApiError ? error.details : {};
    const at = typeof details.field === "string" ? AT.exec(details.field) : null;
    const entry = at ? entries.value[Number(at[1])] : undefined;
    if (code === "invalid_field" && entry) {
      // a placement refused as a whole (an id none of the node's) at its first field
      const named = at?.[2] ?? "";
      const field: PlacementField = PLACEMENT_FIELDS.includes(named as PlacementField) ? (named as PlacementField) : "specification_id";
      return { outcome: "invalid", faults: [[`${entry.key}:${field}`, problemText(details.problem)]] };
    }
    if (code === "stale_revision" && typeof details.current === "object" && details.current !== null) {
      base.value = details.current as NodeRow;
      failure.value = { text: sayAnew(failure.value?.text ?? "", t("documents.tree.placements.changedMeanwhile")), failed: true };
      return { outcome: "stale" };
    }
    if (code && CLOSING.has(code)) {
      closed.value = code;
      return { outcome: "closed" };
    }
    if (code === "no_node") return { outcome: "gone" };
    failure.value = failureNotice(error, t("documents.tree.placements.saveFailed"));
    return { outcome: "failed" };
  }

  return { entries, saving, failure, closed, dirty, save };
}
