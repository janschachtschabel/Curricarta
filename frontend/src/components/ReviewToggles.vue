<script setup lang="ts">
/**
 * The review status of the row chosen, to set (plan M1 9.8, Paket 9c2c M2, M3; rowReview.ts): the editors' alone,
 * where the tree is open - which the panel decides. The three statuses as toggles in a group named for it, the
 * row's own pressed and ticked, not by colour alone, and asking nothing; another sets it for this row. While it
 * sets one nothing more is asked; set, it shows pressed, and another is set at the revision it left, until the row
 * is read again, which then says how it stands. How it went is told by a function (`onReviewed`) with the row's
 * key - heard even where another row was chosen meanwhile -, a failure said here, where it was asked. Given a value
 * of the row (plan M3a G), they set the value's, in a group named for it (`label`) - a specification's too, whose
 * own status these never set (plan M3a H).
 */
import { computed, ref, useId, watch } from "vue";

import AppIcon from "@/components/AppIcon.vue";
import NoticeText from "@/components/NoticeText.vue";
import { t } from "@/i18n/de";
import type { Notice } from "@/notice";
import { reviewRow, reviewValue, rowStatus, type ReviewedValue, type ReviewOutcome } from "@/rowReview";
import { REVIEW_STATUSES, statusIri, statusOf, statusWord, type ReviewStatus } from "@/reviewStatus";
import type { HolderKey, HolderRow } from "@/valueHolder";

const props = defineProps<{
  row: HolderRow;
  documentId: string;
  /** A value of the row, whose status these set rather than the row's. */
  value?: ReviewedValue | null;
  /** The group's name, where it is not the row's status. */
  label?: string;
  /** How setting it went. A prop, not an event: these toggles go with the row chosen. */
  onReviewed?: (done: Exclude<ReviewOutcome, { outcome: "failed" }>, key: HolderKey) => void;
}>();

const labelId = useId();
const busy = ref(false);
const problem = ref<Notice | null>(null);
// the status just set and the revision it left: the row the panel holds has them only once the tree is read again
const pending = ref<{ status: ReviewStatus; revision: number } | null>(null);
// the row whose own status these set: none of a specification's
const own = computed(() => (props.value || props.row.kind === "specification" ? null : props.row));
const current = computed(
  () => pending.value?.status ?? (props.value ? statusOf(props.value.review_status) : own.value && rowStatus(own.value)),
);
watch(
  () => [props.row, props.value],
  () => (pending.value = null),
);

async function choose(status: ReviewStatus): Promise<void> {
  if (busy.value || status === current.value || (!props.value && !own.value)) return;
  const { key } = props.row;
  busy.value = true;
  problem.value = null;
  const revision = pending.value?.revision;
  const done = own.value
    ? await reviewRow(props.documentId, own.value, status, revision)
    : await reviewValue(props.documentId, props.value as ReviewedValue, status, revision);
  busy.value = false;
  if (done.outcome === "set") pending.value = { status: done.status, revision: done.revision };
  if (done.outcome === "failed") problem.value = done.problem;
  else props.onReviewed?.(done, key);
}
</script>

<template>
  <div class="review-toggles" role="group" :aria-labelledby="labelId">
    <span :id="labelId" class="review-toggles__label">{{ label ?? t("documents.tree.review.label") }}</span>
    <!-- aria-disabled, not disabled: a toggle keeps the keyboard while the status is set -->
    <button
      v-for="status in REVIEW_STATUSES"
      :key="status"
      type="button"
      class="btn btn-sm secondary"
      :aria-pressed="current === status ? 'true' : 'false'"
      :aria-disabled="busy || undefined"
      @click="choose(status)"
    >
      <!-- its room kept while off, so the row of toggles does not shift -->
      <span class="review-toggles__tick" aria-hidden="true"><AppIcon v-if="current === status" name="check" /></span>
      {{ statusWord(statusIri(status)) }}
    </button>
    <p v-if="problem" class="field__error review-toggles__problem" role="alert">
      <AppIcon name="warning" /> <NoticeText :notice="problem" />
    </p>
  </div>
</template>

<style scoped>
.review-toggles {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: var(--space-1);
}

.review-toggles__label {
  font-weight: 600;
}

.review-toggles__tick {
  display: inline-flex;
  inline-size: 1em;
}

.review-toggles__problem {
  flex-basis: 100%;
  margin: 0;
}
</style>
