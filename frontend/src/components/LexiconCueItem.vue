<script setup lang="ts">
/**
 * One research cue of the sample, or a retired one's decision shown as the cue was judged (plan M1 10.5, 10e
 * E7): its word or pattern, where it holds, what it says - its concepts by the labels the list sends - and its
 * decision, with whether the files hold it yet. Decided on in a form of its own (CueDecisionForm), opened on the
 * reader's word: a decision made is handed on (`decided`) and, once the list shows it, takes the keyboard; the
 * form left takes it back to the button.
 */
import { computed, useId } from "vue";

import type { CueDecision, Labels, ReviewCue } from "@/api";
import { isolate } from "@/bidi";
import CueDecisionForm from "@/components/CueDecisionForm.vue";
import { momentFormat, t } from "@/i18n/de";
import { useItemForm } from "@/itemForm";
import { labelList, labelOf, sectorWord, strengthText } from "@/lexiconWords";

// `level`: its heading's, 3 by default - 4 under a heading of its list's own
const props = defineProps<{ item: ReviewCue; labels: Labels; retired?: boolean; level?: 3 | 4 }>();
const emit = defineEmits<{ decided: [made: CueDecision]; reload: []; dirty: [dirty: boolean] }>();

const id = useId();
const { open, toggle, summary, cancel, made } = useItemForm(
  () => props.item.decision,
  (now) => emit("dirty", now),
);

const where = computed(() => {
  const regions = props.item.regions.length ? labelList(props.labels, props.item.regions) : t("lexicon.cue.everywhere");
  const state = props.retired
    ? t("lexicon.cue.retired")
    : t(props.item.sampled ? "lexicon.cue.inSample" : "lexicon.cue.outsideSample");
  return [props.item.sector ? sectorWord(props.item.sector) : "", regions, state].filter(Boolean).join(" · ");
});

const strength = computed(() => {
  const value = props.item.strength ? strengthText(props.item.strength) : t("lexicon.cue.noStrength");
  return `${value} · ${t(props.item.verified ? "lexicon.cue.verified" : "lexicon.cue.unverified")}`;
});

// the lists it carries, each shown where it holds anything
const lists = computed(() =>
  (
    [
      ["lexicon.cue.notes", props.item.notes],
      ["lexicon.cue.hints", props.item.recognition_hints],
      ["lexicon.cue.examples", props.item.examples],
      ["lexicon.cue.sources", props.item.sources],
    ] as const
  ).filter(([, values]) => values.length),
);

function applied(decision: CueDecision): string {
  if (decision.applied) return t(decision.decision === "confirmed" ? "lexicon.cue.appliedConfirmed" : "lexicon.cue.appliedRejected");
  // a confirmation of a cue retired since holds nowhere
  return t(decision.decision === "confirmed" && decision.retired ? "lexicon.cue.retiredSince" : "lexicon.item.waiting");
}

const said = computed(() => {
  const decision = props.item.decision;
  if (!decision) return t("lexicon.item.undecided");
  const verdict =
    decision.decision === "confirmed"
      ? t("lexicon.cue.confirmed", { strength: strengthText(decision.strength ?? ""), evidence: isolate(decision.evidence ?? "") })
      : t("lexicon.cue.rejected");
  const by = t("lexicon.item.by", { name: isolate(decision.decided_by), date: momentFormat.format(new Date(decision.decided_at)) });
  const note = decision.note ? t("lexicon.item.note", { note: isolate(decision.note) }) : "";
  return [verdict, by, note, applied(decision)].filter(Boolean).join(" ");
});

function decided(decision: CueDecision): void {
  made();
  emit("decided", decision);
}
</script>

<template>
  <article class="lexicon-item" :aria-labelledby="`${id}-heading`">
    <!-- tabindex -1: where the keyboard goes when "Weitere zeigen" brought it into the list -->
    <component :is="`h${level ?? 3}`" :id="`${id}-heading`" class="lexicon-item__heading" tabindex="-1">
      <template v-if="item.surface_form">„<bdi>{{ item.surface_form }}</bdi>“</template>
      <template v-else>
        {{ t("lexicon.cue.pattern") }} <code><bdi>{{ item.pattern }}</bdi></code>
      </template>
    </component>
    <p class="lexicon-item__where" data-test="where">{{ where }}</p>
    <dl class="facts">
      <div>
        <dt>{{ t("lexicon.cue.role") }}</dt>
        <dd>{{ labelOf(labels, item.role) }}</dd>
      </div>
      <div>
        <dt>{{ t("lexicon.cue.kind") }}</dt>
        <dd>{{ labelOf(labels, item.kind) }}</dd>
      </div>
      <div>
        <dt>{{ t("lexicon.cue.targets") }}</dt>
        <dd>{{ labelList(labels, item.maps_to) }}</dd>
      </div>
      <div v-if="!retired">
        <dt>{{ t("lexicon.cue.strength") }}</dt>
        <dd>{{ strength }}</dd>
      </div>
      <div v-for="[key, values] in lists" :key="key">
        <dt>{{ t(key) }}</dt>
        <dd>
          <ul class="lexicon-item__list">
            <li v-for="(value, index) in values" :key="index"><bdi>{{ value }}</bdi></li>
          </ul>
        </dd>
      </div>
    </dl>
    <!-- tabindex -1: where the keyboard goes once a decision made here shows -->
    <p ref="summary" class="lexicon-item__decision" tabindex="-1" data-test="decision">{{ said }}</p>
    <!-- named with its cue: a long list holds many buttons that say the same -->
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
      {{ item.decision ? t("lexicon.item.decideAgain") : t("lexicon.item.decide") }}
    </button>
    <div v-if="open" :id="`${id}-form`" class="lexicon-item__form">
      <CueDecisionForm
        :cue="item.iri"
        :before="item.decision"
        @decided="decided"
        @cancel="cancel"
        @reload="emit('reload')"
        @dirty="emit('dirty', $event)"
      />
    </div>
  </article>
</template>
