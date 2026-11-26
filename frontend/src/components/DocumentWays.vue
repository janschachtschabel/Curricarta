<script setup lang="ts">
/**
 * The top of a document's page, under its heading: its main next step - opening the tree - and a way to each of
 * the sections the page shows, in its order, each by its heading's words (UI review m10: the step was an inline
 * link among the facts of a page of ten sections). Each section's heading takes the keyboard (tabindex -1).
 */
import { computed } from "vue";
import { RouterLink } from "vue-router";

import type { CurriculumDocument } from "@/api";
import { focusById } from "@/focusRescue";
import { t } from "@/i18n/de";
import { isEditor } from "@/session";

const props = defineProps<{ document: CurriculumDocument }>();

// the sections the page shows, in its order, each by its heading's words: a way to each from the top of a long page
const sections = computed(() => {
  const shown = props.document;
  const mem = shown.mem !== null;
  return [
    { id: "document-facts", label: t("documents.page.facts.heading") },
    { id: "document-source", label: t("documents.page.source.heading") },
    ...(mem ? [{ id: "document-mem", label: t("mem.origin.heading") }] : []),
    { id: "document-edition", label: t("documents.page.edition.heading") },
    { id: "document-scope", label: t("documents.page.scope.heading") },
    { id: "document-assessments", label: t("documents.page.assessments.heading") },
    { id: "document-extraction", label: mem ? t("mem.job.heading") : t("documents.page.extraction") },
    ...(mem ? [] : [{ id: "document-units", label: t("documents.units.heading") }]),
    { id: "document-findings", label: t("documents.findings.heading") },
    // as DocumentFreeze offers itself
    ...(isEditor() && shown.frozen_at === null ? [{ id: "document-freeze", label: t("documents.page.freeze.heading") }] : []),
    ...(shown.frozen_at !== null ? [{ id: "document-kern-export", label: t("documents.page.kernExport.heading") }] : []),
    ...(mem ? [{ id: "document-export", label: t("mem.export.heading") }] : []),
    { id: "document-runs", label: t("documents.page.runs") },
  ];
});
</script>

<template>
  <div class="document-ways">
    <p>
      <RouterLink class="btn primary" data-test="open-tree" :to="{ name: 'documentTree', params: { id: document.id } }">
        {{ t("documents.page.treeLink") }}
      </RouterLink>
    </p>
    <nav data-test="document-sections" :aria-label="t('documents.page.sections')">
      <ul>
        <li v-for="part in sections" :key="part.id">
          <!-- the keyboard to the section's heading, not the address's fragment: the router took that for a move and
               named the tab anew without the document (focusRescue.ts) -->
          <a class="section-link" :href="`#${part.id}`" @click.prevent="focusById(part.id)">{{ part.label }}</a>
        </li>
      </ul>
    </nav>
  </div>
</template>

<style scoped>
.document-ways p {
  margin: 0 0 var(--space-2);
}

.document-ways ul {
  display: flex;
  flex-wrap: wrap;
  gap: var(--space-1) var(--space-3);
  margin: 0;
  padding: 0;
  list-style: none;
}
</style>
