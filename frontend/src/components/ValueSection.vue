<script setup lang="ts">
/**
 * A row's levels, time spans and workloads (plan M3a G; valueSave.ts): "Niveau, Zeit, Umfang" in the row's panel,
 * the kinds its form offers the holder - a node every kind, a statement its levels; a specification's on the
 * document page (plan M3a H; valueHolder.ts), named for it under its title, its applicability contexts too
 * (ContextItemForm). Where the tree is open, a form of entries, each kind's with a button to add one (ValueEntries);
 * the set is saved as a whole on the holder's revision. A field's problem stands at its field, the keyboard taken
 * there (fieldFaults.ts); a set that met another is laid beside it (ValueConflict); a failure is said above the
 * form, the draft kept. Where the tree closed - on this save, or under an open draft as it was read anew
 * (`closedBy`) - it says why and keeps the draft, in words, to copy. Elsewhere its values read in words (ValueList).
 * Each value says who stated it and how far it is reviewed; the editors set its review status here (StoredValue),
 * which the panel hears (`onReviewed`) with words that name the value - one gone meanwhile as one changed, its
 * row kept. A statement's level and time in
 * its wording stand above, to copy from. It tells the panel whether a draft is open (the leave guard).
 */
import { computed, nextTick, onBeforeUnmount, ref, toRef, useId, watch } from "vue";

import type { Form } from "@/api";
import AppIcon from "@/components/AppIcon.vue";
import LoadingState from "@/components/LoadingState.vue";
import ContextItemForm from "@/components/ContextItemForm.vue";
import NoticeText from "@/components/NoticeText.vue";
import StoredValue from "@/components/StoredValue.vue";
import ValueConflict from "@/components/ValueConflict.vue";
import ValueEntries from "@/components/ValueEntries.vue";
import ValueList from "@/components/ValueList.vue";
import { useFieldFaults } from "@/fieldFaults";
import { messages, t } from "@/i18n/de";
import { sayAnew } from "@/liveRegion";
import { refusalText } from "@/refusals";
import type { ReviewOutcome } from "@/rowReview";
import { word } from "@/registerWords";
import { holdsEntry, kindsOf, type DraftKind, type Entry } from "@/valueDraft";
import { holderOf, holderTypeOf, type Holder, type HolderKey, type HolderRow } from "@/valueHolder";
import { useValueSave } from "@/valueSave";
import { shownContexts, shownValues, valueReviewWords, type ShownValue } from "@/valueWords";

const props = defineProps<{
  row: HolderRow;
  form: Form;
  documentId: string;
  /** The caller may set the values now - or a draft the tree closed under is kept to copy. */
  editable: boolean;
  /** The caller may set the values' review status now. */
  reviewable: boolean;
  /** Why the tree, read anew, closed; none while it is open. */
  closedBy: string | null;
  /**
   * A set saved, with the holder as stored: a prop, so that a save landing after another row was chosen still has
   * the tree read anew.
   */
  onSaved?: (answer: Holder) => void;
  /** How a value's review went, with the row's key and, where it was set or met a change, words naming the value. */
  onReviewed?: (done: Exclude<ReviewOutcome, { outcome: "failed" }>, key: HolderKey, words?: string) => void;
}>();
const emit = defineEmits<{ closed: [code: string]; gone: []; dirty: [open: boolean] }>();

const TEXTS = ["levelText", "timeText"] as const;
// a problem's field in words: a value's field, a context's, a kind of a context's values
const FAULT_WORDS: Readonly<Record<string, string>> = { ...messages.documents.tree.values.fields, ...messages.documents.tree.values.kinds };

const sid = useId();
const editing = useValueSave(toRef(props, "row"), toRef(props, "form"));
const { draft, saving, problem, conflict, closed, dirty, changes } = editing;
const status = ref("");
const submitButton = ref<HTMLElement | null>(null);
const panel = ref<InstanceType<typeof ValueConflict> | null>(null);
const closedNotice = ref<HTMLElement | null>(null);

