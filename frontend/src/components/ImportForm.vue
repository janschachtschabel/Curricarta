<script setup lang="ts">
/**
 * An address into the register: the server enters it and starts the job that
 * fetches the file. Only a web address is sent; whether its host may be asked
 * at all is the server's to decide (no address inside its network). It reports
 * the entry and its job; following the job is the page's business.
 */
import { nextTick, ref } from "vue";

import { ApiError, importSource, MAX_TITLE_SIGNS, MAX_URL_SIGNS, type ImportStarted } from "@/api";
import { isolate } from "@/bidi";
import AppIcon from "@/components/AppIcon.vue";
import NoticeText from "@/components/NoticeText.vue";
import { requiredLabel } from "@/formWords";
import { focusIsFree } from "@/focusRescue";
import { t } from "@/i18n/de";
import { sayAnew } from "@/liveRegion";
import { failureNotice, type Notice } from "@/notice";

// `address` names the entry until its file arrives: an import's title is the file's name, unless one was given
const emit = defineEmits<{ imported: [started: ImportStarted, address: string] }>();

const url = ref("");
const title = ref("");
const busy = ref(false);
const status = ref("");
const failure = ref<Notice | null>(null);
const submitButton = ref<HTMLButtonElement | null>(null);

type Field = "url" | "title";
// a refusal of one field, said at that field too; any other below the form alone
const failedField = ref<Field | null>(null);
const FIELD_OF_CODE: Readonly<Record<string, Field>> = {
  url_invalid: "url",
  title_invalid: "title",
  title_too_long: "title",
};

/** The field's help, and the error where it is this field's. */
function describedBy(field: Field): string {
  return failedField.value === field ? `import-${field}-hint import-error` : `import-${field}-hint`;
}

function fieldOf(error: unknown): Field | null {
  return error instanceof ApiError && error.code ? (FIELD_OF_CODE[error.code] ?? null) : null;
}

/**
 * Why the server would not fetch `candidate`, as a catalogue key; null for a web
 * address it takes up. The server checks again (url_invalid): this spares the
 * request, and a password never leaves the page.
 */
function addressFault(candidate: string): string | null {
  // checked rather than held by a field limit, which cut a pasted address to another one silently
  if (candidate.length > MAX_URL_SIGNS) return "sources.import.errors.tooLong";
  if (/\s/.test(candidate)) return "sources.import.errors.spaces";
  let parsed: URL;
  try {
    parsed = new URL(candidate);
  } catch {
    return "sources.import.errors.scheme"; // no address at all
  }
  if (!["http:", "https:"].includes(parsed.protocol)) return "sources.import.errors.scheme";
  return parsed.username || parsed.password ? "sources.import.errors.credentials" : null;
}

// each field by its name, for the status where the keyboard stays elsewhere
const LABELS: Readonly<Record<Field, () => string>> = {
  url: () => t("sources.import.urlLabel"),
  title: () => t("sources.import.titleLabel"),
};

/**
 * The refusal to show, at its field where it is one field's; the same one again is read out again
 * (liveRegion.ts). The keyboard goes to that field from the button or from nothing, as in every other form, and
 * the field reads it; resting elsewhere, the status says it with the field's name - read once either way.
 */
async function refuse(notice: Notice, field: Field | null): Promise<void> {
  failure.value = { ...notice, text: sayAnew(failure.value?.text ?? "", notice.text) };
  failedField.value = field;
  status.value = "";
  if (!field) return;
  await nextTick();
  if (document.activeElement === submitButton.value || focusIsFree()) document.getElementById(`import-${field}`)?.focus();
  else status.value = sayAnew(status.value, t("forms.fieldProblem", { field: LABELS[field](), problem: notice.text }));
}

async function onSubmit(): Promise<void> {
  if (busy.value) return; // the button stays focusable while busy, so it can be pressed again
  const address = url.value.trim();
  if (!address) return refuse({ text: t("sources.import.errors.missing"), failed: true }, "url");
  const fault = addressFault(address);
  if (fault) return refuse({ text: t(fault, { limit: MAX_URL_SIGNS }), failed: true }, "url");
  busy.value = true;
  failure.value = null;
  failedField.value = null;
  status.value = t("sources.import.busy");
  try {
    const started = await importSource(address, title.value);
    status.value = t("sources.import.started", { title: isolate(started.source.title || address) });
    url.value = "";
    title.value = "";
    emit("imported", started, address);
  } catch (error) {
    await refuse(failureNotice(error, t("sources.import.failed")), fieldOf(error));
  } finally {
    busy.value = false;
  }
}
</script>

<template>
  <form class="source-form" novalidate @submit.prevent="onSubmit">
    <h3 class="source-form__heading">{{ t("sources.import.heading") }}</h3>
    <div class="field">
      <label for="import-url">{{ requiredLabel(t("sources.import.urlLabel")) }}</label>
      <input
        id="import-url"
        aria-required="true"
        v-model="url"
        type="url"
        inputmode="url"
        autocomplete="url"
        spellcheck="false"
        :aria-invalid="failedField === 'url' || undefined"
        :aria-describedby="describedBy('url')"
      />
      <p id="import-url-hint" class="field__hint">{{ t("sources.import.urlHint") }}</p>
      <!-- no alert: the field it describes takes the keyboard and reads it, or the status says it -->
      <p v-if="failure && failedField === 'url'" id="import-error" class="field__error">
        <AppIcon name="warning" /> <NoticeText :notice="failure" />
      </p>
    </div>
    <div class="field">
      <label for="import-title">{{ t("sources.import.titleLabel") }}</label>
      <input
        id="import-title"
        v-model="title"
        type="text"
        :maxlength="MAX_TITLE_SIGNS"
        autocomplete="off"
        :aria-invalid="failedField === 'title' || undefined"
        :aria-describedby="describedBy('title')"
      />
      <p id="import-title-hint" class="field__hint">{{ t("sources.import.titleHint") }}</p>
      <!-- no alert: the field it describes takes the keyboard and reads it, or the status says it -->
      <p v-if="failure && failedField === 'title'" id="import-error" class="field__error">
        <AppIcon name="warning" /> <NoticeText :notice="failure" />
      </p>
    </div>

    <!-- a refusal of no one field, below them -->
    <p v-if="failure && !failedField" id="import-error" class="field__error source-form__error" role="alert">
      <AppIcon name="warning" /> <NoticeText :notice="failure" />
    </p>
    <!-- aria-disabled, not disabled: a disabled button drops the focus it holds -->
    <button ref="submitButton" type="submit" class="btn primary" :aria-disabled="busy || undefined">
      {{ t("sources.import.submit") }}
    </button>
    <!-- Always in the page, so a screen reader hears each change of its text -->
    <p id="import-status" class="source-form__status" role="status">{{ status }}</p>
  </form>
</template>

