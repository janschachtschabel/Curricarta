import { readFileSync } from "node:fs";
import { join } from "node:path";

import { describe, expect, it } from "vitest";

import type { DocumentFinding } from "@/api";
import { findingPath } from "@/findingWords";
import { messages } from "@/i18n/de";

// Where in a row a SHACL finding stands (X5 carried to plan M3a L): its path - the row's property down to the one a
// shape found, `cur:applicability/cur:educationSector` - in words, each property by the page's word for it, one it has
// none for by its local name.

function finding(changes: Partial<DocumentFinding> = {}): DocumentFinding {
  return {
    rule: "shacl.ApplicabilityContextShape",
    severity: "violation",
    stage: "X5",
    focus: { kind: "specification", id: "s1", label: "Bachelor", holder_kind: null, holder_id: null, placed_node_id: null },
    path: "cur:applicability/cur:educationSector",
    message: "Wert ist nicht in der Liste.",
    message_lang: "de",
    unit: null,
    ...changes,
  };
}

/** The properties the shapes X5 loads (SHAPE_FILES in backend app/pipeline/shacl_child.py) name by sh:path. */
function shapedProperties(): string[] {
  const child = readFileSync(join(process.cwd(), "..", "backend", "app", "pipeline", "shacl_child.py"), "utf8");
  const files = [...(/^SHAPE_FILES = \(([^)]*)\)/m.exec(child)?.[1] ?? "").matchAll(/"([^"]+\.ttl)"/g)].map(([, name]) => name);
  expect(files.length).toBeGreaterThan(0);
  const names = files.flatMap((name) => {
    const source = readFileSync(join(process.cwd(), "..", "ontology", name), "utf8");
    return [...source.matchAll(/sh:(?:path|inversePath) ([a-z]+:[A-Za-z]+)/g)].map(([, curie]) => curie);
  });
  return [...new Set(names)].sort();
}

describe("a finding's place in its row", () => {
  it("is said in words from the row down, each property by the page's word for it", () => {
    expect(findingPath(finding())).toBe("Angabe: Geltungskontext › Bildungsbereich");
    expect(findingPath(finding({ path: "cur:timeSpan" }))).toBe("Angabe: Zeitraum");
  });

  it("says an inverse property so, and one the page has no word for by its local name", () => {
    expect(findingPath(finding({ path: "^cur:partOf" }))).toBe("Angabe: Teil von (umgekehrt)");
    expect(findingPath(finding({ path: "cur:somethingNew" }))).toBe("Angabe: somethingNew");
    expect(findingPath(finding({ path: "https://example.org/terms#extent" }))).toBe("Angabe: extent");
  });

  it("is none where the finding names no property, or is no shape's", () => {
    expect(findingPath(finding({ path: null }))).toBeNull();
    expect(findingPath(finding({ rule: "x3.unknown_block", path: "statements[2].level" }))).toBeNull();
  });

  it("has a word for every property a shape X5 loads names, and none for another", () => {
    expect(Object.keys(messages.documents.findings.properties).sort()).toEqual(shapedProperties());
  });
});
