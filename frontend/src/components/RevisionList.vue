<script setup lang="ts">
/**
 * The revisions of a document's IRI (plan M1 9.10, Paket 9d2 P4; documentRevision.ts): the documents of its entry
 * under the same IRI - its draft copies among them -, the latest first, each frozen with its date or a draft; the
 * others a way to their page, the document's own marked as the current one and said as the server reads it now. A
 * document that is its IRI's only revision lists nothing; read again once the document is frozen. While the list
 * is read nothing shows; where it fails, a sentence says so.
 */
import { computed, onMounted, ref, watch } from "vue";
import { RouterLink } from "vue-router";

import { listDocuments, type CurriculumDocument } from "@/api";
import { revisionsOf } from "@/documentRevision";
import { momentFormat, t } from "@/i18n/de";

const props = defineProps<{ document: CurriculumDocument }>();

const documents = ref<CurriculumDocument[]>([]);
const failed = ref(false);

// the document's own as the page holds it: newer than the list where it was frozen since, and there where the
// list read does not hold it
const revisions = computed(() =>
  revisionsOf([props.document, ...documents.value.filter((one) => one.id !== props.document.id)], props.document),
);

function words(one: CurriculumDocument): string {
  if (!one.frozen_at) return t("documents.page.revisions.draft", { revision: one.revision });
  const date = momentFormat.format(new Date(one.frozen_at));
  return t("documents.page.revisions.frozen", { revision: one.revision, date });
}

async function load(): Promise<void> {
  try {
    documents.value = await listDocuments(props.document.source_id);
    failed.value = false;
  } catch {
    failed.value = true; // said below; the rest of the page stands
  }
}

onMounted(load);
watch(
  () => props.document.frozen_at,
  () => void load(),
);
</script>

<template>
  <div v-if="revisions.length > 1" class="revision-list">
    <h3>{{ t("documents.page.revisions.heading") }}</h3>
    <ul class="revision-list__items">
      <li v-for="one in revisions" :key="one.id">
        <span v-if="one.id === document.id" aria-current="page">{{ words(one) }}</span>
        <RouterLink v-else :to="{ name: 'document', params: { id: one.id } }">{{ words(one) }}</RouterLink>
      </li>
    </ul>
  </div>
  <p v-else-if="failed" class="revision-list__failed">{{ t("documents.page.revisions.failed") }}</p>
</template>

<style scoped>
.revision-list {
  display: grid;
  gap: var(--space-1);
}

.revision-list h3,
.revision-list__items,
.revision-list__failed {
  margin: 0;
}

.revision-list__items {
  padding-inline-start: var(--space-3);
}

/* the document's own: a weight, so the eye sees what a screen reader hears (as App.vue marks where you are) */
.revision-list [aria-current] {
  font-weight: 600;
}

.revision-list__failed {
  color: var(--text-muted);
}
</style>
