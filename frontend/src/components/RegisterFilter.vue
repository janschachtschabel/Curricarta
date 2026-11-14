<script setup lang="ts">
/**
 * What the register shows: entries whose title or address holds a search, of one Land, the
 * seeds' candidates alone - entries of no account still without their file, which the check
 * looks at - and how far the register has come with an entry. Each change hands on a new value;
 * the page reads the register again with it. The search goes when sent, not at each sign typed:
 * each value is a reading of the register and a step of the address.
 */
import { computed, ref, watch } from "vue";

import type { RegisterStatus } from "@/api";
import { messages, t } from "@/i18n/de";
import { COUNTRIES, MAX_SEARCH_SIGNS, STATUSES, type RegisterFilters } from "@/registerFilters";

const model = defineModel<RegisterFilters>({ required: true });

const candidates = computed({
  get: () => model.value.candidates,
  set: (value: boolean) => (model.value = { ...model.value, candidates: value }),
});
const status = computed({
  get: () => model.value.status,
  set: (value: RegisterStatus | "") => (model.value = { ...model.value, status: value }),
});
const country = computed({
  get: () => model.value.country,
  set: (value: string) => (model.value = { ...model.value, country: value }),
});

// what is typed, until sent; the address's search when that changes (back, the navigation's link)
const typed = ref(model.value.q);
watch(
  () => model.value.q,
  (now) => (typed.value = now),
);

function search(): void {
  const q = typed.value.trim();
  if (q !== model.value.q) model.value = { ...model.value, q };
}
</script>

<template>
  <div class="register-filter">
    <form class="register-filter__search" role="search" @submit.prevent="search">
      <div class="field">
        <label for="register-search">{{ t("sources.filter.search") }}</label>
        <input id="register-search" v-model="typed" type="search" :maxlength="MAX_SEARCH_SIGNS" />
      </div>
      <button type="submit" class="btn secondary">{{ t("sources.filter.searchButton") }}</button>
    </form>
    <fieldset class="register-filter__set">
      <legend class="register-filter__legend">{{ t("sources.filter.legend") }}</legend>
      <div class="field-grid">
        <div class="field checkbox-field">
          <input
            id="register-candidates"
            v-model="candidates"
            type="checkbox"
            aria-describedby="register-candidates-hint"
          />
          <label for="register-candidates">{{ t("sources.filter.candidates") }}</label>
          <p id="register-candidates-hint" class="field__hint">{{ t("sources.filter.candidatesHint") }}</p>
        </div>
        <div class="field">
          <label for="register-status">{{ t("sources.filter.status") }}</label>
          <select id="register-status" v-model="status" class="form-select">
            <option value="">{{ t("sources.filter.anyStatus") }}</option>
            <option v-for="value in STATUSES" :key="value" :value="value">{{ messages.sources.status[value] }}</option>
          </select>
        </div>
        <div class="field">
          <label for="register-country">{{ t("sources.filter.country") }}</label>
          <select id="register-country" v-model="country" class="form-select">
            <option value="">{{ t("sources.filter.anyCountry") }}</option>
            <option v-for="code in COUNTRIES" :key="code" :value="code">{{ messages.sources.countries[code] }}</option>
          </select>
        </div>
      </div>
    </fieldset>
  </div>
</template>

<style scoped>
.register-filter {
  display: grid;
  gap: var(--space-2);
  margin: 0 0 var(--space-2);
}

/* The field takes the room, its button beside it at the field's foot, under it where there is none. */
.register-filter__search {
  display: flex;
  flex-wrap: wrap;
  align-items: end;
  gap: var(--space-1) var(--space-2);
  max-width: var(--reading-width);
}

.register-filter__search .field {
  flex: 1 1 16rem;
  margin: 0;
}

.register-filter__set {
  margin: 0;
  padding: 0;
  border: 0;
  min-inline-size: 0;
}

.register-filter__legend {
  padding: 0;
  margin-block-end: var(--space-1);
  font-size: var(--step--1);
  font-weight: 600;
}
</style>
