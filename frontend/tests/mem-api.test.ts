import { readFileSync } from "node:fs";
import { join } from "node:path";

import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { findMemPlans, IMPORT_KIND, startMemCatalog, startMemImport } from "@/api";

function answer(status: number, body: unknown): Response {
  return new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });
}

function call(index = 0): [string, RequestInit] {
  return vi.mocked(fetch).mock.calls[index] as [string, RequestInit];
}

beforeEach(() => {
  // a body is read once: one answer per request
  vi.stubGlobal("fetch", vi.fn(() => Promise.resolve(answer(200, { plans: [], total: 0, catalog_read_at: null }))));
});

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("MEM-Schule's catalogue and import requests", () => {
  it("look the catalogue up by region and title, a page at a time, leaving out what is not asked", async () => {
    await findMemPlans({ region: "DE-SN", title: "Informatik", offset: 50 });
    await findMemPlans({});

    expect(call(0)[0]).toBe("/api/v1/mem/plans?region=DE-SN&title=Informatik&offset=50");
    expect(call(1)[0]).toBe("/api/v1/mem/plans");
  });

  it("leave an empty title out", async () => {
    await findMemPlans({ region: "", title: "" });

    expect(call()[0]).toBe("/api/v1/mem/plans");
  });

  it("start the catalogue's reading", async () => {
    await startMemCatalog();

    expect([call()[0], call()[1].method]).toEqual(["/api/v1/mem/catalog", "POST"]);
  });

  it("import a plan into a new document of the entry's conversion", async () => {
    await startMemImport("s/1", { plan_iri: "https://w3id.org/p/1", conversion_id: "c1" });

    expect([call()[0], call()[1].method]).toEqual(["/api/v1/sources/s%2F1/mem-import", "POST"]);
    expect(JSON.parse(call()[1].body as string)).toEqual({ plan_iri: "https://w3id.org/p/1", conversion_id: "c1" });
  });

  it("know the import's job kind as the backend names it", () => {
    const source = readFileSync(join(process.cwd(), "..", "backend", "app", "sources", "mem", "import_kind.py"), "utf8");

    expect(source).toContain(`KIND = "${IMPORT_KIND}"`);
  });
});
