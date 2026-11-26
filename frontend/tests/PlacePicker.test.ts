import { mount, type VueWrapper } from "@vue/test-utils";
import { afterEach, describe, expect, it } from "vitest";
import { defineComponent, h, ref } from "vue";

import PlacePicker from "@/components/PlacePicker.vue";
import { t } from "@/i18n/de";
import type { Choice } from "@/placementDraft";

import { violations } from "./axe";

// Where a placement is in the outline (plan M3a K, its bounded search carried to L): a single choice by a search over
// the outline's nodes, each by its path, at most 20 matches shown and the rest counted, the choice said and let go
// again; an Enter in the search submits nothing, a choice keeps the keyboard at the search.
let shown: VueWrapper | null = null;

const PLACES: Choice[] = Array.from({ length: 30 }, (_, at) => ({ id: `n${at}`, label: `B Pflichtbereich › Modul ${at + 1}` }));

function picker(chosen = "", more: Record<string, unknown> = {}): { wrapper: VueWrapper; value: () => string } {
  const model = ref(chosen);
  const Host = defineComponent({
    setup: () => () =>
      h(PlacePicker, {
        modelValue: model.value,
        "onUpdate:modelValue": (value: string) => (model.value = value),
        places: [...PLACES, { id: "w1", label: "W Wahlbereich" }],
        controlId: "pick",
        hint: "Wo im Plan.",
        ...more,
      }),
  });
  shown = mount(Host, { attachTo: document.body });
  return { wrapper: shown, value: () => model.value };
}

const offered = (wrapper: VueWrapper) => wrapper.findAll("[data-test=places-offered] button");

afterEach(() => {
  shown?.unmount();
  shown = null;
  document.body.innerHTML = "";
});

describe("the place of a placement", () => {
  it("is a group named for it, a search and at most 20 places by their paths, the rest counted", async () => {
    const { wrapper } = picker();

    expect(wrapper.get("fieldset > legend").text()).toBe(t("documents.tree.placements.fields.in_node_id"));
    expect(wrapper.get("label[for=pick]").text()).toBe(t("documents.tree.placements.placeSearch"));
    expect(offered(wrapper)).toHaveLength(20);
    expect(offered(wrapper)[0]?.text()).toBe("B Pflichtbereich › Modul 1");
    expect(wrapper.get("#pick-more").text()).toBe("11 weitere Stellen passen; grenze die Suche ein.");
    expect(wrapper.get("#pick-chosen").text()).toBe(t("documents.tree.placements.placeNone"));
    // each place's name begins with its visible words (WCAG 2.5.3)
    for (const button of offered(wrapper)) expect(button.attributes("aria-label")?.startsWith(button.text())).toBe(true);
    expect(await violations(wrapper.html())).toEqual([]);
  });

  it("narrows to the places whose path holds the words searched, and says where none does", async () => {
    const { wrapper } = picker();

    await wrapper.get("#pick").setValue("wahl");
    expect(offered(wrapper).map((one) => one.text())).toEqual(["W Wahlbereich"]);
    expect(wrapper.get("#pick-more").text()).toBe("");
    await wrapper.get("#pick").setValue("Mathematik");
    expect(offered(wrapper)).toHaveLength(0);
    expect(wrapper.get("#pick-more").text()).toBe(t("documents.tree.placements.placeNoMatch"));
  });

  it("takes the place pressed, says so, keeps the keyboard at the search, and lets it go again", async () => {
    const { wrapper, value } = picker();
    await wrapper.get("#pick").setValue("wahl");

    await offered(wrapper)[0]?.trigger("click");

    expect(value()).toBe("w1");
    expect(document.activeElement).toBe(wrapper.get("#pick").element);
    expect(wrapper.get("#pick-chosen").text()).toBe("Gewählt: W Wahlbereich");
    expect(wrapper.get("#pick").attributes("aria-describedby")?.split(" ")).toContain("pick-chosen");
    expect(wrapper.get("[role=status]").text()).toBe("Du hast „W Wahlbereich“ gewählt.");
    expect(offered(wrapper).map((one) => one.text())).not.toContain("W Wahlbereich");

    const release = wrapper.get("[data-test=place-release]");
    expect(release.attributes("aria-label")?.startsWith(release.text())).toBe(true);
    await release.trigger("click");
    expect(value()).toBe("");
    expect(document.activeElement).toBe(wrapper.get("#pick").element);
    expect(wrapper.get("[role=status]").text()).toBe("Du hast die Stelle „W Wahlbereich“ gelöst.");
  });

  it("holds an Enter in the search: it would submit the placements' form", () => {
    const { wrapper } = picker();

    const event = new KeyboardEvent("keydown", { key: "Enter", bubbles: true, cancelable: true });
    wrapper.get("#pick").element.dispatchEvent(event);

    expect(event.defaultPrevented).toBe(true);
  });

  it("says a place kept that the outline holds no more, and a problem at the search", () => {
    const { wrapper } = picker("gone", { error: "Diesen Wert bietet die Liste nicht an." });

    expect(wrapper.get("#pick-chosen").text()).toBe(`Gewählt: ${t("documents.tree.placements.unknownPlace")}`);
    expect(wrapper.get("#pick").attributes("aria-invalid")).toBe("true");
    expect(wrapper.get("#pick").attributes("aria-describedby")?.split(" ")).toContain("pick-error");
    expect(wrapper.get("#pick-error").text()).toContain("Diesen Wert bietet die Liste nicht an.");
  });
});
