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
  // of a row without indent runs 233 px (x 55 to 288), so six steps may take at most 41 px.
  it("tells every level apart by its indent and keeps a level-7 row's text room", () => {
    const file = "components/TreeView.vue";
    expect(source(file)).toContain("'--tree-depth'");
    const step = /padding-inline-start:\s*calc\(var\(--tree-depth\) \* ([\d.]+)rem\)/.exec(narrowRule(file, ".tree__row") ?? "")?.[1];
    expect(step, "one step per level, in rem").toBeDefined();
    const px = Number(step) * 16;
    expect(px).toBeGreaterThanOrEqual(6);
    expect(233 - 6 * px).toBeGreaterThanOrEqual(0.6 * 320);
  });
});

describe("an entry of a row's values on a narrow screen", () => {
  // jsdom lays nothing out: below 40rem the entry's fields stand one under another, a select keeping the width to
  // show its value, and wide its columns collapse to the container rather than widen the page (SC 1.4.10)
  it("stacks its fields one under another, and caps its columns at its width", () => {
    const file = "components/ValueItemForm.vue";
    expect(narrowRule(file, ".value-item__fields")).toMatch(/grid-template-columns:\s*minmax\(0, 1fr\)/);
    expect(stylesOf(source(file))).toMatch(/repeat\(auto-fill, minmax\(min\(12rem, 100%\), 1fr\)\)/);
  });

  it("stacks an applicability context's fields so too, and caps its columns at its width", () => {
    const file = "components/ContextItemForm.vue";
    expect(narrowRule(file, ".context-item__fields")).toMatch(/grid-template-columns:\s*minmax\(0, 1fr\)/);
    expect(stylesOf(source(file))).toMatch(/repeat\(auto-fill, minmax\(min\(12rem, 100%\), 1fr\)\)/);
  });

  it("lets a rule's wording, option texts and links break anywhere rather than widen the page", () => {
    expect(cssRules(stylesOf(source("components/DocumentRules.vue"))).find(({ selectors }) => selectors.includes(".rules__text"))?.body).toMatch(
      /overflow-wrap:\s*anywhere/,
    );
  });

  it("lets an assessment's name, what it assesses and its form's lists keep to the page's width", () => {
    const item = cssRules(stylesOf(source("components/AssessmentItem.vue")));
    const form = cssRules(stylesOf(source("components/AssessmentForm.vue")));
    expect(item.find(({ selectors }) => selectors.includes(".assessment__title bdi"))?.body).toMatch(/overflow-wrap:\s*anywhere/);
    expect(form.find(({ selectors }) => selectors.includes(".assessment-form__target"))?.body).toMatch(/overflow-wrap:\s*anywhere/);
    expect(form.find(({ selectors }) => selectors.includes(".assessment-form select"))?.body).toMatch(/max-inline-size:\s*100%/);
  });

  it("stacks a placement's fields, keeps its lists to the page's width and lets its words break anywhere", () => {
    const file = "components/PlacementItemForm.vue";
    expect(narrowRule(file, ".placement-item__fields")).toMatch(/grid-template-columns:\s*minmax\(0, 1fr\)/);
    const item = cssRules(stylesOf(source(file)));
    expect(item.find(({ selectors }) => selectors.includes(".placement-item select"))?.body).toMatch(/max-inline-size:\s*100%/);
    const section = cssRules(stylesOf(source("components/PlacementList.vue")));
    expect(section.find(({ selectors }) => selectors.includes(".node-placements__list li"))?.body).toMatch(/overflow-wrap:\s*anywhere/);
  });

  it("keeps a placement's place search and its paths to the page's width, a long path breaking anywhere", () => {
    const rules = cssRules(stylesOf(source("components/PlacePicker.vue")));
    const of = (selector: string) => rules.filter(({ selectors }) => selectors.includes(selector)).map(({ body }) => body).join(";");
    expect(of(".place-picker")).toMatch(/min-inline-size:\s*0/);
    expect(of(".place-picker__place")).toMatch(/overflow-wrap:\s*anywhere/);
    expect(of(".place-picker__place")).toMatch(/max-inline-size:\s*100%/);
    expect(of(".place-picker__chosen bdi")).toMatch(/overflow-wrap:\s*anywhere/);
  });

  it("keeps a workload's periods within its width, their fields stacked as every entry's", () => {
    const file = "components/ValueItemForm.vue";
    const periods = cssRules(stylesOf(source(file))).find(({ selectors }) => selectors.includes(".value-item__periods"));
    expect(periods?.body).toMatch(/min-inline-size:\s*0/);
    // a period is an entry of the same form: its fields stack under the same rule
    expect(narrowRule(file, ".value-item__fields")).toMatch(/grid-template-columns:\s*minmax\(0, 1fr\)/);
  });

  it("lets a value's words and a level's label break anywhere rather than widen the panel", () => {
    expect(cssRules(stylesOf(source("components/ValueList.vue"))).find(({ selectors }) => selectors.includes(".value-list__words"))?.body).toMatch(
      /overflow-wrap:\s*anywhere/,
    );
  });
});

