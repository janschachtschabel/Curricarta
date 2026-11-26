<script setup lang="ts">
/**
 * The entries of one kind in the form of a holder's values (plan M3a G; valueDraft.ts): each entry's form
 * (ValueItemForm, or what the `item` slot puts in its place - a specification's applicability context), then a
 * button that adds one more, the keyboard going to the new entry's first field, or from one taken away to the next,
 * else to that button. At as many as a holder takes it adds none and says why. A problem of the kind as a whole - one
 * the store refused in a context - stands above the button, which it describes. What else an entry shows - who
 * stated it and its review status - stands in the default slot. Each change goes back as the kind's entries.
 */
import { computed, nextTick } from "vue";

import type { Form, RuleHolder, ValueKind } from "@/api";
import AppIcon from "@/components/AppIcon.vue";
import ValueItemForm from "@/components/ValueItemForm.vue";
import { t } from "@/i18n/de";
import { faultsOf, fieldsOf, isFull, MOST_VALUES, newEntry, type DraftKind, type Entry } from "@/valueDraft";

const props = defineProps<{
  kind: DraftKind;
  entries: Entry[];
  form: Form;
  /** Whose levels the rules of the form are of. */
  holder: RuleHolder;
  /** A statement's kind, a specification's class: what a level rule's `unless` names. */
  holderType: string | null;
  /** An entry's fields' controls are `<sid>-<its key>-<the field's key>`. */
  sid: string;
  /** The id of the button that adds an entry. */
  addId: string;
  /** The problems by entry and field (`value-7:unit`). */
  faults: Partial<Record<string, string>>;
  /** A problem of the kind as a whole. */
  problem?: string | null;
}>();
const emit = defineEmits<{ change: [entries: Entry[]] }>();

const full = computed(() => isFull(props.entries));
const described = computed(() => {
  const ids = [props.problem ? `${props.addId}-error` : null, full.value ? `${props.addId}-most` : null].filter(Boolean);
  return ids.length ? ids.join(" ") : undefined;
});

function toFirstField(entry: Entry): void {
  const first = fieldsOf(props.form, props.kind)[0];
  if (first) document.getElementById(`${props.sid}-${entry.key}-${first.key}`)?.focus();
}

async function add(): Promise<void> {
  if (full.value) return;
  const entry = newEntry(props.form, props.kind);
  emit("change", [...props.entries, entry]);
  await nextTick();
  toFirstField(entry);
}

async function remove(place: number): Promise<void> {
  const gone = props.entries[place];
  if (!gone) return;
  const next = props.entries[place + 1];
  emit("change", props.entries.filter((entry) => entry.key !== gone.key));
  await nextTick();
  if (next) toFirstField(next);
  else document.getElementById(props.addId)?.focus();
}

function change(entry: Entry): void {
  emit("change", props.entries.map((one) => (one.key === entry.key ? entry : one)));
}
</script>

<template>
  <div class="value-section__kind">
    <template v-for="(entry, place) in entries" :key="entry.key">
      <slot name="item" :entry="entry" :place="place" :change="change" :remove="() => remove(place)">
        <ValueItemForm
          :kind="kind as ValueKind"
          :entry="entry"
          :place="place"
          :form="form"
          :holder="holder"
          :holder-type="holderType"
          :prefix="`${sid}-${entry.key}`"
          :errors="faultsOf(faults, entry.key)"
          @change="(fields) => change({ ...entry, fields })"
          @remove="remove(place)"
        >
          <slot :entry="entry" />
        </ValueItemForm>
      </slot>
    </template>
    <p v-if="problem" :id="`${addId}-error`" class="field__error"><AppIcon name="warning" /> {{ problem }}</p>
    <!-- aria-disabled, not disabled: the button keeps the keyboard and says why it adds no more -->
    <button
      :id="addId"
      type="button"
      class="btn btn-sm secondary value-section__add"
      :aria-disabled="full || undefined"
      :aria-describedby="described"
      @click="add"
    >
      {{ t(`documents.tree.values.add.${kind}`) }}
    </button>
    <p v-if="full" :id="`${addId}-most`" class="value-section__most">
      {{ t("documents.tree.values.most", { most: MOST_VALUES }) }}
    </p>
  </div>
</template>

<style scoped>
.value-section__kind {
  display: grid;
  gap: var(--space-2);
}

.value-section__kind p {
  margin: 0;
}

.value-section__add {
  justify-self: start;
}

.value-section__most {
  color: var(--text-muted);
}
</style>
