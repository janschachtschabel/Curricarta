<script setup lang="ts">
/**
 * A node's placements as they read (plan M3a K; NodePlacements.vue): each in words - where it is, at which node, how
 * binding, its weight - with who stated it and how far it is reviewed; where there is none, that it is placed nowhere
 * yet, or that the document names no specification to place it in.
 */
import type { Form, Placement, Tree } from "@/api";
import { t } from "@/i18n/de";
import { placementStated, placementWords } from "@/placementDraft";

defineProps<{ placements: readonly Placement[]; tree: Tree; form: Form }>();
</script>

<template>
  <p v-if="!placements.length" class="node-placements__none">
    {{ tree.specifications.length ? t("documents.tree.placements.none") : t("documents.tree.placements.noPlaces") }}
  </p>
  <ul v-else class="node-placements__list">
    <li v-for="placement in placements" :key="placement.id">
      <span class="node-placements__words"><bdi>{{ placementWords(placement, tree.specifications, tree.nodes, form) }}</bdi></span>
      <span class="node-placements__stated">{{ placementStated(placement) }}</span>
    </li>
  </ul>
</template>

<style scoped>
.node-placements__none,
.node-placements__stated {
  color: var(--text-muted);
}

.node-placements__none {
  margin: 0;
}

.node-placements__list {
  display: grid;
  gap: var(--space-1);
  margin: 0;
  padding-inline-start: var(--space-3);
}

.node-placements__list li {
  overflow-wrap: anywhere;
}

.node-placements__words {
  display: block;
}
</style>
