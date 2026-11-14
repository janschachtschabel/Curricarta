// The ways between a document tree's row chosen, its panel and the source (DocumentTreeView.vue, UI review M1): a
// long tree puts the panel and the source far from the row, narrow one under the other. The tree keeps its one tab
// stop and its keys; these move the keyboard alone.
import type { Ref } from "vue";

import type { RowKey } from "@/documentTree";

interface Focusable {
  focus: () => void;
}

export interface TreeJumpTargets {
  selected: Ref<RowKey | null>;
  treeView: Ref<{ focusRow: (key: RowKey) => void } | null>;
  panel: Ref<Focusable | null>;
  source: Ref<Focusable | null>;
}

export function useTreeJumps({ selected, treeView, panel, source }: TreeJumpTargets) {
  function toPanel(): void {
    panel.value?.focus();
  }

  function toRow(): void {
    if (selected.value) treeView.value?.focusRow(selected.value);
  }

  function toSource(): void {
    source.value?.focus();
  }

  return { toPanel, toRow, toSource };
}
