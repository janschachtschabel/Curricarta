// A refusal in the register's upload and address forms (UploadForm.vue, ImportForm.vue), each of which checks one
// field before sending and hears the server refuse one: shown at its field where it is one field's, else below the
// fields; the same one again is read out again (liveRegion.ts). The keyboard goes to that field from the button or
// from nothing, as in every other form, and the field reads it; resting elsewhere, the form's status says it with the
// field's name - read once either way.
import { nextTick, ref, type Ref } from "vue";

import { focusIsFree } from "@/focusRescue";
import { t } from "@/i18n/de";
import { sayAnew } from "@/liveRegion";
import type { Notice } from "@/notice";

export function useFieldRefusal<F extends string>(place: {
  /** The form's ids: `<prefix>-<field>` a control, `<prefix>-<field>-hint` its help, `<prefix>-error` the error. */
  prefix: string;
  label: (field: F) => string;
  submit: Ref<HTMLElement | null>;
  status: Ref<string>;
}) {
  const failure = ref<Notice | null>(null);
  const failedField = ref(null) as Ref<F | null>;

  /** The field's help, and the error where it is this field's. */
  function describedBy(field: F): string {
    const hint = `${place.prefix}-${field}-hint`;
    return failedField.value === field ? `${hint} ${place.prefix}-error` : hint;
  }

  async function refuse(notice: Notice, field: F | null): Promise<void> {
    failure.value = { ...notice, text: sayAnew(failure.value?.text ?? "", notice.text) };
    failedField.value = field;
    place.status.value = "";
    if (!field) return;
    await nextTick();
    if (document.activeElement === place.submit.value || focusIsFree()) {
      document.getElementById(`${place.prefix}-${field}`)?.focus();
    } else {
      place.status.value = sayAnew(place.status.value, t("forms.fieldProblem", { field: place.label(field), problem: notice.text }));
    }
  }

  function clear(): void {
    failure.value = null;
    failedField.value = null;
  }

  return { failure, failedField, describedBy, refuse, clear };
}
