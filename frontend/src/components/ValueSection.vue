<script setup lang="ts">
/**
 * A row's levels, time spans and workloads (plan M3a G; valueSave.ts): "Niveau, Zeit, Umfang" in the row's panel,
 * the kinds its form offers the holder - a node every kind, a statement its levels. Where the tree is open, a form
 * of entries, each kind's with a button to add one (ValueEntries); the set is saved as a whole on the holder's
 * revision. A field's problem stands at its field, the keyboard taken
 * there (fieldFaults.ts); a set that met another is laid beside it (ValueConflict); a failure is said above the
 * form, the draft kept. Where the tree closed - on this save, or under an open draft as it was read anew
 * (`closedBy`) - it says why and keeps the draft, in words, to copy. Elsewhere its values read in words (ValueList).
 * Each value says who stated it and how far it is reviewed; the editors set its review status here (ReviewToggles),
 * which the panel hears (`onReviewed`) with words that name the value - one gone meanwhile as one changed, its
 * row kept. A statement's level and time in
 * its wording stand above, to copy from. It tells the panel whether a draft is open (the leave guard).
 */
import { computed, nextTick, onBeforeUnmount, ref, toRef, useId, watch } from "vue";

import type { Form, ValueKind } from "@/api";
import AppIcon from "@/components/AppIcon.vue";
import LoadingState from "@/components/LoadingState.vue";
import NoticeText from "@/components/NoticeText.vue";
import ReviewToggles from "@/components/ReviewToggles.vue";
import ValueConflict from "@/components/ValueConflict.vue";
import ValueEntries from "@/components/ValueEntries.vue";
import ValueList from "@/components/ValueList.vue";
import type { Row, RowKey } from "@/documentTree";
import { useFieldFaults } from "@/fieldFaults";
import { messages, t } from "@/i18n/de";
import { sayAnew } from "@/liveRegion";
import { refusalText } from "@/refusals";
import type { ReviewOutcome } from "@/rowReview";
import { word } from "@/registerWords";
import { kindsOf, type Entry } from "@/valueDraft";
import { useValueSave } from "@/valueSave";
import { shownValues, valueReviewWords, type ShownValue } from "@/valueWords";

const props = defineProps<{
  row: Row;
  form: Form;
  documentId: string;
  /** The caller may set the values now - or a draft the tree closed under is kept to copy. */
  editable: boolean;
  /** The caller may set the values' review status now. */
  reviewable: boolean;
  /** Why the tree, read anew, closed; none while it is open. */
  closedBy: string | null;
  /** A set saved: a prop, so that a save landing after another row was chosen still has the tree read anew. */
  onSaved?: () => void;
  /** How a value's review went, with the row's key. */
  /** How a value's review went, with the row's key and, where it was set or met a change, words naming the value. */
  onReviewed?: (done: Exclude<ReviewOutcome, { outcome: "failed" }>, key: RowKey, words?: string) => void;
}>();
const emit = defineEmits<{ closed: [code: string]; gone: []; dirty: [open: boolean] }>();

const TEXTS = ["levelText", "timeText"] as const;

const sid = useId();
const editing = useValueSave(toRef(props, "row"), toRef(props, "form"));
const { draft, saving, problem, conflict, closed, dirty, changes } = editing;
const status = ref("");
const submitButton = ref<HTMLElement | null>(null);
const panel = ref<InstanceType<typeof ValueConflict> | null>(null);
const closedNotice = ref<HTMLElement | null>(null);

const holder = computed(() => props.row.kind);
const holderType = computed(() => {
  const kind = props.row.kind === "statement" ? props.row.statement.fields.statement_kind : null;
  return typeof kind === "string" ? kind : null;
});
const kinds = computed(() => kindsOf(props.form, holder.value));
const held = computed(() => (props.row.kind === "node" ? props.row.node.values : props.row.statement.values));
const shut = computed(() => closed.value ?? props.closedBy);
const mode = computed(() => {
  if (shut.value && dirty.value) return "closed";
  return props.editable && !shut.value ? "form" : "read";
});
// a statement's level and time in its wording, where it has them
const texts = computed(() => {
  if (props.row.kind !== "statement") return [];
  const fields = props.row.statement.fields;
  return TEXTS.flatMap((key) => {
    const text = fields[key];
    return typeof text === "string" && text.trim() ? [{ key, label: word(messages.documents.tree.fields, key), text }] : [];
  });
});

// each stored value in words: one object while the row is, so that its review toggles do not start over
const shown = computed(() => shownValues(props.form, kinds.value, held.value));
const nothingDrafted = computed(() => kinds.value.every((kind) => !draft.value[kind].length));

function storedOf(kind: ValueKind, id: string | null): ShownValue | undefined {
  return id === null ? undefined : shown.value.get(kind)?.find((one) => one.id === id);
}

// a problem stands at its entry's field by the entry's key and the field's (`value-7:unit`)
const { faults, faultsAt, clear } = useFieldFaults<string>({
  control: (at) => `${sid}-${at.replace(":", "-")}`,
  submit: submitButton,
  say: (at, words) => {
    const field = word(messages.documents.tree.values.fields, at.split(":")[1] ?? at);
    status.value = sayAnew(status.value, t("forms.fieldProblem", { field, problem: words }));
  },
});

