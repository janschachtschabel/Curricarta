<script setup lang="ts">
/**
 * A document's rules on its page (plan M3a I; backend GET /documents/{id}/rules): each rule in the document's order
 * with its kind, wording, values, option texts, what it applies to, its options, what it requires, where it stands
 * and its review status, in words (ruleWords.ts); a selection whose options are text alone says that the export
 * names it no selection until they are linked. The document's owner and the editors change a rule while the document
 * is open (RuleForm), take it away, and add one (RuleNew); saved, the rule stands as stored until the next reading
 * catches up, taken away or added, the list is read again. A draft open in a form the section tells the page
 * (`dirty`, its leave guard). Closed, or another's, the section says why it is to read only. Read as
 * sectionReading.ts reads: loading, a failure with a retry, content no longer the reader's said apart; read again as
 * the page's extraction moves on (`refresh`).
 */
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from "vue";

import { getRules, type Rule, type Rules } from "@/api";
import EmptyState from "@/components/EmptyState.vue";
import ErrorState from "@/components/ErrorState.vue";
import LoadingState from "@/components/LoadingState.vue";
import PartialState from "@/components/PartialState.vue";
import RuleForm from "@/components/RuleForm.vue";
import RuleNew from "@/components/RuleNew.vue";
import { t } from "@/i18n/de";
import { sayAnew } from "@/liveRegion";
import { REVIEW_TONES, statusOf, statusWord } from "@/reviewStatus";
import { anchorWords, kindWord, linkWords, valueWords } from "@/ruleWords";
import { useSectionReading } from "@/sectionReading";

const props = defineProps<{ documentId: string; refresh?: number }>();
const emit = defineEmits<{ dirty: [open: boolean] }>();

const heading = ref<HTMLElement | null>(null);
const addButton = ref<HTMLElement | null>(null);
const { shown, failure, hidden, load, retry } = useSectionReading(
  () => getRules(props.documentId),
  t("documents.page.rules.loadFailed"),
  heading,
);
// a rule as a save gave it back, shown until a reading of the section catches up with it
const saved = ref<Record<string, Rule>>({});
// the forms holding a draft: `rule:<id>`, `new`
const drafting = ref<ReadonlySet<string>>(new Set());
const adding = ref(false);
const status = ref("");

const read = computed<Rules | null>(() => shown.value);
const rules = computed(() =>
  (read.value?.rules ?? []).map((rule) => {
    const kept = saved.value[rule.id];
    return kept && kept.revision > rule.revision ? kept : rule;
  }),
);
const readOnly = computed(() => {
  const found = read.value;
  if (!found || found.editable) return null;
  return found.closed ? t(`documents.page.rules.closed.${found.closed}`) : t("documents.page.rules.readOnly");
});

function tone(reviewStatus: string): string {
  const found = statusOf(reviewStatus);
  return found ? REVIEW_TONES[found] : "neutral";
}

function listed(words: string[]): string {
  return words.join(t("documents.page.rules.listSeparator")) || t("documents.page.rules.none");
}

function draft(form: string, open: boolean): void {
  const now = new Set(drafting.value);
  if (open) now.add(form);
  else now.delete(form);
  drafting.value = now;
}

async function reload(): Promise<void> {
  await load();
  const known = new Map((read.value?.rules ?? []).map((rule) => [rule.id, rule.revision]));
  saved.value = Object.fromEntries(Object.entries(saved.value).filter(([id, kept]) => (known.get(id) ?? Infinity) < kept.revision));
}

function keep(rule: Rule): void {
  saved.value = { ...saved.value, [rule.id]: rule };
}

function said(words: string): void {
  status.value = sayAnew(status.value, words);
  void reload();
}

// the form closed: the keyboard back to the button that opened it
async function closed(words?: string): Promise<void> {
  adding.value = false;
  if (words) said(words);
  await nextTick();
  addButton.value?.focus();
}

watch(
  () => drafting.value.size > 0,
  (open) => emit("dirty", open),
);
onBeforeUnmount(() => emit("dirty", false));
onMounted(load);
watch(() => props.refresh, reload);
</script>

