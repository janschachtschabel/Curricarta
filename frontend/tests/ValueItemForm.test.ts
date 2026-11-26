import { mount, type VueWrapper } from "@vue/test-utils";
import { afterEach, describe, expect, it } from "vitest";

import type { HeldValues } from "@/api";
import ValueItemForm from "@/components/ValueItemForm.vue";
import { draftOfValues, newEntry, type Entry } from "@/valueDraft";

import { violations } from "./axe";
import { CV, LVL, form_, noValues } from "./treeFixtures";

let shown: VueWrapper | null = null;

afterEach(() => {
  shown?.unmount();
  shown = null;
  document.body.innerHTML = "";
});

const FORM = form_();
const STATED = { origin: CV + "orig_human", review_status: CV + "rev_proposed", revision: 1 };

function workload(): Entry {
  const values: HeldValues = {
    ...noValues(),
    workloads: [
      {
        id: "w1",
        ...STATED,
        amount: 80,
        amount_to: null,
        unit: CV + "unit_lesson",
        workload_kind: null,
        is_recommendation: false,
        minutes_per_unit: null,
        total: false,
        periods: [{ id: "p1", ...STATED, time_kind: CV + "time_gradeLevel", span_from: 7, span_to: 8, time_relation: null }],
      },
    ],
  };
  const entry = draftOfValues(FORM, values).workloads[0];
  if (!entry) throw new Error("an entry");
  return entry;
}

function item(kind: "workloads" | "level_assignments", entry: Entry, more: Record<string, unknown> = {}): VueWrapper {
  shown = mount(ValueItemForm, {
    props: { kind, entry, place: 0, form: FORM, holder: "node", holderType: null, prefix: "v", errors: {}, ...more },
    attachTo: document.body,
  });
  return shown;
}

describe("an entry of a value's form", () => {
  it("is a group named by its kind and place, each field labelled, its periods said as they stay", async () => {
    const wrapper = item("workloads", workload());

    expect(wrapper.get("fieldset > legend").text()).toBe("Umfang 1");
    expect(wrapper.findAll("label").map((label) => label.text())).toEqual([
      "Umfang (Pflichtfeld)",
      "Bis",
      "Einheit (Pflichtfeld)",
      "Art des Umfangs",
      "Richtwert, nicht verbindlich",
      "Minuten je Einheit",
      "Gesamtumfang",
    ]);
    expect((wrapper.get("#v-amount").element as HTMLInputElement).value).toBe("80");
    expect(wrapper.get(".value-item__periods").text()).toBe(
      "Zeiträume dieses Umfangs: Jahrgangsstufe 7–8. Sie bleiben beim Speichern, wie sie sind.",
    );
    expect(await violations(wrapper.html())).toEqual([]);
  });

  it("gives each change back as the entry's fields, and asks to be taken away by a button that names it", async () => {
    const wrapper = item("workloads", workload());

    await wrapper.get("#v-amount").setValue("90");
    await wrapper.get("#v-is_recommendation").setValue(true);

    expect(wrapper.emitted("change")?.[0]?.[0]).toMatchObject({ amount: "90", unit: CV + "unit_lesson" });
    expect(wrapper.emitted("change")?.[1]?.[0]).toMatchObject({ is_recommendation: true });
    const remove = wrapper.get("button");
    expect(remove.text()).toBe("Umfang 1 entfernen");
    await remove.trigger("click");
    expect(wrapper.emitted("remove")).toHaveLength(1);
  });

  it("offers a statement no level its rules keep from it, its levels grouped by system", () => {
    const entry = newEntry(FORM, "level_assignments");
    const wrapper = item("level_assignments", entry, { holder: "statement" });

    expect(wrapper.findAll("#v-level optgroup").map((group) => group.attributes("label"))).toEqual(["Sprachniveaus"]);
    expect(wrapper.findAll("#v-level option").map((option) => option.attributes("value"))).not.toContain(LVL + "Q4");
  });

  it("says a field's problem at that field and takes the keyboard to its first field when asked", async () => {
    const wrapper = item("workloads", workload(), { errors: { unit: "Diesen Wert bietet die Auswahlliste nicht an." } });

    expect(wrapper.get("#v-unit").attributes("aria-invalid")).toBe("true");
    expect(wrapper.get("#v-unit-error, [id$=-error]").text()).toBe("Diesen Wert bietet die Auswahlliste nicht an.");
    (wrapper.vm as unknown as { focus: () => void }).focus();
    expect(document.activeElement).toBe(wrapper.get("#v-amount").element);
    expect(await violations(wrapper.html())).toEqual([]);
  });
});