// A value reviewed that is gone or changed meanwhile is no row gone: the tree is read again, the row kept. Told in
// words that name the value, apart from the row's own status set beside it
function reviewed(done: Exclude<ReviewOutcome, { outcome: "failed" }>, key: RowKey, value: string): void {
  const told = done.outcome === "gone" ? ({ outcome: "stale" } as const) : done;
  props.onReviewed?.(told, key, valueReviewWords(told, value));
}

watch(dirty, (open) => emit("dirty", open), { immediate: true });
watch(
  () => props.row.key,
  () => clear(),
);
onBeforeUnmount(() => emit("dirty", false));

function change(kind: ValueKind, entries: Entry[]): void {
  draft.value = { ...draft.value, [kind]: entries };
}

async function submit(): Promise<void> {
  if (saving.value) return;
  const { outcome, faults: found } = await editing.save();
  await nextTick();
  const said: Partial<Record<typeof outcome, string>> = {
    saved: t("documents.tree.form.saved"),
    unchanged: t("documents.tree.form.unchanged"),
    undecided: t("documents.tree.conflict.undecided"),
  };
  const words = said[outcome];
  status.value = words ? sayAnew(status.value, words) : "";
  if (outcome === "saved" || outcome === "unchanged") clear();
  if (outcome === "saved") props.onSaved?.();
  else if (outcome === "conflict" || outcome === "undecided") panel.value?.focus();
  else if (outcome === "invalid") await faultsAt(found ?? []);
  else if (outcome === "closed" && closed.value) {
    await nextTick();
    closedNotice.value?.focus();
    emit("closed", closed.value);
  } else if (outcome === "gone") emit("gone");
}
</script>

<template>
  <section v-if="kinds.length" class="value-section" :aria-labelledby="`${sid}-heading`">
    <h3 :id="`${sid}-heading`">{{ t("documents.tree.values.heading") }}</h3>
    <dl v-if="texts.length" class="facts value-section__texts">
      <template v-for="text in texts" :key="text.key">
        <dt>{{ text.label }}</dt>
        <dd><bdi>{{ text.text }}</bdi></dd>
      </template>
    </dl>

    <section v-if="mode === 'closed'" ref="closedNotice" class="value-section__closed" tabindex="-1" :aria-label="t('documents.tree.form.closedLabel')">
      <p class="field__error" role="alert"><AppIcon name="warning" /> {{ refusalText(shut ?? "") }}</p>
      <p>{{ t("documents.tree.form.keptDraft") }}</p>
      <dl class="facts">
        <template v-for="change_ in changes" :key="change_.kind">
          <dt>{{ t(`documents.tree.values.kinds.${change_.kind}`) }}</dt>
          <dd><bdi>{{ change_.words.length ? change_.words.join("; ") : t("documents.tree.values.conflict.empty") }}</bdi></dd>
        </template>
      </dl>
    </section>

    <template v-else-if="mode === 'form'">
      <p v-if="problem" class="field__error value-section__problem" role="alert">
        <AppIcon name="warning" /> <NoticeText :notice="problem" />
      </p>
      <ValueConflict v-if="conflict" ref="panel" :clashes="conflict.clashes" :taken="conflict.taken" @keep="editing.keep" @take="editing.take" />
      <p v-if="nothingDrafted" class="value-section__none">{{ t("documents.tree.values.none") }}</p>
      <form class="value-section__form" novalidate @submit.prevent="submit">
        <ValueEntries
          v-for="kind in kinds"
          :key="kind"
          :kind="kind"
          :entries="draft[kind]"
          :form="form"
          :holder="holder"
          :holder-type="holderType"
          :sid="sid"
          :add-id="`${sid}-add-${kind}`"
          :faults="faults"
          @change="(entries) => change(kind, entries)"
        >
          <template #default="{ entry }">
            <template v-if="storedOf(kind, entry.id)">
              <p class="value-section__stated">{{ storedOf(kind, entry.id)?.stated }}</p>
              <ReviewToggles
                v-if="reviewable"
                :row="row"
                :value="storedOf(kind, entry.id)?.review"
                :label="t('documents.tree.values.reviewLabel', { value: storedOf(kind, entry.id)?.words ?? '' })"
                :document-id="documentId"
                :on-reviewed="(done, key) => reviewed(done, key, storedOf(kind, entry.id)?.words ?? '')"
              />
            </template>
          </template>
        </ValueEntries>
        <LoadingState v-if="saving" quiet :label="t('documents.tree.values.saving')" />
        <!-- aria-disabled, not disabled: a disabled button drops the focus it holds -->
        <button ref="submitButton" type="submit" class="btn primary value-section__save" :aria-disabled="saving || undefined">
          {{ t("documents.tree.values.save") }}
        </button>
      </form>
    </template>

    <ValueList v-else :row="row" :shown="shown" :reviewable="reviewable" :document-id="documentId" :on-reviewed="reviewed" />
    <!-- always in the page, so the first word is read out -->
    <p class="value-section__status" role="status">{{ status }}</p>
  </section>
</template>

<style scoped>
.value-section {
  display: grid;
  gap: var(--space-1);
}

.value-section h3,
.value-section p {
  margin: 0;
}

.value-section__form {
  display: grid;
  gap: var(--space-2);
}

.value-section__save {
  justify-self: start;
}

.value-section__stated,
.value-section__none {
  color: var(--text-muted);
}

.value-section__texts dd {
  overflow-wrap: anywhere;
}

.value-section__closed {
  display: grid;
  gap: var(--space-1);
}
</style>
