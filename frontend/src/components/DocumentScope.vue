<script setup lang="ts">
/**
 * What a document's specifications are and where they apply, on its page (plan M3a H1; backend
 * GET /documents/{id}/specifications): each specification with its kind, title and field, its variants (X1's, to
 * read), its own levels, time spans and workloads and its applicability contexts, each in words (scopeWords.ts) by
 * the labels of the values' form - a form that did not come leaves the last part of each IRI. The document's owner
 * and the editors set title and field while it is open (SpecificationForm), and its values and contexts as a whole
 * in the values' form (ValueSection, plan M3a join of G and H) - the editors their review status there too, the
 * holder's revision moving with it; saved or reviewed, the list is read again. A draft of its values the document
 * closed under stays, in words, to copy. Closed, or another's, the section says why it is to read only. Read as
 * sectionReading.ts reads: loading, a failure with a retry, content no longer the reader's said apart; read again
 * as the page's extraction moves on (`refresh`).
 */
import { computed, onMounted, ref, watch } from "vue";

import { getForm, getSpecifications, type Form, type Specification, type Specifications } from "@/api";
import EmptyState from "@/components/EmptyState.vue";
import ErrorState from "@/components/ErrorState.vue";
import LoadingState from "@/components/LoadingState.vue";
import PartialState from "@/components/PartialState.vue";
import SpecificationForm from "@/components/SpecificationForm.vue";
import ValueSection from "@/components/ValueSection.vue";
import { t } from "@/i18n/de";
import { sayAnew } from "@/liveRegion";
import { REVIEW_TONES, statusOf, statusWord } from "@/reviewStatus";
import { reviewWords, type ReviewOutcome } from "@/rowReview";
import { contextWords, joined, labelsOf, levelWords, spanWords, stated, workloadWords } from "@/scopeWords";
import { useSectionReading } from "@/sectionReading";
import { isEditor } from "@/session";
import { specificationRow, type Holder } from "@/valueHolder";

// `refresh`: bumped by the page as the extraction moves on, which may write the specifications (X1)
const props = defineProps<{ documentId: string; sector: string; refresh?: number }>();

const heading = ref<HTMLElement | null>(null);
// the values' form names the concepts; without it the section still shows what the specifications say
const read = async (): Promise<[Specifications, Form | null]> =>
  Promise.all([getSpecifications(props.documentId), getForm(props.sector).catch(() => null)]);
const { shown, failure, hidden, load, retry } = useSectionReading(read, t("documents.page.scope.loadFailed"), heading);
// a specification as a save gave it back, shown until a reading of the section catches up with it
const saved = ref<Record<string, Specification>>({});

// the specifications whose values' form holds a draft: it stays where the document closes under it
const drafting = ref<ReadonlySet<string>>(new Set());
const status = ref("");

const form = computed(() => shown.value?.[1] ?? null);
const labels = computed(() => labelsOf(form.value));
const scope = computed(() => shown.value?.[0] ?? null);
const specifications = computed(() =>
  (scope.value?.specifications ?? []).map((specification) => saved.value[specification.id] ?? specification),
);
// to who may edit them: their values' form did not come, so they cannot be edited now - said, with a retry
const formMissing = computed(() => {
  const editable = !!scope.value?.editable && specifications.value.length > 0;
  return editable && form.value === null ? { text: t("documents.page.scope.formFailed") } : null;
});
const readOnly = computed(() => {
  const found = scope.value;
  if (!found || found.editable) return null;
  return found.closed ? t(`documents.page.scope.closed.${found.closed}`) : t("documents.page.scope.readOnly");
});

function ownValues(specification: Specification): string[] {
  const values = specification.values;
  return [
    ...values.level_assignments.map((level) => stated(levelWords(level, labels.value), level.review_status)),
    ...values.time_spans.map((span) => stated(spanWords(span, labels.value), span.review_status)),
    ...values.workloads.map((workload) => stated(workloadWords(workload, labels.value), workload.review_status)),
  ];
}

/** The tone of a review status's badge; its word stands in it. */
function tone(reviewStatus: string): string {
  const status = statusOf(reviewStatus);
  return status ? REVIEW_TONES[status] : "neutral";
}

function keep(specification: Specification): void {
  saved.value = { ...saved.value, [specification.id]: specification };
}

// read again: a specification saved meanwhile at a later revision than the reading found stays as saved
async function reload(): Promise<void> {
  await load();
  const read = new Map((scope.value?.specifications ?? []).map((one) => [one.id, one.revision]));
  saved.value = Object.fromEntries(Object.entries(saved.value).filter(([id, kept]) => (read.get(id) ?? Infinity) < kept.revision));
}

// a specification's set answers the specification as stored: the title's form goes on from its revision at once
function valuesSaved(answer: Holder): void {
  keep(answer as Specification);
  void reload();
}

function draft(id: string, open: boolean): void {
  const now = new Set(drafting.value);
  if (open) now.add(id);
  else now.delete(id);
  drafting.value = now;
}

