import { flushPromises, mount } from "@vue/test-utils";
import { afterEach, describe, expect, it, vi } from "vitest";

import DocumentRuns from "@/components/DocumentRuns.vue";

import { observeResizes, scrollsSideways } from "./resizeObservers";

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("a document's runs", () => {
  // a tab stop with nothing to scroll (browser check 2, NIT 8), as the findings' box was
  it("makes its box a tab stop only while it scrolls sideways", async () => {
    const resized = observeResizes();
    const run = { stage: "X1", attempt: 1, state: "succeeded", started_at: "2026-11-01T10:00:00Z", finished_at: null, failure: null } as const;
    const wrapper = mount(DocumentRuns, { props: { runs: [run] }, attachTo: document.body });
    await flushPromises();
    const box = wrapper.get("[role=region]");
    expect(box.attributes("tabindex")).toBeUndefined();

    scrollsSideways(box.element);
    resized();
    await flushPromises();

    expect(box.attributes("tabindex")).toBe("0");
    wrapper.unmount();
  });
});
