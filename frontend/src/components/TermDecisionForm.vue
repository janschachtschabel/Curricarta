<script setup lang="ts">
/**
 * A decision on a term X1 found no type for (plan M1 10.5, 10e E10; backend POST /api/v1/lexicon/terms): a new
 * cue to a node type of the sector's profile with its role - the node types read once a new cue is asked for, a
 * suggested function's first -, a term peculiar to its document, or a misread one; a note free. A word under four
 * signs gives no cue, and the form says so. Where the import would leave the new cue out - the own lexicon holds
 * the word - it says that too, without holding the decision back. Otherwise as CueDecisionForm: it starts from
 * the decision before, names what is missing at its field, tells the item a decision made (`decided`), offers to
 * read the list again where the term is gone (`reload`), and says whether anything was changed (`dirty`).
 */
import { computed, onMounted, ref, useId, watch } from "vue";

import {
  ApiError,
  decideTerm,
  type HeldCue,
  type Labels,
  type NewCueRole,
  type TermDecision,
  type TermDecisionKind,
} from "@/api";
import AppIcon from "@/components/AppIcon.vue";
import NoticeText from "@/components/NoticeText.vue";
import { useFieldFaults, type Fault } from "@/fieldFaults";
import { requiredLabel } from "@/formWords";
import { t } from "@/i18n/de";
import { grouped, type Targets } from "@/lexiconTargets";
import { skipReason, tooShort } from "@/lexiconWords";
import { sayAnew } from "@/liveRegion";
import { useNodeTypesReading } from "@/nodeTypesReading";
import { failureNotice, type Notice } from "@/notice";

const props = defineProps<{
  /** The term as the list names it: its sector's notation, its regions' codes, its word. */
  term: { sector: string; regions: string[]; term: string };
  /** The functions X1 suggested for it. */
  functions: string[];
  held: HeldCue[];
  before: TermDecision | null;
  targets: Targets;
}>();
// `decided` with the chosen target's label: the list's labels name the targets it showed, not every node type
const emit = defineEmits<{
  decided: [made: TermDecision, labels: Labels];
  cancel: [];
  reload: [];
  dirty: [dirty: boolean];
}>();

type Field = "decision" | "target" | "role";
interface Entered {
  decision: TermDecisionKind | "";
  target: string;
  role: NewCueRole | "";
  note: string;
}

const ROLES: readonly NewCueRole[] = ["pref", "alt", "cue"];
const id = useId();
const short = tooShort(props.term.term);
const start: Entered = {
  decision: props.before?.decision ?? "",
  target: props.before?.maps_to ?? "",
  role: props.before?.role ?? "",
  note: props.before?.note ?? "",
};
const entered = ref<Entered>({ ...start });
const dirty = computed(() => (Object.keys(start) as (keyof Entered)[]).some((key) => entered.value[key] !== start[key]));
watch(dirty, (now) => emit("dirty", now));

const status = ref("");
// a new cue asked to be saved while its node types were missing: said until they come
const typesMissing = ref(false);
const failure = ref<Notice | null>(null);
const {
  types,
  failed: typesFailed,
  loading: typesLoading,
  retry: retryButton,
  select: targetSelect,
  load: loadTypes,
} = useNodeTypesReading(
  () => props.targets(props.term.sector),
  (text) => (status.value = text ? sayAnew(status.value, text) : ""),
  (offered) => {
    // a node type the profile no longer offers is chosen again
    if (!offered.some((type) => type.iri === entered.value.target)) {
      start.target = "";
      entered.value.target = "";
    }
    if (typesMissing.value) {
      typesMissing.value = false;
      failure.value = null;
    }
  },
);
const cue = computed(() => entered.value.decision === "cue");
const offered = computed(() => grouped(types.value ?? [], props.functions));
// why the import would leave the new cue out, once the node types show
const skipped = computed(() =>
  cue.value && types.value !== null ? skipReason(props.held, entered.value.target || null) : null,
);
// the choice that takes the keyboard for a problem of the decision: a new cue, where a new cue may be made
const first = short ? "document" : "cue";

