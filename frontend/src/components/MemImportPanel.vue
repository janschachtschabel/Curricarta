<script setup lang="ts">
/**
 * The import of a MEM-Schule plan into a new document of the entry's finished conversion, for the redaktion
 * and the admins (plan M2-8, A7; backend POST /sources/{id}/mem-import). The catalogue is looked up by
 * region - the entry's own at first, "DE" for the KMK's standards - and title, a page at a time; a plan is
 * chosen, its attribution and licence named, and imported; the page then goes to the new document, where
 * the import is followed. Without a finished conversion nothing is looked up. A plan imported before
 * leads to its document. An answer a newer search overtook is dropped; while one is on its way no more are
 * loaded, and "more" goes on with the search the list shows - so the list is never one of two searches.
 * The number found is said once asked for, not as the section first loads.
 */
import { computed, nextTick, onMounted, ref } from "vue";
import { RouterLink, useRouter } from "vue-router";

import { ApiError, findMemPlans, startMemImport, type MemPlan } from "@/api";
import AppIcon from "@/components/AppIcon.vue";
import ErrorState from "@/components/ErrorState.vue";
import LoadingState from "@/components/LoadingState.vue";
import MemCatalog from "@/components/MemCatalog.vue";
import NoticeText from "@/components/NoticeText.vue";
import { messages, momentFormat, t } from "@/i18n/de";
import { sayAnew } from "@/liveRegion";
import { focusIsFree } from "@/focusRescue";
import { failureNotice, type Notice } from "@/notice";

const props = defineProps<{
  sourceId: string;
  /** The entry's finished conversion; null while there is none. */
  conversionId: string | null;
  /** The entry's Land as the register has it (ISO 3166-2), looked up first. */
  country: string | null;
}>();

const router = useRouter();
const REGIONS = Object.keys(messages.sources.countries);

const region = ref(props.country && REGIONS.includes(props.country) ? props.country : "");
const title = ref("");
const plans = ref<MemPlan[]>([]);
const total = ref(0);
const readAt = ref<string | null>(null);
const loaded = ref(false);
const loading = ref(false);
// a search or more on its way: "more" waits for it
const searching = ref(false);
const loadFailure = ref<Notice | null>(null);
const moreFailure = ref<Notice | null>(null);
const chosen = ref("");
const choiceMissing = ref(false);
const busy = ref(false);
const failure = ref<Notice | null>(null);
const takenBy = ref<string | null>(null);
const status = ref("");
type Filters = { region?: string; title?: string };
// what the shown list was searched with: "more" goes on with it, whatever the form says meanwhile
let searched: Filters = {};
// The latest search counts: an answer it overtook is dropped
let generation = 0;

const chosenPlan = computed(() => plans.value.find((plan) => plan.iri === chosen.value) ?? null);

function asked(): Filters {
  return { region: region.value || undefined, title: title.value.trim() || undefined };
}

function regionName(code: string | null): string {
  if (!code) return "";
  if (code === "DE") return t("mem.import.regionKmk");
  return messages.sources.countries[code as keyof typeof messages.sources.countries] ?? code;
}

function moment(value: string): string {
  return momentFormat.format(new Date(value));
}

function sayFound(): void {
  status.value = sayAnew(status.value, t("mem.import.shown", { shown: plans.value.length, total: total.value }));
}

/** A search with `filters`: the form's, or the list's own again; `quiet` as the section first loads. */
async function search(filters: Filters = asked(), quiet = false): Promise<void> {
  const mine = ++generation;
  loading.value = true;
  searching.value = true;
  loadFailure.value = null;
  moreFailure.value = null;
  choiceMissing.value = false;
  try {
    const found = await findMemPlans({ ...filters, offset: 0 });
    if (mine !== generation) return;
    searched = filters;
    plans.value = found.plans;
    if (!plans.value.some((plan) => plan.iri === chosen.value)) chosen.value = "";
    total.value = found.total;
    readAt.value = found.catalog_read_at;
    loaded.value = true;
    if (!quiet) sayFound();
  } catch (error) {
    if (mine === generation) loadFailure.value = failureNotice(error, t("mem.import.loadFailed"));
  } finally {
    if (mine === generation) loading.value = searching.value = false;
  }
}

