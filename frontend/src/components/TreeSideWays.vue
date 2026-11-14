<script setup lang="ts">
/**
 * The top of a document tree page's side (DocumentTreeView.vue): the way back to the row chosen, while one is, and
 * on to the source (treeJumps.ts), and why the row was not reached (`note`).
 */
import { t } from "@/i18n/de";

defineProps<{ chosen: boolean; note: string }>();
const emit = defineEmits<{ row: []; source: [] }>();
</script>

<template>
  <div class="tree-side-ways">
    <p class="tree-side-ways__buttons">
      <button v-if="chosen" type="button" class="btn link" @click="emit('row')">
        {{ t("documents.tree.jump.toRow") }}
      </button>
      <button type="button" class="btn link" @click="emit('source')">{{ t("documents.tree.jump.toSource") }}</button>
    </p>
    <!-- always in the page, so its first words are read out -->
    <p class="tree-side-ways__note" role="status" data-test="jump-status">{{ note }}</p>
  </div>
</template>

<style scoped>
.tree-side-ways__buttons {
  display: flex;
  flex-wrap: wrap;
  gap: var(--space-1) var(--space-3);
}

.tree-side-ways p {
  margin: 0;
}

/* Empty, it takes no room, but stays in the page, so its first words are read out. */
.tree-side-ways__note:empty {
  position: absolute;
}
</style>
