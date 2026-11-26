<script setup lang="ts">
/**
 * One assessment's fields (plan M3a J; backend POST /documents/{id}/assessments, PATCH /assessments/{id}): new under a
 * parent, or kept and changed on the revision it was read at - then only what changed is sent. Its parent - a
 * specification, a node of the outline, or an assessment but itself and its own parts -, its kind from the list, its
 * name, duration in whole minutes and weight in percent written the German way, whether it is graded, and the nodes
 * it assesses (with what it assesses beside them, kept): as assessmentDraft.ts writes and checks them. A field's problem stands at its field,
 * the entry kept; changed meanwhile, the assessment as it stands is shown and said, the entry kept for a second try; a
 * document closed meanwhile has the section read again (`changed`). It tells the section whether a change is open
 * (`dirty`, the leave guard).
 */
import { computed, onBeforeUnmount, ref, useId, watch } from "vue";

import { ApiError, addAssessment, editAssessment, type Assessment, type Assessments } from "@/api";
import AppIcon from "@/components/AppIcon.vue";
import NoticeText from "@/components/NoticeText.vue";
import { FIELDS, changedFields, draftOf, fieldsOf, parentsOf, targetsOf, type Field } from "@/assessmentDraft";
import { assessmentTitle } from "@/assessmentWords";
import { useFieldFaults } from "@/fieldFaults";
import { messages, t } from "@/i18n/de";
import { sayAnew } from "@/liveRegion";
import { failureNotice, type Notice } from "@/notice";
import { refusalText } from "@/refusals";
import { word } from "@/registerWords";
import { problemText } from "@/rowRefusals";

const props = defineProps<{
  documentId: string;
  read: Assessments;
  /** The assessment kept and changed; none for a new one. */
  assessment?: Assessment;
  /** A new one's parent, where it is added as a part of one. */
  parentId?: string;
}>();
const emit = defineEmits<{ saved: [assessment: Assessment]; changed: []; cancel: []; dirty: [open: boolean] }>();

// a refusal that closes the document to the change: the section reads it again
const CLOSING: ReadonlySet<string> = new Set(["frozen", "job_open", "not_extracted", "no_assessment", "no_document"]);

const id = useId();
const base = ref(props.assessment);
const draft = ref(draftOf(props.assessment, props.parentId));
const start = draftOf(props.assessment, props.parentId);
const busy = ref(false);
const status = ref("");
const failure = ref<Notice | null>(null);
const submit = ref<HTMLElement | null>(null);
// each field's label and hint, by its key
const labels: Readonly<Record<Field, string>> = messages.documents.page.assessments.fields;
const hints: Readonly<Record<Field, string>> = messages.documents.page.assessments.hints;

const heading = computed(() => {
  if (base.value) return t("documents.page.assessments.editHeading", { title: assessmentTitle(base.value) });
  const parent = props.read.assessments.find((one) => one.id === props.parentId);
  return parent ? t("documents.page.assessments.addPartHeading", { title: assessmentTitle(parent) }) : t("documents.page.assessments.addHeading");
});
const parents = computed(() => parentsOf(props.read, base.value));
const targets = computed(() => targetsOf(props.read, base.value));

watch(
  () => props.assessment,
  (now) => {
    if (now && base.value && now.revision > base.value.revision) base.value = now;
  },
);

const { faults, faultsAt, clear } = useFieldFaults<Field>({
  control: (field) => `${id}-${field}`,
  submit,
  say: (field, problem) => {
    status.value = sayAnew(status.value, t("documents.page.assessments.fieldProblem", { field: labels[field], problem }));
  },
});

function describedBy(field: Field): string {
  return faults.value[field] ? `${id}-${field}-hint ${id}-${field}-error` : `${id}-${field}-hint`;
}

const dirty = computed(() => JSON.stringify(draft.value) !== JSON.stringify(start));
watch(dirty, (open) => emit("dirty", open), { immediate: true });
onBeforeUnmount(() => emit("dirty", false));

