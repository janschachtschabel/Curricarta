import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { editSpecification, getSpecifications, setSpecificationValues } from "@/api";

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

  it("have their values and contexts set as a whole, on the revision they were read at", async () => {
    const context = {
      id: "c1", sector: "https://example.org/sec", formality: null, institution_text: "Gymnasium", target_group_text: null,
      level_assignments: [], time_spans: [{ id: null, time_kind: "https://example.org/grade", span_from: 5, span_to: 6, time_relation: null }],
    };
    await setSpecificationValues("s/1", 4, { level_assignments: [], time_spans: [], workloads: [], contexts: [context] });

    const [path, init] = vi.mocked(fetch).mock.calls[0];
    expect(path).toBe("/api/v1/specifications/s%2F1/values");
    expect(init?.method).toBe("PUT");
    expect(JSON.parse(init?.body as string)).toEqual({
      expected_revision: 4, level_assignments: [], time_spans: [], workloads: [], contexts: [context],
    });
  });
});
