import { flushPromises, mount, type VueWrapper } from "@vue/test-utils";
import { readFileSync } from "node:fs";
import { join } from "node:path";

import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import * as api from "@/api";
import { ApiError, type ExportViolation } from "@/api";
import DocumentExport from "@/components/DocumentExport.vue";
import * as download from "@/download";
import { t } from "@/i18n/de";
import { router } from "@/router";

import { violations as axeViolations } from "./axe";
import { documentOf } from "./documentFixtures";

const MEM = { plan_iri: "https://lp-sachsen.org/resource/lehrplan-141-1", attribution: "MEM-Schule", licence: null };
const FROZEN = documentOf({ mem: MEM, frozen_at: "2026-11-13T10:00:00Z", iri: "https://example.org/kk/doc/x" });
let shown: VueWrapper | null = null;

function mountExport(document = FROZEN): VueWrapper {
  shown = mount(DocumentExport, { props: { document }, global: { plugins: [router] }, attachTo: window.document.body });
  return shown;
}

function violation(changes: Partial<ExportViolation> = {}): ExportViolation {
  return {
    focus: "https://lp-sachsen.org/resource/a",
    row_kind: "node",
    row_id: "n1",
    shape: "BereichShape",
    path: "http://purl.obolibrary.org/obo/BFO_0000050",
    message: "Less than 1 values on <a>->BFO_0000050",
    ...changes,
  };
}

async function press(wrapper: VueWrapper): Promise<void> {
  await wrapper.get("[data-test=export-start]").trigger("click");
  await flushPromises();
}

beforeEach(() => {
  vi.restoreAllMocks();
});

afterEach(() => {
  shown?.unmount();
  shown = null;
});

