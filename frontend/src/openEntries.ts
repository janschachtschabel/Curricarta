// What the lexicon's two lists show under "Nur offene zeigen" (LexiconSample.vue, LexiconTerms.vue): the entries
// not yet decided, and those the reader works on here - whose form held input since the filter was set, a
// decision made here among them, as it chose something -, so a form left, emptied or saved does not go from under
// the keyboard; set again, the filter shows the open ones and those whose form still holds input. Tells the page
// whether any form holds what is not saved.
import { computed, reactive, ref, watch, type ComputedRef, type Ref } from "vue";

export interface OpenEntries<T> {
  openOnly: Ref<boolean>;
  /** How many entries are not decided. */
  open: ComputedRef<number>;
  /** The entries to show. */
  listed: ComputedRef<T[]>;
  /** Whether the form of the entry of this key holds what is not saved. */
  dirty: (key: string, now: boolean) => void;
}

/** `entries` reads the list's entries, `key` tells them apart, `decided` says whether one is; `unsavedAny` hears
 * whether any form holds what is not saved. */
export function useOpenEntries<T>(
  entries: () => readonly T[],
  key: (entry: T) => string,
  decided: (entry: T) => boolean,
  unsavedAny: (now: boolean) => void,
): OpenEntries<T> {
  const openOnly = ref(false);
  const unsaved = reactive(new Set<string>());
  const kept = reactive(new Set<string>());

  const open = computed(() => entries().filter((entry) => !decided(entry)).length);
  const listed = computed(() => entries().filter((entry) => !openOnly.value || !decided(entry) || kept.has(key(entry))));

  function dirty(which: string, now: boolean): void {
    if (now) {
      unsaved.add(which);
      kept.add(which);
    } else unsaved.delete(which);
  }

  watch(openOnly, () => {
    kept.clear();
    for (const which of unsaved) kept.add(which);
  });
  watch(
    () => unsaved.size > 0,
    (now) => unsavedAny(now),
  );

  return { openOnly, open, listed, dirty };
}
