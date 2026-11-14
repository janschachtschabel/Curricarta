// A form's problems at its fields, every one of them at one press (UI review m6: a form of three empty fields
// named one, the next two took two more presses). Each stands at its field; the keyboard goes to the first from the
// button or from nothing - the field reads its problem with its name -; resting elsewhere, it stays, and the first
// problem is said where the form says things (`say`).
import { nextTick, ref, type Ref } from "vue";

import { focusIsFree } from "@/focusRescue";

/** A field and its problem. */
export type Fault<F extends string> = readonly [field: F, problem: string];

export function useFieldFaults<F extends string>(place: {
  /** The id of the field's control, where the keyboard goes. */
  control: (field: F) => string;
  submit: Ref<HTMLElement | null>;
  say: (field: F, problem: string) => void;
}) {
  const faults = ref<Partial<Record<F, string>>>({}) as Ref<Partial<Record<F, string>>>;

  async function faultsAt(found: readonly Fault<F>[]): Promise<void> {
    faults.value = Object.fromEntries(found) as Partial<Record<F, string>>;
    const first = found[0];
    if (!first) return;
    await nextTick();
    if (document.activeElement === place.submit.value || focusIsFree()) {
      document.getElementById(place.control(first[0]))?.focus();
      return;
    }
    place.say(...first);
  }

  function clear(): void {
    faults.value = {};
  }

  return { faults, faultsAt, clear };
}
