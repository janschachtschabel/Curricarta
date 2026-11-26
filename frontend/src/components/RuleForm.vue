<script setup lang="ts">
/**
 * One rule's kind, wording, values and links (plan M3a I; backend PATCH /rules/{id}), by the document's owner or an
 * editor, on the revision it was read at: only what changed is sent (ruleDraft.ts), each field's problem the server
 * would refuse found first and stood at its field, as is one the server names. Saved, it says so and hands the rule as
 * stored to the section (`saved`); changed meanwhile, the rule as it stands is shown and said, the entry kept for a
 * second try; a document closed meanwhile, or the rule gone, has the section read again (`changed`). A kind shows the
 * fields it holds alone. The rule is taken away after a question - a run's rejected and kept, an editor's own deleted
 * (`taken`). It tells the section whether a change is open (`dirty`, the leave guard).
 */
import { computed, onBeforeUnmount, ref, useId, watch } from "vue";

import { ApiError, editRule, takeRule, type FormField, type FormValue, type Rule, type Rules } from "@/api";
import AppIcon from "@/components/AppIcon.vue";
import ConfirmDialog from "@/components/ConfirmDialog.vue";
import FormFieldInput from "@/components/FormFieldInput.vue";
import NoticeText from "@/components/NoticeText.vue";
import { useFieldFaults } from "@/fieldFaults";
import { messages, t } from "@/i18n/de";
import { sayAnew } from "@/liveRegion";
import { failureNotice, type Notice } from "@/notice";
import { refusalText } from "@/refusals";
import { problemText } from "@/rowRefusals";
import { MOST_VERBATIM, RULE_KINDS, changesOf, choice as value, draftOf, holds, rebased, type RuleField } from "@/ruleDraft";
import { kindWord } from "@/ruleWords";

const props = defineProps<{ rule: Rule; rules: Rules }>();
const emit = defineEmits<{ saved: [rule: Rule]; changed: []; taken: [words: string]; dirty: [open: boolean] }>();

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
const submit = ref<HTMLElement | null>(null);

const field = (key: RuleField, kind: FormField["kind"], values: FormValue[] | null = null, required = false): FormField => ({
  key,
  kind,
  required,
  many: kind === "concepts",
  most: kind === "longtext" ? MOST_VERBATIM : null,
  values,
});

// what a link field offers: what the rule may name, and the rows it names beyond it - a statement - kept
function linkValues(key: "applies_to" | "options" | "requires"): FormValue[] {
  const offered = props.rules.targets.map((target) => value(target.id, target.label));
  const held = base.value[key].filter((link) => !props.rules.targets.some((target) => target.id === link.id));
  return [...offered, ...held.map((link) => value(link.id, link.label ?? link.id))];
}

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
    field("applies_to", "concepts", linkValues("applies_to")),
    field("options", "concepts", linkValues("options")),
    field("requires", "concepts", linkValues("requires")),
  ];
  return all.filter((each) => holds(draft.value.kind, each.key as RuleField));
});
const named = computed(() => kindWord(base.value.kind));

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
  () => Object.keys(changesOf(base.value, draft.value).fields).length > 0,
  (open) => emit("dirty", open),
  { immediate: true },
);
onBeforeUnmount(() => emit("dirty", false));

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
  if (code === "invalid_field" && fields.value.some((each) => each.key === key)) {
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

const takeWord = computed(() => (base.value.by_hand ? "delete" : "reject"));
</script>

<template>
  <form class="rule-form" novalidate @submit.prevent="onSubmit">
    <h4>{{ t("documents.page.rules.formHeading", { kind: named }) }}</h4>
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
    <p v-if="failure" class="field__error rule-form__error" role="alert">
      <AppIcon name="warning" /> <NoticeText :notice="failure" />
    </p>
    <div class="rule-form__actions">
      <!-- aria-disabled, not disabled: a disabled button drops the focus it holds -->
      <button
        ref="submit"
        type="submit"
        class="btn primary"
        :aria-label="t('documents.page.rules.saveNamed', { rule: base.verbatim })"
        :aria-disabled="busy || undefined"
      >
        {{ t("documents.page.rules.save") }}
      </button>
      <button
        type="button"
        class="btn secondary"
        :aria-label="t(`documents.page.rules.${takeWord}Named`, { rule: base.verbatim })"
        :aria-disabled="busy || undefined"
        @click="busy || (asking = true)"
      >
        {{ t(`documents.page.rules.${takeWord}`) }}
      </button>
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
