<script setup lang="ts">
/**
 * Where a node is placed (plan M3a K; placementDraft.ts): "Verwendungen" in the row's panel, under its values - in
 * which of the document's specifications or variants, at which node, how binding and with what weight in the grade.
 * Where the tree is open, a form of entries with a button to add one (PlacementItemForm), saved as the node's whole on
 * its revision; a field's problem stands at its field, the keyboard taken there; changed meanwhile, the entries are
 * kept and said to be, saved again on the node's new revision; a failure is said above the form. Where the tree closed -
 * on this save, or under an open draft as it was read anew (`closedBy`) - it says why and keeps the draft, in words, to
 * copy. Elsewhere each placement reads in words with who stated it. Each stored placement's time spans and workloads
 * stand under it (ValueSection), set on its own revision; the editors review each and its values (PlacementReview, plan
 * M3a L). The entries go on from a node's revision a review moved (`moved`: the node's own too). It tells of a draft.
 */
import { computed, nextTick, onBeforeUnmount, reactive, ref, toRef, useId, watch } from "vue";

import type { Form, NodeRow, Placement, Tree } from "@/api";
import AppIcon from "@/components/AppIcon.vue";
import LoadingState from "@/components/LoadingState.vue";
import NoticeText from "@/components/NoticeText.vue";
import PlacementItemForm from "@/components/PlacementItemForm.vue";
import PlacementList from "@/components/PlacementList.vue";
import PlacementReview from "@/components/PlacementReview.vue";
import ValueSection from "@/components/ValueSection.vue";
import type { Row } from "@/documentTree";
import { useFieldFaults } from "@/fieldFaults";
import { messages, t } from "@/i18n/de";
import { sayAnew } from "@/liveRegion";
import {
  MOST_PLACEMENTS,
  entryPlace,
  inSpecification,
  newEntry,
  obligationChoices,
  placeChoices,
  placementName,
  placementWords,
  specificationChoices,
  variantChoices,
  type PlacementEntry,
  type PlacementField,
  type PlacementPlace,
} from "@/placementDraft";
import { usePlacementSave } from "@/placementSave";
import { refusalText } from "@/refusals";
import { reviewWords, type ReviewOutcome } from "@/rowReview";
import { placementRow, type Holder, type HolderKey } from "@/valueHolder";

const props = defineProps<{
  row: Row;
  tree: Tree;
  form: Form;
  documentId: string;
  /** The caller may set the placements now - or a draft the tree closed under is kept to copy. */
  editable: boolean;
  /** The caller may set the review status of their values now. */
  reviewable: boolean;
  /** Why the tree, read anew, closed; none while it is open. */
  closedBy: string | null;
  /** The node's placements saved, the node as stored: a prop, so a save landing after another row was chosen counts. */
  onSaved?: (answer: NodeRow) => void;
  /** A placement's values saved: the tree is read again. */
  onValuesSaved?: (answer: Holder) => void;
  /** How a review of a placement or of a value at one went, with words that name it. */
  onReviewed?: (done: Exclude<ReviewOutcome, { outcome: "failed" }>, key: HolderKey, words?: string) => void;
}>();
const emit = defineEmits<{ closed: [code: string]; gone: []; dirty: [open: boolean] }>();

const sid = useId();
const node = computed(() => (props.row.kind === "node" ? props.row.node : null));
const { entries, saving, failure, closed, dirty: entriesDirty, save, moved } = usePlacementSave(toRef(node));
const status = ref("");
const submitButton = ref<HTMLElement | null>(null);
const addButton = ref<HTMLElement | null>(null);
const closedNotice = ref<HTMLElement | null>(null);
// a placement's values with a draft open, by its id
const valueDrafts = reactive(new Set<string>());

