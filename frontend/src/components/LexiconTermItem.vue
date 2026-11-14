<script setup lang="ts">
/**
 * One term X1 found no type for, or a decision on a term gone shown as it was judged (plan M1 10.5, 10e E9): its
 * word, where and in how many documents, the functions X1 suggested, its first places - each a way to its
 * document -, the cues that hold the word already, and its decision with whether the files hold the new cue, or
 * that the import leaves it out. Decided in a form of its own (TermDecisionForm), as LexiconCueItem decides a cue.
 */
import { computed, useId } from "vue";
import { RouterLink } from "vue-router";

import type { HeldCue, Labels, NewTerm, TermDecision } from "@/api";
import { isolate } from "@/bidi";
import TermDecisionForm from "@/components/TermDecisionForm.vue";
import { momentFormat, t } from "@/i18n/de";
import { useItemForm } from "@/itemForm";
import type { Targets } from "@/lexiconTargets";
import { labelList, labelOf, regionWords, sectorWord, skipReason } from "@/lexiconWords";

// `level`: its heading's, 3 by default - 4 under a heading of its list's own
const props = defineProps<{ term: NewTerm; labels: Labels; targets: Targets; gone?: boolean; level?: 3 | 4 }>();
const emit = defineEmits<{ decided: [made: TermDecision, labels: Labels]; reload: []; dirty: [dirty: boolean] }>();

const id = useId();
const { open, toggle, summary, cancel, made } = useItemForm(
  () => props.term.decision,
  (now) => emit("dirty", now),
);

const where = computed(() => {
  const named = props.gone ? t("lexicon.term.gone") : t("lexicon.term.documents", { count: props.term.documents });
  return [sectorWord(props.term.sector), regionWords(props.term.regions), named].join(" · ");
});

// the documents counted but not among the places listed
const more = computed(() => props.term.documents - new Set(props.term.occurrences.map((place) => place.document)).size);

function heldWords(cue: HeldCue): string {
  const regions = cue.regions.length ? labelList(props.labels, cue.regions) : t("lexicon.cue.everywhere");
  const source = t(cue.own ? "lexicon.term.own" : "lexicon.term.research");
  return [labelList(props.labels, cue.maps_to), labelOf(props.labels, cue.role), source, regions].join(" · ");
}

function applied(decision: TermDecision): string {
  if (decision.applied) return t("lexicon.term.applied");
  const skipped = skipReason(props.term.held, decision.maps_to);
  return skipped ? t(`lexicon.term.skipped.${skipped}`) : t("lexicon.item.waiting");
}

const said = computed(() => {
  const decision = props.term.decision;
  if (!decision) return t("lexicon.item.undecided");
  const verdict =
    decision.decision === "cue"
      ? t("lexicon.term.cue", {
          target: labelOf(props.labels, decision.maps_to ?? ""),
          role: decision.role ? t(`lexicon.termForm.roles.${decision.role}`) : "",
        })
      : t(`lexicon.term.${decision.decision}`);
  const by = t("lexicon.item.by", { name: isolate(decision.decided_by), date: momentFormat.format(new Date(decision.decided_at)) });
  const note = decision.note ? t("lexicon.item.note", { note: isolate(decision.note) }) : "";
  // nothing to take into the files of a term peculiar to its document, or misread
  const files = decision.decision === "cue" ? applied(decision) : "";
  return [verdict, by, note, files].filter(Boolean).join(" ");
});

function decided(decision: TermDecision, labels: Labels): void {
  made();
  emit("decided", decision, labels);
}
</script>

<template>
  <article class="lexicon-item" :aria-labelledby="`${id}-heading`">
    <component :is="`h${level ?? 3}`" :id="`${id}-heading`" class="lexicon-item__heading">
      „<bdi>{{ term.term }}</bdi>“
    </component>
    <p class="lexicon-item__where" data-test="where">{{ where }}</p>
    <dl class="facts">
      <div v-if="term.functions.length">
        <dt>{{ t("lexicon.term.functions") }}</dt>
        <dd>{{ labelList(labels, term.functions) }}</dd>
      </div>
      <div v-if="term.occurrences.length">
        <dt>{{ t("lexicon.term.places") }}</dt>
        <dd>
          <ul class="lexicon-item__list">
            <li v-for="(place, index) in term.occurrences" :key="index">
              <RouterLink :to="{ name: 'document', params: { id: place.document } }">
                <bdi>{{ place.title || t("documents.untitled") }}</bdi>
              </RouterLink>
              <template v-if="place.function">
                · {{ t("lexicon.term.placeFunction", { function: labelOf(labels, place.function) }) }}
              </template>
            </li>
            <li v-if="more > 0">{{ t("lexicon.term.more", { count: more }) }}</li>
          </ul>
        </dd>
      </div>
      <div v-if="term.held.length">
        <dt>{{ t("lexicon.term.held") }}</dt>
        <dd>
          <ul class="lexicon-item__list">
            <li v-for="cue in term.held" :key="cue.iri">
              <template v-if="cue.surface_form">„<bdi>{{ cue.surface_form }}</bdi>“</template>
              <template v-else>
                {{ t("lexicon.cue.pattern") }} <code><bdi>{{ cue.pattern }}</bdi></code>
              </template>
              → {{ heldWords(cue) }}
            </li>
          </ul>
        </dd>
      </div>
    </dl>
    <!-- tabindex -1: where the keyboard goes once a decision made here shows -->
    <p ref="summary" class="lexicon-item__decision" tabindex="-1" data-test="decision">{{ said }}</p>
    <!-- named with its word: a long list holds many buttons that say the same -->
    <button
      :id="`${id}-decide`"
      ref="toggle"
      type="button"
      class="btn secondary btn-sm"
      data-test="decide"
      :aria-labelledby="`${id}-decide ${id}-heading`"
      :aria-expanded="open"
      :aria-controls="open ? `${id}-form` : undefined"
      @click="open = !open"
    >
      {{ term.decision ? t("lexicon.item.decideAgain") : t("lexicon.item.decide") }}
    </button>
    <div v-if="open" :id="`${id}-form`" class="lexicon-item__form">
      <TermDecisionForm
        :term="term"
        :functions="term.functions"
        :held="term.held"
        :before="term.decision"
        :targets="targets"
        @decided="decided"
        @cancel="cancel"
        @reload="emit('reload')"
        @dirty="emit('dirty', $event)"
      />
    </div>
  </article>
</template>
