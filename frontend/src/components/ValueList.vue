<script setup lang="ts">
/**
 * A row's levels, time spans and workloads as they read (plan M3a G; valueWords.shownValues): each in words under
 * its kind, with who stated it and how far it is reviewed, "noch nichts erfasst" where none is; the editors set a
 * value's review status beside it (ReviewToggles), told by a function with the row's key.
 */
import { computed } from "vue";

import type { ValueKind } from "@/api";
import ReviewToggles from "@/components/ReviewToggles.vue";
import type { Row, RowKey } from "@/documentTree";
import { t } from "@/i18n/de";
import type { ReviewOutcome } from "@/rowReview";
import type { ShownValue } from "@/valueWords";

const props = defineProps<{
  row: Row;
  /** The values of each kind the holder is offered, in their order. */
  shown: Map<ValueKind, ShownValue[]>;
  reviewable: boolean;
  documentId: string;
  /** How a value's review went, with the row's key and the value's words. */
  onReviewed?: (done: Exclude<ReviewOutcome, { outcome: "failed" }>, key: RowKey, value: string) => void;
}>();

const kinds = computed(() => [...props.shown].filter(([, values]) => values.length));
</script>

<template>
  <p v-if="!kinds.length" class="value-list__none">{{ t("documents.tree.values.none") }}</p>
  <dl v-else class="value-list">
    <template v-for="[kind, values] in kinds" :key="kind">
      <dt>{{ t(`documents.tree.values.kinds.${kind}`) }}</dt>
      <dd v-for="value in values" :key="value.id">
        <span class="value-list__words"><bdi>{{ value.words }}</bdi></span>
        <span class="value-list__stated">{{ value.stated }}</span>
        <ReviewToggles
          v-if="reviewable"
          :row="row"
          :value="value.review"
          :label="t('documents.tree.values.reviewLabel', { value: value.words })"
          :document-id="documentId"
          :on-reviewed="(done, key) => onReviewed?.(done, key, value.words)"
        />
      </dd>
    </template>
  </dl>
</template>

<style scoped>
.value-list {
  display: grid;
  gap: var(--space-0);
  margin: 0;
}

.value-list dt {
  font-weight: 600;
}

.value-list dd {
  display: grid;
  gap: var(--space-0);
  margin: 0 0 var(--space-1);
}

.value-list__none {
  margin: 0;
}

.value-list__stated,
.value-list__none {
  color: var(--text-muted);
}

/* A level's label or a long value breaks anywhere rather than widen the panel (SC 1.4.10). */
.value-list__words {
  overflow-wrap: anywhere;
}
</style>
