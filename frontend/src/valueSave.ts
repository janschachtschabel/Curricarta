// Saving a row's values (plan M3a G; backend app/api/values.py), as rowSave.ts saves its fields: the set goes whole,
// on the revision of the holder its draft began from, and the answer - the holder as stored - is stood on. Each
// problem the draft holds is found before anything is asked (valueDraft.checkDraft). Where another stored a change
// meanwhile (409 stale_revision, details.current: the holder) a kind only the other changed is taken in and a kind
// both changed put before the user, in words, to keep or take (valueDraft.rebaseValues); where the tree closed the
// reason is kept with the draft; a field's problem stands at the field of the entry it names (`workloads[1].unit`)
// - the server's at the entry as the set was sent, by its key, however the entries moved since; above the form
// where that entry was taken away meanwhile -, a problem of a part the form does not show above it, as any other
// failure. The same row read anew is taken where
// nothing was changed; changed, the draft stays - going on from the new revision where only that moved (a value
// reviewed, the holder's fields changed). An entry keeps its key while its value is the same, so a control does not
// lose the keyboard as the row is read again. A specification is saved so (valueHolder.ts), its applicability
// contexts with its values.
import { computed, ref, shallowRef, watch, type Ref } from "vue";

import { ApiError, type Form } from "@/api";
import { t } from "@/i18n/de";
import type { Notice } from "@/notice";
import { applyRefusal, problemText, refusalOf } from "@/rowRefusals";
import {
  changedKinds,
  checkDraft,
  draftOfValues,
  entryField,
  holdsEntry,
  rebaseValues,
  sameValues,
  valueOf,
  type DraftKind,
  type ValueFault,
  type ValuesDraft,
} from "@/valueDraft";
import { heldOf, holderOf, sendValues, type Holder, type HolderRow } from "@/valueHolder";
import { valueWords, type LevelValue } from "@/valueWords";

export type ValueSaveOutcome = "saved" | "unchanged" | "undecided" | "conflict" | "invalid" | "closed" | "gone" | "failed";

/** How a save went; the problems found where it is invalid, the holder as stored where it is saved. */
export interface ValueSaved {
  outcome: ValueSaveOutcome;
  faults?: ValueFault[];
  answer?: Holder;
}

/** A kind both changed: the user's values and the stored, in words. */
export interface ValueClash {
  kind: DraftKind;
  yours: string[];
  stored: string[];
}

export interface ValueConflict {
  clashes: ValueClash[];
  /** The kinds only the other changed, with their values as stored now, in words. */
  taken: { kind: DraftKind; stored: string[] }[];
  stored: ValuesDraft;
}

