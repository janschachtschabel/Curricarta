<script setup lang="ts">
/**
 * Which of the sample's cues to show: those of a Bildungsbereich and of a Land - the strata the sample is drawn
 * from -, a cue that names no region under a choice of its own (lexiconStrata.ts). Each change hands on a new value.
 */
import { computed } from "vue";

import type { Labels, ReviewCue } from "@/api";
import { t } from "@/i18n/de";
import { EVERYWHERE, regionsOf, sectorsOf, type CueChoice } from "@/lexiconStrata";
import { labelOf, sectorWord } from "@/lexiconWords";

const props = defineProps<{ items: readonly ReviewCue[]; labels: Labels }>();
const model = defineModel<CueChoice>({ required: true });

const sectors = computed(() => sectorsOf(props.items));
const regions = computed(() => regionsOf(props.items, props.labels));

const sector = computed({
  get: () => model.value.sector,
  set: (value: string) => (model.value = { ...model.value, sector: value }),
});
const region = computed({
  get: () => model.value.region,
  set: (value: string) => (model.value = { ...model.value, region: value }),
});

function regionWord(value: string): string {
  return value === EVERYWHERE ? t("lexicon.cue.everywhere") : labelOf(props.labels, value);
}
</script>

<template>
  <div class="field-grid lexicon-cue-filter">
    <div class="field">
      <label for="lexicon-sector">{{ t("lexicon.sample.filter.sector") }}</label>
      <select id="lexicon-sector" v-model="sector" class="form-select">
        <option value="">{{ t("lexicon.sample.filter.anySector") }}</option>
        <option v-for="value in sectors" :key="value" :value="value">{{ sectorWord(value) }}</option>
      </select>
    </div>
    <div class="field">
      <label for="lexicon-region">{{ t("lexicon.sample.filter.region") }}</label>
      <select id="lexicon-region" v-model="region" class="form-select">
        <option value="">{{ t("lexicon.sample.filter.anyRegion") }}</option>
        <option v-for="value in regions" :key="value" :value="value">{{ regionWord(value) }}</option>
      </select>
    </div>
  </div>
</template>

<style scoped>
.lexicon-cue-filter {
  max-width: var(--reading-width);
}
</style>
