<script setup lang="ts">
/**
 * MEM-Schule's catalogue, as the import's section needs it (plan M2-8, A6): when it was last read - a
 * catalogue never read is said so, not shown as a search that found nothing - and, for an admin, its
 * reading (backend source.mem_catalog). The reading asks MEM-Schule's server, so the page asks first; one
 * that waits or runs already is followed rather than started again (409 catalog_running). A reading done
 * tells the section, which looks the catalogue up anew.
 */
import { computed, ref } from "vue";

import { ApiError, startMemCatalog, type Job } from "@/api";
import AppIcon from "@/components/AppIcon.vue";
import ConfirmDialog from "@/components/ConfirmDialog.vue";
import JobProgress from "@/components/JobProgress.vue";
import NoticeText from "@/components/NoticeText.vue";
import { momentFormat, t } from "@/i18n/de";
import { sayAnew } from "@/liveRegion";
import { failureNotice, type Notice } from "@/notice";
import { hasRole } from "@/session";

const props = defineProps<{
  /** When the catalogue last read a plan; null: never. */
  readAt: string | null;
}>();
const emit = defineEmits<{ read: [] }>();

// a catalogue older than this may miss plans MEM-Schule has since
const OLD_AFTER_MS = 30 * 24 * 60 * 60 * 1000;

const admin = computed(() => hasRole("admin"));
const old = computed(() => props.readAt !== null && Date.now() - Date.parse(props.readAt) > OLD_AFTER_MS);
const asking = ref(false);
const busy = ref(false);
const jobId = ref<string | null>(null);
const status = ref("");
const failure = ref<Notice | null>(null);

function ask(): void {
  if (!busy.value) asking.value = true;
}

async function start(): Promise<void> {
  asking.value = false;
  busy.value = true;
  failure.value = null;
  try {
    // JobProgress says the reading's states from here: no line of its own beside them
    jobId.value = (await startMemCatalog()).job_id;
  } catch (error) {
    const running = runningReading(error);
    if (running) {
      status.value = sayAnew(status.value, t("refusals.catalog_running"));
      jobId.value = running;
    } else {
      status.value = "";
      failure.value = failureNotice(error, t("mem.catalog.startFailed"));
    }
  } finally {
    busy.value = false;
  }
}

/** The reading that waits or runs already, as the server names it in its refusal. */
function runningReading(error: unknown): string | null {
  if (!(error instanceof ApiError) || error.status !== 409 || error.code !== "catalog_running") return null;
  const id = error.details.job_id;
  return typeof id === "string" ? id : null;
}

function ended(job: Job): void {
  status.value = ""; // JobProgress says how it ended
  if (job.status === "done") emit("read");
}
</script>

<template>
  <div class="catalog">
    <p v-if="readAt === null" class="catalog__state" data-test="catalog-never">
      {{ admin ? t("mem.catalog.neverAdmin") : t("mem.catalog.never") }}
    </p>
    <template v-else>
      <p class="catalog__state">
        {{ t("mem.catalog.readAt") }}
        <time :datetime="readAt">{{ momentFormat.format(new Date(readAt)) }}</time>
      </p>
      <p v-if="old" class="catalog__old" data-test="catalog-old">
        <AppIcon name="warning" /> {{ t("mem.catalog.old") }}
      </p>
    </template>
    <template v-if="admin">
      <p v-if="failure" class="field__error" role="alert">
        <AppIcon name="warning" /> <NoticeText :notice="failure" />
      </p>
      <!-- aria-disabled, not disabled: a disabled button drops the focus it holds -->
      <button
        type="button"
        class="btn"
        data-test="catalog-start"
        :aria-disabled="busy || undefined"
        @click="ask"
      >
        {{ readAt === null ? t("mem.catalog.start") : t("mem.catalog.restart") }}
      </button>
      <!-- Always in the page, so a screen reader hears each change of its text -->
      <p class="catalog__status visually-hidden" role="status">{{ status }}</p>
      <JobProgress v-if="jobId" :key="jobId" :job-id="jobId" :label="t('mem.catalog.jobLabel')" @ended="ended" />
      <ConfirmDialog
        v-if="asking"
        :title="t('mem.catalog.confirmTitle')"
        :message="t('mem.catalog.confirmMessage')"
        :confirm-label="t('mem.catalog.confirm')"
        :danger="false"
        @confirm="start"
        @cancel="asking = false"
      />
    </template>
  </div>
</template>

<style scoped>
.catalog {
  display: flex;
  flex-direction: column;
  align-items: flex-start;
  gap: var(--space-1);
}

.catalog__state,
.catalog__old,
.catalog__status {
  max-width: var(--reading-width);
  margin: 0;
}

.catalog__status {
  font-size: var(--step--1);
}
</style>
