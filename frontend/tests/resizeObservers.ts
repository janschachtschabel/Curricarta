import { vi } from "vitest";

/**
 * Stubs ResizeObserver with one that keeps its callbacks; the returned function calls them all, as a box that
 * changed size would. Undo with `vi.unstubAllGlobals()`.
 */
export function observeResizes(): () => void {
  const observed: (() => void)[] = [];
  vi.stubGlobal(
    "ResizeObserver",
    class {
      constructor(callback: () => void) {
        observed.push(callback);
      }
      observe(): void {}
      disconnect(): void {}
    },
  );
  return () => {
    for (const callback of observed) callback();
  };
}

/** jsdom lays nothing out: the widths of a wide table in a narrow box stand in. */
export function scrollsSideways(box: Element): void {
  Object.defineProperty(box, "scrollWidth", { value: 710, configurable: true });
  Object.defineProperty(box, "clientWidth", { value: 270, configurable: true });
}
