// What an entry of the lexicon's lists does with its form (LexiconCueItem.vue, LexiconTermItem.vue): opened on the
// reader's word; left, it takes the keyboard back to its button; a decision made in it takes the keyboard to the
// entry's decision once the list shows it - and only then: a decision the list brings from elsewhere, read again,
// leaves the keyboard where it is. However the form goes - left, saved, closed by its button, or with its entry
// when the list no longer shows it - the page hears that it holds nothing any more.
import { nextTick, onBeforeUnmount, ref, watch, type Ref } from "vue";

import { focusIsFree } from "@/focusRescue";

export interface ItemForm {
  open: Ref<boolean>;
  /** The button that opens the form, and the entry's decision: the template's refs. */
  toggle: Ref<HTMLElement | null>;
  summary: Ref<HTMLElement | null>;
  /** The form left: closed, the keyboard back on the button. */
  cancel: () => Promise<void>;
  /** A decision made in the form: closed, the keyboard to the decision once the list shows it. */
  made: () => void;
}

/** `decision` reads the entry's decision; `dirty` hears that the form went with whatever it held. */
export function useItemForm(decision: () => unknown, dirty: (now: boolean) => void): ItemForm {
  const open = ref(false);
  const toggle = ref<HTMLElement | null>(null);
  const summary = ref<HTMLElement | null>(null);
  let awaited = false;

  async function cancel(): Promise<void> {
    open.value = false;
    await nextTick();
    toggle.value?.focus();
  }

  function made(): void {
    awaited = true;
    open.value = false;
  }

  watch(open, (now) => {
    if (!now) dirty(false);
  });
  onBeforeUnmount(() => {
    if (open.value) dirty(false);
  });

  watch(decision, async () => {
    if (!awaited) return;
    awaited = false;
    await nextTick();
    // where the form took the keyboard along as it went; taken on elsewhere meanwhile, it stays
    if (focusIsFree()) summary.value?.focus();
  });

  return { open, toggle, summary, cancel, made };
}
