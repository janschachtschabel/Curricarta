<script setup lang="ts">
/**
 * A document's assessments, on its page (plan M3a J; backend GET /documents/{id}/assessments): each with its parts
 * under it (AssessmentItem), what it states in words by the labels its list and the values' form give. The
 * document's owner and the editors add one, edit one, add a part of one and take one away with its parts while the
 * document is open - one form at a time (AssessmentForm), a taking away asked first -, and set the levels at one as a
 * whole (ValueSection); saved, added, taken away, the list is read again, and the keyboard, where nothing holds it,
 * goes to the section's heading. A draft of levels the document closed under stays, in words, to copy; a draft open in
 * a form the section tells the page (`dirty`, its leave guard). Closed, or another's, the section says why it is to
 * read only. Read as sectionReading.ts reads: loading, a failure with a retry, content no longer the reader's said
 * apart; read again as the page's extraction moves on (`refresh`).
 */
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from "vue";

import { ApiError, dropAssessment, getAssessments, getForm, type Assessment, type Assessments, type Form } from "@/api";
import AssessmentForm from "@/components/AssessmentForm.vue";
import AssessmentItem from "@/components/AssessmentItem.vue";
import ConfirmDialog from "@/components/ConfirmDialog.vue";
import EmptyState from "@/components/EmptyState.vue";
import ErrorState from "@/components/ErrorState.vue";
import LoadingState from "@/components/LoadingState.vue";
import PartialState from "@/components/PartialState.vue";
import { assessmentTitle, kindLabels, namesOf, partsOf, subtreeOf, type ItemActions } from "@/assessmentWords";
import { focusIsFree } from "@/focusRescue";
import { t } from "@/i18n/de";
import { sayAnew } from "@/liveRegion";
import { failureNotice, type Notice } from "@/notice";
import { refusalText } from "@/refusals";
import { labelsOf } from "@/scopeWords";
import { useSectionReading } from "@/sectionReading";

// `refresh`: bumped by the page as the extraction moves on, which may write the outline the assessments hang at
const props = defineProps<{ documentId: string; sector: string; refresh?: number }>();
const emit = defineEmits<{ dirty: [open: boolean] }>();

const heading = ref<HTMLElement | null>(null);
// the values' form names the levels; without it the section still shows what the assessments say
const read = async (): Promise<[Assessments, Form | null]> =>
  Promise.all([getAssessments(props.documentId), getForm(props.sector).catch(() => null)]);
const { shown, failure, hidden, load, retry } = useSectionReading(read, t("documents.page.assessments.loadFailed"), heading);

const opened = ref<{ mode: "add" | "edit" | "part"; id: string | null } | null>(null);
// the forms holding a draft: `form`, and `values:<id>` - a values' form stays where the document closes under it
const drafting = ref<ReadonlySet<string>>(new Set());
const dropping = ref<Assessment | null>(null);
const dropFailure = ref<Notice | null>(null);
const status = ref("");

const listed = computed(() => shown.value?.[0] ?? null);
const form = computed(() => shown.value?.[1] ?? null);
const parts = computed(() => partsOf(listed.value?.assessments ?? []));
const tops = computed(() => parts.value.get("") ?? []);
const names = computed(() => (listed.value ? namesOf(listed.value) : new Map<string, string>()));
const kinds = computed(() => (listed.value ? kindLabels(listed.value) : new Map<string, string>()));
const levels = computed(() => labelsOf(form.value));
const editable = computed(() => !!listed.value?.editable);
// to who may edit them: the values' form did not come, so their levels cannot be edited now - said, with a retry
const formMissing = computed(() => {
  const some = editable.value && tops.value.length > 0;
  return some && form.value === null ? { text: t("documents.page.assessments.formFailed") } : null;
});
const readOnly = computed(() => {
  const found = listed.value;
  if (!found || found.editable) return null;
  return found.closed ? t(`documents.page.assessments.closed.${found.closed}`) : t("documents.page.assessments.readOnly");
});
const dropMessage = computed(() => {
  const one = dropping.value;
  if (!one) return "";
  const count = subtreeOf(one.id, parts.value).size - 1;
  return t("documents.page.assessments.dropMessage", { title: assessmentTitle(one), parts: count });
});

function draft(key: string, open: boolean): void {
  const now = new Set(drafting.value);
  if (open) now.add(key);
  else now.delete(key);
  drafting.value = now;
}

function say(words: string): void {
  status.value = sayAnew(status.value, words);
}

/** Read again; the keyboard, where nothing holds it - a form or a dialog went -, to the section's heading. */
async function reload(): Promise<void> {
  await load();
  await nextTick();
  if (focusIsFree()) heading.value?.focus();
}

function close(): void {
  opened.value = null;
  draft("form", false);
}

