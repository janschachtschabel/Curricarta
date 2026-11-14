import { readFileSync } from "node:fs";
import { join } from "node:path";

import { describe, expect, it } from "vitest";

import type * as api from "@/api";
import { isolate } from "@/bidi";
import { conversionFailureText, findingText } from "@/conversionWords";
import { messages, t } from "@/i18n/de";

/** true where `A` and `B` name the same values; vue-tsc fails the list below where they do not. */
type Same<A, B> = [A] extends [B] ? ([B] extends [A] ? true : false) : false;

// a text block says no kind: it is what most blocks are
const typesFollow: [
  Same<api.FindingCode, Exclude<keyof typeof messages.conversions.findings, "other">>,
  Same<api.DropReason, keyof typeof messages.conversions.findings.text_dropped>,
  Same<Exclude<api.BlockKind, "text">, keyof typeof messages.conversionPage.kind>,
] = [true, true, true];

/** The values of the `Literal[...]` the backend names `name` in app/conversion/base.py. */
function backendValues(name: string): string[] {
  const source = readFileSync(join(process.cwd(), "..", "backend", "app", "conversion", "base.py"), "utf8");
  const literal = new RegExp(`^${name} = Literal\\[([^\\]]*)\\]`, "m").exec(source)?.[1] ?? "";
  return [...literal.matchAll(/"([^"]+)"/g)].map(([, value]) => value).sort();
}

const symbol = (params: Record<string, unknown>): api.ConversionFinding => ({ code: "unmapped_symbol", params });

