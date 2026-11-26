<script setup lang="ts">
/**
 * One placement of a node in the form of its placements (plan M3a K; placementDraft.ts): a group named by its place,
 * the specification and the variant it is in - one at least -, the node it is at, by a search over the outline
 * (PlacePicker), its obligation from the node's list and its grade weight written the German way, each with its hint;
 * and a button that names the entry to take it away. A problem stands at its field (`<entry key>:<field>`). What else it shows - who stated it, how far it is
 * reviewed - stands in the slot.
 */
import { computed } from "vue";

import AppIcon from "@/components/AppIcon.vue";
import PlacePicker from "@/components/PlacePicker.vue";
import { messages, t } from "@/i18n/de";
import type { Choice, PlacementEntry, PlacementField } from "@/placementDraft";

const props = defineProps<{
  entry: PlacementEntry;
  /** Its place among the node's placements, from 0. */
  place: number;
  /** Its fields' controls are `<sid>-<its key>-<the field>`. */
  sid: string;
  specifications: readonly Choice[];
  variants: readonly Choice[];
  places: readonly Choice[];
  obligations: readonly Choice[];
  /** The problems by entry and field (`placement-3:obligation`). */
  faults: Partial<Record<string, string>>;
}>();
const emit = defineEmits<{ change: [entry: PlacementEntry]; remove: [] }>();

const SELECTS = ["specification_id", "variant_id", "in_node_id", "obligation"] as const;
// the one field a placement must have beside where it is: its list offers no "none"
const REQUIRED: PlacementField = "obligation";
const WEIGHT: PlacementField = "grade_weight";
const labels: Readonly<Record<PlacementField, string>> = messages.documents.tree.placements.fields;
const hints: Readonly<Record<PlacementField, string>> = messages.documents.tree.placements.hints;

const legend = computed(() => t("documents.tree.placements.entry", { place: props.place + 1 }));
const choices = computed<Record<(typeof SELECTS)[number], readonly Choice[]>>(() => ({
  specification_id: props.specifications,
  variant_id: props.variants,
  in_node_id: props.places,
  obligation: props.obligations,
}));

function control(field: PlacementField): string {
  return `${props.sid}-${props.entry.key}-${field}`;
}

function fault(field: PlacementField): string | undefined {
  return props.faults[`${props.entry.key}:${field}`];
}

function describedBy(field: PlacementField): string {
  return fault(field) === undefined ? `${control(field)}-hint` : `${control(field)}-hint ${control(field)}-error`;
}

function change(field: PlacementField, value: string): void {
  emit("change", { ...props.entry, [field]: value });
}
</script>

<template>
  <fieldset class="placement-item">
    <legend>{{ legend }}</legend>
    <slot :entry="entry" />
    <div class="placement-item__fields">
      <template v-for="field in SELECTS" :key="field">
        <PlacePicker
          v-if="field === 'in_node_id'"
          :model-value="entry.in_node_id"
          :places="places"
          :control-id="control(field)"
          :hint="hints[field]"
          :error="fault(field) ?? null"
          @update:model-value="(value) => change(field, value)"
        />
        <div v-else class="field">
          <label :for="control(field)">{{ labels[field] }}</label>
          <select
            :id="control(field)"
            :value="entry[field]"
            :aria-required="field === REQUIRED || undefined"
            :aria-invalid="fault(field) !== undefined || undefined"
            :aria-describedby="describedBy(field)"
            @change="change(field, ($event.target as HTMLSelectElement).value)"
          >
            <option value="">
              {{ field === REQUIRED ? t("documents.tree.placements.choose") : t("documents.tree.placements.noChoice") }}
            </option>
            <option v-for="choice in choices[field]" :key="choice.id" :value="choice.id">{{ choice.label }}</option>
          </select>
          <p v-if="fault(field) !== undefined" :id="`${control(field)}-error`" class="field__error"><AppIcon name="warning" /> {{ fault(field) }}</p>
          <p :id="`${control(field)}-hint`" class="field__hint">{{ hints[field] }}</p>
        </div>
      </template>
      <div class="field">
        <label :for="control(WEIGHT)">{{ labels.grade_weight }}</label>
        <input
          :id="control(WEIGHT)"
          :value="entry.grade_weight"
          type="text"
          inputmode="decimal"
          maxlength="20"
          autocomplete="off"
          :aria-invalid="fault(WEIGHT) !== undefined || undefined"
          :aria-describedby="describedBy(WEIGHT)"
          @input="change(WEIGHT, ($event.target as HTMLInputElement).value)"
        />
        <p v-if="fault(WEIGHT) !== undefined" :id="`${control(WEIGHT)}-error`" class="field__error">
          <AppIcon name="warning" /> {{ fault(WEIGHT) }}
        </p>
        <p :id="`${control(WEIGHT)}-hint`" class="field__hint">{{ hints.grade_weight }}</p>
      </div>
    </div>
    <button type="button" class="btn btn-sm secondary placement-item__remove" @click="emit('remove')">
      {{ t("documents.tree.placements.remove", { place: place + 1 }) }}
    </button>
  </fieldset>
</template>

<style scoped>
/* No frame of the browser's, as every fieldset; a rule at its start sets one placement apart from the next. */
.placement-item {
  display: grid;
  gap: var(--space-2);
  margin: 0;
  padding: 0 0 0 var(--space-2);
  border: 0;
  border-inline-start: 2px solid var(--border);
  min-inline-size: 0;
}

.placement-item legend {
  padding: 0 var(--space-0);
  font-weight: 600;
}

/* Side by side where there is room; a field's label and control keep their width. */
.placement-item__fields {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(min(12rem, 100%), 1fr));
  column-gap: var(--space-2);
}

/* a long title of a specification or a node does not widen the page: the select keeps to its field (SC 1.4.10) */
.placement-item select {
  max-inline-size: 100%;
}

.placement-item__remove {
  justify-self: start;
}

@media (max-width: 40rem) {
  /* One field under another: at 320 px two columns leave a select too narrow to read its value (SC 1.4.10). */
  .placement-item__fields {
    grid-template-columns: minmax(0, 1fr);
  }

  .placement-item {
    padding-inline-start: var(--space-1);
  }
}
</style>