const actions: ItemActions = {
  open: (mode, id) => {
    opened.value = { mode, id };
  },
  drop: (assessment) => {
    dropFailure.value = null;
    dropping.value = assessment;
  },
  saved: (_assessment, added) => {
    close();
    say(t(added ? "documents.page.assessments.added" : "documents.page.assessments.saved"));
    void reload();
  },
  changed: () => void load(),
  cancel: () => close(),
  dirty: draft,
  valuesSaved: () => void load(),
  gone: () => {
    say(t("documents.page.assessments.gone"));
    void load();
  },
};

async function confirmDrop(): Promise<void> {
  const one = dropping.value;
  if (!one) return;
  try {
    await dropAssessment(one.id, one.revision);
    dropping.value = null;
    say(t("documents.page.assessments.dropped", { title: assessmentTitle(one) }));
  } catch (error) {
    dropping.value = null;
    const code = error instanceof ApiError ? error.code : undefined;
    const words = code === "stale_revision" ? t("documents.page.assessments.changedMeanwhile") : refusalText(code);
    dropFailure.value = words ? { text: words, failed: true } : failureNotice(error, t("documents.page.assessments.dropFailed"));
  }
  await reload();
}

watch(
  () => drafting.value.size > 0,
  (open) => emit("dirty", open),
);
onBeforeUnmount(() => emit("dirty", false));
onMounted(load);
watch(() => props.refresh, () => void load());
</script>

<template>
  <section class="assessments" aria-labelledby="document-assessments">
    <!-- tabindex -1: where the keyboard goes once a form, a dialog or a retry's button went -->
    <h2 id="document-assessments" ref="heading" tabindex="-1">{{ t("documents.page.assessments.heading") }}</h2>
    <p class="assessments__note">{{ t("documents.page.assessments.intro") }}</p>
    <template v-if="listed === null">
      <EmptyState v-if="hidden" :level="3" :title="t('conversionPage.hiddenTitle')" :body="t('refusals.file_hidden')" />
      <ErrorState v-else-if="failure" :message="failure.text" :reason="failure.reason" :explanation="failure.explanation"
        @retry="retry()" />
      <LoadingState v-else :label="t('documents.page.assessments.loading')" />
    </template>
    <template v-else>
      <p v-if="readOnly" class="assessments__note" data-test="assessments-read-only">{{ readOnly }}</p>
      <EmptyState v-if="!tops.length" :level="3" :title="t('documents.page.assessments.noneTitle')"
        :body="editable ? t('documents.page.assessments.noneBodyEditable') : t('documents.page.assessments.noneBody')" />
      <ul v-else class="assessments__list">
        <AssessmentItem v-for="assessment in tops" :key="assessment.id" :assessment="assessment" :read="listed" :parts="parts"
          :names="names" :kinds="kinds" :levels="levels" :form="form" :document-id="documentId" :editable="editable"
          :opened="opened" :drafting="drafting" :closed-by="listed.closed" :actions="actions" />
      </ul>
      <template v-if="editable">
        <AssessmentForm v-if="opened?.mode === 'add'" :document-id="documentId" :read="listed"
          @saved="(saved) => actions.saved(saved, true)" @changed="actions.changed()" @cancel="close()"
          @dirty="(open) => draft('form', open)" />
        <button v-else-if="opened === null" type="button" class="btn secondary assessments__add" @click="opened = { mode: 'add', id: null }">
          {{ t("documents.page.assessments.add") }}
        </button>
      </template>
    </template>
    <!-- always in the page, so the first word is read out -->
    <p class="assessments__status" role="status">{{ status }}</p>
    <!-- in the page from the start, so its first word is heard -->
    <PartialState :notice="formMissing" :retry="true" @retry="retry()" />
    <PartialState :notice="dropFailure" />
    <!-- in the page from the start, so a failure of a later reading is heard -->
    <PartialState :notice="listed !== null ? failure : null" :retry="!hidden" @retry="retry()" />
    <ConfirmDialog v-if="dropping" :title="t('documents.page.assessments.dropTitle')" :message="dropMessage"
      :confirm-label="t('documents.page.assessments.dropConfirm')" @confirm="confirmDrop" @cancel="dropping = null" />
  </section>
</template>

<style scoped>
.assessments {
  display: grid;
  gap: var(--space-3);
  align-content: start;
}

.assessments h2,
.assessments__note,
.assessments__status {
  margin: 0;
}

/* Empty, it takes no room - as a cell of the grid its gap would stand twice - but stays in the page. */
.assessments__status:empty {
  position: absolute;
}

.assessments__note {
  max-width: var(--reading-width);
  color: var(--text-muted);
}

.assessments__list {
  display: grid;
  gap: var(--space-4);
  margin: 0;
  padding: 0;
  list-style: none;
}

.assessments__add {
  justify-self: start;
}
</style>
