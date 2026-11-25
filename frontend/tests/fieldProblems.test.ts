import { readFileSync } from "node:fs";
import { join } from "node:path";

import { describe, expect, it } from "vitest";

import { messages } from "@/i18n/de";

import { sourceFiles } from "./sources";

/**
 * The problem words a refused field names (backend app/vocab/form_values.py, FieldError): every
 * `FieldError(<field>, "<problem>")` the backend writes, a value's set (app/vocab/value_checks.py,
 * app/api/values.py) among them.
 */
function backendProblems(): string[] {
  const code = sourceFiles(join(process.cwd(), "..", "backend", "app"), /\.py$/)
    .map((path) => readFileSync(path, "utf8"))
    .join("\n");
  const named = [...code.matchAll(/FieldError\([^()]*?(?:\([^()]*\)[^()]*?)*,\s*"([a-z_]+)"\)/g)];
  return [...new Set(named.map(([, problem]) => problem))].sort();
}

describe("the problems of a refused field", () => {
  it("are read from the backend, a value's set's among them", () => {
    expect(backendProblems()).toEqual(expect.arrayContaining(["required", "not_offered", "not_held", "refused"]));
  });

  it("each have words where the tree's forms say them", () => {
    // without, the page says the general "other" (rowRefusals.ts)
    for (const problem of backendProblems()) expect(Object.keys(messages.documents.tree.problems)).toContain(problem);
  });
});
