<script setup lang="ts">
/**
 * A specification's title and field (plan M3a H1; backend PATCH /specifications/{id}), by the document's owner or an
 * editor, on the revision it was read at: only what changed is sent, an emptied field as none. Saved, it says so and
 * hands the specification as stored to the section (`saved`). A field's problem stands at the field, the entry kept;
 * changed meanwhile, the specification as it stands is shown and said, the entry kept for a second try; a document
 * closed meanwhile has the section read again (`changed`). The kind and key it does not touch: X1's, and the key is
 * what the specification's IRI is made of.
 */
import { computed, ref, useId, watch } from "vue";

import { ApiError, editSpecification, type Specification, type SpecificationFields } from "@/api";
import AppIcon from "@/components/AppIcon.vue";
import NoticeText from "@/components/NoticeText.vue";
import { useFieldFaults } from "@/fieldFaults";
import { t } from "@/i18n/de";
import { sayAnew } from "@/liveRegion";
import { failureNotice, type Notice } from "@/notice";
import { refusalText } from "@/refusals";
import { problemText } from "@/rowRefusals";

const props = defineProps<{ specification: Specification }>();
const emit = defineEmits<{ saved: [specification: Specification]; changed: [] }>();

type Field = "title" | "field_text";
const FIELDS: readonly Field[] = ["title", "field_text"];
// a refusal that closes the document to the change: the section reads it again
const CLOSING: ReadonlySet<string> = new Set(["frozen", "job_open", "not_extracted", "no_specification"]);

const id = useId();
const draftOf = (specification: Specification) => ({
  title: specification.title,
  field_text: specification.field_text ?? "",
});
const base = ref(props.specification);
const draft = ref(draftOf(props.specification));
const busy = ref(false);
const status = ref("");
const failure = ref<Notice | null>(null);
const submit = ref<HTMLElement | null>(null);

const inputs = computed(() => [
  {
    key: "title" as const,
    label: t("documents.page.scope.title"),
    hint: t("documents.page.scope.titleHint"),
    max: 1000,
    required: true,
  },
  {
    key: "field_text" as const,
    label: t("documents.page.scope.fieldText"),
    hint: t("documents.page.scope.fieldTextHint"),
    max: 2000,
    required: false,
  },
]);

// Read anew: a field the user left as it was takes the value read, an entry made meanwhile stays
function rebase(now: Specification): void {
  const was = draftOf(base.value);
  const next = draftOf(now);
  for (const key of FIELDS) if (draft.value[key].trim() === was[key].trim()) draft.value[key] = next[key];
  base.value = now;
}

watch(
  () => props.specification,
  (now) => rebase(now),
);

const { faults, faultsAt, clear } = useFieldFaults<Field>({
  control: (field) => `${id}-${field}`,
  submit,
  say: (field, problem) => {
    const label = inputs.value.find((input) => input.key === field)?.label ?? "";
    status.value = sayAnew(status.value, t("documents.page.scope.fieldProblem", { field: label, problem }));
  },
});

function describedBy(field: Field): string {
  const hint = `${id}-${field}-hint`;
  return faults.value[field] ? `${hint} ${id}-${field}-error` : hint;
}

/** The fields the draft changes, both sides trimmed; an emptied field text none. */
function changes(): SpecificationFields {
  const found: SpecificationFields = {};
  const title = draft.value.title.trim();
  if (title !== base.value.title.trim()) found.title = draft.value.title;
  const field = draft.value.field_text.trim() || null;
  if (field !== (base.value.field_text?.trim() || null)) found.field_text = field;
  return found;
}

function refuse(text: string): void {
  failure.value = { text: sayAnew(failure.value?.text ?? "", text), failed: true };
}

async function onSubmit(): Promise<void> {
  if (busy.value) return; // the button stays focusable while busy, so it can be pressed again
  const changed = changes();
  failure.value = null;
  clear();
  if (!Object.keys(changed).length) {
    status.value = sayAnew(status.value, t("documents.page.scope.unchanged"));
    return;
  }
  status.value = "";
  busy.value = true;
  try {
    const saved = await editSpecification(base.value.id, base.value.revision, changed);
    base.value = saved;
    draft.value = draftOf(saved);
    status.value = sayAnew(status.value, t("documents.page.scope.saved"));
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
  if (code === "invalid_field" && FIELDS.includes(details.field as Field)) {
    await faultsAt([[details.field as Field, problemText(details.problem)]]);
  } else if (code === "stale_revision" && typeof details.current === "object" && details.current !== null) {
    refuse(t("documents.page.scope.changedMeanwhile"));
    emit("saved", details.current as Specification);
  } else if (code && CLOSING.has(code)) {
    refuse(refusalText(code) ?? t("documents.page.scope.saveFailed"));
    emit("changed");
  } else {
    failure.value = failureNotice(error, t("documents.page.scope.saveFailed"));
  }
}
</script>

<template>
  <form class="specification-form" novalidate @submit.prevent="onSubmit">
    <h4>{{ t("documents.page.scope.formHeading", { title: base.title }) }}</h4>
    <div v-for="input in inputs" :key="input.key" class="field">
      <label :for="`${id}-${input.key}`">{{ input.label }}</label>
      <input
        :id="`${id}-${input.key}`"
        v-model="draft[input.key]"
        type="text"
        :maxlength="input.max"
        autocomplete="off"
        :aria-required="input.required || undefined"
        :aria-invalid="faults[input.key] !== undefined || undefined"
        :aria-describedby="describedBy(input.key)"
      />
      <p v-if="faults[input.key] !== undefined" :id="`${id}-${input.key}-error`" class="field__error">
        <AppIcon name="warning" /> {{ faults[input.key] }}
      </p>
      <p :id="`${id}-${input.key}-hint`" class="field__hint">{{ input.hint }}</p>
    </div>
    <p v-if="failure" class="field__error specification-form__error" role="alert">
      <AppIcon name="warning" /> <NoticeText :notice="failure" />
    </p>
    <!-- aria-disabled, not disabled: a disabled button drops the focus it holds -->
    <button
      ref="submit"
      type="submit"
      class="btn primary"
      :aria-label="t('documents.page.scope.saveNamed', { title: base.title })"
      :aria-disabled="busy || undefined"
    >
      {{ t("documents.page.scope.save") }}
    </button>
    <!-- always in the page, so a screen reader hears each change of its text -->
    <p class="specification-form__status" role="status">{{ status }}</p>
  </form>
</template>

<style scoped>
.specification-form {
  display: grid;
  gap: var(--space-2);
  justify-items: start;
  max-width: var(--reading-width);
}

.specification-form .field {
  justify-self: stretch;
}

.specification-form h4,
.specification-form__error,
.specification-form__status {
  margin: 0;
}

/* Empty, it takes no room - as a cell of the grid its gap would stand twice - but stays in the page. */
.specification-form__status:empty {
  position: absolute;
}
</style>
