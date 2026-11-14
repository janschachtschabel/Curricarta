/**
 * The app's icons, drawn once.
 *
 * Not emoji: an emoji's glyph belongs to the operating system, so the same
 * button is a flat outline on Windows and a glossy object on macOS; a screen
 * reader reads out the Unicode name over whatever the control does; and a set
 * borrowed from several vendors shares no stroke weight or optical size.
 *
 * Every glyph here is a list of path data on the same 24x24 grid at the same
 * weight, so they sit together. Paths rather than an injected markup string,
 * because rendering raw markup is forbidden across this SPA
 * (tests/no-raw-html.test.ts). `tests/icons.test.ts` keeps the table honest in
 * both directions: every name the app asks for is drawn, and every name drawn
 * is asked for.
 */
export const GLYPHS = {
  /* The start: the map the app draws of curricula. */
  map: ["M3.5 6.5 9 4.5l6 2 5.5-2v13l-5.5 2-6-2-5.5 2v-13Z", "M9 4.5v13", "M15 6.5v13"],
  /* The register of curriculum documents: a page with its corner turned. */
  document: ["M6.5 3.5h7l4 4v13h-11v-17Z", "M13.5 3.5v4h4", "M9 12h6", "M9 15.5h6"],
  /* The lexicon the editors review: a book, open. */
  lexicon: ["M12 7c-2-1.5-5-2-8.5-1.5v13c3.5-.5 6.5 0 8.5 1.5 2-1.5 5-2 8.5-1.5v-13C17 5 14 5.5 12 7Z", "M12 7v13"],
  /* A node of the tree, closed; turned a quarter to the right while it is open. */
  chevron: ["M9.5 6.5 15 12l-5.5 5.5"],
  /* A toggle that is on (the tree's filter by review status). */
  check: ["M5 12.5 10 17.5 19 7"],
  /* Something failed, or is only partly there. */
  warning: ["M12 4 3 20a1 1 0 0 0 .87 1.5h16.26A1 1 0 0 0 21 20L12 4Z", "M12 10v4.5", "M12 18h.01"],
};

export type IconName = keyof typeof GLYPHS;
