<script setup lang="ts">
/**
 * Where a document comes from, on its page (plan M1 9.10, Paket 9d2 P2): its entry's provenance, rights, license and
 * their evidence and kind of source, in the entry page's words, and how its file came into the register
 * (AcquisitionList) - what an edition is backed by; the file, land and address stand on the entry's page. An entry
 * the account does not see is said as such, nothing to try again, and the page told (`hidden`): it offers no way
 * to the entry's page; another failure offers to read again, as
 * sectionReading.ts reads: waiting meanwhile, the keyboard to the section's heading once the button went.
 */
import { onMounted, ref } from "vue";

import { ApiError, getSource, type CurriculumDocument, type SourceDetail } from "@/api";
import AcquisitionList from "@/components/AcquisitionList.vue";
import ErrorState from "@/components/ErrorState.vue";
import LoadingState from "@/components/LoadingState.vue";
import { messages, t } from "@/i18n/de";
import { word } from "@/registerWords";
import { useSectionReading } from "@/sectionReading";

const props = defineProps<{ document: CurriculumDocument }>();
const emit = defineEmits<{ hidden: [] }>();

// an entry the account does not see is an answer, not a failure: no retry changes it
async function read(): Promise<SourceDetail | "hidden"> {
  try {
    return await getSource(props.document.source_id);
  } catch (error) {
    if (!(error instanceof ApiError && error.status === 404)) throw error;
    emit("hidden");
    return "hidden";
  }
}

const heading = ref<HTMLElement | null>(null);
const {
  shown: source,
  failure,
  load,
  retry,
} = useSectionReading(read, t("documents.page.source.failed"), heading);

onMounted(load);
</script>

<template>
  <section class="document-source" aria-labelledby="document-source">
    <!-- tabindex -1: where the keyboard goes once a retry's button went with its notice -->
    <h2 id="document-source" ref="heading" tabindex="-1">{{ t("documents.page.source.heading") }}</h2>
    <template v-if="source === null">
      <ErrorState
        v-if="failure"
        :message="failure.text"
        :reason="failure.reason"
        :explanation="failure.explanation"
        @retry="retry()"
      />
      <LoadingState v-else :label="t('documents.page.source.loading')" />
    </template>
    <p v-else-if="source === 'hidden'" class="document-source__note">{{ t("documents.page.source.hidden") }}</p>
    <template v-else>
      <dl class="facts">
        <dt>{{ t("entryPage.facts.provenance") }}</dt>
        <dd>{{ word(messages.sources.provenance, source.provenance) }}</dd>
        <dt>{{ t("entryPage.facts.rights") }}</dt>
        <dd>{{ word(messages.sources.rights, source.rights_status) }}</dd>
        <template v-if="source.license">
          <dt>{{ t("entryPage.facts.license") }}</dt>
          <dd><bdi>{{ source.license }}</bdi></dd>
        </template>
        <template v-if="source.rights_evidence">
          <dt>{{ t("entryPage.facts.rightsEvidence") }}</dt>
          <dd><bdi>{{ source.rights_evidence }}</bdi></dd>
        </template>
        <template v-if="source.source_type">
          <dt>{{ t("entryPage.facts.sourceType") }}</dt>
          <dd>{{ word(messages.entryPage.sourceType, source.source_type) }}</dd>
        </template>
      </dl>
      <template v-if="source.acquisitions.length">
        <h3>{{ t("entryPage.acquisitions.heading") }}</h3>
        <AcquisitionList :acquisitions="source.acquisitions" />
      </template>
    </template>
  </section>
</template>

<style scoped>
.document-source {
  display: grid;
  gap: var(--space-2);
  align-content: start;
}

.document-source h2,
.document-source h3,
.document-source .facts,
.document-source__note {
  margin: 0;
}

.document-source__note {
  color: var(--text-muted);
}
</style>
