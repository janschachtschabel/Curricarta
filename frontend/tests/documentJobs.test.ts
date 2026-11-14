import { describe, expect, it } from "vitest";

import { CHECK_KIND, IMPORT_KIND, REPAIR_KIND } from "@/api";
import { jobLabel, lastStatus, startedWords } from "@/documentJobs";
import { t } from "@/i18n/de";

describe("a document's job in words", () => {
  it("is named by its kind: an extraction, a repair, a check", () => {
    expect(jobLabel("extract.run")).toBe(t("documents.page.jobLabel"));
    expect(jobLabel(REPAIR_KIND)).toBe(t("documents.page.repairLabel"));
    expect(jobLabel(CHECK_KIND)).toBe("Prüfung");
    expect(jobLabel(IMPORT_KIND)).toBe("Import aus MEM-Schule");
  });

  it("says how the latest stands, by its kind", () => {
    const done = t("jobs.status.done");

    expect(lastStatus({ kind: "extract.run", status: "done" })).toBe(t("documents.page.lastStatus", { status: done }));
    expect(lastStatus({ kind: REPAIR_KIND, status: "done" })).toBe(t("documents.page.lastRepairStatus", { status: done }));
    expect(lastStatus({ kind: CHECK_KIND, status: "done" })).toBe(`Letzte Prüfung: ${done}`);
    expect(lastStatus({ kind: IMPORT_KIND, status: "done" })).toBe(`Letzter Import: ${done}`);
  });

  it("says what a start set going, or met waiting or running, by its kind", () => {
    expect(startedWords("extract.run")).toBe(t("documents.page.started"));
    expect(startedWords(REPAIR_KIND)).toBe(t("documents.page.repairRunning"));
    expect(startedWords(CHECK_KIND)).toBe("Die Prüfung läuft; ihr Stand steht hier.");
    expect(startedWords(IMPORT_KIND)).toBe("Der Import ist gestartet; sein Stand steht hier.");
  });
});
