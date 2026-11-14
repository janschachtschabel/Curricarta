<script lang="ts">
// The frames open, the last opened on top: Escape is the top one's alone.
const openFrames: symbol[] = [];
// The page's scrolling before the first frame opened: one for all frames, given back by whichever goes last
let overflowBefore = "";
</script>

<script setup lang="ts">
// The frame of a modal: the scrim, the dialog's role and its name, the Tab
// kept inside, Escape and a click on the scrim, and the keyboard given back
// to whatever opened it. Five dialogs had each written it out for themselves
// (old app, review D of the round "Sichtung", finding 8).
//
// What the dialog says, and where the keyboard starts in it, stay the
// dialog's own: a share dialog starts on its close button, an import on its
// file field. So does whether it may close now -- `close` is a request, and a
// dialog with a request out may turn it down.
//
// The keyboard's way back is learnt as the frame is mounted: before the
// dialog's own `onMounted`, which is where it moves the keyboard in.
import { onBeforeUnmount, onMounted, ref } from "vue";

import { trapTab } from "@/focusTrap";

defineProps<{
  /** The id of the dialog's heading, which names it. */
  labelledby: string;
  /** The id of what is read with the name as the dialog opens. */
  describedby?: string;
}>();

const emit = defineEmits<{ close: [] }>();

const dialog = ref<HTMLElement | null>(null);
const backdrop = ref<HTMLElement | null>(null);
const frame = Symbol("modal");
let previouslyFocused: HTMLElement | null = null;

// The page behind the frame is inert while it is open - a screen reader's browse mode does not wander out of the
// dialog - and does not scroll under the scrim. Inert are the siblings of the frame and of each element it sits in,
// up to the body: the frame renders where its opener is, not at the body's end. What was inert before stays so.
const madeInert: Element[] = [];

function quietPage(): void {
  for (let inside: Element | null = backdrop.value; inside && inside !== document.body; inside = inside.parentElement) {
    for (const sibling of inside.parentElement?.children ?? []) {
      if (sibling === inside || sibling.hasAttribute("inert")) continue;
      sibling.setAttribute("inert", "");
      madeInert.push(sibling);
    }
  }
  if (openFrames.length === 1) {
    overflowBefore = document.body.style.overflow;
    document.body.style.overflow = "hidden";
  }
}

function wakePage(): void {
  for (const element of madeInert.splice(0)) element.removeAttribute("inert");
  if (openFrames.length === 0) document.body.style.overflow = overflowBefore;
}

onMounted(() => {
  previouslyFocused = document.activeElement as HTMLElement | null;
  openFrames.push(frame);
  document.addEventListener("keydown", onEscape);
  quietPage();
});

onBeforeUnmount(() => {
  document.removeEventListener("keydown", onEscape);
  // Gone within the flush that mounted it, the frame never got on the stack:
  // splicing at -1 would take another frame off instead.
  const at = openFrames.indexOf(frame);
  if (at >= 0) openFrames.splice(at, 1);
  // before the keyboard goes back: an inert opener takes no focus
  wakePage();
  // The opener may be gone -- the row it sat in can be what was just removed.
  if (previouslyFocused?.isConnected) previouslyFocused.focus();
});

/**
 * Escape, heard on the whole page while the frame is open: a control that
 * went away drops the keyboard to the page's body, and heard on the dialog
 * alone, Escape then closed nothing (old app, review A2, pre-existing). Only the
 * top frame closes - every modal of the app, ConfirmDialog too, is a frame on
 * the one stack. The check on `aria-modal` guards against a modal built without
 * this frame: one asked over it answers Escape itself.
 */
function onEscape(event: KeyboardEvent): void {
  if (event.key !== "Escape" || openFrames.at(-1) !== frame) return;
  const target = event.target instanceof Element ? event.target : null;
  const modal = target?.closest("[aria-modal='true']");
  if (modal && modal !== dialog.value) return;
  emit("close");
}

function onKeydown(event: KeyboardEvent): void {
  trapTab(event, dialog.value);
}

// A click whose press and release fell on two elements - a text selection let go past
// the dialog's edge, or begun beside it and ended inside - lands on the scrim as their
// common ancestor; only a press and a release both on the scrim close.
let pressedOnScrim = false;
let releasedOnScrim = false;

function onScrimPress(event: MouseEvent): void {
  pressedOnScrim = event.target === event.currentTarget;
}

function onScrimRelease(event: MouseEvent): void {
  releasedOnScrim = event.target === event.currentTarget;
}

function onScrimClick(): void {
  if (pressedOnScrim && releasedOnScrim) emit("close");
  pressedOnScrim = false;
  releasedOnScrim = false;
}

defineExpose({ dialog });
</script>

<template>
  <div ref="backdrop" class="backdrop" @mousedown="onScrimPress" @mouseup="onScrimRelease" @click.self="onScrimClick">
    <div
      ref="dialog"
      class="dialog"
      role="dialog"
      aria-modal="true"
      :aria-labelledby="labelledby"
      :aria-describedby="describedby"
      @keydown="onKeydown"
    >
      <slot />
    </div>
  </div>
</template>

<style scoped>
.backdrop {
  position: fixed;
  inset: 0;
  background: var(--scrim);
  display: flex;
  align-items: center;
  justify-content: center;
  padding: var(--space-2);
  z-index: 50;
}

.dialog {
  background: var(--surface);
  color: var(--text);
  border: 1px solid var(--border);
  border-radius: var(--radius);
  padding: var(--space-3);
  max-width: 36rem;
  width: 100%;
  /* Within the scrim's padding on every side: a long dialog scrolls, its way
     out in reach, rather than pushing it off a phone's screen or at 200 %. */
  max-height: calc(100dvh - 2 * var(--space-2));
  overflow-y: auto;
}
</style>
