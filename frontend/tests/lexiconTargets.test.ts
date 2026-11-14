import { afterEach, describe, expect, it, vi } from "vitest";

import * as api from "@/api";
import { ApiError, type Form, type FormValue } from "@/api";
import { grouped, targetLoader } from "@/lexiconTargets";

import { CV, SCHOOL } from "./lexiconFixtures";

function value(name: string, functions: string[]): FormValue {
  return {
    iri: SCHOOL + name,
    notation: null,
    label: name,
    alt_labels: [],
    definition: null,
    note: null,
    delimitation: null,
    examples: [],
    broader: functions,
  };
}

const AREA = value("Inhaltsbereich", [CV + "fn_area"]);
const FIELD = value("Lernfeld", [CV + "fn_unit"]);

function form(sector: string): Form {
  return {
    sector,
    profile: SCHOOL + "Terminology",
    node: [
      { key: "function", kind: "concept", required: true, many: false, most: null, values: [] },
      { key: "node_type", kind: "concept", required: false, many: false, most: null, values: [AREA, FIELD] },
    ],
    statement: [],
  };
}

afterEach(() => {
  vi.restoreAllMocks();
});

describe("the node types a new cue may point to", () => {
  it("are the node types of the sector's form, read once for each sector", async () => {
    const read = vi.spyOn(api, "getForm").mockImplementation((sector) => Promise.resolve(form(sector)));
    const targets = targetLoader();

    const [first, again] = await Promise.all([targets("school"), targets("school")]);
    await targets("vocational");

    expect(first).toEqual([AREA, FIELD]);
    expect(again).toBe(first);
    expect(read.mock.calls.map(([sector]) => sector)).toEqual(["school", "vocational"]);
  });

  it("are read again where the reading failed", async () => {
    const read = vi
      .spyOn(api, "getForm")
      .mockRejectedValueOnce(new ApiError("server", 503, "service_unavailable"))
      .mockResolvedValueOnce(form("school"));
    const targets = targetLoader();

    await expect(targets("school")).rejects.toBeInstanceOf(ApiError);
    expect(await targets("school")).toEqual([AREA, FIELD]);
    expect(read).toHaveBeenCalledTimes(2);
  });

  it("are none for a form without the field", async () => {
    vi.spyOn(api, "getForm").mockResolvedValue({ ...form("school"), node: [] });

    expect(await targetLoader()("school")).toEqual([]);
  });

  it("come those of a suggested function first, the others after, each in its order", () => {
    const other = value("Rahmenteil", []);

    expect(grouped([AREA, FIELD, other], [CV + "fn_unit"])).toEqual({ suggested: [FIELD], others: [AREA, other] });
    expect(grouped([AREA, FIELD], [])).toEqual({ suggested: [], others: [AREA, FIELD] });
  });
});
