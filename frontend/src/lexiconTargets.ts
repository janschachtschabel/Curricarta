// The node types a new cue may point to (TermDecisionForm.vue): those of the sector's profile, as its form offers
// them (backend GET /api/v1/profiles/{sector}/form, field node_type) - read once a section asks, and again where
// the reading failed. Those refining a function X1 suggested for the term come first.
import { getForm, type FormValue } from "@/api";

/** The node types of a sector, read once for as long as the loader is kept - one loader to a page's section. */
export type Targets = (sector: string) => Promise<FormValue[]>;

export function targetLoader(): Targets {
  const read = new Map<string, Promise<FormValue[]>>();
  return (sector) => {
    let found = read.get(sector);
    if (!found) {
      found = getForm(sector).then((form) => form.node.find((field) => field.key === "node_type")?.values ?? []);
      found.catch(() => read.delete(sector)); // a failure is said by the caller; the next asks again
      read.set(sector, found);
    }
    return found;
  };
}

/** The node types refining one of `functions` first, the others after, each in the form's order. */
export function grouped(types: readonly FormValue[], functions: readonly string[]) {
  const fits = (type: FormValue) => type.broader.some((one) => functions.includes(one));
  return { suggested: types.filter(fits), others: types.filter((type) => !fits(type)) };
}
