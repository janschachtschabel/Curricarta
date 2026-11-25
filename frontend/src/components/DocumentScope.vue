<script setup lang="ts">
/**
 * What a document's specifications are and where they apply, on its page (plan M3a H1; backend
 * GET /documents/{id}/specifications): each specification with its kind, title and field, its variants (X1's, to
 * read), its own levels, time spans and workloads and its applicability contexts, each in words (scopeWords.ts) by
 * the labels of the values' form - a form that did not come leaves the last part of each IRI. The document's owner
 * and the editors set title and field while it is open (SpecificationForm); closed, or another's, the section says
 * why it is to read only. Read as sectionReading.ts reads: loading, a failure with a retry, content no longer the
 * reader's said apart; read again as the page's extraction moves on (`refresh`).
 */
import { computed, onMounted, ref, watch } from "vue";

import { getScopeForm, getSpecifications, type ScopeForm, type Specification, type Specifications } from "@/api";
import EmptyState from "@/components/EmptyState.vue";
import ErrorState from "@/components/ErrorState.vue";
import LoadingState from "@/components/LoadingState.vue";
import PartialState from "@/components/PartialState.vue";
import SpecificationForm from "@/components/SpecificationForm.vue";
import { t } from "@/i18n/de";
import { contextWords, labelsOf, levelWords, spanWords, workloadWords } from "@/scopeWords";
import { useSectionReading } from "@/sectionReading";

// `refresh`: bumped by the page as the extraction moves on, which may write the specifications (X1)
const props = defineProps<{ documentId: string; sector: string; refresh?: number }>();

const heading = ref<HTMLElement | null>(null);
// the values' form names the concepts; without it the section still shows what the specifications say
const read = async (): Promise<[Specifications, ScopeForm | null]> =>
  Promise.all([getSpecifications(props.documentId), getScopeForm(props.sector).catch(() => null)]);
const { shown, failure, hidden, load, retry } = useSectionReading(read, t("documents.page.scope.loadFailed"), heading);
// a specification as a save gave it back, shown until the section is read again
const saved = ref<Record<string, Specification>>({});

const labels = computed(() => labelsOf(shown.value?.[1] ?? null));
const scope = computed(() => shown.value?.[0] ?? null);
const specifications = computed(() =>
  (scope.value?.specifications ?? []).map((specification) => saved.value[specification.id] ?? specification),
);
const readOnly = computed(() => {
  const found = scope.value;
  if (!found || found.editable) return null;
  return found.closed ? t(`documents.page.scope.closed.${found.closed}`) : t("documents.page.scope.readOnly");
});

function ownValues(specification: Specification): string[] {
  const values = specification.values;
  return [
    ...values.level_assignments.map((level) => levelWords(level, labels.value)),
    ...values.time_spans.map((span) => spanWords(span, labels.value)),
    ...values.workloads.map((workload) => workloadWords(workload, labels.value)),
  ];
}

function keep(specification: Specification): void {
  saved.value = { ...saved.value, [specification.id]: specification };
}

async function reload(): Promise<void> {
  await load();
  saved.value = {};
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
            <bdi>{{ specification.variants.map((variant) => variant.label).join(", ") || t("documents.page.scope.none") }}</bdi>
          </dd>
          <dt>{{ t("documents.page.scope.values") }}</dt>
          <dd>{{ ownValues(specification).join(" · ") || t("documents.page.scope.noValues") }}</dd>
          <dt>{{ t("documents.page.scope.contexts") }}</dt>
          <dd>
            <ul v-if="specification.contexts.length" class="scope__contexts">
              <li v-for="context in specification.contexts" :key="context.id" data-test="scope-context">
                <bdi>{{ contextWords(context, labels).join(" · ") }}</bdi>
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
      </article>
    </template>
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
.scope__note {
  margin: 0;
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