export function useValueSave(row: Ref<HolderRow>, form: Ref<Form>) {
  const before = shallowRef<ValuesDraft>(draftOfValues(form.value, heldOf(holderOf(row.value))));
  const draft = shallowRef<ValuesDraft>(before.value);
  const revision = ref(holderOf(row.value).revision);
  const saving = ref(false);
  const problem = shallowRef<Notice | null>(null);
  const conflict = shallowRef<ValueConflict | null>(null);
  const closed = ref<string | null>(null);
  const dirty = computed(() => !sameValues(before.value, draft.value));

  function stand(holder: Holder): void {
    before.value = draftOfValues(form.value, heldOf(holder), draft.value);
    draft.value = before.value;
    revision.value = holder.revision;
  }

  watch(row, (now, was) => {
    if (now.key !== was.key) {
      problem.value = null;
      conflict.value = null;
      closed.value = null;
      stand(holderOf(now));
    } else if (!dirty.value) stand(holderOf(now));
    else if (sameValues(before.value, draftOfValues(form.value, heldOf(holderOf(now))))) revision.value = holderOf(now).revision;
  });

  /** The entries of `kind` in words. */
  function wordsOf(set: ValuesDraft, kind: DraftKind): string[] {
    return set[kind].map((entry) => valueWords(kind, valueOf(form.value, kind, entry) as unknown as LevelValue, form.value));
  }

  function met(current: Holder): ValueSaveOutcome {
    const stored = draftOfValues(form.value, heldOf(current), draft.value);
    const laid = rebaseValues(before.value, draft.value, stored);
    // the other stored what the user asked: saved, by whoever
    if (sameValues(stored, laid.draft)) {
      stand(current);
      conflict.value = null;
      return "saved";
    }
    const yours = draft.value;
    before.value = stored;
    draft.value = laid.draft;
    revision.value = current.revision;
    conflict.value = {
      clashes: laid.clashes.map((kind) => ({ kind, yours: wordsOf(yours, kind), stored: wordsOf(stored, kind) })),
      taken: laid.taken.map((kind) => ({ kind, stored: wordsOf(stored, kind) })),
      stored,
    };
    return "conflict";
  }

  function refused(error: unknown, sent: ValuesDraft): ValueSaved {
    const code = error instanceof ApiError ? error.code : undefined;
    const details = error instanceof ApiError ? error.details : {};
    if (code === "stale_revision") {
      const current = details.current as Partial<Holder> | null;
      if (!current?.values || typeof current.revision !== "number") return { outcome: "gone" };
      return { outcome: met(current as Holder), answer: current as Holder };
    }
    if (code === "invalid_field") {
      const at = typeof details.field === "string" ? entryField(form.value, sent, details.field) : null;
      // the store's refusal of a context as a whole: the context refused, no value of it
      const words =
        at?.endsWith(":context") && details.problem === "refused" ? t("documents.tree.values.contextRefused") : problemText(details.problem);
      const kept = at !== null && holdsEntry(draft.value, at.slice(0, at.indexOf(":")));
      if (at !== null && kept) return { outcome: "invalid", faults: [[at, words]] };
      problem.value = { text: t("documents.tree.values.saveFailed"), explanation: words, failed: true };
      return { outcome: "invalid", faults: [] };
    }
    const errors = ref<Record<string, string>>({});
    const refusal = refusalOf(error, [], t("documents.tree.values.saveFailed"));
    return { outcome: applyRefusal(refusal, { closed, errors, problem }) };
  }

  /** Save the draft; how it went. */
  async function save(): Promise<ValueSaved> {
    if (conflict.value?.clashes.length) return { outcome: "undecided" };
    problem.value = null;
    const found = checkDraft(form.value, draft.value);
    if (found.length) {
      return { outcome: "invalid", faults: found.map(([path, words]) => [entryField(form.value, draft.value, path) ?? path, words]) };
    }
    if (!dirty.value) {
      conflict.value = null;
      return { outcome: "unchanged", faults: [] };
    }
    const current = row.value;
    const sent = draft.value;
    saving.value = true;
    try {
      const answer = await sendValues(current, revision.value, form.value, draft.value);
      // another row chosen meanwhile: the tree read anew shows what was saved
      if (row.value.key !== current.key) return { outcome: "saved", answer };
      const typed = draft.value;
      stand(answer);
      // typed on while it was saved: that stays, laid on the holder as stored
      if (typed !== sent) draft.value = rebaseValues(sent, typed, before.value).draft;
      conflict.value = null;
      return { outcome: "saved", faults: [], answer };
    } catch (error) {
      return row.value.key === current.key ? refused(error, sent) : { outcome: "failed" };
    } finally {
      saving.value = false;
    }
  }

  function settle(kind: DraftKind, take: boolean): void {
    const now = conflict.value;
    if (!now) return;
    if (take) draft.value = { ...draft.value, [kind]: now.stored[kind] };
    conflict.value = { ...now, clashes: now.clashes.filter((clash) => clash.kind !== kind) };
  }

  return {
    draft,
    revision,
    saving,
    problem,
    conflict,
    closed,
    dirty,
    save,
    /** The kinds the draft changes, each in words, to copy where the tree closed on it. */
    changes: computed(() => changedKinds(before.value, draft.value).map((kind) => ({ kind, words: wordsOf(draft.value, kind) }))),
    /** Keep the user's values of a kind both changed. */
    keep: (kind: DraftKind) => settle(kind, false),
    /** Take the stored values of a kind both changed. */
    take: (kind: DraftKind) => settle(kind, true),
  };
}
