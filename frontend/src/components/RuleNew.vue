<script setup lang="ts">
/**
 * A rule an editor adds to a document (plan M3a I; backend POST /documents/{id}/rules): its kind, its wording and the
 * page of the file it stands on, its anchor - the blocks of a page are chosen in the tree's source pane, the page
 * alone here. Each problem the server would refuse is found first and stood at its field, as is one the server names,
 * a missing anchor at the page. Made, it hands the rule to the section (`created`); a document closed meanwhile has
 * the section read again (`changed`). Cancelled, nothing is sent (`cancel`). It tells the section whether an entry is
 * open (`dirty`).
 */
import { computed, onBeforeUnmount, onMounted, ref, useId, watch } from "vue";

import { ApiError, addRule, type FormField, type Rule, type RuleKind } from "@/api";
import AppIcon from "@/components/AppIcon.vue";
import FormFieldInput from "@/components/FormFieldInput.vue";
import NoticeText from "@/components/NoticeText.vue";
import { useFieldFaults } from "@/fieldFaults";
import { requiredLabel } from "@/formWords";
import { messages, t } from "@/i18n/de";
import { sayAnew } from "@/liveRegion";
import { failureNotice, type Notice } from "@/notice";
import { refusalText } from "@/refusals";
import { problemText } from "@/rowRefusals";
import { MOST_VERBATIM, RULE_KINDS, choice } from "@/ruleDraft";
import { kindWord } from "@/ruleWords";

const props = defineProps<{ documentId: string }>();
const emit = defineEmits<{ created: [rule: Rule]; changed: []; cancel: []; dirty: [open: boolean] }>();

type Field = "kind" | "verbatim" | "page";
const CLOSING: ReadonlySet<string> = new Set(["frozen", "job_open", "not_extracted", "no_document"]);
const LABELS: Readonly<Record<string, string>> = messages.documents.page.rules.fields;
const PAGE = /^[1-9]\d{0,4}$/;

const id = useId();
const draft = ref({ kind: "", verbatim: "", page: "" });
const busy = ref(false);
const status = ref("");
const failure = ref<Notice | null>(null);
const submit = ref<HTMLElement | null>(null);
const heading = ref<HTMLElement | null>(null);

const kindField: FormField = {
  key: "kind",
  kind: "concept",
  required: true,
  many: false,
  most: null,
  values: RULE_KINDS.map((kind) => choice(kind, kindWord(kind))),
};
const verbatimField: FormField = { key: "verbatim", kind: "longtext", required: true, many: false, most: MOST_VERBATIM, values: null };
const open = computed(() => Boolean(draft.value.kind || draft.value.verbatim.trim() || draft.value.page.trim()));

const { faults, faultsAt, clear } = useFieldFaults<Field>({
  control: (field) => `${id}-${field}`,
  submit,
  say: (field, problem) => {
    status.value = sayAnew(status.value, t("documents.page.rules.fieldProblem", { field: LABELS[field] ?? field, problem }));
  },
});

watch(open, (now) => emit("dirty", now), { immediate: true });
onBeforeUnmount(() => emit("dirty", false));
onMounted(() => heading.value?.focus());

function problems(): [Field, string][] {
  const found: [Field, string][] = [];
  if (!draft.value.kind) found.push(["kind", t("documents.tree.problems.required")]);
  if (!draft.value.verbatim.trim()) found.push(["verbatim", t("documents.tree.problems.required")]);
  if (!PAGE.test(draft.value.page.trim())) found.push(["page", t("documents.page.rules.problems.not_page")]);
  return found;
}

async function onSubmit(): Promise<void> {
  if (busy.value) return;
  failure.value = null;
  clear();
  const found = problems();
  if (found.length) {
    await faultsAt(found);
    return;
  }
  busy.value = true;
  try {
    const made = await addRule(props.documentId, {
      kind: draft.value.kind as RuleKind,
      verbatim: draft.value.verbatim,
      anchors: [{ page: Number(draft.value.page.trim()) }],
    });
    draft.value = { kind: "", verbatim: "", page: "" };
    emit("created", made);
  } catch (error) {
    await refused(error);
  } finally {
    busy.value = false;
  }
}

async function refused(error: unknown): Promise<void> {
  const code = error instanceof ApiError ? error.code : undefined;
  const details = error instanceof ApiError ? error.details : {};
  if (code === "anchor_missing" || (code === "invalid_field" && details.field === "anchors")) {
    await faultsAt([["page", t("documents.page.rules.problems.not_page")]]);
  } else if (code === "invalid_field" && (details.field === "kind" || details.field === "verbatim")) {
    await faultsAt([[details.field, problemText(details.problem)]]);
  } else if (code && CLOSING.has(code)) {
    failure.value = { text: refusalText(code) ?? t("documents.page.rules.createFailed"), failed: true };
    emit("changed");
  } else {
    failure.value = failureNotice(error, t("documents.page.rules.createFailed"));
  }
}
</script>

<template>
  <form class="rule-new" novalidate @submit.prevent="onSubmit">
    <!-- tabindex -1: where the keyboard goes as the form opens -->
    <h4 ref="heading" tabindex="-1">{{ t("documents.page.rules.newHeading") }}</h4>
    <FormFieldInput v-model="draft.kind" :field="kindField" :values="kindField.values ?? []" :labels="LABELS"
      :control-id="`${id}-kind`" :error="faults.kind ?? null" />
    <FormFieldInput v-model="draft.verbatim" :field="verbatimField" :values="[]" :labels="LABELS"
      :control-id="`${id}-verbatim`" :error="faults.verbatim ?? null" />
    <div class="field">
      <label :for="`${id}-page`">{{ requiredLabel(LABELS.page) }}</label>
      <input
        :id="`${id}-page`"
        v-model="draft.page"
        type="text"
        inputmode="numeric"
        autocomplete="off"
        maxlength="5"
        aria-required="true"
        :aria-invalid="faults.page !== undefined || undefined"
        :aria-describedby="faults.page !== undefined ? `${id}-page-hint ${id}-page-error` : `${id}-page-hint`"
      />
      <p v-if="faults.page !== undefined" :id="`${id}-page-error`" class="field__error"><AppIcon name="warning" /> {{ faults.page }}</p>
      <p :id="`${id}-page-hint`" class="field__hint">{{ t("documents.page.rules.pageHint") }}</p>
    </div>
    <p v-if="failure" class="field__error" role="alert"><AppIcon name="warning" /> <NoticeText :notice="failure" /></p>
    <div class="rule-new__actions">
      <button ref="submit" type="submit" class="btn primary" :aria-disabled="busy || undefined">
        {{ t("documents.page.rules.create") }}
      </button>
      <button type="button" class="btn secondary" @click="emit('cancel')">{{ t("documents.page.rules.cancel") }}</button>
    </div>
    <p class="rule-new__status" role="status">{{ status }}</p>
  </form>
</template>

<style scoped>
.rule-new {
  display: grid;
  gap: var(--space-2);
  max-width: var(--reading-width);
}

.rule-new h4,
.rule-new__status {
  margin: 0;
}

.rule-new__actions {
  display: flex;
  flex-wrap: wrap;
  gap: var(--space-2);
}

.rule-new__status:empty {
  position: absolute;
}
</style>
