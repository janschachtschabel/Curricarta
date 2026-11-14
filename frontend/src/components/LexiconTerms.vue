<script setup lang="ts">
/**
 * The terms X1 found no type for (plan M1 10.5, 10e E9; backend GET /api/v1/lexicon/terms): each once for its
 * sector, regions and word, with its places and its decision (LexiconTermItem), and the decisions on terms no
 * document names any more, each as it was judged. Read as sectionReading.ts reads; the node types a new cue may
 * point to are read once for each sector as long as the section stands. Otherwise as LexiconSample: a decision
 * made is taken into the list, a term decided here stays in sight while only the open ones show, and the page is
 * told while a form holds what is not saved (`dirty`).
 */
import { computed, onMounted, ref } from "vue";

import { getTerms, type Labels, type TermDecision, type TermsList } from "@/api";
import EmptyState from "@/components/EmptyState.vue";
import ErrorState from "@/components/ErrorState.vue";
import LexiconTermItem from "@/components/LexiconTermItem.vue";
import LoadingState from "@/components/LoadingState.vue";
import PartialState from "@/components/PartialState.vue";
import { t } from "@/i18n/de";
import { goneTerm, termDecidedIn, termKey } from "@/lexiconReview";
import { targetLoader } from "@/lexiconTargets";
import { useOpenEntries } from "@/openEntries";
import { useSectionReading } from "@/sectionReading";

const emit = defineEmits<{ dirty: [dirty: boolean] }>();

const heading = ref<HTMLElement | null>(null);
const { shown: list, failure, load, retry } = useSectionReading<TermsList>(
  getTerms,
  t("lexicon.terms.loadFailed"),
  heading,
);
const targets = targetLoader();

const terms = computed(() => list.value?.terms ?? []);
const { openOnly, open, listed, dirty } = useOpenEntries(
  () => terms.value,
  termKey,
  (term) => term.decision !== null,
  (now) => emit("dirty", now),
);
const gone = computed(() => (list.value?.gone ?? []).map(goneTerm));

// `key`: the entry's the decision was made in
function decided(key: string, made: TermDecision, labels: Labels): void {
  if (!list.value) return;
  list.value = termDecidedIn(list.value, key, made, labels);
}

onMounted(load);
</script>

<template>
  <section class="lexicon-terms" aria-labelledby="lexicon-terms">
    <!-- tabindex -1: where the keyboard goes once a retry's button went with its notice -->
    <h2 id="lexicon-terms" ref="heading" tabindex="-1">{{ t("lexicon.terms.heading") }}</h2>
    <p class="lexicon-terms__intro">{{ t("lexicon.terms.intro") }}</p>
    <template v-if="list === null">
      <ErrorState
        v-if="failure"
        :message="failure.text"
        :reason="failure.reason"
        :explanation="failure.explanation"
        @retry="retry()"
      />
      <LoadingState v-else :label="t('lexicon.terms.loading')" />
    </template>
    <EmptyState
      v-else-if="!list.terms.length && !list.gone.length"
      :level="3"
      :title="t('lexicon.terms.noneTitle')"
      :body="t('lexicon.terms.noneBody')"
    />
    <template v-else>
      <div v-if="terms.length" class="lexicon-terms__tools">
        <button
          type="button"
          class="btn secondary btn-sm"
          data-test="open-only"
          :aria-pressed="openOnly"
          @click="openOnly = !openOnly"
        >
          {{ t("lexicon.list.openOnly") }}
        </button>
        <p data-test="open-count">{{ t("lexicon.list.openCount", { open, total: terms.length }) }}</p>
      </div>
      <p v-if="openOnly && !listed.length">{{ t("lexicon.list.allDecided") }}</p>
      <LexiconTermItem
        v-for="term in listed"
        :key="termKey(term)"
        :term="term"
        :labels="list.labels"
        :targets="targets"
        @decided="(made, labels) => decided(termKey(term), made, labels)"
        @reload="retry()"
        @dirty="dirty(termKey(term), $event)"
      />
      <div v-if="gone.length" class="lexicon-terms__gone" data-test="gone">
        <h3>{{ t("lexicon.terms.goneHeading") }}</h3>
        <p>{{ t("lexicon.terms.goneIntro") }}</p>
        <LexiconTermItem
          v-for="term in gone"
          :key="termKey(term)"
          :term="term"
          :labels="list.labels"
          :targets="targets"
          :level="4"
          gone
          @decided="(made, labels) => decided(termKey(term), made, labels)"
          @reload="retry()"
          @dirty="dirty(`gone ${termKey(term)}`, $event)"
        />
      </div>
    </template>
    <!-- in the page from the start, so a failure of a later reading is heard -->
    <PartialState :notice="list !== null ? failure : null" retry @retry="retry()" />
  </section>
</template>

<style scoped>
.lexicon-terms,
.lexicon-terms__gone {
  display: grid;
  gap: var(--space-2);
}

.lexicon-terms > h2,
.lexicon-terms p,
.lexicon-terms__gone h3 {
  margin: 0;
}

.lexicon-terms__intro {
  max-width: var(--reading-width);
}

.lexicon-terms__tools {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: var(--space-2);
}

.lexicon-terms__gone {
  padding-block-start: var(--space-3);
}
</style>
