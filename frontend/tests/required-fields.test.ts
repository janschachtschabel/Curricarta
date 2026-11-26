import { mount } from "@vue/test-utils";
import { describe, expect, it } from "vitest";

import ExtractionStart from "@/components/ExtractionStart.vue";
import FormFieldInput from "@/components/FormFieldInput.vue";
import ImportForm from "@/components/ImportForm.vue";
import RuleForm from "@/components/RuleForm.vue";
import RuleNew from "@/components/RuleNew.vue";
import UploadForm from "@/components/UploadForm.vue";
import { messages } from "@/i18n/de";
import { router } from "@/router";
import LoginView from "@/views/LoginView.vue";

import { ruleOf, rulesOf } from "./ruleFixtures";
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

  it("of a rule is its kind and wording, a new rule's its page too; its values and links are free", () => {
    const rules = rulesOf();
    for (const wrapper of [mount(RuleForm, { props: { rule: ruleOf(), rules } }), mount(RuleNew, { props: { documentId: "d1" } })]) {
      const required = wrapper.findAll("[aria-required=true]").map((control) => wrapper.get(`label[for=${control.attributes("id")}]`).text());
      const free = wrapper.findAll("input[type=text]:not([aria-required]), select:not([aria-required])");
      expect(required.every((label) => /\(Pflichtfeld\)$/.test(label)), required.join()).toBe(true);
      expect(free.every((control) => !/\(Pflichtfeld\)/.test(wrapper.get(`label[for=${control.attributes("id")}]`).text()))).toBe(true);
      expect(required.length).toBe(wrapper.findComponent(RuleNew).exists() ? 3 : 2);
      wrapper.unmount();
    }
  });

  it("of an applicability context is none: every field of the context's form is free", () => {
    for (const field of form_().context.fields) {
      const wrapper = mount(FormFieldInput, {
        props: { field, values: field.values ?? [], modelValue: "", labels: messages.documents.tree.values.fields },
      });
      expect(wrapper.get("input, select").attributes("aria-required"), field.key).toBeUndefined();
      expect(wrapper.get("label").text(), field.key).not.toMatch(/\(|freiwillig/);
      wrapper.unmount();
    }
  });

  it("of a value's form is said to be required, one the form leaves free is not, a yes or no never", () => {
    const fields = form_().values.workloads.fields;
    for (const [key, expected] of [
      ["amount", "true"],
      ["unit", "true"],
      ["amount_to", undefined],
      ["workload_kind", undefined],
    ] as const) {
      const field = fields.find((one) => one.key === key);
      if (!field) throw new Error(key);
      const wrapper = mount(FormFieldInput, {
        props: { field, values: field.values ?? [], modelValue: "", labels: messages.documents.tree.values.fields },
      });
      expect(wrapper.get("input, select").attributes("aria-required"), key).toBe(expected);
      expect(wrapper.get("label").text().endsWith("(Pflichtfeld)"), key).toBe(expected === "true");
      wrapper.unmount();
    }
    const flag = fields.find((one) => one.key === "total");
    if (!flag) throw new Error("total");
    const box = mount(FormFieldInput, { props: { field: flag, values: [], modelValue: false, labels: messages.documents.tree.values.fields } });
    expect(box.get("input[type=checkbox]").attributes("aria-required")).toBeUndefined();
    box.unmount();
  });
});

