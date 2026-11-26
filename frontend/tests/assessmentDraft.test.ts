import { describe, expect, it } from "vitest";

import { draftOf, fieldsOf } from "@/assessmentDraft";
import { t } from "@/i18n/de";

describe("an assessment's entry", () => {
  it("assesses at most as many rows as the server takes, said at its targets", () => {
    const entry = { ...draftOf(undefined, "s1"), assessment_kind: "k", targets: Array.from({ length: 201 }, (_, at) => `n${at}`) };

    const [, problems] = fieldsOf(entry);
    const [, fine] = fieldsOf({ ...entry, targets: entry.targets.slice(0, 200) });

    expect(problems).toEqual([["targets", t("documents.page.assessments.problems.too_many_targets", { most: 200 })]]);
    expect(fine).toEqual([]);
  });
});
