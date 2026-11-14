// The node types a new cue's form offers (TermDecisionForm.vue; lexiconTargets.ts reads them): read once the form
// asks, said in the form's own status as they come or do not - a region in the page from the start, so it is
// heard. A failure keeps its retry while the next reading runs, so the button holding the keyboard does not go
// from under it, and once they come the keyboard goes from that button to the node types.
import { nextTick, ref, type Ref } from "vue";

import type { FormValue } from "@/api";
import { t } from "@/i18n/de";

export interface NodeTypesReading {
  /** The node types, once read; null before. */
  types: Ref<FormValue[] | null>;
  failed: Ref<boolean>;
  loading: Ref<boolean>;
  /** The retry and the node types' field: the template's refs. */
  retry: Ref<HTMLElement | null>;
  select: Ref<HTMLElement | null>;
  load: () => Promise<void>;
}

/**
 * `read` asks for the node types; `say` puts a sentence in the form's status ("" to empty it); `came` hears them
 * once they come, before they show.
 */
export function useNodeTypesReading(
  read: () => Promise<FormValue[]>,
  say: (text: string) => void,
  came: (types: FormValue[]) => void,
): NodeTypesReading {
  const types = ref<FormValue[] | null>(null);
  const failed = ref(false);
  const loading = ref(false);
  const retry = ref<HTMLElement | null>(null);
  const select = ref<HTMLElement | null>(null);

  async function load(): Promise<void> {
    if (loading.value) return; // the retry stays focusable while busy, so it can be pressed again
    loading.value = true;
    say(t("lexicon.termForm.targetsLoading"));
    try {
      const found = await read();
      came(found);
      const retried = failed.value && document.activeElement === retry.value;
      types.value = found;
      failed.value = false;
      say("");
      await nextTick();
      if (retried) select.value?.focus();
    } catch {
      failed.value = true;
      say(t("lexicon.termForm.targetsFailed"));
    } finally {
      loading.value = false;
    }
  }

  return { types, failed, loading, retry, select, load };
}
