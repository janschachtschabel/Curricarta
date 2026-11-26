import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { addRule, editRule, getRules, takeRule } from "@/api";

function json(body: unknown): Response {
  return new Response(JSON.stringify(body), { status: 200, headers: { "Content-Type": "application/json" } });
}

beforeEach(() => {
  vi.stubGlobal("fetch", vi.fn(() => Promise.resolve(json({ outcome: "rejected", revision: 2 }))));
});

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("a document's rules", () => {
  it("are asked of the document", async () => {
    await getRules("d/1");

    expect(vi.mocked(fetch).mock.calls[0][0]).toBe("/api/v1/documents/d%2F1/rules");
  });

  it("are edited on the revision they were read at, only the fields named sent", async () => {
    await editRule("r/1", 3, { max_count: null, options: ["n1"] });

    const [path, init] = vi.mocked(fetch).mock.calls[0];
    expect(path).toBe("/api/v1/rules/r%2F1");
    expect(init?.method).toBe("PATCH");
    expect(JSON.parse(init?.body as string)).toEqual({ expected_revision: 3, max_count: null, options: ["n1"] });
  });

  it("are added to the document on their anchors", async () => {
    await addRule("d/1", { kind: "completion", verbatim: "Alles.", anchors: [{ page: 2 }] });

    const [path, init] = vi.mocked(fetch).mock.calls[0];
    expect(path).toBe("/api/v1/documents/d%2F1/rules");
    expect(init?.method).toBe("POST");
    expect(JSON.parse(init?.body as string)).toEqual({ kind: "completion", verbatim: "Alles.", anchors: [{ page: 2 }] });
  });

  it("are taken away on the revision they were read at", async () => {
    expect(await takeRule("r/1", 4)).toEqual({ outcome: "rejected", revision: 2 });

    const [path, init] = vi.mocked(fetch).mock.calls[0];
    expect(path).toBe("/api/v1/rules/r%2F1?expected_revision=4");
    expect(init?.method).toBe("DELETE");
  });
});
