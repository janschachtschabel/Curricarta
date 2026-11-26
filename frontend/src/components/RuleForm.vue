<script setup lang="ts">
/**
 * One rule's kind, wording, values and links (plan M3a I; backend PATCH /rules/{id}), by the document's owner or an
 * editor, on the revision it was read at: only what changed is sent (ruleDraft.ts), each field's problem the server
 * would refuse found first and stood at its field, as is one the server names. Saved, it says so and hands the rule as
 * stored to the section (`saved`); changed meanwhile, the rule as it stands is shown and said, the entry kept for a
 * second try; a document closed meanwhile, or the rule gone, has the section read again (`changed`). A kind shows the
 * fields it holds alone. The rule is taken away after a question - a run's rejected and kept, an editor's own deleted
 * (`taken`); a run's rejected already is not offered so again. The rows a rule names are chosen through a search
 * (RuleTargets.vue), not from every node at once. Opened, it takes the keyboard to its heading; closed, nothing is
 * sent (`close`) - over a draft only once the user confirms it goes. It tells the section whether an entry the user made is open (`dirty`, the leave guard): a rule the
 * run read with what its kind does not show is none.
 */
import { computed, onBeforeUnmount, onMounted, ref, useId, watch } from "vue";

import { ApiError, editRule, takeRule, type FormField, type FormValue, type Rule, type Rules } from "@/api";
import AppIcon from "@/components/AppIcon.vue";
import ConfirmDialog from "@/components/ConfirmDialog.vue";
import FormFieldInput from "@/components/FormFieldInput.vue";
import NoticeText from "@/components/NoticeText.vue";
import RuleTargets from "@/components/RuleTargets.vue";
import { useFieldFaults } from "@/fieldFaults";
import { messages, t } from "@/i18n/de";
import { sayAnew } from "@/liveRegion";
import { failureNotice, type Notice } from "@/notice";
import { refusalText } from "@/refusals";
import { statusOf } from "@/reviewStatus";
import { problemText } from "@/rowRefusals";
import { MOST_VERBATIM, RULE_KINDS, changesOf, choice as value, draftOf, holds, isDirty, rebased, type RuleField } from "@/ruleDraft";
import { kindWord, ruleName } from "@/ruleWords";

const props = defineProps<{ rule: Rule; rules: Rules }>();
const emit = defineEmits<{ saved: [rule: Rule]; changed: []; taken: [words: string]; close: []; dirty: [open: boolean] }>();

// a refusal that closes the document to the change, or the rule gone: the section reads it again
const CLOSING: ReadonlySet<string> = new Set(["frozen", "job_open", "not_extracted", "no_rule"]);
const LABELS: Readonly<Record<string, string>> = messages.documents.page.rules.fields;

const id = useId();
const base = ref(props.rule);
const draft = ref(draftOf(props.rule));
const busy = ref(false);
const status = ref("");
const failure = ref<Notice | null>(null);
const asking = ref(false);
const discarding = ref(false); // closing over a draft: asked first
const submit = ref<HTMLElement | null>(null);
const heading = ref<HTMLElement | null>(null);
type LinkField = "applies_to" | "options" | "requires";
const LINKS: readonly LinkField[] = ["applies_to", "options", "requires"];

const field = (key: RuleField, kind: FormField["kind"], values: FormValue[] | null = null, required = false): FormField => ({
  key,
  kind,
  required,
  many: kind === "concepts",
  most: kind === "longtext" ? MOST_VERBATIM : null,
  values,
});

const fields = computed<FormField[]>(() => {
  const all: FormField[] = [
    field("kind", "concept", RULE_KINDS.map((kind) => value(kind, kindWord(kind))), true),
    field("verbatim", "longtext", null, true),
    field("min_count", "number"),
    field("max_count", "number"),
    field("min_amount", "number"),
    field("max_amount", "number"),
    field("amount_unit", "concept", props.rules.units.map((each) => value(each.iri, each.label))),
    field("requirement_kind", "concept", props.rules.requirement_kinds.map((each) => value(each.iri, each.label))),
    field("max_share", "number"),
    field("option_texts", "longtext"),
  ];
  return all.filter((each) => holds(draft.value.kind, each.key as RuleField));
});
const links = computed(() => LINKS.filter((key) => holds(draft.value.kind, key)));
const named = computed(() => kindWord(base.value.kind));
const name = computed(() => ruleName(base.value));

watch(
  () => props.rule,
  (now) => {
    draft.value = rebased(draft.value, base.value, now);
    base.value = now;
  },
);

const { faults, faultsAt, clear } = useFieldFaults<RuleField>({
  control: (key) => `${id}-${key}`,
  submit,
  say: (key, problem) => {
    status.value = sayAnew(status.value, t("documents.page.rules.fieldProblem", { field: LABELS[key] ?? key, problem }));
  },
});

watch(
  () => isDirty(base.value, draft.value),
  (open) => emit("dirty", open),
  { immediate: true },
);
onBeforeUnmount(() => emit("dirty", false));
onMounted(() => heading.value?.focus());

function refuse(text: string): void {
  failure.value = { text: sayAnew(failure.value?.text ?? "", text), failed: true };
}

