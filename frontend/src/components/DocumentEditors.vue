<script setup lang="ts">
/**
 * The document page's editor sections, in their order: what its specifications are and where they apply
 * (DocumentScope, plan M3a H1), its rules (DocumentRules, plan M3a I) and its assessments (DocumentAssessments,
 * plan M3a J). A draft open in any of them is asked about once before the page goes (leaveGuard.ts), in the
 * section's own words while one section holds a draft and in the page's where several do. A new section is one
 * entry in SECTIONS and one in the template.
 */
import { computed, reactive } from "vue";

import ConfirmDialog from "@/components/ConfirmDialog.vue";
import DocumentAssessments from "@/components/DocumentAssessments.vue";
import DocumentRules from "@/components/DocumentRules.vue";
import DocumentScope from "@/components/DocumentScope.vue";
import { t } from "@/i18n/de";
import { useLeaveGuard } from "@/leaveGuard";

defineProps<{ documentId: string; sector: string; refresh: number }>();

// each section's words for its own draft, in the order the page shows them
const SECTIONS = {
  scope: "documents.page.scope.leave.message",
  rules: "documents.page.rules.leave",
  assessments: "documents.page.assessments.leave",
} as const;
type Section = keyof typeof SECTIONS;

const drafts = reactive<Record<Section, boolean>>({ scope: false, rules: false, assessments: false });

const open = computed(() => (Object.keys(SECTIONS) as Section[]).filter((section) => drafts[section]));
const { leaving, answer } = useLeaveGuard(() => open.value.length > 0);
const leaveMessage = computed(() =>
  open.value.length === 1 ? t(SECTIONS[open.value[0]]) : t("documents.page.leaveSeveral"),
);
</script>

<template>
  <DocumentScope class="document__section" :document-id="documentId" :sector="sector" :refresh="refresh"
    @dirty="drafts.scope = $event" />
  <DocumentRules class="document__section" :document-id="documentId" :refresh="refresh" @dirty="drafts.rules = $event" />
  <DocumentAssessments class="document__section" :document-id="documentId" :sector="sector" :refresh="refresh"
    @dirty="drafts.assessments = $event" />
  <ConfirmDialog v-if="leaving" :title="t('documents.page.scope.leave.title')" :message="leaveMessage"
    :confirm-label="t('documents.page.scope.leave.confirm')" :cancel-label="t('documents.page.scope.leave.cancel')"
    @confirm="answer(true)" @cancel="answer(false)" />
</template>

<style scoped>
/* as the page's other sections (DocumentView.vue) */
.document__section {
  margin-block-start: var(--space-4);
}
</style>
