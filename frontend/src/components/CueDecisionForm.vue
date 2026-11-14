<script setup lang="ts">
/**
 * A decision on one research cue (plan M1 10.5, 10e E8; backend POST /api/v1/lexicon/review): confirmed at a
 * strength with where the editors found it - no confirmation without -, or rejected; a note free. It starts from
 * the decision before, and says whether anything was changed (`dirty`). What is missing is said at its field
 * before anything is sent - the keyboard taken there from the button or from nothing, else the problem said where
 * the keyboard rests. Saved, the item is told (`decided`), and nothing more is sent until the form goes with the
 * decision; a cue gone meanwhile offers to read the list again (`reload`); another failure is said, what was
 * entered kept.
 */
import { computed, ref, useId, watch } from "vue";

import { ApiError, decideCue, type CueDecision, type CueDecisionKind } from "@/api";
import AppIcon from "@/components/AppIcon.vue";
import NoticeText from "@/components/NoticeText.vue";
import { useFieldFaults, type Fault } from "@/fieldFaults";
import { requiredLabel } from "@/formWords";
import { t } from "@/i18n/de";
import { STRENGTHS, strengthText } from "@/lexiconWords";
import { sayAnew } from "@/liveRegion";
import { failureNotice, type Notice } from "@/notice";

const props = defineProps<{ cue: string; before: CueDecision | null }>();
const emit = defineEmits<{ decided: [made: CueDecision]; cancel: []; reload: []; dirty: [dirty: boolean] }>();

type Field = "decision" | "strength" | "evidence";
interface Entered {
  decision: CueDecisionKind | "";
  strength: string;
  evidence: string;
  note: string;
}

const id = useId();
const start: Entered = {
  decision: props.before?.decision ?? "",
  // as the list offers it: "0.9" is "0.90"; one no option offers is chosen again
  strength: STRENGTHS.find((one) => Number(one) === Number(props.before?.strength ?? NaN)) ?? "",
  evidence: props.before?.evidence ?? "",
  note: props.before?.note ?? "",
};
const entered = ref<Entered>({ ...start });
const dirty = computed(() => (Object.keys(start) as (keyof Entered)[]).some((key) => entered.value[key] !== start[key]));
watch(dirty, (now) => emit("dirty", now));

const busy = ref(false);
const status = ref("");
const submit = ref<HTMLElement | null>(null);
const failure = ref<Notice | null>(null);
// the cue gone meanwhile: the list is read again on the reader's word
const gone = ref(false);
const confirming = computed(() => entered.value.decision === "confirmed");

const LABELS: Readonly<Record<Field, () => string>> = {
  decision: () => t("lexicon.cueForm.legend"),
  strength: () => t("lexicon.cueForm.strength"),
  evidence: () => t("lexicon.cueForm.evidence"),
};

/** The field's hint where it has one, and its error where it has one. */
function describedBy(field: Field, hint = false): string | undefined {
  const ids = [hint ? `${id}-${field}-hint` : "", faults.value[field] ? `${id}-${field}-error` : ""];
  return ids.filter(Boolean).join(" ") || undefined;
}

// Every field's problem at its field (fieldFaults.ts); where the keyboard stays elsewhere, the first is said
const { faults, faultsAt, clear } = useFieldFaults<Field>({
  control: (field) => `${id}-${field}`,
  submit,
  say: (field, problem) => {
    status.value = sayAnew(status.value, t("lexicon.form.fieldProblem", { field: LABELS[field](), problem }));
  },
});

/** What is missing before anything is sent, every field of it; none where the form may go. */
function unready(): Fault<Field>[] {
  if (!entered.value.decision) return [["decision", t("lexicon.cueForm.chooseDecision")]];
  if (!confirming.value) return [];
  const found: Fault<Field>[] = [];
  if (!entered.value.strength) found.push(["strength", t("lexicon.cueForm.chooseStrength")]);
  if (!entered.value.evidence.trim()) found.push(["evidence", t("lexicon.cueForm.evidenceMissing")]);
  return found;
}

async function onSubmit(): Promise<void> {
  if (busy.value) return; // the button stays focusable while busy, so it can be pressed again
  const missing = unready();
  if (missing.length) {
    failure.value = null;
    return faultsAt(missing);
  }
  const decision = entered.value.decision as CueDecisionKind;
  clear();
  failure.value = null;
  gone.value = false;
  busy.value = true;
  try {
    const made = await decideCue({
      cue: props.cue,
      decision,
      strength: confirming.value ? entered.value.strength : null,
      evidence: confirming.value ? entered.value.evidence.trim() : null,
      note: entered.value.note.trim() || null,
    });
    emit("decided", made); // busy until the form goes with the decision: a second press would send it again
  } catch (error) {
    busy.value = false;
    gone.value = error instanceof ApiError && error.code === "no_cue";
    failure.value = failureNotice(error, t("lexicon.form.failed"));
  }
}
</script>

