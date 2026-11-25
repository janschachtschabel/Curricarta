import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { editSpecification, getScopeForm, getSpecifications } from "@/api";

function json(body: unknown): Response {
  return new Response(JSON.stringify(body), { status: 200, headers: { "Content-Type": "application/json" } });
}

beforeEach(() => {
  vi.stubGlobal("fetch", vi.fn(() => Promise.resolve(json({ editable: true, closed: null, specifications: [] }))));
});

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("a document's specifications", () => {
  it("are asked of the document", async () => {
    expect(await getSpecifications("d/1")).toEqual({ editable: true, closed: null, specifications: [] });
    expect(vi.mocked(fetch).mock.calls[0][0]).toBe("/api/v1/documents/d%2F1/specifications");
  });

  it("are edited on the revision they were read at, only the fields named sent", async () => {
    await editSpecification("s/1", 3, { field_text: null });

    const [path, init] = vi.mocked(fetch).mock.calls[0];
    expect(path).toBe("/api/v1/specifications/s%2F1");
    expect(init?.method).toBe("PATCH");
    expect(JSON.parse(init?.body as string)).toEqual({ expected_revision: 3, field_text: null });
  });

  it("are named by the lists of the sector's form", async () => {
    await getScopeForm("school");

    expect(vi.mocked(fetch).mock.calls[0][0]).toBe("/api/v1/profiles/school/form");
  });
});
