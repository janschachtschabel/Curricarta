<script setup lang="ts">
/**
 * The export of a frozen MEM import as MEM-Schule's RDF (plan M2-8, B2; backend GET
 * /documents/{id}/export.ttl). The request checks the export against MEM's shapes before it answers -
 * up to a minute - so the page says it works and asks once however often the button is pressed; the file
 * is fetched with the session's token and saved under its name. A refused export lists the shapes its rows
 * broke, each linked to its row in the tree, the checker's English marked as English; a busy one says when
 * to try again - in the seconds the server names, where it names them. One no longer frozen meanwhile has
 * the page read the document again. A file made but not handed to the browser is said as such.
 */
import { onUnmounted, ref } from "vue";
import { RouterLink } from "vue-router";

import { ApiError, exportMem, exportViolations, type CurriculumDocument, type ExportViolation } from "@/api";
import AppIcon from "@/components/AppIcon.vue";
import NoticeText from "@/components/NoticeText.vue";
import { ROW_PARAM } from "@/documentTree";
import { saveBlob } from "@/download";
import { messages, t } from "@/i18n/de";
import { sayAnew } from "@/liveRegion";
import { failureNotice, type Notice } from "@/notice";

const props = defineProps<{ document: CurriculumDocument }>();
const emit = defineEmits<{ changed: [] }>();

const busy = ref(false);
const status = ref("");
const failure = ref<Notice | null>(null);
// when to try again after a refusal for now (429, 503): the seconds the server names, 0 where it names none
const retry = ref<number | null>(null);
const listed = ref<ExportViolation[]>([]);
const total = ref(0);
// an answer that comes after the page was left saves and says nothing
let gone = false;
onUnmounted(() => {
  gone = true;
});

function shapeName(shape: string): string {
  const words = messages.mem.export.shapes as Record<string, string>;
  return Object.hasOwn(words, shape) ? words[shape] : shape;
}

function rowOf(violation: ExportViolation): string | null {
  const kind = violation.row_kind;
  return (kind === "node" || kind === "statement") && violation.row_id ? `${kind}:${violation.row_id}` : null;
}

async function start(): Promise<void> {
  if (busy.value) return; // the button stays focusable while busy, so it can be pressed again
  busy.value = true;
  failure.value = null;
  retry.value = null;
  listed.value = [];
  status.value = sayAnew(status.value, t("mem.export.working"));
  try {
    const made = await exportMem(props.document.id);
    if (gone) return;
    try {
      saveBlob(made.blob, made.filename);
    } catch {
      status.value = "";
      failure.value = { text: t("mem.export.saveFailed"), failed: true };
      return;
    }
    status.value = sayAnew(status.value, t("mem.export.saved", { name: made.filename }));
  } catch (error) {
    if (gone) return;
    status.value = "";
    failure.value = failureNotice(error, t("mem.export.failed"));
    if (!(error instanceof ApiError)) return;
    if (error.code === "export_invalid") {
      const refused = exportViolations(error);
      listed.value = refused.violations;
      total.value = refused.total;
    }
    // its own refusals for now name no time: when to try again is said here; another (the service's)
    // says it in its own words
    if (error.code === "export_unavailable" || error.code === "too_many_exports") retry.value = error.retryAfter ?? 0;
    if (error.code === "export_not_frozen" || error.code === "not_mem_import") emit("changed");
  } finally {
    busy.value = false;
  }
}
</script>

<template>
  <section class="export" aria-labelledby="document-export">
    <h2 id="document-export" tabindex="-1">{{ t("mem.export.heading") }}</h2>
    <p v-if="!document.frozen_at" class="export__note">{{ t("refusals.export_not_frozen") }}</p>
    <template v-else>
      <p class="export__note">{{ t("mem.export.contains") }}</p>
      <p v-if="failure" class="field__error" role="alert">
        <AppIcon name="warning" /> <NoticeText :notice="failure" />
        <template v-if="retry !== null">
          {{ retry > 0 ? t("mem.export.wait", { count: retry }) : t("mem.export.again") }}
        </template>
      </p>
      <!-- aria-disabled, not disabled: a disabled button drops the focus it holds -->
      <button
        type="button"
        class="btn primary"
        data-test="export-start"
        :aria-disabled="busy || undefined"
        @click="start"
      >
        {{ t("mem.export.button") }}
      </button>
      <template v-if="listed.length">
        <h3 class="export__heading">{{ t("mem.export.violations.heading") }}</h3>
        <p class="export__note">{{ t("mem.export.violations.shown", { shown: listed.length, total }) }}</p>
        <!-- wider than a phone: scrolled on its own, by the keyboard too -->
        <div class="export__table" tabindex="0" role="region" :aria-label="t('mem.export.violations.table')">
          <table>
            <thead>
              <tr>
                <th scope="col">{{ t("mem.export.violations.columns.place") }}</th>
                <th scope="col">{{ t("mem.export.violations.columns.shape") }}</th>
                <th scope="col">{{ t("mem.export.violations.columns.path") }}</th>
                <th scope="col">{{ t("mem.export.violations.columns.message") }}</th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="(violation, index) in listed" :key="index">
                <td>
                  <!-- one name for every link: the rule its row broke tells them apart -->
                  <RouterLink
                    v-if="rowOf(violation)"
                    :to="{ name: 'documentTree', params: { id: document.id }, query: { [ROW_PARAM]: rowOf(violation) } }"
                    :aria-describedby="`export-shape-${index}`"
                  >
                    {{ t("mem.export.violations.toRow") }}
                  </RouterLink>
                  <template v-else-if="violation.row_kind === 'document'">
                    {{ t("mem.export.violations.document") }}
                  </template>
                  <bdi v-else class="export__iri">{{ violation.focus }}</bdi>
                </td>
                <td :id="`export-shape-${index}`">{{ shapeName(violation.shape) }}</td>
                <td><bdi class="export__iri">{{ violation.path ?? "–" }}</bdi></td>
                <td><q lang="en">{{ violation.message }}</q></td>
              </tr>
            </tbody>
          </table>
        </div>
      </template>
    </template>
    <!-- always in the page, so a screen reader hears each change of its text; shown, as the export may
         take a minute -->
    <p class="export__status" role="status">{{ status }}</p>
  </section>
</template>

<style scoped>
.export {
  display: flex;
  flex-direction: column;
  align-items: flex-start;
  gap: var(--space-1);
}

.export__note {
  max-width: var(--reading-width);
  margin: 0;
  color: var(--text-muted);
}

.export__status {
  max-width: var(--reading-width);
  margin: 0;
}

/* Empty, it takes no room - its gap would stand twice - but stays in the page, so its first word is read
   out (style.css: never display: none while empty) */
.export__status:empty {
  position: absolute;
}

.export__heading {
  margin: var(--space-2) 0 0;
}

.export__table {
  max-width: 100%;
  overflow-x: auto;
}

.export__table table {
  border-collapse: collapse;
  min-width: 40rem;
}

.export__table th,
.export__table td {
  padding: var(--space-0) var(--space-2) var(--space-0) 0;
  text-align: start;
  vertical-align: top;
}

.export__iri,
.export__table q {
  overflow-wrap: anywhere;
}
</style>
