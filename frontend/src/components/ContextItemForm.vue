<script setup lang="ts">
/**
 * One applicability context of a specification in the form of its values (plan M3a H; valueDraft.ts): a group named
 * by its place, a field for each of the context's form (FormFieldInput) - sector and formality from their lists,
 * institution and target group as written -, then its own levels and time spans, each kind's entries with a button
 * to add one (ValueEntries), their levels by the rules of a context, and a button that names the context to take it
 * away with them. A problem stands at its field; one the store found with the context as a whole stands at its top,
 * named and where the keyboard goes; one with a kind of its values, at that kind's button. What else the context
 * and each of its values show - who stated it and its review status - stands in the slot.
 */
import { computed } from "vue";

import type { Form, ValueKind } from "@/api";
import AppIcon from "@/components/AppIcon.vue";
import FormFieldInput from "@/components/FormFieldInput.vue";
import ValueEntries from "@/components/ValueEntries.vue";
import { messages, t } from "@/i18n/de";
import { faultsOf, type Entry } from "@/valueDraft";

const props = defineProps<{
  entry: Entry;
  /** Its place among the contexts, from 0. */
  place: number;
  form: Form;
  /** Its fields' controls are `<sid>-<its key>-<the field's key>`, its values' so by theirs. */
  sid: string;
  /** The problems by entry and field (`value-7:unit`), its values' among them. */
  faults: Partial<Record<string, string>>;
}>();
const emit = defineEmits<{ change: [entry: Entry]; remove: [] }>();

const prefix = computed(() => `${props.sid}-${props.entry.key}`);
const legend = computed(() => t("documents.tree.values.entry.contexts", { place: props.place + 1 }));
const errors = computed(() => faultsOf(props.faults, props.entry.key));

function change(key: string, value: string | string[] | boolean): void {
  if (!Array.isArray(value)) emit("change", { ...props.entry, fields: { ...props.entry.fields, [key]: value } });
}

function changeValues(kind: ValueKind, entries: Entry[]): void {
  if (props.entry.inner) emit("change", { ...props.entry, inner: { ...props.entry.inner, [kind]: entries } });
}
</script>

<template>
  <!-- its problem as a whole heard whenever the keyboard comes into it -->
  <fieldset class="context-item" :aria-describedby="errors.context ? `${prefix}-context` : undefined">
    <legend>{{ legend }}</legend>
    <slot :entry="entry" />
    <!-- tabindex -1: where the keyboard goes with a problem of the context as a whole -->
    <p v-if="errors.context" :id="`${prefix}-context`" class="field__error context-item__problem" tabindex="-1">
      <AppIcon name="warning" /> {{ t("documents.tree.values.contextProblem", { entry: legend, problem: errors.context }) }}
    </p>
    <div class="context-item__fields">
      <FormFieldInput
        v-for="field in form.context.fields"
        :key="field.key"
        :field="field"
        :values="field.values ?? []"
        :labels="messages.documents.tree.values.fields"
        :control-id="`${prefix}-${field.key}`"
        :error="errors[field.key] ?? null"
        :model-value="entry.fields[field.key] ?? ''"
        @update:model-value="(value) => change(field.key, value)"
      />
    </div>
    <ValueEntries
      v-for="kind in form.context.values"
      :key="kind"
      :kind="kind"
      :entries="entry.inner?.[kind] ?? []"
      :form="form"
      holder="applicability_context"
      :holder-type="null"
      :sid="sid"
      :add-id="`${prefix}-${kind}`"
      :faults="faults"
      :problem="errors[kind] ?? null"
      @change="(entries) => changeValues(kind, entries)"
    >
      <template #default="{ entry: value }"><slot :entry="value" /></template>
    </ValueEntries>
    <button type="button" class="btn btn-sm secondary context-item__remove" @click="emit('remove')">
      {{ t("documents.tree.values.remove", { entry: legend }) }}
    </button>
  </fieldset>
</template>

<style scoped>
/* No frame of the browser's, as every fieldset; a rule at its start sets it apart from the specification's own
   values, its values standing within it. */
.context-item {
  display: grid;
  gap: var(--space-2);
  margin: 0;
  padding: 0 0 0 var(--space-2);
  border: 0;
  border-inline-start: 2px solid var(--border);
  min-inline-size: 0;
}

.context-item legend {
  padding: 0 var(--space-0);
  font-weight: 600;
}

.context-item__problem {
  margin: 0;
}

/* Side by side where there is room; a field's label and control keep their width. */
.context-item__fields {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(min(12rem, 100%), 1fr));
  column-gap: var(--space-2);
}

.context-item__remove {
  justify-self: start;
}

@media (max-width: 40rem) {
  /* One field under another: at 320 px two columns leave a select too narrow to read its value (SC 1.4.10). */
  .context-item__fields {
    grid-template-columns: minmax(0, 1fr);
  }

  /* Less room lost to the rule's indent on a narrow screen. */
  .context-item {
    padding-inline-start: var(--space-1);
  }
}
</style>
