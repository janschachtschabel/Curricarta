// The way of an export's button on the document's page (DocumentExport.vue, DocumentKernExport.vue): the
// request may take up to a minute, so the page says it works and asks once however often the button is
// pressed; the file is fetched with the session's token and saved under its name; a busy refusal says when to
// try again - in the seconds the server names, where it names them. An answer that comes after the page was
// left saves and says nothing. A file made but not handed to the browser is said as such.
import { onUnmounted, ref, type Ref } from "vue";

import { ApiError } from "@/api";
import { saveBlob } from "@/download";
import { sayAnew } from "@/liveRegion";
import { failureNotice, type Notice } from "@/notice";

/** What an export says, in its own words. */
export interface ExportWords<T> {
  working: string;
  saved: (made: T) => string;
  failed: string;
  saveFailed: string;
}

export interface ExportDownload {
  busy: Ref<boolean>;
  /** What the live region says: working, saved. */
  status: Ref<string>;
  failure: Ref<Notice | null>;
  /** When to try again after a refusal for now (429, 503): the seconds the server names, 0 where none. */
  retry: Ref<number | null>;
  start: () => Promise<void>;
}

/** An export's state and its start; ``refused`` hears each refusal of the server's, once it is shown. */
export function useExportDownload<T extends { blob: Blob; filename: string }>(
  fetchFile: () => Promise<T>,
  words: ExportWords<T>,
  refused: (error: ApiError) => void = () => undefined,
): ExportDownload {
  const busy = ref(false);
  const status = ref("");
  const failure = ref<Notice | null>(null);
  const retry = ref<number | null>(null);
  let gone = false;
  onUnmounted(() => {
    gone = true;
  });

  async function start(): Promise<void> {
    if (busy.value) return; // the button stays focusable while busy, so it can be pressed again
    busy.value = true;
    failure.value = null;
    retry.value = null;
    status.value = sayAnew(status.value, words.working);
    try {
      const made = await fetchFile();
      if (gone) return;
      try {
        saveBlob(made.blob, made.filename);
      } catch {
        status.value = "";
        failure.value = { text: words.saveFailed, failed: true };
        return;
      }
      status.value = sayAnew(status.value, words.saved(made));
    } catch (error) {
      if (gone) return;
      status.value = "";
      failure.value = failureNotice(error, words.failed);
      if (!(error instanceof ApiError)) return;
      // the exports' own refusals for now name no time: when to try again is said here; another (the
      // service's) says it in its own words
      if (error.code === "export_unavailable" || error.code === "too_many_exports") retry.value = error.retryAfter ?? 0;
      refused(error);
    } finally {
      busy.value = false;
    }
  }

  return { busy, status, failure, retry, start };
}