describe("the MEM export on a document's page", () => {
  it("is offered for a frozen import only, saying what the file holds", async () => {
    const wrapper = mountExport();

    expect(wrapper.get("h2").text()).toBe(t("mem.export.heading"));
    expect(wrapper.text()).toContain(t("mem.export.contains"));
    expect(wrapper.get("[data-test=export-start]").text()).toBe(t("mem.export.button"));
    expect(await axeViolations(wrapper.html())).toEqual([]);
  });

  it("says an import not frozen is exported once it is, and offers nothing yet", () => {
    const wrapper = mountExport(documentOf({ mem: MEM }));

    expect(wrapper.text()).toContain(t("refusals.export_not_frozen"));
    expect(wrapper.find("[data-test=export-start]").exists()).toBe(false);
  });

  it("fetches the file and saves it under its name, saying so", async () => {
    const blob = new Blob(["x"]);
    const asked = vi.spyOn(api, "exportMem").mockResolvedValue({ blob, filename: "mem-d1.ttl" });
    const saved = vi.spyOn(download, "saveBlob").mockImplementation(() => undefined);
    const wrapper = mountExport();

    await press(wrapper);

    expect(asked).toHaveBeenCalledWith("d1");
    expect(saved).toHaveBeenCalledWith(blob, "mem-d1.ttl");
    expect(wrapper.get("[role=status]").text()).toBe(t("mem.export.saved", { name: "mem-d1.ttl" }));
  });

  it("says it works while the check runs, and asks once however often it is pressed", async () => {
    const asked = vi.spyOn(api, "exportMem").mockReturnValue(new Promise(() => undefined));
    const wrapper = mountExport();

    await press(wrapper);
    await press(wrapper);

    expect(asked).toHaveBeenCalledTimes(1);
    expect(wrapper.get("[role=status]").text()).toBe(t("mem.export.working"));
    expect(wrapper.get("[data-test=export-start]").attributes("aria-disabled")).toBe("true");
  });

  it("lists the violations of a refused export, each at its row, the checker's English marked", async () => {
    const listed = [violation(), violation({ row_kind: "document", row_id: null, shape: "LPBundeslandShape", path: null })];
    vi.spyOn(api, "exportMem").mockRejectedValue(
      new ApiError("server", 409, "export_invalid", "invalid", { total: 250, violations: listed }),
    );
    const wrapper = mountExport();

    await press(wrapper);

    expect(wrapper.get("[role=alert]").text()).toContain(t("refusals.export_invalid"));
    expect(wrapper.text()).toContain(t("mem.export.violations.shown", { shown: 2, total: 250 }));
    const rows = wrapper.findAll("tbody tr");
    expect(rows).toHaveLength(2);
    expect(rows[0].get("a").attributes("href")).toBe("/dokumente/d1/baum?zeile=node:n1");
    expect(rows[0].text()).toContain(t("mem.export.shapes.BereichShape"));
    expect(rows[0].get("q").attributes("lang")).toBe("en");
    expect(rows[1].find("a").exists()).toBe(false);
    expect(rows[1].text()).toContain(t("mem.export.violations.document"));
    expect(await axeViolations(wrapper.html())).toEqual([]);
  });

  it("names a shape it has no words for by its own name", async () => {
    vi.spyOn(api, "exportMem").mockRejectedValue(
      new ApiError("server", 409, "export_invalid", "invalid", { total: 1, violations: [violation({ shape: "NeueShape" })] }),
    );
    const wrapper = mountExport();

    await press(wrapper);

    expect(wrapper.get("tbody tr").text()).toContain("NeueShape");
  });

  it("names the wait the server asks for where the export is busy", async () => {
    vi.spyOn(api, "exportMem").mockRejectedValue(
      new ApiError("server", 503, "export_unavailable", "busy", {}, 30),
    );
    const wrapper = mountExport();

    await press(wrapper);

    const alert = wrapper.get("[role=alert]").text();
    expect(alert).toContain(t("refusals.export_unavailable"));
    expect(alert).toContain(t("mem.export.wait", { count: 30 }));
    expect(alert).not.toContain(t("mem.export.again"));
  });

  it("reads the document again where it was no longer frozen meanwhile", async () => {
    vi.spyOn(api, "exportMem").mockRejectedValue(new ApiError("server", 409, "export_not_frozen", "not frozen"));
    const wrapper = mountExport();

    await press(wrapper);

    expect(wrapper.emitted("changed")).toHaveLength(1);
    expect(wrapper.get("[role=alert]").text()).toContain(t("refusals.export_not_frozen"));
  });

  it("shows that it works, not only to a screen reader, and has nothing axe finds meanwhile", async () => {
    vi.spyOn(api, "exportMem").mockReturnValue(new Promise(() => undefined));
    const wrapper = mountExport();

    await press(wrapper);

    const status = wrapper.get("[role=status]");
    expect(status.classes()).not.toContain("visually-hidden");
    expect(status.text()).toBe(t("mem.export.working"));
    expect(await axeViolations(wrapper.html())).toEqual([]);
  });

  it("saves nothing and says nothing once the page was left", async () => {
    let answer: (made: { blob: Blob; filename: string }) => void = () => undefined;
    vi.spyOn(api, "exportMem").mockReturnValue(new Promise((resolve) => (answer = resolve)));
    const saved = vi.spyOn(download, "saveBlob").mockImplementation(() => undefined);
    const wrapper = mountExport();
    await press(wrapper);

    wrapper.unmount();
    shown = null;
    answer({ blob: new Blob(["x"]), filename: "mem-d1.ttl" });
    await flushPromises();

    expect(saved).not.toHaveBeenCalled();
  });

  it("says the file was made but not saved where the browser refused to save it", async () => {
    vi.spyOn(api, "exportMem").mockResolvedValue({ blob: new Blob(["x"]), filename: "mem-d1.ttl" });
    vi.spyOn(download, "saveBlob").mockImplementation(() => {
      throw new Error("blocked");
    });
    const wrapper = mountExport();

    await press(wrapper);

    expect(wrapper.get("[role=alert]").text()).toContain(t("mem.export.saveFailed"));
    expect(wrapper.get("[role=status]").text()).toBe("");
  });

  it.each([
    [429, "too_many_exports", 30, "mem.export.wait"],
    [503, "export_unavailable", undefined, "mem.export.again"],
  ])("names when to try again after a %s, once", async (status, code, seconds, line) => {
    vi.spyOn(api, "exportMem").mockRejectedValue(new ApiError("server", status, code, "busy", {}, seconds));
    const wrapper = mountExport();

    await press(wrapper);

    const alert = wrapper.get("[role=alert]").text();
    expect(alert).toContain(t(`refusals.${code}`));
    expect(alert).toContain(t(line, { count: seconds ?? 0 }));
    expect(alert.match(/[Vv]ersuch es/g)).toHaveLength(1);
  });

  it("reads the document again where it is no import", async () => {
    vi.spyOn(api, "exportMem").mockRejectedValue(new ApiError("server", 409, "not_mem_import", "no import"));
    const wrapper = mountExport();

    await press(wrapper);

    expect(wrapper.emitted("changed")).toHaveLength(1);
  });

  it("forgets the last failure, its wait and its list with a new try", async () => {
    vi.spyOn(api, "exportMem")
      .mockRejectedValueOnce(new ApiError("server", 409, "export_invalid", "invalid", { total: 1, violations: [violation()] }))
      .mockRejectedValueOnce(new ApiError("server", 429, "too_many_exports", "busy", {}, 30))
      .mockRejectedValueOnce(new ApiError("network", 0));
    const wrapper = mountExport();
    await press(wrapper);
    await press(wrapper);
    expect(wrapper.find("table").exists()).toBe(false);

    await press(wrapper);

    expect(wrapper.get("[role=alert]").text()).not.toContain(t("mem.export.wait", { count: 30 }));
  });

  it("names a violation of no row by its focus, and a path of none as none", async () => {
    vi.spyOn(api, "exportMem").mockRejectedValue(
      new ApiError("server", 409, "export_invalid", "invalid", {
        total: 1, violations: [violation({ row_kind: null, row_id: null, path: null, focus: "https://p/x" })],
      }),
    );
    const wrapper = mountExport();

    await press(wrapper);

    const cells = wrapper.get("tbody tr").findAll("td");
    expect(cells[0].text()).toBe("https://p/x");
    expect(cells[2].text()).toBe("–");
    expect(wrapper.find("tbody a").exists()).toBe(false); // no row: nothing to open
  });

  it("describes each link to a row by the rule its row broke", async () => {
    vi.spyOn(api, "exportMem").mockRejectedValue(
      new ApiError("server", 409, "export_invalid", "invalid", { total: 2, violations: [violation(), violation({ row_id: "n2", shape: "VerweisShape" })] }),
    );
    const wrapper = mountExport();

    await press(wrapper);

    const links = wrapper.findAll("tbody a");
    const named = links.map((link) => wrapper.get(`#${link.attributes("aria-describedby")}`).text());
    expect(named).toEqual([t("mem.export.shapes.BereichShape"), t("mem.export.shapes.VerweisShape")]);
  });

  it("has nothing axe finds where the import is not frozen or the file was saved", async () => {
    vi.spyOn(api, "exportMem").mockResolvedValue({ blob: new Blob(["x"]), filename: "mem-d1.ttl" });
    vi.spyOn(download, "saveBlob").mockImplementation(() => undefined);
    const open = mountExport(documentOf({ mem: MEM }));
    expect(await axeViolations(open.html())).toEqual([]);
    open.unmount();

    const saved = mountExport();
    await press(saved);
    expect(await axeViolations(saved.html())).toEqual([]);
  });

  it("keeps its empty state line in the page, so the first thing it says is read out", () => {
    const source = readFileSync(join(process.cwd(), "src", "components", "DocumentExport.vue"), "utf8");
    const empty = /\.export__status:empty\s*\{([^}]*)\}/.exec(source)?.[1] ?? "";

    expect(empty).not.toMatch(/display\s*:\s*none/);
  });

  it("adds no wait of its own to a refusal of the service's that names one", async () => {
    vi.spyOn(api, "exportMem").mockRejectedValue(new ApiError("server", 503, "service_unavailable", "down", {}, 5));
    const wrapper = mountExport();

    await press(wrapper);

    const alert = wrapper.get("[role=alert]").text();
    expect(alert).not.toContain(t("mem.export.wait", { count: 5 }));
    expect(alert).not.toContain(t("mem.export.again"));
  });
});
