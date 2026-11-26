<script setup lang="ts">
/**
 * The rows a rule names in one role (plan M3a I; RuleForm.vue): the ones chosen, each a box to let it go, then a
 * search that narrows what the rule may name - specifications, variants, nodes - to at most MOST_SHOWN boxes, and how
 * many more match. A document of hundreds of nodes so puts a few boxes on the page, not all of them. A row chosen
 * that no list offers - a statement - stays chosen under its own words. A problem the server names stands below,
 * tied to the search, where the keyboard goes for it (`controlId`).
 */
import { computed, nextTick, ref, useId } from "vue";

import type { RuleLink, RuleTarget } from "@/api";
import AppIcon from "@/components/AppIcon.vue";
import { t } from "@/i18n/de";

const props = defineProps<{
  label: string;
  targets: RuleTarget[];
  /** The rule's links of this role as read: their words, where no target names them. */
  held: RuleLink[];
  error?: string | null;
  controlId?: string;
}>();
const model = defineModel<string[]>({ required: true });

const MOST_SHOWN = 20;
const ownId = useId();
const id = props.controlId ?? ownId;
const query = ref("");

const labelOf = (target: string): string =>
  props.targets.find((one) => one.id === target)?.label ?? props.held.find((one) => one.id === target)?.label ?? target;
const chosen = computed(() => model.value.map((target) => ({ id: target, label: labelOf(target) })));
const matching = computed(() => {
  const words = query.value.trim().toLocaleLowerCase("de");
  return props.targets.filter((target) => !model.value.includes(target.id) && target.label.toLocaleLowerCase("de").includes(words));
});
const shown = computed(() => matching.value.slice(0, MOST_SHOWN));
const more = computed(() => matching.value.length - shown.value.length);
const described = computed(() => [`${id}-more`, props.error ? `${id}-error` : ""].filter(Boolean).join(" "));

// the box pressed moves from one list to the other: the keyboard stays in the field, at its search
async function choose(target: string, on: boolean): Promise<void> {
  model.value = on ? [...model.value, target] : model.value.filter((one) => one !== target);
  await nextTick();
  document.getElementById(id)?.focus();
}
</script>

<template>
  <fieldset class="rule-targets">
    <legend>{{ label }}</legend>
    <ul v-if="chosen.length" class="rule-targets__list" data-test="targets-chosen">
      <li v-for="(each, index) in chosen" :key="each.id" class="field checkbox-field">
        <input :id="`${id}-chosen-${index}`" type="checkbox" checked @change="choose(each.id, false)" />
        <label :for="`${id}-chosen-${index}`">{{ each.label }}</label>
      </li>
    </ul>
    <p v-else class="field__hint">{{ t("documents.page.rules.noneChosen") }}</p>
    <div class="field">
      <label :for="id">{{ t("documents.page.rules.search") }}</label>
      <input
        :id="id"
        v-model="query"
        type="search"
        autocomplete="off"
        :aria-invalid="error ? true : undefined"
        :aria-describedby="described"
      />
    </div>
    <ul class="rule-targets__list" data-test="targets-offered">
      <li v-for="(each, index) in shown" :key="each.id" class="field checkbox-field">
        <input :id="`${id}-offered-${index}`" type="checkbox" @change="choose(each.id, true)" />
        <label :for="`${id}-offered-${index}`">{{ each.label }}</label>
      </li>
    </ul>
    <p :id="`${id}-more`" class="field__hint" aria-live="polite">
      {{ more > 0 ? t("documents.page.rules.moreMatch", { count: more }) : !shown.length ? t("documents.page.rules.noMatch") : "" }}
    </p>
    <p v-if="error" :id="`${id}-error`" class="field__error"><AppIcon name="warning" /> {{ error }}</p>
  </fieldset>
</template>

<style scoped>
.rule-targets {
  margin: 0;
  padding: 0;
  border: 0;
  display: grid;
  gap: var(--space-1);
}

.rule-targets legend {
  padding: 0;
  font-size: var(--step--1);
  font-weight: 500;
}

.rule-targets__list {
  margin: 0;
  padding: 0;
  list-style: none;
}

.rule-targets__list label {
  overflow-wrap: anywhere;
}

.rule-targets .field__hint:empty {
  display: none;
}
</style>
