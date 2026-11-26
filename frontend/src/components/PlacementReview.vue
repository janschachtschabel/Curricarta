<script setup lang="ts">
/**
 * Beside a stored placement in the node's form of them (plan M3a L; NodePlacements.vue): who stated it and how far it
 * is reviewed, and to the editors the toggles that set its review status (ReviewToggles), in a group named for it.
 * How a review went is told by a function with the placement's key and words that name it.
 */
import ReviewToggles from "@/components/ReviewToggles.vue";
import { t } from "@/i18n/de";
import { placementStated } from "@/placementDraft";
import { namedReviewWords, type ReviewOutcome } from "@/rowReview";
import type { HolderKey, PlacementHolderRow } from "@/valueHolder";

const props = defineProps<{
  /** The placement as a row, named by where it is. */
  row: PlacementHolderRow;
  reviewable: boolean;
  documentId: string;
  onReviewed?: (done: Exclude<ReviewOutcome, { outcome: "failed" }>, key: HolderKey, words?: string) => void;
}>();

function reviewed(done: Exclude<ReviewOutcome, { outcome: "failed" }>, key: HolderKey): void {
  const title = props.row.title;
  props.onReviewed?.(done, key, namedReviewWords(done, title, t("documents.tree.placements.reviewStale", { title })));
}
</script>

<template>
  <p class="node-placements__stated">{{ placementStated(row.placement) }}</p>
  <ReviewToggles
    v-if="reviewable"
    :row="row"
    :label="t('documents.tree.placements.reviewLabel', { title: row.title })"
    :document-id="documentId"
    :on-reviewed="reviewed"
  />
</template>

<style scoped>
.node-placements__stated {
  margin: 0;
  color: var(--text-muted);
}
</style>