/** The next page of the search the list shows, below it; nothing while a search is on its way. */
async function more(): Promise<void> {
  if (searching.value) return; // the button stays focusable while busy, so it can be pressed again
  const mine = ++generation;
  const from = plans.value.length;
  searching.value = true;
  moreFailure.value = null;
  try {
    const found = await findMemPlans({ ...searched, offset: from });
    if (mine !== generation) return;
    plans.value = [...plans.value, ...found.plans];
    total.value = found.total;
    sayFound();
    // the last page takes the button away: the keyboard goes on at the first plan it brought
    await nextTick();
    if (focusIsFree()) document.querySelectorAll<HTMLInputElement>("input[name=mem-import-plan]")[from]?.focus();
  } catch (error) {
    if (mine === generation) moreFailure.value = failureNotice(error, t("mem.import.moreFailed"));
  } finally {
    if (mine === generation) searching.value = false;
  }
}

async function start(): Promise<void> {
  if (busy.value) return; // the button stays focusable while busy, so it can be pressed again
  failure.value = null;
  takenBy.value = null;
  choiceMissing.value = chosen.value === "";
  if (chosen.value === "" || props.conversionId === null) {
    // the first choice takes the keyboard: the group's name and why it is invalid are read there
    await nextTick();
    document.querySelector<HTMLInputElement>("input[name=mem-import-plan]")?.focus();
    return;
  }
  busy.value = true;
  try {
    const started = await startMemImport(props.sourceId, {
      plan_iri: chosen.value,
      conversion_id: props.conversionId,
    });
    await router.push({ name: "document", params: { id: started.document.id } });
  } catch (error) {
    failure.value = failureNotice(error, t("mem.import.failed"));
    if (error instanceof ApiError && error.code === "mem_plan_taken") {
      const id = error.details.document_id;
      takenBy.value = typeof id === "string" ? id : null;
    }
    if (error instanceof ApiError && error.code === "mem_unknown_plan") void search(searched);
  } finally {
    busy.value = false;
  }
}

onMounted(() => {
  if (props.conversionId !== null) void search(asked(), true);
});
</script>

