<script setup lang="ts">
/**
 * The editors' review of the lexicon (plan M1 10.5, 10e E11): the sample of the research's cues (LexiconSample)
 * and the terms X1 found no type for (LexiconTerms), each read for itself - one shown where the other did not
 * come, a refusal said in its words. A decision not saved in either is asked about before the page is left
 * (leaveGuard.ts), the browser asking before the tab closes. The decisions reach the lexicon once the
 * administration exports them and the research's importer writes the land files anew (README "Lexikon prüfen").
 */
import { computed, reactive } from "vue";

import ConfirmDialog from "@/components/ConfirmDialog.vue";
import LexiconSample from "@/components/LexiconSample.vue";
import LexiconTerms from "@/components/LexiconTerms.vue";
import { t } from "@/i18n/de";
import { useLeaveGuard } from "@/leaveGuard";

// whether a form of each section holds what is not saved
const unsaved = reactive({ sample: false, terms: false });
const { leaving, answer } = useLeaveGuard(computed(() => unsaved.sample || unsaved.terms));
</script>

<template>
  <div class="page lexicon">
    <h1>{{ t("lexicon.page.heading") }}</h1>
    <p class="lexicon__intro">{{ t("lexicon.page.intro") }}</p>
    <LexiconSample @dirty="unsaved.sample = $event" />
    <LexiconTerms @dirty="unsaved.terms = $event" />
    <ConfirmDialog
      v-if="leaving"
      :title="t('lexicon.page.leave.title')"
      :message="t('lexicon.page.leave.message')"
      :confirm-label="t('lexicon.page.leave.confirm')"
      :cancel-label="t('lexicon.page.leave.cancel')"
      @confirm="answer(true)"
      @cancel="answer(false)"
    />
  </div>
</template>

<style scoped>
.lexicon {
  display: grid;
  gap: var(--space-4);
}

.lexicon > h1,
.lexicon__intro {
  margin: 0;
}

.lexicon__intro {
  max-width: var(--reading-width);
}
</style>