const stored = computed<Placement[]>(() => node.value?.placements ?? []);
const specifications = computed(() => specificationChoices(props.tree.specifications));
const places = computed(() => placeChoices(props.tree.nodes, node.value?.id ?? ""));
const obligations = computed(() => obligationChoices(props.form, entries.value.map((one) => one.obligation)));
const dirty = computed(() => entriesDirty.value || valueDrafts.size > 0);
const shut = computed(() => closed.value ?? props.closedBy);
const mode = computed(() => {
  if (shut.value && entriesDirty.value) return "closed";
  return props.editable && !shut.value ? "form" : "read";
});
const full = computed(() => entries.value.length >= MOST_PLACEMENTS);
const heading = computed(() => {
  const title = node.value?.fields.original_title;
  return typeof title === "string" && title ? title : t("documents.tree.placements.untitled");
});

const labels: Readonly<Record<PlacementField, string>> = messages.documents.tree.placements.fields;
const { faults, faultsAt, clear } = useFieldFaults<string>({
  control: (at) => `${sid}-${at.replace(":", "-")}`,
  submit: submitButton,
  say: (at, words) => {
    const field = (at.split(":")[1] ?? "") as PlacementField;
    status.value = sayAnew(status.value, t("forms.fieldProblem", { field: labels[field] ?? field, problem: words }));
  },
});

watch(dirty, (open) => emit("dirty", open), { immediate: true });
onBeforeUnmount(() => emit("dirty", false));
defineExpose({ moved });

function wordsOf(placement: PlacementPlace): string {
  return placementWords(placement, props.tree.specifications, props.tree.nodes, props.form);
}

/** The stored placement an entry keeps; none for a new one. */
function storedOf(id: string | null): Placement | undefined {
  return stored.value.find((each) => each.id === id);
}

function holderOf(placement: Placement) {
  return placementRow(placement, placementName(placement, props.tree.specifications, props.tree.nodes));
}

// a set of a placement's values counted the node's revision too: the entries go on from it
function valuesSaved(answer: Holder): void {
  if ("node_revision" in answer && typeof answer.node_revision === "number") moved(answer.node_revision);
  props.onValuesSaved?.(answer);
}

// a review here counted the node's revision, which it names: go on from it; said here, as the panel says its row's alone
function reviewed(done: Exclude<ReviewOutcome, { outcome: "failed" }>, key: HolderKey, words?: string): void {
  const now = done.outcome === "set" ? done.nodes.find((one) => one.id === node.value?.id) : undefined;
  if (now) moved(now.revision);
  status.value = sayAnew(status.value, words ?? reviewWords(done));
  props.onReviewed?.(done, key, words);
}

function valueDirty(id: string, open: boolean): void {
  if (open) valueDrafts.add(id);
  else valueDrafts.delete(id);
}

async function add(): Promise<void> {
  if (full.value) return;
  const made = newEntry(props.tree.specifications);
  entries.value = [...entries.value, made];
  status.value = sayAnew(status.value, t("documents.tree.placements.added", { place: entries.value.length }));
  await nextTick();
  document.getElementById(`${sid}-${made.key}-specification_id`)?.focus();
}

async function remove(place: number): Promise<void> {
  entries.value = entries.value.filter((_, at) => at !== place);
  status.value = sayAnew(status.value, t("documents.tree.placements.removed", { place: place + 1 }));
  await nextTick();
  addButton.value?.focus();
}

function change(place: number, entry: PlacementEntry): void {
  const fitted = inSpecification(entry, entry.specification_id, props.tree.specifications);
  entries.value = entries.value.map((one, at) => (at === place ? fitted : one));
}

async function submit(): Promise<void> {
  if (saving.value) return; // the button stays focusable while busy, so it can be pressed again
  clear();
  const { outcome, faults: found, answer } = await save();
  await nextTick();
  if (outcome === "invalid") await faultsAt(found ?? []);
  else if (outcome === "unchanged") status.value = sayAnew(status.value, t("documents.tree.form.unchanged"));
  else if (outcome === "saved" && answer) {
    status.value = sayAnew(status.value, t("documents.tree.form.saved"));
    props.onSaved?.(answer);
  } else if (outcome === "closed" && closed.value) {
    closedNotice.value?.focus();
    emit("closed", closed.value);
  } else if (outcome === "gone") emit("gone");
}
</script>

