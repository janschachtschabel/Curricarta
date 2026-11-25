<script setup lang="ts">
/**
 * One field of a row's form (plan M1 9.8, Paket 9c2 K9), built from the sector's form: a text in a box as long
 * as the form allows, a long text in a text area, one value of a list in a select, several in a group of
 * boxes - a value's form (plan M3a G) a number as written, in a box that asks for digits, a yes or no in a box of
 * its own, and the values of many systems in the select grouped by system (`groups`), its labels by `labels`. A
 * required field says so in its label's words. A value the form does not know - retired from the
 * vocabulary since it was written - stays a choice of its own, so that saving does not drop it unasked. A
 * problem the server names stands at the field, tied to its control, with the warning sign beside the words.
 */
import { computed, ref, useId } from "vue";

import type { FormField, FormValue } from "@/api";
import { isolate } from "@/bidi";
import AppIcon from "@/components/AppIcon.vue";
import { messages, t } from "@/i18n/de";
import { requiredLabel } from "@/formWords";
import { word } from "@/registerWords";

const props = defineProps<{
  field: FormField;
  values: FormValue[];
  error?: string | null;
  /** The labels of the fields by their keys; the row's form's by default. */
  labels?: Readonly<Record<string, string>>;
  /** The label of each group a value names: its values grouped under it. */
  groups?: Readonly<Record<string, string>>;
  /** The control's id, where the form finds it by its own; one of its own by default. */
  controlId?: string;
}>();
const model = defineModel<string | string[] | boolean>({ required: true });

// asked for always, as a component's ids are counted in the order they are asked for
const ownId = useId();
const id = props.controlId ?? ownId;
const errorId = `${id}-error`;
const control = ref<HTMLElement | null>(null);
const group = ref<HTMLElement | null>(null);

const name = computed(() => {
  const label = word(props.labels ?? messages.documents.tree.fields, props.field.key);
  return props.field.required ? requiredLabel(label) : label;
});
// the values held that the form does not know
const unknown = computed(() => {
  const held = Array.isArray(model.value) ? model.value : typeof model.value === "string" && model.value ? [model.value] : [];
  return held.filter((iri) => !props.values.some((value) => value.iri === iri));
});
// the boxes of a field of many: the values offered, then those held the form does not know
const boxes = computed(() => [
  ...props.values.map((value) => ({ iri: value.iri, label: value.label })),
  ...unknown.value.map((iri) => ({ iri, label: unknownLabel(iri) })),
]);
const described = computed(() => (props.error ? errorId : undefined));
// a select's, a text's and a number's value: always a string there
const text = computed<string>({
  get: () => (typeof model.value === "string" ? model.value : ""),
  set: (value) => (model.value = value),
});
// the values by group, in the order the form gives them; those of no group stand on their own
const grouped = computed(() => {
  const groups: { iri: string | null; label: string; values: FormValue[] }[] = [];
  for (const value of props.values) {
    const group = props.groups && value.group ? value.group : null;
    const last = groups.at(-1);
    if (last && last.iri === group) last.values.push(value);
    else groups.push({ iri: group, label: group ? (props.groups?.[group] ?? group) : "", values: [value] });
  }
  return groups;
});

// an IRI set apart from the words around it: its own direction does not turn them
function unknownLabel(iri: string): string {
  return t("documents.tree.form.unknownValue", { iri: isolate(iri) });
}

function focus(): void {
  (control.value ?? group.value?.querySelector("input"))?.focus();
}

defineExpose({ focus });
</script>

<template>
  <div v-if="field.kind === 'boolean'" class="field checkbox-field">
    <input
      :id="id"
      ref="control"
      v-model="model"
      type="checkbox"
      :aria-invalid="error ? true : undefined"
      :aria-describedby="described"
    />
    <label :for="id">{{ name }}</label>
    <p v-if="error" :id="errorId" class="field__error"><AppIcon name="warning" /> {{ error }}</p>
  </div>
  <fieldset v-else-if="field.many" ref="group" class="form-field__group" :aria-describedby="described">
    <legend>{{ name }}</legend>
    <div v-for="(box, index) in boxes" :key="box.iri" class="field checkbox-field">
      <!-- each box says it too: a screen reader reads the box focused, not always its group -->
      <input
        :id="`${id}-${index}`"
        v-model="model"
        type="checkbox"
        :value="box.iri"
        :aria-invalid="error ? true : undefined"
        :aria-describedby="described"
      />
      <label :for="`${id}-${index}`">{{ box.label }}</label>
    </div>
    <p v-if="error" :id="errorId" class="field__error"><AppIcon name="warning" /> {{ error }}</p>
  </fieldset>
  <div v-else class="field">
    <label :for="id">{{ name }}</label>
    <select
      v-if="field.kind === 'concept'"
      :id="id"
      :aria-required="field.required || undefined"
      ref="control"
      v-model="text"
      :aria-invalid="error ? true : undefined"
      :aria-describedby="described"
    >
      <option v-if="!field.required || !model" value="">
        {{ field.required ? t("documents.tree.form.choose") : t("documents.tree.form.none") }}
      </option>
      <template v-for="group in grouped" :key="group.iri ?? ''">
        <optgroup v-if="group.iri" :label="group.label">
          <option v-for="value in group.values" :key="value.iri" :value="value.iri">{{ value.label }}</option>
        </optgroup>
        <template v-else>
          <option v-for="value in group.values" :key="value.iri" :value="value.iri">{{ value.label }}</option>
        </template>
      </template>
      <option v-for="iri in unknown" :key="iri" :value="iri">{{ unknownLabel(iri) }}</option>
    </select>
    <textarea
      v-else-if="field.kind === 'longtext'"
      :id="id"
      :aria-required="field.required || undefined"
      ref="control"
      v-model="text"
      rows="4"
      :maxlength="field.most ?? undefined"
      :aria-invalid="error ? true : undefined"
      :aria-describedby="described"
    ></textarea>
    <input
      v-else
      :id="id"
      :aria-required="field.required || undefined"
      ref="control"
      v-model="text"
      type="text"
      :inputmode="field.kind === 'number' ? 'decimal' : undefined"
      :autocomplete="field.kind === 'number' ? 'off' : undefined"
      :maxlength="field.most ?? undefined"
      :aria-invalid="error ? true : undefined"
      :aria-describedby="described"
    />
    <p v-if="error" :id="errorId" class="field__error"><AppIcon name="warning" /> {{ error }}</p>
  </div>
</template>

<style scoped>
.form-field__group {
  margin: 0 0 var(--space-2);
  padding: 0;
  border: 0;
}

.form-field__group legend {
  padding: 0;
  margin-block-end: var(--space-0);
  font-size: var(--step--1);
  font-weight: 500;
}

.form-field__group .field {
  margin-block-end: var(--space-0);
}

/* An IRI as a box's label breaks anywhere rather than widen the page (SC 1.4.10). */
.form-field__group label {
  overflow-wrap: anywhere;
}
</style>