describe("what a conversion found, in words", () => {
  it("says how many signs of a symbol font were left as they are, and on which page", () => {
    const text = findingText(symbol({ codepoint: "U+F0B7", count: 3, pages: [1] }));

    expect(text).toBe(t("conversions.findings.unmapped_symbol", { count: 3, codepoint: "U+F0B7", pageCount: 1, pages: "1" }));
    expect(text).toContain("3 Zeichen");
    expect(text).toContain("U+F0B7");
    expect(text).toContain("Seite 1 ");
  });

  it("says one sign as one, and runs of pages as ranges", () => {
    const one = findingText(symbol({ codepoint: "U+F0A7", count: 1, pages: [2] }));
    const many = findingText(symbol({ codepoint: "U+F0A7", count: 40, pages: [1, 2, 3, 5, 7, 8] }));

    expect(one).toContain("1 Zeichen");
    expect(one).toContain("steht es");
    const ranges = [t("conversions.pageRange", { from: 1, to: 3 }), "5", t("conversions.pageRange", { from: 7, to: 8 })];
    expect(many).toContain(`Seiten ${new Intl.ListFormat("de-DE", { type: "conjunction" }).format(ranges)} `);
  });

  it("says that the text layer looks damaged, how much of it, and what it looks like", () => {
    const text = findingText({ code: "encoding_suspect", params: { share: 0.034, count: 41, examples: ["Ã¤", "(cid:3)"] } });

    expect(text).toContain("41 verdächtige Zeichen");
    expect(text).toContain("3,4");
    // the document's own signs, set apart from the sentence around them
    expect(text).toContain(`„${isolate("Ã¤")}“`);
    expect(text).toContain(`„${isolate("(cid:3)")}“`);
  });

  it("says how many signs of text the conversion dropped, why, and on which pages", () => {
    // the backend counts signs: pdfplumber splinters a word set upwards into words of its own
    const text = findingText({ code: "text_dropped", params: { reason: "vertical", count: 23, pages: [1, 3] } });
    const pages = new Intl.ListFormat("de-DE", { type: "conjunction" }).format(["1", "3"]);

    expect(text).toBe(t("conversions.findings.text_dropped.vertical", { count: 23, pageCount: 2, pages }));
    expect(text).toContain("23 Zeichen Text auf Seiten 1 und 3 ");
    expect(text).toContain("senkrecht");
    expect(text).not.toContain("Wort");
  });

  it("has words for each reason text is dropped, one sign as one", () => {
    for (const reason of backendValues("DropReason")) {
      const text = findingText({ code: "text_dropped", params: { reason, count: 1, pages: [4] } });

      expect(text).toBe(t(`conversions.findings.text_dropped.${reason}`, { count: 1, pageCount: 1, pages: "4" }));
      expect(text).toContain("1 Zeichen Text auf Seite 4 ");
      expect(text).not.toMatch(/[{}]/);
    }
  });

  it("says a dropping for a reason it does not know, or without its numbers, by its code", () => {
    const other = t("conversions.findings.other", { code: "text_dropped" });

    expect(findingText({ code: "text_dropped", params: { reason: "faded", count: 2, pages: [1] } })).toBe(other);
    expect(findingText({ code: "text_dropped", params: { reason: "toString", count: 2, pages: [1] } })).toBe(other);
    expect(findingText({ code: "text_dropped", params: { reason: "tiny", count: 2 } })).toBe(other);
  });

  it("says which pages were read by text recognition, and how sure it was on the least sure", () => {
    const text = findingText({ code: "ocr_read", params: { pages: [2, 3, 4], confidence: 0.75 } });
    const pages = t("conversions.pageRange", { from: 2, to: 4 });

    const confidence = new Intl.NumberFormat("de-DE", { style: "percent" }).format(0.75);

    expect(text).toBe(t("conversions.findings.ocr_read", { pageCount: 3, pages, confidence }));
    expect(text).toContain("Seiten 2–4 ");
    expect(text).toContain(confidence);
  });

  it("says text a file without pages hid from its reader, left out before it was paged", () => {
    // a DOCX's runs, an HTML page's elements, taken out before Docling reads the file: on no page yet
    const hidden = findingText({ code: "text_dropped", params: { reason: "hidden", count: 42, pages: [] } });
    const tiny = findingText({ code: "text_dropped", params: { reason: "tiny", count: 1, pages: [] } });

    expect(hidden).toBe(t("conversions.unpagedDrops.hidden", { count: 42 }));
    expect(hidden).toContain("42 Zeichen Text ");
    expect(hidden).not.toMatch(/Seite|[{}]/);
    expect(tiny).toBe(t("conversions.unpagedDrops.tiny", { count: 1 }));
    expect(tiny).toContain("1 Zeichen Text ist ");
  });

  it("says a dropping before the pages for a reason it has no such words for by its code", () => {
    const other = t("conversions.findings.other", { code: "text_dropped" });

    expect(findingText({ code: "text_dropped", params: { reason: "vertical", count: 2, pages: [] } })).toBe(other);
    expect(findingText({ code: "text_dropped", params: { reason: "toString", count: 2, pages: [] } })).toBe(other);
  });

  it("says that a file without pages was cut into pages of so many signs, which count as pages", () => {
    const text = findingText({ code: "flow_pages", params: { signs: 3000 } });

    expect(text).toBe(t("conversions.findings.flow_pages", { signs: 3000 }));
    expect(text).toContain("3000 Zeichen");
    expect(findingText({ code: "flow_pages", params: {} })).toBe(t("conversions.findings.other", { code: "flow_pages" }));
    expect(findingText({ code: "flow_pages", params: { signs: 0 } })).toBe(t("conversions.findings.other", { code: "flow_pages" }));
  });

  it("says a page read by text recognition without its numbers by its code", () => {
    const other = t("conversions.findings.other", { code: "ocr_read" });

    expect(findingText({ code: "ocr_read", params: { pages: [1] } })).toBe(other);
    expect(findingText({ code: "ocr_read", params: { pages: [], confidence: 0.9 } })).toBe(other);
    expect(findingText({ code: "ocr_read", params: { pages: [1], confidence: 3 } })).toBe(other);
  });

  it("says a finding it has no words for, or whose numbers are missing, by its code rather than guess", () => {
    expect(findingText({ code: "something_new", params: {} })).toBe(t("conversions.findings.other", { code: "something_new" }));
    expect(findingText(symbol({ codepoint: "U+F0B7", count: "drei", pages: [1] }))).toBe(
      t("conversions.findings.other", { code: "unmapped_symbol" }),
    );
    expect(findingText({ code: "encoding_suspect", params: { share: 0.5, count: 30 } })).toBe(
      t("conversions.findings.other", { code: "encoding_suspect" }),
    );
  });

  it("has words for every finding the backend reports, and for no other", () => {
    expect(typesFollow.every(Boolean)).toBe(true);
    const worded = Object.keys(messages.conversions.findings).filter((code) => code !== "other");

    expect(worded.sort()).toEqual(backendValues("FindingCode"));
    expect(Object.keys(messages.conversions.findings.text_dropped).sort()).toEqual(backendValues("DropReason"));
    for (const reason of Object.keys(messages.conversions.unpagedDrops)) expect(backendValues("DropReason")).toContain(reason);
  });
});

describe("what a block is, in words", () => {
  it("names every kind the backend has but text, and no other", () => {
    expect(backendValues("BlockKind")).toContain("page_header");

    expect([...Object.keys(messages.conversionPage.kind), "text"].sort()).toEqual(backendValues("BlockKind"));
  });
});

describe("why a conversion failed, in words", () => {
  it("is its job's reason", () => {
    expect(conversionFailureText("needs_ocr")).toBe(t("jobs.failures.needs_ocr"));
    expect(conversionFailureText("lease_lost")).toBe(t("jobs.failures.lease_lost"));
  });

  it("is that it was stopped, where its job was cancelled", () => {
    expect(conversionFailureText("cancelled")).toBe(t("conversions.cancelled"));
  });

  it("is the service's failure, not a foreign server's, where its job failed again and again", () => {
    // a conversion asks no other server: the words of a fetch would point the wrong way
    expect(conversionFailureText("handler_error")).toBe(t("conversions.handlerError"));
    expect(conversionFailureText("handler_error")).not.toBe(t("jobs.failures.handler_error"));
  });

  it("is the general words for a code the page does not know, or for none", () => {
    expect(conversionFailureText("something_new")).toBe(t("jobs.failedUnknown"));
    expect(conversionFailureText(null)).toBe(t("jobs.failedUnknown"));
  });
});