async function onSubmit(): Promise<void> {
  if (busy.value) return; // the button stays focusable while busy, so it can be pressed again
  failure.value = null;
  clear();
  const [fields, problems] = fieldsOf(draft.value);
  if (problems.length) {
    await faultsAt(problems);
    return;
  }
  const changes = base.value ? changedFields(fields, start) : fields;
  if (!Object.keys(changes).length) {
    status.value = sayAnew(status.value, t("documents.page.assessments.unchanged"));
    return;
  }
  busy.value = true;
  try {
    const saved = base.value
      ? await editAssessment(base.value.id, base.value.revision, changes)
      : await addAssessment(props.documentId, fields);
    emit("saved", saved);
  } catch (error) {
    await refused(error);
  } finally {
    busy.value = false;
  }
}

async function refused(error: unknown): Promise<void> {
  const code = error instanceof ApiError ? error.code : undefined;
  const details = error instanceof ApiError ? error.details : {};
  const field = typeof details.field === "string" ? (details.field.replace(/\[\d+\]$/, "") as Field) : null;
  if (code === "invalid_field" && field && FIELDS.includes(field)) {
    await faultsAt([[field, problemText(details.problem)]]);
  } else if (code === "stale_revision" && typeof details.current === "object" && details.current !== null) {
    base.value = details.current as Assessment;
    failure.value = { text: sayAnew(failure.value?.text ?? "", t("documents.page.assessments.changedMeanwhile")), failed: true };
  } else if (code && CLOSING.has(code)) {
    failure.value = { text: refusalText(code) ?? t("documents.page.assessments.saveFailed"), failed: true };
    emit("changed");
  } else {
    failure.value = failureNotice(error, t("documents.page.assessments.saveFailed"));
  }
}
</script>