async function onSubmit(): Promise<void> {
  if (busy.value) return; // the button stays focusable while busy, so it can be pressed again
  const { fields: changed, faults: found } = changesOf(base.value, draft.value);
  failure.value = null;
  clear();
  if (found.length) {
    await faultsAt(found);
    return;
  }
  if (!Object.keys(changed).length) {
    status.value = sayAnew(status.value, t("documents.page.rules.unchanged"));
    return;
  }
  status.value = "";
  busy.value = true;
  try {
    const saved = await editRule(base.value.id, base.value.revision, changed);
    base.value = saved;
    draft.value = draftOf(saved);
    status.value = sayAnew(status.value, t("documents.page.rules.saved"));
    emit("saved", saved);
  } catch (error) {
    await refused(error, t("documents.page.rules.saveFailed"));
  } finally {
    busy.value = false;
  }
}

async function refused(error: unknown, failed: string): Promise<void> {
  const code = error instanceof ApiError ? error.code : undefined;
  const details = error instanceof ApiError ? error.details : {};
  const key = details.field as RuleField;
  if (code === "invalid_field" && (fields.value.some((each) => each.key === key) || links.value.includes(key as LinkField))) {
    await faultsAt([[key, problemText(details.problem)]]);
  } else if (code === "stale_revision" && typeof details.current === "object" && details.current !== null) {
    refuse(t("documents.page.rules.changedMeanwhile"));
    emit("saved", details.current as Rule);
  } else if (code && CLOSING.has(code)) {
    refuse(refusalText(code) ?? failed);
    emit("changed");
  } else {
    failure.value = failureNotice(error, failed);
  }
}

async function take(): Promise<void> {
  asking.value = false;
  busy.value = true;
  failure.value = null;
  try {
    const taken = await takeRule(base.value.id, base.value.revision);
    emit("taken", t(taken.outcome === "deleted" ? "documents.page.rules.deleted" : "documents.page.rules.rejected"));
  } catch (error) {
    await refused(error, t("documents.page.rules.takeFailed"));
  } finally {
    busy.value = false;
  }
}

function close(): void {
  if (isDirty(base.value, draft.value)) discarding.value = true;
  else emit("close");
}

const takeWord = computed(() => (base.value.by_hand ? "delete" : "reject"));
// a run's rule rejected already stays so: no second rejection is offered
const takeable = computed(() => base.value.by_hand || statusOf(base.value.review_status) !== "rejected");
</script>

<template>
  <form class="rule-form" novalidate @submit.prevent="onSubmit">
    <!-- tabindex -1: where the keyboard goes as the form opens -->
    <h4 ref="heading" tabindex="-1">{{ t("documents.page.rules.formHeading", { kind: named }) }}</h4>
    <template v-for="each in fields" :key="each.key">
      <FormFieldInput
        v-model="draft[each.key as RuleField]"
        :field="each"
        :values="each.values ?? []"
        :labels="LABELS"
        :control-id="`${id}-${each.key}`"
        :error="faults[each.key as RuleField] ?? null"
      />
      <p v-if="each.key === 'kind'" class="field__hint">{{ t("documents.page.rules.kindHint") }}</p>
    </template>
    <RuleTargets
      v-for="key in links"
      :key="key"
      v-model="draft[key]"
      :label="LABELS[key] ?? key"
      :targets="rules.targets"
      :held="base[key]"
      :control-id="`${id}-${key}`"
      :error="faults[key] ?? null"
    />
    <p v-if="failure" class="field__error rule-form__error" role="alert">
      <AppIcon name="warning" /> <NoticeText :notice="failure" />
    </p>
    <div class="rule-form__actions">
      <!-- aria-disabled, not disabled: a disabled button drops the focus it holds -->
      <button
        ref="submit"
        type="submit"
        class="btn primary"
        :aria-label="t('documents.page.rules.saveNamed', { rule: name })"
        :aria-disabled="busy || undefined"
      >
        {{ t("documents.page.rules.save") }}
      </button>
      <button
        v-if="takeable"
        type="button"
        class="btn secondary"
        :aria-label="t(`documents.page.rules.${takeWord}Named`, { rule: name })"
        :aria-disabled="busy || undefined"
        @click="busy || (asking = true)"
      >
        {{ t(`documents.page.rules.${takeWord}`) }}
      </button>
      <button type="button" class="btn secondary" @click="close">{{ t("documents.page.rules.close") }}</button>
    </div>
    <!-- always in the page, so a screen reader hears each change of its text -->
    <p class="rule-form__status" role="status">{{ status }}</p>
    <ConfirmDialog
      v-if="asking"
      :title="t(`documents.page.rules.${takeWord}Title`)"
      :message="t(`documents.page.rules.${takeWord}Message`)"
      :confirm-label="t(`documents.page.rules.${takeWord}`)"
      @confirm="take"
      @cancel="asking = false"
    />
    <ConfirmDialog
      v-if="discarding"
      :title="t('documents.page.rules.discardTitle')"
      :message="t('documents.page.rules.discardMessage')"
      :confirm-label="t('documents.page.rules.discardConfirm')"
      :cancel-label="t('documents.page.rules.discardCancel')"
      @confirm="(discarding = false), emit('close')"
      @cancel="discarding = false"
    />
  </form>
</template>

<style scoped>
.rule-form {
  display: grid;
  gap: var(--space-2);
  max-width: var(--reading-width);
}

.rule-form h4,
.rule-form__error,
.rule-form__status,
.rule-form .field__hint {
  margin: 0;
}

.rule-form__actions {
  display: flex;
  flex-wrap: wrap;
  gap: var(--space-2);
}

/* Empty, it takes no room - as a cell of the grid its gap would stand twice - but stays in the page. */
.rule-form__status:empty {
  position: absolute;
}
</style>