<template>
  <section class="mem-import card" aria-labelledby="source-mem-import">
    <h2 id="source-mem-import" class="mem-import__heading">{{ t("mem.import.heading") }}</h2>
    <p class="mem-import__intro">{{ t("mem.import.intro") }}</p>
    <p v-if="conversionId === null" class="mem-import__note">
      {{ t("mem.import.needsConversion") }}
      <a href="#source-conversion">{{ t("mem.import.toConversion") }}</a>
    </p>
    <template v-else>
      <LoadingState v-if="loading && !loaded" :label="t('mem.import.loading')" />
      <ErrorState
        v-else-if="loadFailure && !loaded"
        :message="loadFailure.text"
        :explanation="loadFailure.explanation"
        @retry="search(asked(), true)"
      />
      <template v-if="loaded">
        <MemCatalog :read-at="readAt" @read="search(searched)" />
        <form v-if="readAt !== null" class="mem-import__search" novalidate @submit.prevent="search()">
          <div class="field">
            <label for="mem-import-region">{{ t("mem.import.region") }}</label>
            <select id="mem-import-region" v-model="region">
              <option value="">{{ t("mem.import.regionAny") }}</option>
              <option v-for="code in REGIONS" :key="code" :value="code">{{ regionName(code) }}</option>
            </select>
          </div>
          <div class="field">
            <label for="mem-import-title">{{ t("mem.import.title") }}</label>
            <input id="mem-import-title" v-model="title" type="search" maxlength="200" autocomplete="off" />
          </div>
          <!-- aria-disabled, not disabled: a disabled button drops the focus it holds -->
          <button type="submit" class="btn secondary" data-test="mem-search" :aria-disabled="searching || undefined">
            {{ searching ? t("mem.import.searching") : t("mem.import.search") }}
          </button>
        </form>
        <p v-if="loadFailure" class="field__error" role="alert">
          <AppIcon name="warning" /> <NoticeText :notice="loadFailure" />
        </p>
        <template v-if="readAt !== null">
          <p v-if="plans.length === 0 && !loadFailure" class="mem-import__none">{{ t("mem.import.noneFound") }}</p>
          <fieldset
            v-else-if="plans.length > 0"
            class="mem-import__plans"
            :aria-busy="searching || undefined"
            :aria-describedby="choiceMissing ? 'mem-import-choice-error' : undefined"
          >
            <legend>{{ t("mem.import.results") }}</legend>
            <p v-if="choiceMissing" id="mem-import-choice-error" class="field__error">
              <AppIcon name="warning" /> {{ t("mem.import.chooseMissing") }}
            </p>
            <label v-for="plan in plans" :key="plan.iri" class="mem-import__plan">
              <input
                v-model="chosen"
                type="radio"
                name="mem-import-plan"
                :value="plan.iri"
                :aria-invalid="choiceMissing || undefined"
                :aria-describedby="choiceMissing ? 'mem-import-choice-error' : undefined"
                @change="choiceMissing = false"
              />
              <span>
                <bdi class="mem-import__title">{{ plan.title }}</bdi>
                <span class="mem-import__meta">
                  <template v-if="plan.region">{{ regionName(plan.region) }} ·</template>
                  {{ t("mem.import.readAt") }}
                  <time :datetime="plan.read_at">{{ moment(plan.read_at) }}</time>
                </span>
              </span>
            </label>
          </fieldset>
          <p v-if="plans.length > 0" class="mem-import__shown" data-test="mem-shown">
            {{ t("mem.import.shown", { shown: plans.length, total }) }}
          </p>
          <!-- aria-disabled, not disabled: a disabled button drops the focus it holds -->
          <button
            v-if="plans.length < total"
            type="button"
            class="btn secondary"
            data-test="mem-more"
            :aria-disabled="searching || undefined"
            @click="more"
          >
            {{ t("mem.import.more") }}
          </button>
          <p v-if="moreFailure" class="field__error" role="alert">
            <AppIcon name="warning" /> <NoticeText :notice="moreFailure" />
          </p>
          <dl v-if="chosenPlan" class="facts mem-import__chosen" data-test="mem-chosen">
            <dt>{{ t("mem.import.attribution") }}</dt>
            <dd>{{ chosenPlan.attribution ?? t("mem.import.attributionNone") }}</dd>
            <dt>{{ t("mem.import.licence") }}</dt>
            <dd>{{ chosenPlan.licence ?? t("mem.import.licenceNone") }}</dd>
            <dt>{{ t("mem.import.rights") }}</dt>
            <dd>{{ t("mem.import.rightsNote") }}</dd>
          </dl>
          <p v-if="failure" class="field__error" role="alert">
            <AppIcon name="warning" /> <NoticeText :notice="failure" />
            <RouterLink v-if="takenBy" :to="{ name: 'document', params: { id: takenBy } }">
              {{ t("mem.import.toDocument") }}
            </RouterLink>
          </p>
          <!-- aria-disabled, not disabled: a disabled button drops the focus it holds -->
          <button
            v-if="plans.length > 0"
            type="button"
            class="btn primary"
            data-test="mem-import"
            :aria-disabled="busy || undefined"
            @click="start"
          >
            {{ t("mem.import.submit") }}
          </button>
        </template>
      </template>
      <!-- Always in the page, so a screen reader hears each change of its text -->
      <p class="mem-import__status visually-hidden" role="status">{{ status }}</p>
    </template>
  </section>
</template>

<style scoped>
.mem-import {
  display: flex;
  flex-direction: column;
  align-items: flex-start;
  gap: var(--space-2);
}

.mem-import__heading,
.mem-import__intro,
.mem-import__note,
.mem-import__none,
.mem-import__shown {
  max-width: var(--reading-width);
  margin: 0;
}

.mem-import__search {
  display: flex;
  flex-wrap: wrap;
  align-items: flex-end;
  gap: var(--space-1) var(--space-2);
}

.mem-import__plans {
  display: flex;
  flex-direction: column;
  gap: var(--space-1);
  margin: 0;
  padding: 0;
  border: 0;
}

.mem-import__plans legend {
  padding: 0;
  font-weight: 600;
}

/* WCAG 2.5.8: the radio and its words a target of 24px at least */
.mem-import__plan {
  display: flex;
  align-items: flex-start;
  gap: var(--space-1);
  min-height: 24px;
}

.mem-import__plan input[type="radio"] {
  width: auto;
  min-width: 24px;
  min-height: 24px;
  margin: 0;
}

.mem-import__title {
  display: block;
  font-weight: 600;
}

.mem-import__meta {
  color: var(--text-muted);
  font-size: var(--step--1);
}
</style>