<template>
  <section class="rules" aria-labelledby="document-rules">
    <!-- tabindex -1: where the keyboard goes once a retry's button went with its notice -->
    <h2 id="document-rules" ref="heading" tabindex="-1">{{ t("documents.page.rules.heading") }}</h2>
    <p class="rules__note">{{ t("documents.page.rules.intro") }}</p>
    <template v-if="read === null">
      <EmptyState v-if="hidden" :level="3" :title="t('conversionPage.hiddenTitle')" :body="t('refusals.file_hidden')" />
      <ErrorState
        v-else-if="failure"
        :message="failure.text"
        :reason="failure.reason"
        :explanation="failure.explanation"
        @retry="retry()"
      />
      <LoadingState v-else :label="t('documents.page.rules.loading')" />
    </template>
    <template v-else>
      <p v-if="readOnly" class="rules__note" data-test="rules-read-only">{{ readOnly }}</p>
      <EmptyState
        v-if="!rules.length"
        :level="3"
        :title="t('documents.page.rules.noneTitle')"
        :body="read.editable ? t('documents.page.rules.noneBody') : t('documents.page.rules.noneBodyReadOnly')"
      />
      <article v-for="rule in rules" :key="rule.id" class="rules__rule" data-test="rule">
        <h3>
          {{ kindWord(rule.kind) }}
          <span class="status-badge" :class="tone(rule.review_status)">{{ statusWord(rule.review_status) }}</span>
        </h3>
        <dl class="facts">
          <dt>{{ t("documents.page.rules.verbatim") }}</dt>
          <dd><bdi class="rules__text">{{ rule.verbatim }}</bdi></dd>
          <dt>{{ t("documents.page.rules.values") }}</dt>
          <dd>{{ listed(valueWords(rule, read.units, read.requirement_kinds)) }}</dd>
          <template v-if="rule.option_texts.length">
            <dt>{{ t("documents.page.rules.optionTexts") }}</dt>
            <dd><bdi class="rules__text">{{ listed(rule.option_texts) }}</bdi></dd>
          </template>
          <dt>{{ t("documents.page.rules.appliesTo") }}</dt>
          <dd><bdi class="rules__text">{{ listed(linkWords(rule.applies_to)) }}</bdi></dd>
          <template v-if="rule.kind === 'selection'">
            <dt>{{ t("documents.page.rules.options") }}</dt>
            <dd><bdi class="rules__text">{{ listed(linkWords(rule.options)) }}</bdi></dd>
          </template>
          <template v-if="rule.kind === 'prerequisite'">
            <dt>{{ t("documents.page.rules.requires") }}</dt>
            <dd><bdi class="rules__text">{{ listed(linkWords(rule.requires)) }}</bdi></dd>
          </template>
          <dt>{{ t("documents.page.rules.anchors") }}</dt>
          <dd>{{ anchorWords(rule) || t("documents.page.rules.none") }}</dd>
        </dl>
        <p v-if="rule.kind === 'selection' && !rule.options.length" class="rules__note" data-test="rule-unlinked">
          {{ t("documents.page.rules.unlinked") }}
        </p>
        <RuleForm
          v-if="read.editable"
          :key="`form-${rule.id}`"
          :rule="rule"
          :rules="read"
          @saved="keep"
          @changed="reload()"
          @taken="said"
          @dirty="(open) => draft(`rule:${rule.id}`, open)"
        />
      </article>
      <template v-if="read.editable">
        <RuleNew
          v-if="adding"
          :document-id="documentId"
          @created="closed(t('documents.page.rules.created'))"
          @changed="reload()"
          @cancel="closed()"
          @dirty="(open) => draft('new', open)"
        />
        <button v-else ref="addButton" type="button" class="btn secondary rules__add" @click="adding = true">
          {{ t("documents.page.rules.add") }}
        </button>
      </template>
    </template>
    <!-- always in the page, so the first word is read out -->
    <p class="rules__status" role="status">{{ status }}</p>
    <!-- in the page from the start, so a failure of a later reading is heard -->
    <PartialState :notice="read !== null ? failure : null" :retry="!hidden" @retry="retry()" />
  </section>
</template>

<style scoped>
.rules {
  display: grid;
  gap: var(--space-3);
  align-content: start;
}

.rules h2,
.rules h3,
.rules .facts,
.rules__note,
.rules__status {
  margin: 0;
}

.rules__status:empty {
  position: absolute;
}

.rules__note {
  max-width: var(--reading-width);
  color: var(--text-muted);
}

.rules__rule {
  display: grid;
  gap: var(--space-2);
}

.rules__text {
  overflow-wrap: anywhere;
}

.rules__add {
  justify-self: start;
}
</style>