// a value's or context's review, in words naming it: set or changed meanwhile, the list is read again
function reviewed(done: Exclude<ReviewOutcome, { outcome: "failed" }>, _key: string, words?: string): void {
  status.value = sayAnew(status.value, words ?? reviewWords(done));
  if (done.outcome !== "refused") void reload();
}

function gone(): void {
  status.value = sayAnew(status.value, t("documents.page.scope.gone"));
  void reload();
}

onMounted(load);
watch(() => props.refresh, reload);
</script>

<template>
  <section class="scope" aria-labelledby="document-scope">
    <!-- tabindex -1: where the keyboard goes once a retry's button went with its notice -->
    <h2 id="document-scope" ref="heading" tabindex="-1">{{ t("documents.page.scope.heading") }}</h2>
    <p class="scope__note">{{ t("documents.page.scope.intro") }}</p>
    <template v-if="scope === null">
      <EmptyState v-if="hidden" :level="3" :title="t('conversionPage.hiddenTitle')" :body="t('refusals.file_hidden')" />
      <ErrorState
        v-else-if="failure"
        :message="failure.text"
        :reason="failure.reason"
        :explanation="failure.explanation"
        @retry="retry()"
      />
      <LoadingState v-else :label="t('documents.page.scope.loading')" />
    </template>
    <EmptyState
      v-else-if="!specifications.length"
      :level="3"
      :title="t('documents.page.scope.noneTitle')"
      :body="t('documents.page.scope.noneBody')"
    />
    <template v-else>
      <p v-if="readOnly" class="scope__note" data-test="scope-read-only">{{ readOnly }}</p>
      <article v-for="specification in specifications" :key="specification.id" class="scope__specification">
        <h3><bdi class="scope__title">{{ specification.title }}</bdi></h3>
        <dl class="facts">
          <dt>{{ t("documents.page.scope.kind") }}</dt>
          <dd>{{ t(`documents.page.scope.kinds.${specification.spec_kind}`) }}</dd>
          <dt>{{ t("documents.page.scope.field") }}</dt>
          <dd>
            <bdi>{{ specification.field_text || t("documents.page.scope.none") }}</bdi>
          </dd>
          <dt>{{ t("documents.page.scope.variants") }}</dt>
          <dd>
            <bdi>{{
              joined(
                specification.variants.map((variant) => variant.label),
                t("documents.page.scope.listSeparator"),
              ) || t("documents.page.scope.none")
            }}</bdi>
          </dd>
          <dt>{{ t("documents.page.scope.values") }}</dt>
          <dd>{{ joined(ownValues(specification)) || t("documents.page.scope.noValues") }}</dd>
          <dt>{{ t("documents.page.scope.contexts") }}</dt>
          <dd>
            <ul v-if="specification.contexts.length" class="scope__contexts">
              <li v-for="context in specification.contexts" :key="context.id" data-test="scope-context">
                <!-- the badge's word, then what the context states: one space between, on one line -->
                <span class="status-badge" :class="tone(context.review_status)">{{ statusWord(context.review_status) }}</span> <bdi>{{ joined(contextWords(context, labels)) }}</bdi>
              </li>
            </ul>
            <template v-else>{{ t("documents.page.scope.noContexts") }}</template>
          </dd>
        </dl>
        <SpecificationForm
          v-if="scope.editable"
          :key="specification.id"
          :specification="specification"
          @saved="keep"
          @changed="reload()"
        />
        <ValueSection
          v-if="form && (scope.editable || drafting.has(specification.id))"
          :key="`values-${specification.id}`"
          :row="specificationRow(specification)"
          :form="form"
          :document-id="documentId"
          :editable="scope.editable"
          :reviewable="scope.editable && isEditor()"
          :closed-by="scope.editable ? null : scope.closed"
          :on-saved="valuesSaved"
          :on-reviewed="reviewed"
          @closed="reload()"
          @gone="gone"
          @dirty="(open) => draft(specification.id, open)"
        />
      </article>
    </template>
    <!-- always in the page, so the first word is read out -->
    <p class="scope__status" role="status">{{ status }}</p>
    <!-- in the page from the start, so its first word is heard -->
    <PartialState :notice="formMissing" :retry="true" @retry="retry()" />
    <!-- in the page from the start, so a failure of a later reading is heard -->
    <PartialState :notice="scope !== null ? failure : null" :retry="!hidden" @retry="retry()" />
  </section>
</template>

<style scoped>
.scope {
  display: grid;
  gap: var(--space-3);
  align-content: start;
}

.scope h2,
.scope h3,
.scope .facts,
.scope__note,
.scope__status {
  margin: 0;
}

/* Empty, it takes no room - as a cell of the grid its gap would stand twice - but stays in the page. */
.scope__status:empty {
  position: absolute;
}

.scope__note {
  max-width: var(--reading-width);
  color: var(--text-muted);
}

.scope__specification {
  display: grid;
  gap: var(--space-2);
}

.scope__title {
  overflow-wrap: anywhere;
}

.scope__contexts {
  margin: 0;
  padding-inline-start: var(--space-3);
}
</style>