<template>
  <section v-if="node" class="node-placements" :aria-labelledby="`${sid}-heading`">
    <h3 :id="`${sid}-heading`">{{ t("documents.tree.placements.heading") }}</h3>
    <p class="node-placements__intro">{{ t("documents.tree.placements.intro") }}</p>

    <section v-if="mode === 'closed'" ref="closedNotice" class="node-placements__closed" tabindex="-1" :aria-label="t('documents.tree.form.closedLabel')">
      <p class="field__error" role="alert"><AppIcon name="warning" /> {{ refusalText(shut ?? "") }}</p>
      <p>{{ t("documents.tree.form.keptDraft") }}</p>
      <ul>
        <li v-for="entry in entries" :key="entry.key"><bdi>{{ wordsOf(entryPlace(entry)) }}</bdi></li>
      </ul>
    </section>

    <template v-else-if="mode === 'form' && specifications.length">
      <p v-if="failure" class="field__error node-placements__problem" role="alert"><AppIcon name="warning" /> <NoticeText :notice="failure" /></p>
      <p v-if="!entries.length" class="node-placements__none">{{ t("documents.tree.placements.none") }}</p>
      <form class="node-placements__form" novalidate @submit.prevent="submit">
        <PlacementItemForm
          v-for="(entry, place) in entries"
          :key="entry.key"
          :entry="entry"
          :place="place"
          :sid="sid"
          :specifications="specifications"
          :variants="variantChoices(tree.specifications, entry.specification_id)"
          :places="places"
          :obligations="obligations"
          :faults="faults"
          @change="(one) => change(place, one)"
          @remove="remove(place)"
        >
          <template #default="{ entry: one }">
            <PlacementReview
              v-if="storedOf(one.id)"
              :row="holderOf(storedOf(one.id) as Placement)"
              :reviewable="reviewable"
              :document-id="documentId"
              :on-reviewed="reviewed"
            />
          </template>
        </PlacementItemForm>
        <!-- aria-disabled, not disabled: a disabled button drops the focus it holds -->
        <button
          ref="addButton"
          type="button"
          class="btn btn-sm secondary node-placements__add"
          :aria-disabled="full || undefined"
          :aria-describedby="full ? `${sid}-most` : undefined"
          @click="add"
        >
          {{ t("documents.tree.placements.add") }}
        </button>
        <p v-if="full" :id="`${sid}-most`" class="field__hint">{{ t("documents.tree.placements.most", { most: MOST_PLACEMENTS }) }}</p>
        <LoadingState v-if="saving" quiet :label="t('documents.tree.placements.saving')" />
        <button
          ref="submitButton"
          type="submit"
          class="btn primary node-placements__save"
          :aria-label="t('documents.tree.placements.saveNamed', { title: heading })"
          :aria-disabled="saving || undefined"
        >
          {{ t("documents.tree.placements.save") }}
        </button>
      </form>
    </template>

    <PlacementList v-else :placements="stored" :tree="tree" :form="form" />

    <ValueSection
      v-for="placement in stored"
      :key="placement.id"
      :row="holderOf(placement)"
      :form="form"
      :document-id="documentId"
      :editable="editable"
      :reviewable="reviewable"
      :closed-by="closedBy"
      :on-saved="valuesSaved"
      :on-reviewed="reviewed"
      @closed="(code) => emit('closed', code)"
      @gone="emit('gone')"
      @dirty="(open) => valueDirty(placement.id, open)"
    />
    <!-- always in the page, so the first word is read out -->
    <p class="node-placements__status" role="status">{{ status }}</p>
  </section>
</template>

<style scoped>
.node-placements {
  display: grid;
  gap: var(--space-1);
}

.node-placements h3,
.node-placements p {
  margin: 0;
}

.node-placements__intro,
.node-placements__none {
  color: var(--text-muted);
}

.node-placements__form {
  display: grid;
  gap: var(--space-2);
}

.node-placements__add,
.node-placements__save {
  justify-self: start;
}

.node-placements__closed li {
  overflow-wrap: anywhere;
}

.node-placements__closed {
  display: grid;
  gap: var(--space-1);
}
</style>
