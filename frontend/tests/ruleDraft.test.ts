import { describe, expect, it } from "vitest";

import { changesOf, draftOf, isDirty } from "@/ruleDraft";

import { ruleOf } from "./ruleFixtures";

const CV = "https://w3id.org/wlo/curriculum/vocab#";
// as a run may have read it: a share at a completion, an option text with blanks around and an empty line
const read = ruleOf({ kind: "completion", max_share: 0.3, requirement_kind: CV + "req_formal", option_texts: [" A ", ""] });

describe("a rule's draft", () => {
  it("is no change as it was read, though the rule holds what its kind does not show", () => {
    const draft = draftOf(read);

    expect(isDirty(read, draft)).toBe(false);
    expect(changesOf(read, draft)).toEqual({ fields: {}, faults: [] });
  });

  it("sends the change of one field alone, not the clean-up of the others", () => {
    const draft = { ...draftOf(read), max_count: "3" };

    expect(isDirty(read, draft)).toBe(true);
    expect(changesOf(read, draft).fields).toEqual({ max_count: 3 });
  });

  it("sends the option texts cleaned once they are changed", () => {
    const draft = { ...draftOf(read), option_texts: " A \n\n B " };

    expect(changesOf(read, draft).fields).toEqual({ option_texts: ["A", "B"] });
  });

  it("empties what a new kind does not hold, with the kind", () => {
    const draft = { ...draftOf(read), kind: "selection" };

    expect(changesOf(read, draft).fields).toEqual({ kind: "selection", max_share: null, requirement_kind: null });
  });
});
