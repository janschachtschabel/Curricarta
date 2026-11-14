import { mount } from "@vue/test-utils";
import { describe, expect, it } from "vitest";

import ExtractionStart from "@/components/ExtractionStart.vue";
import FormFieldInput from "@/components/FormFieldInput.vue";
import ImportForm from "@/components/ImportForm.vue";
import UploadForm from "@/components/UploadForm.vue";
import { router } from "@/router";
import LoginView from "@/views/LoginView.vue";

import { form_ } from "./treeFixtures";

// No form said which of its fields it needs to assistive technology (UI review m6)
describe("a required field", () => {
  it.each([
    ["the upload's file", () => mount(UploadForm), "#upload-file", "#upload-title"],
    ["the import's address", () => mount(ImportForm), "#import-url", "#import-title"],
    ["the sign-in's token", () => mount(LoginView, { global: { plugins: [router] } }), "#token", null],
    [
      "the extraction's sector",
      () => mount(ExtractionStart, { props: { sourceId: "s1", conversionId: "c1", country: null }, global: { plugins: [router] } }),
      "#extraction-sector",
      null,
    ],
  ])("is said to be required: %s", (_what, render, required, optional) => {
    const wrapper = render();

    expect(wrapper.get(required).attributes("aria-required")).toBe("true");
    // one convention in every form: a required field says so in its label, a free one says nothing
    expect(wrapper.get(`label[for=${required.slice(1)}]`).text()).toMatch(/\(Pflichtfeld\)$/);
    if (optional) {
      expect(wrapper.get(optional).attributes("aria-required")).toBeUndefined();
      expect(wrapper.get(`label[for=${optional.slice(1)}]`).text()).not.toMatch(/\(|freiwillig/);
    }
    wrapper.unmount();
  });

  it("of a row's form is said to be required, one the form leaves free is not", () => {
    const fields = [...form_().node, ...form_().statement].filter((field) => !field.many);
    const required = fields.find((field) => field.required);
    const free = fields.find((field) => !field.required);
    expect(required && free, "the fixture holds both").toBeTruthy();

    for (const [field, expected] of [
      [required, "true"],
      [free, undefined],
    ] as const) {
      if (!field) continue;
      const wrapper = mount(FormFieldInput, { props: { field, values: field.values ?? [], modelValue: "" } });
      expect(wrapper.get("input, select, textarea").attributes("aria-required"), field.key).toBe(expected);
      wrapper.unmount();
    }
  });
});
