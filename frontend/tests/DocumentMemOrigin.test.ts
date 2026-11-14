import { mount } from "@vue/test-utils";
import { describe, expect, it } from "vitest";

import DocumentMemOrigin from "@/components/DocumentMemOrigin.vue";
import { t } from "@/i18n/de";

import { violations } from "./axe";

function described(html: HTMLElement, term: string): string {
  const found = [...html.querySelectorAll("dt")].find((dt) => dt.textContent?.trim() === term);
  expect(found, `no ${term}`).toBeDefined();
  return (found?.nextElementSibling?.textContent ?? "").trim();
}

describe("where an imported document came from", () => {
  it("names its plan, linked, its attribution and the data's licence", async () => {
    const wrapper = mount(DocumentMemOrigin, {
      props: { origin: { plan_iri: "https://lp-sachsen.org/resource/lehrplan-141-1", attribution: "MEM-Schule", licence: "https://creativecommons.org/licenses/by-sa/4.0/" } },
    });

    expect(wrapper.get("h2").text()).toBe(t("mem.origin.heading"));
    const link = wrapper.get("a");
    expect([link.attributes("href"), link.attributes("rel")]).toEqual(["https://lp-sachsen.org/resource/lehrplan-141-1", "noreferrer"]);
    expect(described(wrapper.element as HTMLElement, t("mem.origin.attribution"))).toBe("MEM-Schule");
    expect(described(wrapper.element as HTMLElement, t("mem.origin.licence"))).toBe("https://creativecommons.org/licenses/by-sa/4.0/");
    expect(wrapper.text()).toContain(t("mem.origin.rightsNote"));
    expect(await violations(wrapper.html())).toEqual([]);
  });

  it("says a licence is not named while none is checked, and links no plan that is no web address", () => {
    const wrapper = mount(DocumentMemOrigin, {
      props: { origin: { plan_iri: "urn:x:1", attribution: null, licence: null } },
    });

    expect(wrapper.find("a").exists()).toBe(false);
    expect(wrapper.text()).toContain("urn:x:1");
    expect(described(wrapper.element as HTMLElement, t("mem.origin.licence"))).toBe(t("mem.origin.licenceNone"));
    expect(described(wrapper.element as HTMLElement, t("mem.origin.attribution"))).toBe(t("mem.origin.attributionNone"));
  });
});
