// The ways between a document tree's row chosen, its panel and the source (DocumentTreeView.vue, UI review M1): a
// long tree puts the panel and the source far from the row, narrow one under the other. The tree keeps its one tab
// stop and its keys; these move the keyboard alone. A row the status filter hides is said, not reached; the words go
// with the row chosen.
import { ref, watch, type Ref } from "vue";

import type { RowKey } from "@/documentTree";
import { t } from "@/i18n/de";
import { sayAnew } from "@/liveRegion";

interface Focusable {
  focus: () => void;
}

export interface TreeJumpTargets {
  selected: Ref<RowKey | null>;
  /** focusRow says whether the row could be reached. */
  treeView: Ref<{ focusRow: (key: RowKey) => boolean } | null>;
  panel: Ref<Focusable | null>;
  source: Ref<Focusable | null>;
}

export function useTreeJumps({ selected, treeView, panel, source }: TreeJumpTargets) {
  const note = ref("");
  watch(selected, () => (note.value = ""));

  function toPanel(): void {
    panel.value?.focus();
  }

  function toRow(): void {
    if (!selected.value || !treeView.value) return;
    if (treeView.value.focusRow(selected.value)) note.value = "";
    else note.value = sayAnew(note.value, t("documents.tree.jump.rowFiltered"));
  }

  function toSource(): void {
    source.value?.focus();
  }

  return { note, toPanel, toRow, toSource };
}
