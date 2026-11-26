<script setup lang="ts">
/**
 * Beside a stored value - or a specification's applicability context - in its form (plan M3a G, H): who stated it
 * and how far it is reviewed, and to the editors the toggles that set its review status (ReviewToggles), in a
 * group named for it. How a review went is told by a function with the holder's key and the value's words. Nothing
 * for a value not yet stored.
 */
import ReviewToggles from "@/components/ReviewToggles.vue";
import { t } from "@/i18n/de";
import type { ReviewOutcome } from "@/rowReview";
import type { HolderKey, HolderRow } from "@/valueHolder";
import type { ShownValue } from "@/valueWords";

defineProps<{
  row: HolderRow;
  value?: ShownValue;
  reviewable: boolean;
  documentId: string;
  onReviewed?: (done: Exclude<ReviewOutcome, { outcome: "failed" }>, key: HolderKey, value: string) => void;
}>();
</script>

<template>
  <template v-if="value">
    <p class="stored-value">{{ value.stated }}</p>
    <ReviewToggles
      v-if="reviewable"
      :row="row"
      :value="value.review"
      :label="t('documents.tree.values.reviewLabel', { value: value.words })"
      :document-id="documentId"
      :on-reviewed="(done, key) => onReviewed?.(done, key, value?.words ?? '')"
    />
  </template>
</template>

<style scoped>
.stored-value {
  margin: 0;
  color: var(--text-muted);
}
</style>
