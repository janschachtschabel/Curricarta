import { readFileSync } from "node:fs";
import { join } from "node:path";

import { describe, expect, it } from "vitest";

import { SRC, cssRules, stylesOf } from "./sources";

/**
 * At 320 px the findings and the register needed sideways scrolling to read a sentence, and a deep tree row kept
 * a third of its width (UI review m7, m8). jsdom lays nothing out: the rules are read from the components' styles.
 */
const source = (path: string) => readFileSync(join(SRC, ...path.split("/")), "utf8");

/** The body of the rule for `selector` inside `@media (max-width: 40rem)`. */
function narrowRule(file: string, selector: string): string | undefined {
  const narrow = /@media \(max-width: 40rem\) \{([\s\S]*?)\n\}/.exec(stylesOf(source(file)))?.[1] ?? "";
  return cssRules(narrow).find(({ selectors }) => selectors.includes(selector))?.body;
}

describe("a table of prose on a narrow screen", () => {
  it.each([
    ["components/DocumentFindings.vue", ".findings"],
    ["components/SourceTable.vue", ".register__table"],
  ])("stacks each row as a block: %s", (file, table) => {
    expect(narrowRule(file, `${table} tr`)).toMatch(/display:\s*block/);
    expect(narrowRule(file, `${table} td`)).toMatch(/display:\s*block/);
    // what a cell is, said before it, as its column's head no longer stands above it
    expect(narrowRule(file, `${table} td[data-label]::before`)).toMatch(/content:\s*attr\(data-label\)/);
  });

  it.each([
    ["components/DocumentFindings.vue", 2],
    ["components/SourceTable.vue", 4],
  ])("names the cells a stacked row labels by their column: %s", (file, count) => {
    expect(source(file).match(/:data-label="t\(/g)).toHaveLength(count);
  });
});

describe("a deep tree row on a narrow screen", () => {
  it("keeps its indent within three levels", () => {
    const file = "components/TreeView.vue";
    expect(source(file)).toContain("'--tree-depth'");
    expect(narrowRule(file, ".tree__row")).toMatch(/padding-inline-start:\s*calc\(min\(var\(--tree-depth\), 3\)/);
  });
});
