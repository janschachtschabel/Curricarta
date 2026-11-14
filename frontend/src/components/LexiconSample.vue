<script setup lang="ts">
/**
 * The sample of the research's cues (plan M1 10.5, 10e E7; backend GET /api/v1/lexicon/review): its strata in a
 * table - cues, how many sampled, how many decided -, each cue of the list with its decision (LexiconCueItem),
 * and the decisions on cues retired since, each as it was judged. Read as sectionReading.ts reads; a decision
 * made is taken into the list without reading it again, and a cue decided here stays in sight while only the open
 * ones show, so the keyboard keeps its place. Tells the page whether a form holds what is not saved (`dirty`).
 */
import { computed, nextTick, onMounted, ref, watch } from "vue";

import { getReview, type CueDecision, type ReviewList } from "@/api";
import EmptyState from "@/components/EmptyState.vue";
import ErrorState from "@/components/ErrorState.vue";
import LexiconCueFilter from "@/components/LexiconCueFilter.vue";
import LexiconCueItem from "@/components/LexiconCueItem.vue";
import LoadingState from "@/components/LoadingState.vue";
import PartialState from "@/components/PartialState.vue";
import { LOCALE, t } from "@/i18n/de";
import { decidedIn, judgedCue } from "@/lexiconReview";
import { ANY_CUE, SAMPLE_PAGE, chosen, type CueChoice } from "@/lexiconStrata";
import { labelList, sectorWord } from "@/lexiconWords";
import { useOpenEntries } from "@/openEntries";
import { useSectionReading } from "@/sectionReading";

const emit = defineEmits<{ dirty: [dirty: boolean] }>();

const heading = ref<HTMLElement | null>(null);
const { shown: list, failure, load, retry } = useSectionReading<ReviewList>(
  getReview,
  t("lexicon.sample.loadFailed"),
  heading,
);
const number = new Intl.NumberFormat(LOCALE);

const items = computed(() => list.value?.items ?? []);
// the cues of a Bildungsbereich and a Land, a page at a time
const choice = ref<CueChoice>(ANY_CUE);
const inChoice = computed(() => items.value.filter((item) => chosen(item, choice.value)));
const open = computed(() => inChoice.value.filter((item) => item.decision === null).length);
const { openOnly, listed, dirty, held } = useOpenEntries(
  () => items.value,
  (item) => item.iri,
  (item) => item.decision !== null,
  (now) => emit("dirty", now),
);
// a cue whose form holds input is never taken from under the keyboard: not by the choice, not by the page's end
const shown = computed(() => listed.value.filter((item) => chosen(item, choice.value) || held(item.iri)));
const pageEnd = ref(SAMPLE_PAGE);
const paged = computed(() => shown.value.slice(0, pageEnd.value));
watch([choice, openOnly], () => {
  const lastHeld = shown.value.reduce((last, item, index) => (held(item.iri) ? index : last), -1);
  pageEnd.value = Math.max(SAMPLE_PAGE, lastHeld + 1);
});


const itemsBox = ref<HTMLElement | null>(null);

// as the register's "Weitere laden": the keyboard to the first cue the press brought
async function more(): Promise<void> {
  const first = paged.value.length;
  pageEnd.value += SAMPLE_PAGE;
  await nextTick();
  itemsBox.value?.querySelectorAll<HTMLElement>(".lexicon-item__heading")[first]?.focus();
}
const retired = computed(() => (list.value?.retired ?? []).map(judgedCue));

function regions(iris: string[]): string {
  return iris.length ? labelList(list.value?.labels ?? {}, iris) : t("lexicon.cue.everywhere");
}

function decided(made: CueDecision): void {
  if (!list.value) return;
  list.value = decidedIn(list.value, made);
}

onMounted(load);
</script>

