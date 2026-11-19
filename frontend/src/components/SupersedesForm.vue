<script setup lang="ts">
/**
 * The edition a document supersedes (plan M3a B2; backend app/api/document_meta.py), by its owner or an editor until
 * it is frozen: one of the frozen editions of its work under another IRI - each IRI once, as its latest revision -,
 * read from all the documents of its work the caller sees (listWorkDocuments); or none. The edition it
 * supersedes now is offered though the list read lacks it. Without a work, or where the work has no other frozen
 * edition, a sentence says why there is nothing to choose; while the editions are read only that is shown, so no field
 * goes from under the user. Saved, it says so and the page reads the document again (`changed`); the server's problem
 * with the choice stands at the field - the keyboard taken there from the button or from nothing -, a document closed to
 * the change meanwhile is said and read again, another refusal said.
 */
import { computed, onMounted, ref, useId, watch } from "vue";

import { listWorkDocuments, type CurriculumDocument, type SupersededEdition } from "@/api";
import AppIcon from "@/components/AppIcon.vue";
import NoticeText from "@/components/NoticeText.vue";
import { saveMeta } from "@/documentMeta";
import { useFieldFaults } from "@/fieldFaults";
import { t } from "@/i18n/de";
import { sayAnew } from "@/liveRegion";
import type { Notice } from "@/notice";
import { refusalText } from "@/refusals";

const props = defineProps<{ document: CurriculumDocument }>();
const emit = defineEmits<{ changed: [] }>();

const id = useId();
const editions = ref<SupersededEdition[]>([]);
const loading = ref(true);
const loadFailed = ref(false);
const chosen = ref(props.document.supersedes?.id ?? "");
const busy = ref(false);
const status = ref("");
const failure = ref<Notice | null>(null);
const submit = ref<HTMLElement | null>(null);

// the edition it supersedes now, there though the documents read lack it
const offered = computed(() => {
  const now = props.document.supersedes;
  return now && !editions.value.some((one) => one.id === now.id) ? [now, ...editions.value] : editions.value;
});

/** An edition in words: its edition as written, and its IRI. */
function words(one: SupersededEdition): string {
  return t("documents.page.edition.supersedesOption", {
    edition: one.edition || t("documents.page.edition.none"),
    iri: one.iri,
  });
}

/** The frozen editions of the document's work under another IRI than its own, each IRI as its latest revision. */
function editionsOf(documents: readonly CurriculumDocument[]): SupersededEdition[] {
  const work = props.document.work?.id;
  const latest = new Map<string, CurriculumDocument>();
  for (const one of documents) {
    if (!one.frozen_at || !one.iri || one.work?.id !== work || one.iri === props.document.iri) continue;
    const before = latest.get(one.iri);
    if (!before || before.revision < one.revision) latest.set(one.iri, one);
  }
  return [...latest.values()].map((one) => ({ id: one.id, iri: one.iri ?? "", edition: one.edition }));
}

const { faults, faultsAt, clear } = useFieldFaults<"supersedes">({
  control: () => `${id}-supersedes`,
  submit,
  say: (_field, problem) => {
    const field = t("documents.page.edition.supersedesChosen");
    status.value = sayAnew(status.value, t("documents.page.edition.fieldProblem", { field, problem }));
  },
});

// Read anew: a choice the user left as it was takes the value read
watch(
  () => props.document.supersedes?.id ?? "",
  (now, was) => {
    if (chosen.value === was) chosen.value = now;
  },
);

async function onSubmit(): Promise<void> {
  if (busy.value) return; // the button stays focusable while busy, so it can be pressed again
  failure.value = null;
  clear();
  const supersedes = chosen.value || null;
  if (supersedes === (props.document.supersedes?.id ?? null)) {
    status.value = sayAnew(status.value, t("documents.page.edition.unchanged"));
    return;
  }
  status.value = "";
  busy.value = true;
  const done = await saveMeta(props.document.id, { supersedes });
  busy.value = false;
  if (done.outcome === "saved") {
    status.value = sayAnew(status.value, t("documents.page.edition.supersedesSaved"));
    emit("changed");
  } else if (done.outcome === "invalid") {
    if (done.field === "supersedes") await faultsAt([["supersedes", done.problem]]);
    else failure.value = { text: done.problem, failed: true };
  } else if (done.outcome === "failed") {
    failure.value = done.problem;
  } else {
    failure.value = { text: refusalText(done.code) ?? t("documents.page.edition.supersedesFailed"), failed: true };
    if (done.outcome === "closed") emit("changed");
  }
}

onMounted(async () => {
  const work = props.document.work;
  if (!work) {
    loading.value = false;
    return;
  }
  try {
    editions.value = editionsOf(await listWorkDocuments(work.id));
  } catch {
    loadFailed.value = true; // said below; the rest of the page stands
  } finally {
    loading.value = false;
  }
});
</script>

<template>
  <form class="supersedes-form" novalidate @submit.prevent="onSubmit">
    <h3>{{ t("documents.page.edition.supersedesHeading") }}</h3>
    <p class="field__hint">{{ t("documents.page.edition.supersedesIntro") }}</p>
    <p v-if="!document.work" class="field__hint">{{ t("documents.page.edition.supersedesNoWork") }}</p>
    <p v-else-if="loading" class="field__hint">{{ t("documents.page.edition.supersedesLoading") }}</p>
    <p v-else-if="loadFailed && !offered.length" class="field__hint">
      {{ t("documents.page.edition.supersedesLoadFailed") }}
    </p>
    <p v-else-if="!offered.length" class="field__hint">{{ t("documents.page.edition.supersedesNone") }}</p>
    <template v-else>
      <p v-if="loadFailed" class="field__hint">{{ t("documents.page.edition.supersedesLoadFailed") }}</p>
      <div class="field">
        <label :for="`${id}-supersedes`">{{ t("documents.page.edition.supersedesChosen") }}</label>
        <select
          :id="`${id}-supersedes`"
          v-model="chosen"
          :aria-invalid="Boolean(faults.supersedes) || undefined"
          :aria-describedby="faults.supersedes ? `${id}-supersedes-error` : undefined"
        >
          <option value="">{{ t("documents.page.edition.supersedesNothing") }}</option>
          <option v-for="one in offered" :key="one.id" :value="one.id">{{ words(one) }}</option>
        </select>
        <p v-if="faults.supersedes" :id="`${id}-supersedes-error`" class="field__error">
          <AppIcon name="warning" /> {{ faults.supersedes }}
        </p>
      </div>
      <p v-if="failure" class="field__error supersedes-form__error" role="alert">
        <AppIcon name="warning" /> <NoticeText :notice="failure" />
      </p>
      <!-- aria-disabled, not disabled: a disabled button drops the focus it holds -->
      <button ref="submit" type="submit" class="btn secondary" :aria-disabled="busy || undefined">
        {{ t("documents.page.edition.supersedesSave") }}
      </button>
    </template>
    <!-- always in the page, so a screen reader hears each change of its text -->
    <p class="supersedes-form__status" role="status">{{ status }}</p>
  </form>
</template>

<style scoped>
.supersedes-form {
  display: grid;
  gap: var(--space-2);
  justify-items: start;
  max-width: var(--reading-width);
}

.supersedes-form .field {
  justify-self: stretch;
}

.supersedes-form h3,
.supersedes-form p {
  margin: 0;
}

/* Empty, it takes no room - as a cell of the grid its gap would stand twice - but stays in the page. */
.supersedes-form__status:empty {
  position: absolute;
}
</style>