const holder = computed(() => props.row.kind);
const holderType = computed(() => holderTypeOf(props.row));
const kinds = computed(() => kindsOf(props.form, holder.value));
// a specification holds its applicability contexts beside its values (backend CONTEXT_HOLDERS)
const drafted = computed<DraftKind[]>(() => (props.row.kind === "specification" ? [...kinds.value, "contexts"] : kinds.value));
const held = computed(() => holderOf(props.row).values);
// a specification's title: its section stands under it on the document page, named for it
const named = computed(() => (props.row.kind === "specification" ? props.row.specification.title : null));
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
// every stored value and context by its id, as its entry shows it
const stored = computed(() => {
  const contexts = shownContexts(props.form, holderOf(props.row).contexts ?? []);
  return new Map([...[...shown.value.values()].flat(), ...contexts].map((one) => [one.id, one]));
});
const nothingDrafted = computed(() => drafted.value.every((kind) => !draft.value[kind].length));

function storedOf(id: string | null): ShownValue | undefined {
  return id === null ? undefined : stored.value.get(id);
}

// a problem stands at its entry's field by the entry's key and the field's (`value-7:unit`)
const { faults, faultsAt, clear } = useFieldFaults<string>({
  control: (at) => `${sid}-${at.replace(":", "-")}`,
  submit: submitButton,
  say: (at, words) => {
    status.value = sayAnew(status.value, t("forms.fieldProblem", { field: faultField(at), problem: words }));
  },
});

/** The field of the problem at `at` (`value-7:unit`) in words, the context it is in or of named first. */
function faultField(at: string): string {
  const [key = "", field = at] = at.split(":");
  const place = draft.value.contexts.findIndex((one) => one.key === key || (!!one.inner && holdsEntry(one.inner, key)));
  if (place < 0) return word(FAULT_WORDS, field);
  const context = t("documents.tree.values.entry.contexts", { place: place + 1 });
  return field === "context" ? context : t("documents.tree.values.inContext", { context, field: word(FAULT_WORDS, field) });
}

// A value reviewed that is gone or changed meanwhile is no row gone: the tree is read again, the row kept. Told in
// words that name the value, apart from the row's own status set beside it
function reviewed(done: Exclude<ReviewOutcome, { outcome: "failed" }>, key: HolderKey, value: ShownValue): void {
  const told = done.outcome === "gone" ? ({ outcome: "stale" } as const) : done;
  props.onReviewed?.(told, key, valueReviewWords(told, value.words, value.review.table));
}

watch(dirty, (open) => emit("dirty", open), { immediate: true });
watch(
  () => props.row.key,
  () => clear(),
);
onBeforeUnmount(() => emit("dirty", false));

function change(kind: DraftKind, entries: Entry[]): void {
  draft.value = { ...draft.value, [kind]: entries };
}

async function submit(): Promise<void> {
  if (saving.value) return;
  const { outcome, faults: found, answer } = await editing.save();
  await nextTick();
  const said: Partial<Record<typeof outcome, string>> = {
    saved: t("documents.tree.form.saved"),
    unchanged: t("documents.tree.form.unchanged"),
    undecided: t("documents.tree.conflict.undecided"),
  };
  const words = said[outcome];
  status.value = words ? sayAnew(status.value, words) : "";
  if (outcome === "saved" || outcome === "unchanged") clear();
  if (outcome === "saved" && answer) props.onSaved?.(answer);
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
    <h3 v-if="named === null" :id="`${sid}-heading`">{{ t("documents.tree.values.heading") }}</h3>
    <h4 v-else :id="`${sid}-heading`">{{ t("documents.page.scope.valuesHeading", { title: named }) }}</h4>
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
          v-for="kind in drafted"
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
            <StoredValue :row="row" :value="storedOf(entry.id)" :reviewable="reviewable" :document-id="documentId" :on-reviewed="reviewed" />
          </template>
          <template v-if="kind === 'contexts'" #item="{ entry, place, change: changed, remove }">
            <ContextItemForm :entry="entry" :place="place" :form="form" :sid="sid" :faults="faults" @change="changed" @remove="remove">
              <template #default="{ entry: one }">
                <StoredValue :row="row" :value="storedOf(one.id)" :reviewable="reviewable" :document-id="documentId" :on-reviewed="reviewed" />
              </template>
            </ContextItemForm>
          </template>
        </ValueEntries>
        <LoadingState v-if="saving" quiet :label="t('documents.tree.values.saving')" />
        <!-- aria-disabled, not disabled: a disabled button drops the focus it holds -->
        <button
          ref="submitButton"
          type="submit"
          class="btn primary value-section__save"
          :aria-label="named === null ? undefined : t('documents.page.scope.valuesSaveNamed', { title: named })"
          :aria-disabled="saving || undefined"
        >
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