<template>
  <form class="decision-form" novalidate @submit.prevent="onSubmit">
    <fieldset class="decision-form__choice">
      <legend>{{ requiredLabel(t("lexicon.cueForm.legend")) }}</legend>
      <label>
        <input
          :id="`${id}-decision`"
          v-model="entered.decision"
          type="radio"
          :name="`${id}-decision`"
          value="confirmed"
          :aria-invalid="Boolean(faults.decision) || undefined"
          :aria-describedby="describedBy('decision')"
        />
        {{ t("lexicon.cueForm.confirmed") }}
      </label>
      <!-- one name: the arrow keys move between the two, and Tab passes them as one group -->
      <label>
        <input
          v-model="entered.decision"
          type="radio"
          :name="`${id}-decision`"
          value="rejected"
          :aria-invalid="Boolean(faults.decision) || undefined"
          :aria-describedby="describedBy('decision')"
        />
        {{ t("lexicon.cueForm.rejected") }}
      </label>
    </fieldset>
    <p v-if="faults.decision" :id="`${id}-decision-error`" class="field__error">
      <AppIcon name="warning" /> {{ faults.decision }}
    </p>
    <template v-if="confirming">
      <div class="field">
        <label :for="`${id}-strength`">{{ requiredLabel(t("lexicon.cueForm.strength")) }}</label>
        <select
          :id="`${id}-strength`"
          aria-required="true"
          v-model="entered.strength"
          :aria-invalid="Boolean(faults.strength) || undefined"
          :aria-describedby="describedBy('strength', true)"
        >
          <option value="">{{ t("lexicon.cueForm.strengthChoose") }}</option>
          <option v-for="one in STRENGTHS" :key="one" :value="one">{{ strengthText(one) }}</option>
        </select>
        <p v-if="faults.strength" :id="`${id}-strength-error`" class="field__error">
          <AppIcon name="warning" /> {{ faults.strength }}
        </p>
        <p :id="`${id}-strength-hint`" class="field__hint">{{ t("lexicon.cueForm.strengthHint") }}</p>
      </div>
      <div class="field">
        <label :for="`${id}-evidence`">{{ requiredLabel(t("lexicon.cueForm.evidence")) }}</label>
        <input
          :id="`${id}-evidence`"
          aria-required="true"
          v-model="entered.evidence"
          type="text"
          maxlength="500"
          autocomplete="off"
          :aria-invalid="Boolean(faults.evidence) || undefined"
          :aria-describedby="describedBy('evidence', true)"
        />
        <p v-if="faults.evidence" :id="`${id}-evidence-error`" class="field__error">
          <AppIcon name="warning" /> {{ faults.evidence }}
        </p>
        <p :id="`${id}-evidence-hint`" class="field__hint">{{ t("lexicon.cueForm.evidenceHint") }}</p>
      </div>
    </template>
    <div class="field">
      <label :for="`${id}-note`">{{ t("lexicon.form.note") }}</label>
      <textarea :id="`${id}-note`" v-model="entered.note" rows="2" maxlength="2000"></textarea>
    </div>
    <div v-if="failure" class="field__error decision-form__error" role="alert">
      <p><AppIcon name="warning" /> <NoticeText :notice="failure" /></p>
      <button v-if="gone" type="button" class="btn secondary btn-sm" data-test="decision-reload" @click="emit('reload')">
        {{ t("lexicon.form.reload") }}
      </button>
    </div>
    <div class="decision-form__actions">
      <!-- aria-disabled, not disabled: a disabled button drops the focus it holds -->
      <button ref="submit" type="submit" class="btn primary" :aria-disabled="busy || undefined">
        {{ t("lexicon.form.save") }}
      </button>
      <button type="button" class="btn secondary" data-test="decision-cancel" @click="emit('cancel')">
        {{ t("lexicon.form.cancel") }}
      </button>
    </div>
    <!-- always in the page, so a screen reader hears a field's problem said where the keyboard stayed -->
    <p class="visually-hidden" role="status">{{ status }}</p>
  </form>
</template>