<template>
  <section class="lexicon-sample" aria-labelledby="lexicon-sample">
    <!-- tabindex -1: where the keyboard goes once a retry's button went with its notice -->
    <h2 id="lexicon-sample" ref="heading" tabindex="-1">{{ t("lexicon.sample.heading") }}</h2>
    <p class="lexicon-sample__intro">{{ t("lexicon.sample.intro") }}</p>
    <template v-if="list === null">
      <ErrorState
        v-if="failure"
        :message="failure.text"
        :reason="failure.reason"
        :explanation="failure.explanation"
        @retry="retry()"
      />
      <LoadingState v-else :label="t('lexicon.sample.loading')" />
    </template>
    <EmptyState
      v-else-if="!list.strata.length && !list.retired.length"
      :level="3"
      :title="t('lexicon.sample.noneTitle')"
      :body="t('lexicon.sample.noneBody')"
    />
    <template v-else>
      <!-- scrolled on its own where wider than a phone, by the keyboard too; a name of its own -->
      <div v-if="list.strata.length" class="lexicon-sample__strata" tabindex="0" role="region" aria-labelledby="lexicon-strata">
        <table>
          <caption id="lexicon-strata">{{ t("lexicon.sample.strata") }}</caption>
          <thead>
            <tr>
              <th scope="col">{{ t("lexicon.sample.columns.sector") }}</th>
              <th scope="col">{{ t("lexicon.sample.columns.regions") }}</th>
              <th scope="col">{{ t("lexicon.sample.columns.cues") }}</th>
              <th scope="col">{{ t("lexicon.sample.columns.sampled") }}</th>
              <th scope="col">{{ t("lexicon.sample.columns.decided") }}</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="stratum in list.strata" :key="`${stratum.sector} ${stratum.regions.join(' ')}`">
              <td>{{ sectorWord(stratum.sector) }}</td>
              <td>{{ regions(stratum.regions) }}</td>
              <td>{{ number.format(stratum.cues) }}</td>
              <td>{{ number.format(stratum.sampled) }}</td>
              <td>{{ number.format(stratum.decided) }}</td>
            </tr>
          </tbody>
        </table>
      </div>
      <LexiconCueFilter v-if="items.length" v-model="choice" :items="items" :labels="list.labels" />
      <div v-if="items.length" class="lexicon-sample__tools">
        <button
          type="button"
          class="btn secondary btn-sm"
          data-test="open-only"
          :aria-pressed="openOnly"
          @click="openOnly = !openOnly"
        >
          {{ t("lexicon.list.openOnly") }}
        </button>
        <p data-test="open-count">{{ t("lexicon.list.openCount", { open, total: inChoice.length }) }}</p>
      </div>
      <p v-if="items.length && !inChoice.length">{{ t("lexicon.sample.filter.none") }}</p>
      <p v-else-if="openOnly && !shown.length">{{ t("lexicon.list.allDecided") }}</p>
      <div ref="itemsBox" class="lexicon-sample__items">
        <LexiconCueItem
          v-for="item in paged"
          :key="item.iri"
          :item="item"
          :labels="list.labels"
          @decided="decided"
          @reload="retry()"
          @dirty="dirty(item.iri, $event)"
        />
      </div>
      <div v-if="shown.length > SAMPLE_PAGE" class="lexicon-sample__tools">
        <p data-test="shown-count">{{ t("lexicon.sample.shownCount", { shown: paged.length, total: shown.length }) }}</p>
        <button v-if="paged.length < shown.length" type="button" class="btn secondary" data-test="more-cues" @click="more">
          {{ t("lexicon.sample.more") }}
        </button>
      </div>
      <div v-if="retired.length" class="lexicon-sample__retired" data-test="retired">
        <h3>{{ t("lexicon.sample.retiredHeading") }}</h3>
        <p>{{ t("lexicon.sample.retiredIntro") }}</p>
        <LexiconCueItem
          v-for="item in retired"
          :key="item.iri"
          :item="item"
          :labels="list.labels"
          :level="4"
          retired
          @decided="decided"
          @reload="retry()"
          @dirty="dirty(`retired ${item.iri}`, $event)"
        />
      </div>
    </template>
    <!-- in the page from the start, so a failure of a later reading is heard -->
    <PartialState :notice="list !== null ? failure : null" retry @retry="retry()" />
  </section>
</template>

<style scoped>
.lexicon-sample {
  display: grid;
  gap: var(--space-2);
}

.lexicon-sample > h2,
.lexicon-sample p {
  margin: 0;
}

.lexicon-sample__intro {
  max-width: var(--reading-width);
}

.lexicon-sample__strata {
  overflow-x: auto;
}

.lexicon-sample__strata table {
  border-collapse: collapse;
  min-width: 32rem;
}

.lexicon-sample__strata caption {
  text-align: start;
  font-weight: 600;
}

.lexicon-sample__strata th,
.lexicon-sample__strata td {
  padding: var(--space-0) var(--space-2) var(--space-0) 0;
  text-align: start;
  vertical-align: top;
}

.lexicon-sample__tools {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: var(--space-2);
}

.lexicon-sample__items,
.lexicon-sample__retired {
  display: grid;
  gap: var(--space-2);
}

.lexicon-sample__retired {
  padding-block-start: var(--space-3);
}

.lexicon-sample__retired h3 {
  margin: 0;
}
</style>
