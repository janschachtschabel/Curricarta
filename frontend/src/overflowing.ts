// Whether a box scrolls sideways (SourceTable.vue, DocumentFindings.vue). Such a box is a tab stop, so a keyboard can
// scroll it, and only then: a stop with nothing to scroll is a stop for nothing - a table stacked on a narrow screen
// scrolls no more. Measured as the box or its table changes size (a font, the rail: changes the window does not see),
// as the window does, and as `again` changes.
import { nextTick, onMounted, onUnmounted, ref, watch, type Ref, type WatchSource } from "vue";

export function useOverflowing(box: Ref<HTMLElement | null>, again?: WatchSource): Ref<boolean> {
  const overflowing = ref(false);
  let observer: ResizeObserver | null = null;

  function measure(): void {
    const element = box.value;
    overflowing.value = element !== null && element.scrollWidth > element.clientWidth;
  }

  // the box may come later than the component, with the content it waits for
  watch(
    box,
    (element) => {
      observer?.disconnect();
      observer = null;
      measure();
      if (!element) return;
      observer = new ResizeObserver(measure);
      observer.observe(element);
      if (element.firstElementChild) observer.observe(element.firstElementChild);
    },
    { immediate: true, flush: "post" },
  );
  if (again) watch(again, () => void nextTick(measure));

  onMounted(() => window.addEventListener("resize", measure));
  onUnmounted(() => {
    window.removeEventListener("resize", measure);
    observer?.disconnect();
  });

  return overflowing;
}
