<script setup lang="ts">
/**
 * A row's values laid beside them as another stored them meanwhile (plan M3a G; valueSave.ts works it out), as
 * ConflictPanel lays a row's fields: each kind both changed, the user's values and the stored in words - none as
 * such - with the choice to keep theirs or take the stored; the kinds taken in because only the other changed them,
 * named with their values. Once a kind is decided the keyboard goes on to the next; with none left, to the panel,
 * whose intro says to save again. The section takes the keyboard to the panel as it appears (`focus`).
 */
import { computed, nextTick, ref, useId, watch } from "vue";

import type { ValueKind } from "@/api";
import { t } from "@/i18n/de";
import type { ValueClash } from "@/valueSave";

const props = defineProps<{ clashes: ValueClash[]; taken: { kind: ValueKind; stored: string[] }[] }>();
const emit = defineEmits<{ keep: [kind: ValueKind]; take: [kind: ValueKind] }>();

const id = useId();
const section = ref<HTMLElement | null>(null);
// the place of the kind last decided, where the keyboard goes on once the list is shorter
let decided: number | null = null;

const intro = computed(() => {
  if (props.clashes.length) return t("documents.tree.values.conflict.intro");
  return props.taken.length ? t("documents.tree.values.conflict.introNothing") : t("documents.tree.values.conflict.introAgain");
});

function kindWord(kind: ValueKind): string {
  return t(`documents.tree.values.kinds.${kind}`);
}

function shown(words: string[]): string {
  return words.length ? words.join("; ") : t("documents.tree.values.conflict.empty");
}

function decide(index: number, kind: ValueKind, how: "keep" | "take"): void {
  decided = index;
  if (how === "keep") emit("keep", kind);
  else emit("take", kind);
}

watch(
  () => props.clashes,
  async (now) => {
    if (decided === null) return;
    const at = Math.min(decided, now.length - 1);
    decided = null;
    await nextTick();
    if (at < 0) section.value?.focus();
    else section.value?.querySelectorAll(".value-conflict__clash")[at]?.querySelector("button")?.focus();
  },
);

/** The keyboard to the panel. */
function focus(): void {
  section.value?.focus();
}

defineExpose({ focus });
</script>

<template>
  <!-- focused as it appears, read with its intro: what to do -->
  <section ref="section" class="value-conflict" tabindex="-1" :aria-labelledby="`${id}-heading`" :aria-describedby="`${id}-intro`">
    <h4 :id="`${id}-heading`">{{ t("documents.tree.conflict.heading") }}</h4>
    <p :id="`${id}-intro`">{{ intro }}</p>
    <ul v-if="clashes.length" class="value-conflict__list">
      <li v-for="(clash, index) in clashes" :key="clash.kind" class="value-conflict__clash">
        <p :id="`${id}-${clash.kind}`" class="value-conflict__kind">{{ kindWord(clash.kind) }}</p>
        <dl class="value-conflict__values">
          <div>
            <dt>{{ t("documents.tree.values.conflict.yours") }}</dt>
            <dd><bdi>{{ shown(clash.yours) }}</bdi></dd>
          </div>
          <div>
            <dt>{{ t("documents.tree.conflict.stored") }}</dt>
            <dd><bdi>{{ shown(clash.stored) }}</bdi></dd>
          </div>
        </dl>
        <span class="value-conflict__actions">
          <button type="button" class="btn btn-sm secondary" :aria-describedby="`${id}-${clash.kind}`" @click="decide(index, clash.kind, 'keep')">
            {{ t("documents.tree.conflict.keep") }}
          </button>
          <button type="button" class="btn btn-sm secondary" :aria-describedby="`${id}-${clash.kind}`" @click="decide(index, clash.kind, 'take')">
            {{ t("documents.tree.conflict.take") }}
          </button>
        </span>
      </li>
    </ul>
    <div v-if="taken.length">
      <p>{{ t("documents.tree.conflict.taken") }}</p>
      <ul>
        <li v-for="one in taken" :key="one.kind">{{ kindWord(one.kind) }}: <bdi>{{ shown(one.stored) }}</bdi></li>
      </ul>
    </div>
  </section>
</template>

<style scoped>
.value-conflict {
  display: grid;
  gap: var(--space-1);
  padding: var(--space-2);
  border: 1px solid var(--border);
  border-inline-start: 3px solid var(--warning);
  border-radius: var(--radius);
}

.value-conflict h4,
.value-conflict p {
  margin: 0;
}

.value-conflict__list {
  display: grid;
  gap: var(--space-2);
  margin: 0;
  padding: 0;
  list-style: none;
}

.value-conflict__kind {
  font-weight: 600;
}

.value-conflict__values {
  display: grid;
  gap: var(--space-0);
  margin: var(--space-0) 0;
}

.value-conflict__values div {
  display: grid;
  grid-template-columns: minmax(6rem, auto) minmax(0, 1fr);
  gap: var(--space-1);
}

.value-conflict__values dt {
  color: var(--text-muted);
}

.value-conflict__values dd,
.value-conflict li {
  margin: 0;
  overflow-wrap: anywhere;
}

.value-conflict__actions {
  display: flex;
  flex-wrap: wrap;
  gap: var(--space-1);
}
</style>