const busy = ref(false);
const submit = ref<HTMLElement | null>(null);
const gone = ref(false);

const LABELS: Readonly<Record<Field, () => string>> = {
  decision: () => t("lexicon.termForm.legend"),
  target: () => t("lexicon.termForm.target"),
  role: () => t("lexicon.termForm.role"),
};
// Every field's problem at its field (fieldFaults.ts); where the keyboard stays elsewhere, the first is said
const { faults, faultsAt, clear } = useFieldFaults<Field>({
  control: (field) => `${id}-${field}`,
  submit,
  say: (field, problem) => {
    status.value = sayAnew(status.value, t("lexicon.form.fieldProblem", { field: LABELS[field](), problem }));
  },
});

// said as it appears - hung on the node type's field alone, it would be heard only there -, and taken back
// with its reason
watch(skipped, (now, before) => {
  if (now) status.value = sayAnew(status.value, t(`lexicon.termForm.skipped.${now}`));
  else if (before && status.value.trim() === t(`lexicon.termForm.skipped.${before}`)) status.value = "";
});

function wantTypes(): void {
  if (cue.value && types.value === null && !typesFailed.value) void loadTypes();
}

watch(cue, wantTypes);
// a decision before that was a new cue reads them once the form is in the page: the status region is there
// first, empty, and is heard when the waiting is said
onMounted(wantTypes);

/** The field's hints and its error where it has them. */
function describedBy(field: Field, ...hints: string[]): string | undefined {
  const ids = [...hints, faults.value[field] ? `${id}-${field}-error` : ""];
  return ids.filter(Boolean).join(" ") || undefined;
}

/** What is missing before anything is sent, every field of it; none where the form may go. */
function unready(): Fault<Field>[] {
  if (!entered.value.decision) return [["decision", t("lexicon.termForm.chooseDecision")]];
  if (!cue.value) return [];
  const found: Fault<Field>[] = [];
  if (!entered.value.target) found.push(["target", t("lexicon.termForm.chooseTarget")]);
  if (!entered.value.role) found.push(["role", t("lexicon.termForm.chooseRole")]);
  return found;
}

async function onSubmit(): Promise<void> {
  if (busy.value) return; // the button stays focusable while busy, so it can be pressed again
  if (cue.value && types.value === null) {
    clear();
    typesMissing.value = true;
    const text = t(typesLoading.value ? "lexicon.termForm.targetsPending" : "lexicon.termForm.targetsMissing");
    failure.value = { text, failed: true };
    return;
  }
  const missing = unready();
  if (missing.length) {
    failure.value = null;
    return faultsAt(missing);
  }
  clear();
  failure.value = null;
  gone.value = false;
  busy.value = true;
  try {
    // the term by what tells it apart alone: the list's entry carries its places too, which the server refuses
    const made = await decideTerm({
      sector: props.term.sector,
      regions: props.term.regions,
      term: props.term.term,
      decision: entered.value.decision as TermDecisionKind,
      maps_to: cue.value ? entered.value.target : null,
      role: cue.value ? (entered.value.role as NewCueRole) : null,
      note: entered.value.note.trim() || null,
    });
    const chosen = cue.value ? types.value?.find((type) => type.iri === entered.value.target) : undefined;
    // busy until the form goes with the decision: a second press would send it again
    emit("decided", made, chosen ? { [chosen.iri]: chosen.label } : {});
  } catch (error) {
    busy.value = false;
    gone.value = error instanceof ApiError && error.code === "no_term";
    failure.value = failureNotice(error, t("lexicon.form.failed"));
  }
}
</script>

