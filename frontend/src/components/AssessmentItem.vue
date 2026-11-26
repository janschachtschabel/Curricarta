<script setup lang="ts">
/**
 * One assessment of a document's section of them (plan M3a J; DocumentAssessments.vue), its parts listed under it,
 * each an item of its own: its name, its review status, what it states in words (assessmentWords.ts). Where the
 * section lets it be edited, the ways on from it - edit it, add a part of it, take it away -, the form the section
 * has open at it (AssessmentForm), and the levels at it in the values' form (ValueSection). To the editors, the
 * toggles of its review status, in a group named for it, and of each level's (plan M3a L). What it does the section
 * does (`actions`): one form is open in the section at a time.
 */
import { computed } from "vue";

import type { Assessment, Assessments, Form } from "@/api";
import type { ItemActions } from "@/assessmentWords";
import AssessmentForm from "@/components/AssessmentForm.vue";
import ReviewToggles from "@/components/ReviewToggles.vue";
import ValueSection from "@/components/ValueSection.vue";
import { assessmentTitle, factsOf } from "@/assessmentWords";
import { t } from "@/i18n/de";
import { REVIEW_TONES, statusOf, statusWord } from "@/reviewStatus";
import { namedReviewWords } from "@/rowReview";
import type { Labels } from "@/scopeWords";
import { assessmentRow } from "@/valueHolder";

const props = defineProps<{
  assessment: Assessment;
  read: Assessments;
  parts: ReadonlyMap<string, Assessment[]>;
  names: ReadonlyMap<string, string>;
  kinds: Labels;
  levels: Labels;
  form: Form | null;
  documentId: string;
  editable: boolean;
  /** The caller may set the review status of it and its levels now. */
  reviewable: boolean;
  /** The form the section has open: of which kind, at which assessment; none open. */
  opened: { mode: "add" | "edit" | "part"; id: string | null } | null;
  /** The values' forms holding a draft, by `values:<id>`: one stays where the document closes under it. */
  drafting: ReadonlySet<string>;
  closedBy: string | null;
  actions: ItemActions;
}>();

const title = computed(() => assessmentTitle(props.assessment));
const facts = computed(() => factsOf(props.assessment, props.names, props.kinds, props.levels));
const children = computed(() => props.parts.get(props.assessment.id) ?? []);
const tone = computed(() => {
  const status = statusOf(props.assessment.review_status);
  return status ? REVIEW_TONES[status] : "neutral";
});
const mine = (mode: "edit" | "part") => props.opened?.mode === mode && props.opened.id === props.assessment.id;
const row = computed(() => assessmentRow(props.assessment));
</script>

<template>
  <li class="assessment">
    <article class="assessment__body">
      <h3 class="assessment__title">
        <bdi>{{ title }}</bdi> <span class="status-badge" :class="tone">{{ statusWord(assessment.review_status) }}</span>
      </h3>
      <dl class="facts">
        <template v-for="fact in facts" :key="fact.key">
          <dt>{{ fact.term }}</dt>
          <dd><bdi>{{ fact.words }}</bdi></dd>
        </template>
      </dl>
      <ReviewToggles
        v-if="reviewable"
        :row="row"
        :label="t('documents.page.assessments.reviewLabel', { title })"
        :document-id="documentId"
        :on-reviewed="(done, key) => actions.reviewed(done, key, namedReviewWords(done, title, t('documents.page.assessments.reviewStale', { title })))"
      />
      <div v-if="editable && opened === null" class="assessment__actions">
        <button type="button" class="btn btn-sm secondary" :aria-label="t('documents.page.assessments.editNamed', { title })"
          :data-opener="`edit:${assessment.id}`" @click="actions.open('edit', assessment.id)">
          {{ t("documents.page.assessments.edit") }}
        </button>
        <button type="button" class="btn btn-sm secondary" :aria-label="t('documents.page.assessments.addPartNamed', { title })"
          :data-opener="`part:${assessment.id}`" @click="actions.open('part', assessment.id)">
          {{ t("documents.page.assessments.addPart") }}
        </button>
        <button type="button" class="btn btn-sm secondary danger" :aria-label="t('documents.page.assessments.dropNamed', { title })"
          @click="actions.drop(assessment)">
          {{ t("documents.page.assessments.drop") }}
        </button>
      </div>
      <AssessmentForm v-if="editable && mine('edit')" :document-id="documentId" :read="read" :assessment="assessment"
        @saved="(saved) => actions.saved(saved, false)" @changed="actions.changed()" @cancel="actions.cancel()"
        @dirty="(open) => actions.dirty('form', open)" />
      <AssessmentForm v-if="editable && mine('part')" :document-id="documentId" :read="read" :parent-id="assessment.id"
        @saved="(saved) => actions.saved(saved, true)" @changed="actions.changed()" @cancel="actions.cancel()"
        @dirty="(open) => actions.dirty('form', open)" />
      <ValueSection
        v-if="form && (editable || drafting.has(`values:${assessment.id}`))"
        :row="row"
        :form="form"
        :document-id="documentId"
        :editable="editable"
        :reviewable="reviewable"
        :closed-by="editable ? null : closedBy"
        :on-saved="actions.valuesSaved"
        :on-reviewed="actions.reviewed"
        @closed="actions.changed()"
        @gone="actions.gone()"
        @dirty="(open) => actions.dirty(`values:${assessment.id}`, open)"
      />
    </article>
    <ul v-if="children.length" class="assessment__parts" :aria-label="t('documents.page.assessments.parts', { title })">
      <AssessmentItem
        v-for="part in children"
        :key="part.id"
        :assessment="part"
        :read="read"
        :parts="parts"
        :names="names"
        :kinds="kinds"
        :levels="levels"
        :form="form"
        :document-id="documentId"
        :editable="editable"
        :reviewable="reviewable"
        :opened="opened"
        :drafting="drafting"
        :closed-by="closedBy"
        :actions="actions"
      />
    </ul>
  </li>
</template>

<style scoped>
.assessment {
  display: grid;
  gap: var(--space-2);
}

.assessment__body {
  display: grid;
  gap: var(--space-2);
}

.assessment__title,
.assessment .facts {
  margin: 0;
}

.assessment__title bdi {
  overflow-wrap: anywhere;
}

.assessment__actions {
  display: flex;
  flex-wrap: wrap;
  gap: var(--space-2);
}

.assessment__parts {
  display: grid;
  list-style: none;
  gap: var(--space-3);
  margin: 0;
  padding-inline-start: var(--space-3);
  border-inline-start: 2px solid var(--border);
}
</style>
