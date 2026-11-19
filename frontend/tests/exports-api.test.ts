import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { ApiError, exportKern, exportMem, exportViolations } from "@/api";

function turtle(disposition: string | null): Response {
  const headers = new Headers({ "Content-Type": "text/turtle" });
  if (disposition !== null) headers.set("Content-Disposition", disposition);
  return new Response("@prefix lp: <https://w3id.org/lehrplan/ontology/> .\n", { status: 200, headers });
}

beforeEach(() => {
  vi.stubGlobal("fetch", vi.fn(() => Promise.resolve(turtle('attachment; filename="mem-d1.ttl"'))));
});

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("the MEM export of a document", () => {
  it("asks for the document's Turtle and gives it with the server's file name", async () => {
    const made = await exportMem("d/1");

    expect(vi.mocked(fetch).mock.calls[0][0]).toBe("/api/v1/documents/d%2F1/export.ttl");
    expect(made.filename).toBe("mem-d1.ttl");
    expect(await made.blob.text()).toContain("@prefix lp:");
  });

  it.each([
    ['attachment; filename="../../etc/passwd"'],
    ['attachment; filename="a b.ttl"'],
    ['attachment; filename=".htaccess"'],
    ['attachment; filename=".."'],
    [null],
  ])("names the file itself where the server names it otherwise or not at all (%s)", async (disposition) => {
    vi.mocked(fetch).mockResolvedValue(turtle(disposition));

    expect((await exportMem("d/1")).filename).toBe("mem-d1.ttl");
  });

  it("reads the violations of a refusal, their number beside those listed", () => {
    const violation = { focus: "https://p/1", row_kind: "node", row_id: "n1", shape: "BereichShape", path: null, message: "m" };
    const refused = new ApiError("server", 409, "export_invalid", "invalid", { total: 250, violations: [violation] });

    expect(exportViolations(refused)).toEqual({ total: 250, violations: [violation] });
  });

  it("reads a refusal of another form as no violations, never failing on it", () => {
    const odd = new ApiError("server", 409, "export_invalid", "invalid", { total: "x", violations: [{ shape: 3 }, "y"] });

    expect(exportViolations(odd)).toEqual({ total: 0, violations: [] });
    expect(exportViolations(new ApiError("server", 409, "export_invalid"))).toEqual({ total: 0, violations: [] });
  });

  it("says a file broken off on the way as the network's failure", async () => {
    const broken = turtle('attachment; filename="mem-d1.ttl"');
    vi.spyOn(broken, "blob").mockRejectedValue(new TypeError("network error"));
    vi.mocked(fetch).mockResolvedValue(broken);

    await expect(exportMem("d1")).rejects.toMatchObject({ kind: "network" });
  });
});

describe("the Kern export of a document", () => {
  function kern(accepted: string | null): Response {
    const answer = turtle('attachment; filename="kern-d1-r2.ttl"');
    if (accepted !== null) answer.headers.set("Curricarta-Accepted-Violations", accepted);
    return answer;
  }

  it("asks for the document's Kern Turtle and gives it with its name and the violations accepted", async () => {
    vi.mocked(fetch).mockResolvedValue(kern("3"));

    const made = await exportKern("d/1");

    expect(vi.mocked(fetch).mock.calls[0][0]).toBe("/api/v1/documents/d%2F1/kern.ttl");
    expect([made.filename, made.accepted]).toEqual(["kern-d1-r2.ttl", 3]);
  });

  it.each([[null], ["x"], ["-1"]])("reads an accepted count it cannot read (%s) as none", async (accepted) => {
    vi.mocked(fetch).mockResolvedValue(kern(accepted));

    expect((await exportKern("d1")).accepted).toBe(0);
  });

  it("names the file itself where the server names none", async () => {
    vi.mocked(fetch).mockResolvedValue(turtle(null));

    expect((await exportKern("d/1")).filename).toBe("kern-d1.ttl");
  });
});
