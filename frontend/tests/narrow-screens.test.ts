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

  // display: none took the column heads out of the accessibility tree, and display: block drops a table's roles in
  // some engines (UI review 1, finding 7)
  it.each([
    ["components/DocumentFindings.vue", ".findings"],
    ["components/SourceTable.vue", ".register__table"],
  ])("keeps its column heads and its table's roles: %s", (file, table) => {
    // its heads clipped below 40rem by the shared rule, not taken out by display: none
    expect(narrowRule(file, `${table} thead`) ?? "").not.toMatch(/display:\s*none/);
    expect(source(file)).toMatch(/<thead role="rowgroup" class="visually-hidden-narrow">/);
    const roles: Record<string, string> = { table: "table", thead: "rowgroup", tbody: "rowgroup", tr: "row", th: "columnheader", td: "cell" };
    const tags = [...source(file).matchAll(/<(table|thead|tbody|tr|th|td)(?![\w-])((?:[^>"']|"[^"]*"|'[^']*')*)>/g)];
    expect(tags.length).toBeGreaterThan(6);
    for (const [, tag, attributes] of tags) expect(attributes, `<${tag}>`).toContain(`role="${roles[tag]}"`);
  });

  it.each([
    ["components/DocumentFindings.vue", 2],
    ["components/SourceTable.vue", 4],
  ])("names the cells a stacked row labels by their column: %s", (file, count) => {
    expect(source(file).match(/:data-label="t\(/g)).toHaveLength(count);
  });
});

describe("the column heads of a stacked table", () => {
  it("are clipped below 40rem as visually-hidden clips, by one rule beside it", () => {
    const stylesheet = source("style.css");
    const hidden = cssRules(stylesheet).find(({ selectors }) => selectors.includes(".visually-hidden"))?.body;
    const narrow = /@media \(max-width: 40rem\) \{\s*\.visually-hidden-narrow \{([^}]*)\}/.exec(stylesheet)?.[1];
    expect(hidden).toBeDefined();
    expect(narrow?.replace(/\s+/g, " ").trim()).toBe(hidden?.replace(/\s+/g, " ").trim());
  });
});

describe("a deep tree row on a narrow screen", () => {
  // Levels 4 to 7 shared one indent at 320 px (browser check 2, defect 3): every level is told apart by a step of
  // at least 6 px, and a level-7 row (depth 6) keeps 60 % of 320 px for its text. Measured at 320 px, the text
  // of a row without indent runs 233.6 px (x 54.4 to 288), so six steps may take at most 41.6 px.
  it("tells every level apart by its indent and keeps a level-7 row's text room", () => {
    const file = "components/TreeView.vue";
    expect(source(file)).toContain("'--tree-depth'");
    const step = /padding-inline-start:\s*calc\(var\(--tree-depth\) \* ([\d.]+)rem\)/.exec(narrowRule(file, ".tree__row") ?? "")?.[1];
    expect(step, "one step per level, in rem").toBeDefined();
    const px = Number(step) * 16;
    expect(px).toBeGreaterThanOrEqual(6);
    expect(233.6 - 6 * px).toBeGreaterThanOrEqual(0.6 * 320);
  });
});
