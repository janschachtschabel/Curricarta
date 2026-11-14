<script setup lang="ts">
/**
 * The top of a document tree page's side (DocumentTreeView.vue): the way back to the row chosen, while one is, and
 * on to the source (treeJumps.ts).
 */
import { t } from "@/i18n/de";

defineProps<{ chosen: boolean }>();
const emit = defineEmits<{ row: []; source: [] }>();
</script>

<template>
  <p class="tree-side-ways">
    <button v-if="chosen" type="button" class="btn link" @click="emit('row')">
      {{ t("documents.tree.jump.toRow") }}
    </button>
    <button type="button" class="btn link" @click="emit('source')">{{ t("documents.tree.jump.toSource") }}</button>
  </p>
</template>

<style scoped>
.tree-side-ways {
  display: flex;
  flex-wrap: wrap;
  gap: var(--space-1) var(--space-3);
  margin: 0;
}
</style>