<template>
  <form class="decision-form" novalidate @submit.prevent="onSubmit">
    <fieldset class="decision-form__choice">
      <legend>{{ requiredLabel(t("lexicon.termForm.legend")) }}</legend>
      <!-- one name: the arrow keys move between the three, and Tab passes them as one group -->
      <label v-for="choice in ['cue', 'document', 'error'] as const" :key="choice">
        <input
          :id="choice === first ? `${id}-decision` : undefined"
          v-model="entered.decision"
          type="radio"
          :name="`${id}-decision`"
          :value="choice"
          :disabled="choice === 'cue' && short"
          :aria-invalid="Boolean(faults.decision) || undefined"
          :aria-describedby="describedBy('decision', choice === 'cue' && short ? `${id}-short` : '')"
        />
        {{ t(`lexicon.termForm.${choice}`) }}
      </label>
    </fieldset>
    <p v-if="short" :id="`${id}-short`" class="field__hint">{{ t("refusals.too_short") }}</p>
    <p v-if="faults.decision" :id="`${id}-decision-error`" class="field__error">
      <AppIcon name="warning" /> {{ faults.decision }}
    </p>
    <template v-if="cue">
      <div v-if="typesFailed" class="field__error" data-test="targets-failed">
        <p><AppIcon name="warning" /> {{ t("lexicon.termForm.targetsFailed") }}</p>
        <!-- aria-disabled, not disabled: a disabled button drops the focus it holds -->
        <button
          ref="retryButton"
          type="button"
          class="btn secondary btn-sm"
          :aria-disabled="typesLoading || undefined"
          @click="loadTypes"
        >
          {{ t("states.retry") }}
        </button>
      </div>
      <!-- shown, not said: the form's status says it -->
      <p v-else-if="types === null" class="field__hint">{{ t("lexicon.termForm.targetsLoading") }}</p>
      <template v-else>
        <div class="field">
          <label :for="`${id}-target`">{{ requiredLabel(t("lexicon.termForm.target")) }}</label>
          <select
            :id="`${id}-target`"
            aria-required="true"
            ref="targetSelect"
            v-model="entered.target"
            :aria-invalid="Boolean(faults.target) || undefined"
            :aria-describedby="describedBy('target', skipped ? `${id}-skipped` : '')"
          >
            <option value="">{{ t("lexicon.termForm.targetChoose") }}</option>
            <optgroup v-if="offered.suggested.length" :label="t('lexicon.termForm.suggested')">
              <option v-for="type in offered.suggested" :key="type.iri" :value="type.iri">{{ type.label }}</option>
            </optgroup>
            <optgroup v-if="offered.others.length" :label="t('lexicon.termForm.others')">
              <option v-for="type in offered.others" :key="type.iri" :value="type.iri">{{ type.label }}</option>
            </optgroup>
          </select>
          <p v-if="faults.target" :id="`${id}-target-error`" class="field__error">
            <AppIcon name="warning" /> {{ faults.target }}
          </p>
          <p v-if="skipped" :id="`${id}-skipped`" class="field__hint" data-test="skipped">
            <AppIcon name="warning" /> {{ t(`lexicon.termForm.skipped.${skipped}`) }}
          </p>
        </div>
        <div class="field">
          <label :for="`${id}-role`">{{ requiredLabel(t("lexicon.termForm.role")) }}</label>
          <select
            :id="`${id}-role`"
            aria-required="true"
            v-model="entered.role"
            :aria-invalid="Boolean(faults.role) || undefined"
            :aria-describedby="describedBy('role', `${id}-role-hint`)"
          >
            <option value="">{{ t("lexicon.termForm.roleChoose") }}</option>
            <option v-for="role in ROLES" :key="role" :value="role">{{ t(`lexicon.termForm.roles.${role}`) }}</option>
          </select>
          <p v-if="faults.role" :id="`${id}-role-error`" class="field__error">
            <AppIcon name="warning" /> {{ faults.role }}
          </p>
          <p :id="`${id}-role-hint`" class="field__hint">{{ t("lexicon.termForm.roleHint") }}</p>
        </div>
      </template>
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
