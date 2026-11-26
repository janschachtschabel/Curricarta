<script setup lang="ts">
/**
 * Where a placement is in the outline (plan M3a K, L; PlacementItemForm.vue): one node or none, chosen by a search
 * that narrows the outline's nodes - each by its path - to at most MOST_SHOWN buttons and counts the rest, as
 * RuleTargets.vue narrows a rule's. A document of hundreds of nodes so puts a few on the page, not all of them. The
 * place chosen is said under the group's name and described to the search, with a button to let it go; one the
 * outline holds no more is said so. A place pressed is taken, the keyboard stays at the search, and a status line says
 * what was chosen or let go. An Enter in the search is held: it would submit the placements' form. A problem stands
 * below, tied to the search, where the keyboard goes for it (`controlId`).
 */
import { computed, nextTick, ref } from "vue";

import AppIcon from "@/components/AppIcon.vue";
import { t } from "@/i18n/de";
import { sayAnew } from "@/liveRegion";
import type { Choice } from "@/placementDraft";

const props = defineProps<{
  places: readonly Choice[];
  /** The search's id, where the keyboard goes for a problem. */
  controlId: string;
  hint: string;
  error?: string | null;
}>();
const model = defineModel<string>({ required: true });

const MOST_SHOWN = 20;
const id = props.controlId;
const query = ref("");
const said = ref("");

const chosen = computed(() =>
  model.value ? (props.places.find((one) => one.id === model.value)?.label ?? t("documents.tree.placements.unknownPlace")) : null,
);
const matching = computed(() => {
  const words = query.value.trim().toLocaleLowerCase("de");
  return props.places.filter((place) => place.id !== model.value && place.label.toLocaleLowerCase("de").includes(words));
});
const shown = computed(() => matching.value.slice(0, MOST_SHOWN));
const more = computed(() => matching.value.length - shown.value.length);
const described = computed(() => [`${id}-chosen`, `${id}-more`, `${id}-hint`, props.error ? `${id}-error` : ""].filter(Boolean).join(" "));

// taken or let go: the keyboard stays in the group, at its search
async function choose(place: string): Promise<void> {
  const words = place
    ? t("documents.tree.placements.placeChosenSaid", { place: props.places.find((one) => one.id === place)?.label ?? "" })
    : t("documents.tree.placements.placeReleasedSaid", { place: chosen.value ?? "" });
  model.value = place;
  said.value = sayAnew(said.value, words);
  await nextTick();
  document.getElementById(id)?.focus();
}
</script>

<template>
  <fieldset class="place-picker">
    <legend>{{ t("documents.tree.placements.fields.in_node_id") }}</legend>
    <p :id="`${id}-chosen`" class="place-picker__chosen">
      <bdi v-if="chosen">{{ t("documents.tree.placements.placeChosen", { place: chosen }) }}</bdi>
      <template v-else>{{ t("documents.tree.placements.placeNone") }}</template>
    </p>
    <button
      v-if="chosen"
      type="button"
      class="btn btn-sm secondary place-picker__release"
      data-test="place-release"
      :aria-label="t('documents.tree.placements.placeReleaseNamed', { place: chosen })"
      @click="choose('')"
    >
      {{ t("documents.tree.placements.placeRelease") }}
    </button>
    <div class="field">
      <label :for="id">{{ t("documents.tree.placements.placeSearch") }}</label>
      <input
        :id="id"
        v-model="query"
        type="search"
        autocomplete="off"
        :aria-invalid="error ? true : undefined"
        :aria-describedby="described"
        @keydown.enter.prevent
      />
    </div>
    <ul class="place-picker__list" data-test="places-offered">
      <li v-for="place in shown" :key="place.id">
        <button
          type="button"
          class="btn btn-sm secondary place-picker__place"
          :aria-label="t('documents.tree.placements.placeChoose', { place: place.label })"
          @click="choose(place.id)"
        >
          {{ place.label }}
        </button>
      </li>
    </ul>
    <p :id="`${id}-more`" class="field__hint" aria-live="polite">
      {{ more > 0 ? t("documents.tree.placements.placeMore", { count: more }) : !shown.length ? t("documents.tree.placements.placeNoMatch") : "" }}
    </p>
    <p :id="`${id}-hint`" class="field__hint">{{ hint }}</p>
    <p v-if="error" :id="`${id}-error`" class="field__error"><AppIcon name="warning" /> {{ error }}</p>
    <!-- always in the page, so a screen reader hears each choice -->
    <p class="place-picker__status" role="status">{{ said }}</p>
  </fieldset>
</template>

<style scoped>
.place-picker {
  display: grid;
  gap: var(--space-1);
  margin: 0;
  padding: 0;
  border: 0;
  min-inline-size: 0;
}

.place-picker legend {
  padding: 0;
  font-weight: 500;
}

.place-picker p {
  margin: 0;
}

.place-picker__chosen bdi,
.place-picker__place {
  overflow-wrap: anywhere;
}

.place-picker__release {
  justify-self: start;
}

.place-picker__list {
  display: grid;
  gap: var(--space-0);
  margin: 0;
  padding: 0;
  list-style: none;
}

/* A path may be long: the button takes the room it needs, its words wrapping, its start where the list's is. */
.place-picker__place {
  justify-self: start;
  max-inline-size: 100%;
  text-align: start;
}

.place-picker .field__hint:empty {
  display: none;
}

/* Empty, it takes no room, but stays in the page. */
.place-picker__status:empty {
  position: absolute;
}
</style>
