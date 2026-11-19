import { flushPromises, mount, type VueWrapper } from "@vue/test-utils";

import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import * as api from "@/api";
import { ApiError } from "@/api";
import DocumentKernExport from "@/components/DocumentKernExport.vue";
import * as download from "@/download";
import { t } from "@/i18n/de";

import { violations as axeViolations } from "./axe";
import { documentOf } from "./documentFixtures";

const FROZEN = documentOf({ frozen_at: "2026-11-13T10:00:00Z", iri: "https://example.org/kk/doc/x" });
let shown: VueWrapper | null = null;

function mountExport(document = FROZEN): VueWrapper {
  shown = mount(DocumentKernExport, { props: { document }, attachTo: window.document.body });
  return shown;
}

async function press(wrapper: VueWrapper): Promise<void> {
  await wrapper.get("[data-test=kern-export-start]").trigger("click");
  await flushPromises();
}

beforeEach(() => {
  vi.restoreAllMocks();
});

afterEach(() => {
  shown?.unmount();
  shown = null;
});

describe("the Kern export on a document's page", () => {
  it("is offered for a frozen document, saying what the file holds", async () => {
    const wrapper = mountExport();

    expect(wrapper.get("h2").text()).toBe(t("documents.page.kernExport.heading"));
    expect(wrapper.text()).toContain(t("documents.page.kernExport.contains"));
    expect(wrapper.get("[data-test=kern-export-start]").text()).toBe(t("documents.page.kernExport.button"));
    expect(await axeViolations(wrapper.html())).toEqual([]);
  });

  it("offers nothing for a document not frozen", () => {
    const wrapper = mountExport(documentOf({}));

    expect(wrapper.find("[data-test=kern-export-start]").exists()).toBe(false);
  });

  it("fetches the file and saves it under its name, saying so in the live region", async () => {
    const blob = new Blob(["x"]);
    const asked = vi.spyOn(api, "exportKern").mockResolvedValue({ blob, filename: "kern-d1-r1.ttl", accepted: 0 });
    const saved = vi.spyOn(download, "saveBlob").mockImplementation(() => undefined);
    const wrapper = mountExport();

    await press(wrapper);

    expect(asked).toHaveBeenCalledWith("d1");
    expect(saved).toHaveBeenCalledWith(blob, "kern-d1-r1.ttl");
    expect(wrapper.get("[role=status]").text()).toBe(t("documents.page.kernExport.saved", { name: "kern-d1-r1.ttl" }));
    expect(await axeViolations(wrapper.html())).toEqual([]);
  });

  it("says how many violations the editors accepted when they froze it", async () => {
    vi.spyOn(api, "exportKern").mockResolvedValue({ blob: new Blob(["x"]), filename: "kern-d1-r1.ttl", accepted: 2 });
    vi.spyOn(download, "saveBlob").mockImplementation(() => undefined);
    const wrapper = mountExport();

    await press(wrapper);

    expect(wrapper.get("[role=status]").text()).toBe(
      t("documents.page.kernExport.savedAccepted", { name: "kern-d1-r1.ttl", count: 2 }),
    );
  });

  it("says it works, shown, and asks once however often it is pressed", async () => {
    const asked = vi.spyOn(api, "exportKern").mockReturnValue(new Promise(() => undefined));
    const wrapper = mountExport();

    await press(wrapper);
    await press(wrapper);

    expect(asked).toHaveBeenCalledTimes(1);
    const status = wrapper.get("[role=status]");
    expect(status.text()).toBe(t("documents.page.kernExport.working"));
    expect(status.classes()).not.toContain("visually-hidden");
    expect(wrapper.get("[data-test=kern-export-start]").attributes("aria-disabled")).toBe("true");
    expect(await axeViolations(wrapper.html())).toEqual([]);
  });

  it("says a document frozen before its specifications were named is the administration's to name", async () => {
    vi.spyOn(api, "exportKern").mockRejectedValue(new ApiError("server", 409, "export_unnamed", "unnamed"));
    const wrapper = mountExport();

    await press(wrapper);

    expect(wrapper.get("[role=alert]").text()).toContain(t("refusals.export_unnamed"));
    expect(wrapper.get("[role=status]").text()).toBe("");
    expect(await axeViolations(wrapper.html())).toEqual([]);
  });

  it.each([
    [429, "too_many_exports", 30, "documents.page.kernExport.wait"],
    [503, "export_unavailable", undefined, "documents.page.kernExport.again"],
  ])("names when to try again after a %s, once", async (status, code, seconds, line) => {
    vi.spyOn(api, "exportKern").mockRejectedValue(new ApiError("server", status, code, "busy", {}, seconds));
    const wrapper = mountExport();

    await press(wrapper);

    const alert = wrapper.get("[role=alert]").text();
    expect(alert).toContain(t(`refusals.${code}`));
    expect(alert).toContain(t(line, { count: seconds ?? 0 }));
    expect(alert.match(/[Vv]ersuch es/g)).toHaveLength(1);
  });

  it("reads the document again where it was no longer frozen meanwhile", async () => {
    vi.spyOn(api, "exportKern").mockRejectedValue(new ApiError("server", 409, "export_not_frozen", "not frozen"));
    const wrapper = mountExport();

    await press(wrapper);

    expect(wrapper.emitted("changed")).toHaveLength(1);
  });

  it("says the file was made but not saved where the browser refused to save it", async () => {
    vi.spyOn(api, "exportKern").mockResolvedValue({ blob: new Blob(["x"]), filename: "kern-d1-r1.ttl", accepted: 0 });
    vi.spyOn(download, "saveBlob").mockImplementation(() => {
      throw new Error("blocked");
    });
    const wrapper = mountExport();

    await press(wrapper);

    expect(wrapper.get("[role=alert]").text()).toContain(t("documents.page.kernExport.saveFailed"));
  });

  it("saves nothing once the page was left", async () => {
    let answer: (made: { blob: Blob; filename: string; accepted: number }) => void = () => undefined;
    vi.spyOn(api, "exportKern").mockReturnValue(new Promise((resolve) => (answer = resolve)));
    const saved = vi.spyOn(download, "saveBlob").mockImplementation(() => undefined);
    const wrapper = mountExport();
    await press(wrapper);

    wrapper.unmount();
    shown = null;
    answer({ blob: new Blob(["x"]), filename: "kern-d1-r1.ttl", accepted: 0 });
    await flushPromises();

    expect(saved).not.toHaveBeenCalled();
  });
});
