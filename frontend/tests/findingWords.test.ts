import { readFileSync } from "node:fs";
import { join } from "node:path";

import { describe, expect, it } from "vitest";

import type { DocumentFinding } from "@/api";
import { isolate } from "@/bidi";
import { findingRow, findingText, focusText } from "@/findingWords";
import { messages, t } from "@/i18n/de";

import { sourceFiles } from "./sources";

function backendCode(): string {
  return sourceFiles(join(process.cwd(), "..", "backend", "app"), /\.py$/)
    .map((path) => readFileSync(path, "utf8"))
    .join("\n");
}

/**
 * The rules whose findings X3 to X6 write, by name without their stage: a `Finding("x5.…"` of X5's
 * checks, a stage's own (`f"{…stage}.pattern_timeout"`), and what the reading of an answer notes
 * (`reading.note("unknown_block", …)`, app/pipeline/statement_read.py, x3_read.py).
 */
function backendRules(code: string): string[] {
  const named = [...code.matchAll(/Finding\(\s*"x[3-6]\.([a-z_]+)"/g)];
  const staged = [...code.matchAll(/Finding\(\s*f"\{[a-z_.]+\}\.([a-z_]+)"/g)];
  const noted = [...code.matchAll(/\bnote\(\s*"([a-z_]+)"/g)];
  return [...new Set([...named, ...staged, ...noted].map(([, rule]) => rule))].sort();
}

/** A finding's focus: a row of its own, no holder. */
function at(kind: string, id: string, label: string | null): DocumentFinding["focus"] {
  return { kind, id, label, holder_kind: null, holder_id: null };
}

/** A finding on a value, the value's holder named - none where the value is no longer there. */
function onValue(kind: string, holder: [string, string, string | null] | null): DocumentFinding {
  const [holderKind, holderId, label] = holder ?? [null, null, null];
  return finding({ focus: { kind, id: "v1", label, holder_kind: holderKind, holder_id: holderId } });
}

function finding(changes: Partial<DocumentFinding> = {}): DocumentFinding {
  return {
    rule: "x5.wording_not_found",
    severity: "violation",
    stage: "X5",
    focus: { kind: "statement", id: "s1", label: "Die Lernenden messen.", holder_kind: null, holder_id: null },
    path: null,
    message: "the wording is not in the blocks its anchor names",
    message_lang: null,
    unit: null,
    ...changes,
  };
}

describe("a finding in words", () => {
  it("finds the rules the backend writes", () => {
    const rules = backendRules(backendCode());

    expect(rules).toEqual(expect.arrayContaining(["wording_not_found", "unknown_block", "unanswered", "pattern_timeout"]));
  });

  it("has words for every rule X3 to X6 write", () => {
    // the reading's rules are named alike at every stage that reads an answer (x3., x4., x6.)
    for (const rule of backendRules(backendCode())) expect(Object.keys(messages.documents.findings.rules)).toContain(rule);
  });

  it("says a rule it has words for in them, whichever stage wrote it", () => {
    expect(findingText(finding())).toEqual({ text: t("documents.findings.rules.wording_not_found") });
    expect(findingText(finding({ rule: "x6.unknown_block", message: "a block the conversion does not hold" }))).toEqual({
      text: t("documents.findings.rules.unknown_block"),
    });
    expect(findingText(finding({ rule: "x1.unknown_block" }))).toEqual({ text: t("documents.findings.rules.unknown_block") });
  });

  it("says a message in German where the server says it is, and quotes any other as English", () => {
    // SHACL's own messages are German where the shapes give one; pyshacl writes its own in English
    const shacl = finding({
      rule: "shacl.StatementShape",
      message: "Eine Aussage braucht genau einen Wortlaut.",
      message_lang: "de",
    });
    const generic = finding({ rule: "shacl.StatementShape", message: "Less than 1 values on cur:obligation" });

    expect(findingText(shacl)).toEqual({ text: "Eine Aussage braucht genau einen Wortlaut." });
    expect(findingText(generic)).toEqual({ text: "Less than 1 values on cur:obligation", lang: "en" });
    expect(findingText(finding({ rule: "x1.regions_differ", message: "the Länder read differ" }))).toEqual({
      text: "the Länder read differ",
      lang: "en",
    });
  });

  it("names what a finding is about by its kind, its wording or title, and the work package", () => {
    // the wording set apart, so its direction does not turn the sentence around it
    expect(focusText(finding())).toBe(
      t("documents.findings.about", { kind: t("documents.findings.kinds.statement"), label: isolate("Die Lernenden messen.") }),
    );
    expect(focusText(finding({ focus: at("document", "d1", null), unit: "E2" }))).toBe(
      t("documents.findings.inUnit", { what: t("documents.findings.kinds.document"), unit: "E2" }),
    );
    expect(focusText(finding({ focus: at("work", "w1", null) }))).toBe("work");
  });

  it("names a value by its kind and its holder, and one no longer there as gone", () => {
    const kinds = messages.documents.findings.kinds;
    const holder = (kind: string, label: string) =>
      t("documents.findings.about", { kind: kinds[kind as keyof typeof kinds], label: isolate(label) });

    expect(focusText(onValue("workload", ["node", "n1", "Optik"]))).toBe(
      t("documents.findings.valueAt", { value: kinds.workload, holder: holder("node", "Optik") }),
    );
    expect(focusText(onValue("level_assignment", ["statement", "s1", "Sie messen."]))).toBe(
      t("documents.findings.valueAt", { value: kinds.level_assignment, holder: holder("statement", "Sie messen.") }),
    );
    expect(focusText(onValue("time_span", ["node", "n1", null]))).toBe(
      t("documents.findings.valueAt", { value: kinds.time_span, holder: kinds.node }),
    );
    expect(focusText(onValue("time_span", null))).toBe(t("documents.findings.valueGone"));
  });

  it("names an assessment by its name, and a level at one with it (plan M3a J)", () => {
    const kinds = messages.documents.findings.kinds;

    expect(focusText(finding({ focus: at("assessment", "a1", "Abschlussprüfung") }))).toBe(
      t("documents.findings.about", { kind: kinds.assessment, label: isolate("Abschlussprüfung") }),
    );
    expect(focusText(onValue("level_assignment", ["assessment", "a1", "Abschlussprüfung"]))).toBe(
      t("documents.findings.valueAt", {
        value: kinds.level_assignment,
        holder: t("documents.findings.about", { kind: kinds.assessment, label: isolate("Abschlussprüfung") }),
      }),
    );
    // no row of the tree to lead to
    expect(findingRow(finding({ focus: at("assessment", "a1", "Abschlussprüfung") }))).toBeNull();
  });

  it("says a statement no longer there is gone: why it alone has no row to lead to", () => {
    const gone = finding({ focus: at("statement", "s1", null), unit: "E3" });

    expect(focusText(gone)).toBe(t("documents.findings.inUnit", { what: t("documents.findings.statementGone"), unit: "E3" }));
  });
});

describe("the row a finding is about", () => {
  it("is the node's or the statement's row of the tree, where the finding is about one", () => {
    expect(findingRow(finding({ focus: at("node", "n1", "Optik") }))).toBe("node:n1");
    expect(findingRow(finding({ focus: at("statement", "s1", "Sie erklären.") }))).toBe(
      "statement:s1",
    );
  });

  it("is a node's row even where the node has neither title nor code", () => {
    expect(findingRow(finding({ focus: at("node", "n1", null) }))).toBe("node:n1");
  });

  it("is none for a statement no longer there: a repair of its package dropped it, its wording with it", () => {
    expect(findingRow(finding({ focus: at("statement", "s1", null) }))).toBeNull();
  });

  it("is the holder's row where the finding is about a value", () => {
    expect(findingRow(onValue("workload", ["node", "n1", "Optik"]))).toBe("node:n1");
    expect(findingRow(onValue("time_span", ["node", "n1", "Optik"]))).toBe("node:n1");
    expect(findingRow(onValue("level_assignment", ["statement", "s1", "Sie messen."]))).toBe("statement:s1");
  });

  it("is none for a value no longer there, and for one whose holder has no row in the tree", () => {
    expect(findingRow(onValue("level_assignment", null))).toBeNull();
    expect(findingRow(onValue("workload", ["specification", "sp1", "Physik"]))).toBeNull();
  });

  it("is none for what has no row of its own: an anchor, a frame part, the document", () => {
    for (const kind of ["anchor", "frame_part", "document", "variant"]) {
      expect(findingRow(finding({ focus: at(kind, "x1", null) }))).toBeNull();
    }
  });
});
