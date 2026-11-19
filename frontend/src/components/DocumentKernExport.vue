<script setup lang="ts">
/**
 * The export of a frozen document as Curriculum-Kern RDF (plan M3a C2; backend GET
 * /documents/{id}/kern.ttl): its graph under the IRIs freezing gave, built in a child process - seconds,
 * up to a minute -; how the button waits, saves and says so is the exports' own (useExportDownload.ts).
 * Saved, it says how many violations the editors accepted when they froze the document, as the file's
 * head does. One no longer frozen meanwhile has the page read the document again.
 */
import { exportKern, type CurriculumDocument } from "@/api";
import AppIcon from "@/components/AppIcon.vue";
import NoticeText from "@/components/NoticeText.vue";
import { t } from "@/i18n/de";
import { useExportDownload } from "@/useExportDownload";

const props = defineProps<{ document: CurriculumDocument }>();
const emit = defineEmits<{ changed: [] }>();

const { busy, status, failure, retry, start } = useExportDownload(
  () => exportKern(props.document.id),
  {
    working: t("documents.page.kernExport.working"),
    saved: (made) =>
      made.accepted > 0
        ? t("documents.page.kernExport.savedAccepted", { name: made.filename, count: made.accepted })
        : t("documents.page.kernExport.saved", { name: made.filename }),
    failed: t("documents.page.kernExport.failed"),
    saveFailed: t("documents.page.kernExport.saveFailed"),
  },
  (error) => {
    if (error.code === "export_not_frozen") emit("changed");
  },
);
</script>

<template>
  <section class="kern-export" aria-labelledby="document-kern-export">
    <h2 id="document-kern-export" tabindex="-1">{{ t("documents.page.kernExport.heading") }}</h2>
    <template v-if="document.frozen_at">
      <p class="kern-export__note">{{ t("documents.page.kernExport.contains") }}</p>
      <p v-if="failure" class="field__error" role="alert">
        <AppIcon name="warning" /> <NoticeText :notice="failure" />
        <template v-if="retry !== null">
          {{
            retry > 0
              ? t("documents.page.kernExport.wait", { count: retry })
              : t("documents.page.kernExport.again")
          }}
        </template>
      </p>
      <!-- aria-disabled, not disabled: a disabled button drops the focus it holds -->
      <button
        type="button"
        class="btn primary"
        data-test="kern-export-start"
        :aria-disabled="busy || undefined"
        @click="start"
      >
        {{ t("documents.page.kernExport.button") }}
      </button>
    </template>
    <!-- always in the page, so a screen reader hears each change of its text; shown, as the export may
         take a minute -->
    <p class="kern-export__status" role="status">{{ status }}</p>
  </section>
</template>

<style scoped>
.kern-export {
  display: flex;
  flex-direction: column;
  align-items: flex-start;
  gap: var(--space-1);
}

.kern-export__note,
.kern-export__status {
  max-width: var(--reading-width);
  margin: 0;
}

.kern-export__note {
  color: var(--text-muted);
}

/* Empty, it takes no room - its gap would stand twice - but stays in the page, so its first word is read
   out (style.css: never display: none while empty) */
.kern-export__status:empty {
  position: absolute;
}
</style>
