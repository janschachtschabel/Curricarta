<script setup lang="ts">
/**
 * Freezing a document, on its page (plan M1 9.10, Paket 9d1 N6; documentRevision.ts): offered to an editor while it
 * is open. Asked first (FreezeDialog); where its findings name violations, asked again by their count, a yes taking
 * them. Frozen, the document goes to the page (`frozen`), which reads it and says so. What is missing for its IRI is
 * named item by item; a check owed is said with the way to the tree, where it is checked; a document closed
 * meanwhile is said and read again (`changed`); another refusal said. While it freezes nothing more is asked.
 */
import { computed, ref, watch } from "vue";
import { RouterLink } from "vue-router";

import { getDocument, type CurriculumDocument } from "@/api";
import AppIcon from "@/components/AppIcon.vue";
import ConfirmDialog from "@/components/ConfirmDialog.vue";
import FreezeDialog from "@/components/FreezeDialog.vue";
import NoticeText from "@/components/NoticeText.vue";
import { freeze, freezeParts, missingParts, missingWords, partState, type IriPart } from "@/documentRevision";
import { LOCALE, t } from "@/i18n/de";
import { sayAnew } from "@/liveRegion";
import type { Notice } from "@/notice";
import { refusalText } from "@/refusals";
import { isEditor } from "@/session";

const props = defineProps<{ document: CurriculumDocument }>();
const emit = defineEmits<{ frozen: [document: CurriculumDocument]; changed: [] }>();

const asking = ref<"freeze" | "violations" | null>(null);
const count = ref(0);
const busy = ref(false);
const problem = ref<Notice | null>(null);
// a check owed: the way to the tree goes with the words
const owed = ref(false);

const offered = computed(() => isEditor() && props.document.frozen_at === null);
// what its IRI is made of, as the document shows it: what is missing is said on pressing, not asked about
const parts = computed(() => freezeParts(props.document));
// The words of a press are of the parts in the state they were said of - the document read again, or as the server
// found it -: once the page shows the parts otherwise, they go. The page reading it as they were said keeps them.
const stateOf = (list: readonly { part: IriPart; set: boolean }[]) => list.map(({ part, set }) => `${part}:${set}`).join(" ");
let saidOf = "";
watch(
  () => stateOf(parts.value),
  (now) => {
    if (now === saidOf) return;
    problem.value = null;
    owed.value = false;
  },
);

function incomplete(missing: readonly string[]): Notice {
  const words = missingWords(missing);
  const text = words.length
    ? t("documents.page.freeze.incomplete", { missing: new Intl.ListFormat(LOCALE).format(words) })
    : (refusalText("incomplete") ?? t("documents.page.freeze.failed"));
  return { text, failed: true };
}

// A part missing on the page may be set already in another tab: the document is read again before the press is
// refused, and the page asked to read it too (`changed`) where it differs; a reading that fails refuses on what the
// page holds. Never the other way: the irreversible question is asked only of a document found complete.
async function ask(): Promise<void> {
  if (busy.value) return; // the button stays focusable while busy, so it can be pressed again
  let missing = missingParts(props.document);
  if (missing.length) {
    busy.value = true;
    const fresh = await getDocument(props.document.id).catch(() => null);
    busy.value = false;
    if (fresh) missing = missingParts(fresh);
    saidOf = stateOf(freezeParts(fresh ?? props.document));
    if (fresh && saidOf !== stateOf(parts.value)) emit("changed");
  }
  if (missing.length) {
    owed.value = false;
    // pressed again, the same words: said anew, or the alert stays as it was and a screen reader silent
    const words = incomplete(missing);
    problem.value = { ...words, text: sayAnew(problem.value?.text ?? "", words.text) };
    return;
  }
  asking.value = "freeze";
}

async function run(acceptViolations: boolean): Promise<void> {
  asking.value = null;
  busy.value = true;
  problem.value = null;
  owed.value = false;
  saidOf = stateOf(parts.value);
  const done = await freeze(props.document.id, acceptViolations);
  busy.value = false;
  switch (done.outcome) {
    case "frozen":
      emit("frozen", done.document);
      return;
    case "violations":
      count.value = done.count;
      asking.value = "violations";
      return;
    case "incomplete":
      problem.value = incomplete(done.missing);
      // the page held a part as set the server does not: its list is read anew, the words kept for what it shows
      saidOf = stateOf(parts.value.map(({ part, set }) => ({ part, set: set && !done.missing.includes(part) })));
      if (saidOf !== stateOf(parts.value)) emit("changed");
      return;
    case "owed":
      owed.value = true;
      problem.value = { text: refusalText("check_owed") ?? t("documents.page.freeze.failed"), failed: true };
      return;
    case "failed":
      problem.value = done.problem;
      return;
    default:
      problem.value = { text: refusalText(done.code) ?? t("documents.page.freeze.failed"), failed: true };
      if (done.outcome === "closed") emit("changed");
  }
}
</script>

<template>
  <section v-if="offered" class="freeze" aria-labelledby="document-freeze">
    <h2 id="document-freeze" tabindex="-1">{{ t("documents.page.freeze.heading") }}</h2>
    <p class="freeze__intro">{{ t("documents.page.freeze.intro") }}</p>
    <ul class="freeze__checks" :aria-label="t('documents.page.freeze.checks')">
      <li v-for="item in parts" :key="item.part" data-test="freeze-check" :class="{ 'freeze__check--missing': !item.set }">
        <AppIcon :name="item.set ? 'check' : 'warning'" /> {{ partState(item) }}
      </li>
    </ul>
    <p v-if="problem" class="field__error freeze__problem" role="alert">
      <AppIcon name="warning" /> <NoticeText :notice="problem" />
      <template v-if="owed">
        {{ " " }}
        <RouterLink data-test="freeze-tree" :to="{ name: 'documentTree', params: { id: document.id } }">
          {{ t("documents.page.freeze.toTree") }}
        </RouterLink>
      </template>
    </p>
    <!-- aria-disabled, not disabled: a disabled button drops the focus it holds -->
    <button type="button" class="btn primary" data-test="freeze" :aria-disabled="busy || undefined" @click="ask">
      {{ t("documents.page.freeze.button") }}
    </button>
    <FreezeDialog
      v-if="asking === 'freeze'"
      :title="document.title || t('documents.untitled')"
      :revision="document.revision"
      @confirm="run(false)"
      @cancel="asking = null"
    />
    <ConfirmDialog
      v-if="asking === 'violations'"
      :title="t('documents.page.freeze.violationsTitle')"
      :message="t('documents.page.freeze.violationsMessage', { count })"
      :confirm-label="t('documents.page.freeze.violationsConfirm')"
      @confirm="run(true)"
      @cancel="asking = null"
    />
  </section>
</template>

<style scoped>
.freeze {
  display: grid;
  gap: var(--space-2);
  justify-items: start;
}

.freeze h2,
.freeze__intro,
.freeze__checks,
.freeze__problem {
  margin: 0;
}

.freeze__intro {
  max-width: var(--reading-width);
}

.freeze__checks {
  display: grid;
  gap: var(--space-0);
  margin: 0;
  padding: 0;
  list-style: none;
}

/* the words say it; the ink is the second signal */
.freeze__check--missing {
  color: var(--danger);
}
</style>
