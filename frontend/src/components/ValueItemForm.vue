<script setup lang="ts">
/**
 * One value of a row in the form of its values (plan M3a G; valueDraft.ts): a group named by its kind and place,
 * a field for each of its kind's form (FormFieldInput) - the lists offering what the holder may hold
 * (valueOffers.offeredFor), the levels grouped by system -, a problem at its field, and a button that names the
 * entry to take it away. Each change goes back as the entry's fields. A workload's periods stand in a group of their
 * own within it, named for it (the `periods` slot: their entries). What else an entry shows - who stated it and its
 * review status - stands in the default slot.
 */
import { computed } from "vue";

import type { Form, RuleHolder, ValueKind } from "@/api";
import FormFieldInput from "@/components/FormFieldInput.vue";
import { messages, t } from "@/i18n/de";
import type { Entry } from "@/valueDraft";
import { offeredFor } from "@/valueOffers";

const props = defineProps<{
  kind: ValueKind;
  entry: Entry;
  /** Its place among the entries of its kind, from 0. */
  place: number;
  form: Form;
  holder: RuleHolder;
  /** A statement's kind, which some levels ask of it. */
  holderType: string | null;
  /** Its fields' controls are `<prefix>-<key>`. */
  prefix: string;
  /** By the keys of its fields, the words of their problems. */
  errors: Partial<Record<string, string>>;
}>();
const emit = defineEmits<{ change: [fields: Entry["fields"]]; remove: [] }>();

const fields = computed(() => props.form.values[props.kind].fields);
const legend = computed(() => t(`documents.tree.values.entry.${props.kind}`, { place: props.place + 1 }));

function change(key: string, value: string | string[] | boolean): void {
  if (!Array.isArray(value)) emit("change", { ...props.entry.fields, [key]: value });
}

/** The keyboard to its first field. */
function focus(): void {
  const first = fields.value[0];
  if (first) document.getElementById(`${props.prefix}-${first.key}`)?.focus();
}

defineExpose({ focus });
</script>

<template>
  <fieldset class="value-item">
    <legend>{{ legend }}</legend>
    <slot />
    <div class="value-item__fields">
      <FormFieldInput
        v-for="field in fields"
        :key="field.key"
        :field="field"
        :values="offeredFor(form, kind, field.key, entry, holder, holderType)"
        :labels="messages.documents.tree.values.fields"
        :groups="form.groups"
        :control-id="`${prefix}-${field.key}`"
        :error="errors[field.key] ?? null"
        :model-value="entry.fields[field.key] ?? ''"
        @update:model-value="(value) => change(field.key, value)"
      />
    </div>
    <fieldset v-if="$slots.periods" class="value-item__periods">
      <legend>{{ t("documents.tree.values.periodsOf", { entry: legend }) }}</legend>
      <slot name="periods" />
    </fieldset>
    <button type="button" class="btn btn-sm secondary value-item__remove" @click="emit('remove')">
      {{ t("documents.tree.values.remove", { entry: legend }) }}
    </button>
  </fieldset>
</template>

<style scoped>
/* No frame of the browser's, as every fieldset: its legend and the room around it tell one entry from the next. */
.value-item {
  display: grid;
  gap: var(--space-1);
  margin: 0;
  padding: 0;
  border: 0;
  min-inline-size: 0;
}

.value-item legend {
  padding: 0;
  margin-block-end: var(--space-0);
  font-weight: 600;
}

/* Side by side where there is room; a field's label and control keep their width. */
.value-item__fields {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(min(12rem, 100%), 1fr));
  column-gap: var(--space-2);
}

/* Its periods within it, a rule at their start: as a context's values stand within the context. */
.value-item__periods {
  display: grid;
  gap: var(--space-1);
  margin: 0;
  padding: 0 0 0 var(--space-2);
  border: 0;
  border-inline-start: 2px solid var(--border);
  min-inline-size: 0;
}

.value-item__periods legend {
  padding: 0 var(--space-0);
}

.value-item__remove {
  justify-self: start;
}

@media (max-width: 40rem) {
  /* One field under another: at 320 px two columns leave a select too narrow to read its value (SC 1.4.10). */
  .value-item__fields {
    grid-template-columns: minmax(0, 1fr);
  }
}
</style>