<template>
  <form class="assessment-form" novalidate @submit.prevent="onSubmit">
    <h4>{{ heading }}</h4>
    <div class="field">
      <label :for="`${id}-parent_id`">{{ labels.parent_id }}</label>
      <select :id="`${id}-parent_id`" v-model="draft.parent_id" aria-required="true" :aria-invalid="faults.parent_id !== undefined || undefined"
        :aria-describedby="describedBy('parent_id')">
        <option value="">{{ t("documents.page.assessments.choose") }}</option>
        <optgroup v-for="group in parents" :key="group.group" :label="word(messages.documents.page.assessments.groups, group.group)">
          <option v-for="option in group.options" :key="option.id" :value="option.id">{{ option.label }}</option>
        </optgroup>
      </select>
      <p v-if="faults.parent_id !== undefined" :id="`${id}-parent_id-error`" class="field__error"><AppIcon name="warning" /> {{ faults.parent_id }}</p>
      <p :id="`${id}-parent_id-hint`" class="field__hint">{{ hints.parent_id }}</p>
    </div>
    <div class="field">
      <label :for="`${id}-assessment_kind`">{{ labels.assessment_kind }}</label>
      <select :id="`${id}-assessment_kind`" v-model="draft.assessment_kind" aria-required="true"
        :aria-invalid="faults.assessment_kind !== undefined || undefined" :aria-describedby="describedBy('assessment_kind')">
        <option value="">{{ t("documents.page.assessments.choose") }}</option>
        <option v-for="kind in read.kinds" :key="kind.iri" :value="kind.iri">{{ kind.label }}</option>
      </select>
      <p v-if="faults.assessment_kind !== undefined" :id="`${id}-assessment_kind-error`" class="field__error">
        <AppIcon name="warning" /> {{ faults.assessment_kind }}
      </p>
      <p :id="`${id}-assessment_kind-hint`" class="field__hint">{{ hints.assessment_kind }}</p>
    </div>
    <div v-for="field in ['label', 'duration_minutes', 'weight_percent'] as const" :key="field" class="field">
      <label :for="`${id}-${field}`">{{ labels[field] }}</label>
      <input :id="`${id}-${field}`" v-model="draft[field]" type="text" :maxlength="field === 'label' ? 1000 : 20" autocomplete="off"
        :inputmode="field === 'label' ? undefined : 'decimal'" :aria-invalid="faults[field] !== undefined || undefined"
        :aria-describedby="describedBy(field)" />
      <p v-if="faults[field] !== undefined" :id="`${id}-${field}-error`" class="field__error"><AppIcon name="warning" /> {{ faults[field] }}</p>
      <p :id="`${id}-${field}-hint`" class="field__hint">{{ hints[field] }}</p>
    </div>
    <div class="field">
      <label :for="`${id}-graded`">{{ labels.graded }}</label>
      <select :id="`${id}-graded`" v-model="draft.graded" :aria-describedby="describedBy('graded')">
        <option value="">{{ t("documents.page.assessments.gradedUnknown") }}</option>
        <option value="yes">{{ t("documents.page.assessments.yes") }}</option>
        <option value="no">{{ t("documents.page.assessments.no") }}</option>
      </select>
      <p :id="`${id}-graded-hint`" class="field__hint">{{ hints.graded }}</p>
    </div>
    <fieldset :id="`${id}-targets`" class="assessment-form__targets" tabindex="-1" :aria-describedby="describedBy('targets')">
      <legend>{{ labels.targets }}</legend>
      <p :id="`${id}-targets-hint`" class="field__hint">{{ hints.targets }}</p>
      <p v-if="faults.targets !== undefined" :id="`${id}-targets-error`" class="field__error"><AppIcon name="warning" /> {{ faults.targets }}</p>
      <p v-if="!targets.length">{{ t("documents.page.assessments.noChoices") }}</p>
      <label v-for="target in targets" :key="target.id" class="assessment-form__target">
        <input v-model="draft.targets" type="checkbox" :value="target.id" /> <bdi>{{ target.label }}</bdi>
      </label>
    </fieldset>
    <p v-if="failure" class="field__error assessment-form__error" role="alert"><AppIcon name="warning" /> <NoticeText :notice="failure" /></p>
    <div class="assessment-form__actions">
      <!-- aria-disabled, not disabled: a disabled button drops the focus it holds -->
      <button ref="submit" type="submit" class="btn primary" :aria-label="t('documents.page.assessments.saveNamed', { title: heading })"
        :aria-disabled="busy || undefined">
        {{ t("documents.page.assessments.save") }}
      </button>
      <button type="button" class="btn secondary" @click="emit('cancel')">{{ t("documents.page.assessments.cancel") }}</button>
    </div>
    <!-- always in the page, so a screen reader hears each change of its text -->
    <p class="assessment-form__status" role="status">{{ status }}</p>
  </form>
</template>

<style scoped>
.assessment-form {
  display: grid;
  gap: var(--space-2);
  justify-items: start;
  max-width: var(--reading-width);
}

.assessment-form .field,
.assessment-form__targets {
  justify-self: stretch;
}

/* a long name of a parent or a kind does not widen the page: the select keeps to the form (SC 1.4.10) */
.assessment-form select {
  max-inline-size: 100%;
}

.assessment-form h4,
.assessment-form__error,
.assessment-form__status {
  margin: 0;
}

.assessment-form__targets {
  display: grid;
  gap: var(--space-1);
  margin: 0;
  padding: 0;
  border: 0;
  min-inline-size: 0;
  max-height: 16rem;
  overflow-y: auto;
}

.assessment-form__target {
  overflow-wrap: anywhere;
}

.assessment-form__actions {
  display: flex;
  flex-wrap: wrap;
  gap: var(--space-2);
}

/* Empty, it takes no room - as a cell of the grid its gap would stand twice - but stays in the page. */
.assessment-form__status:empty {
  position: absolute;
}
</style>
