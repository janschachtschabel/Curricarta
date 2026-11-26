import { flushPromises, mount, type VueWrapper } from "@vue/test-utils";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import * as api from "@/api";
import { ApiError } from "@/api";
import DocumentScope from "@/components/DocumentScope.vue";
import { t } from "@/i18n/de";

import { violations } from "./axe";
import { SCOPE_FORM, specificationOf, specificationsOf, valuedSpecification } from "./scopeFixtures";

let shown: VueWrapper | null = null;

async function open(): Promise<VueWrapper> {
  shown = mount(DocumentScope, { props: { documentId: "d1", sector: "school" }, attachTo: document.body });
  await flushPromises();
  return shown;
}

const field = (wrapper: VueWrapper, label: string) => {
  const found = wrapper.findAll("label").find((one) => one.text() === label);
  if (!found) throw new Error(label);
  return wrapper.get<HTMLInputElement>(`#${found.attributes("for")}`);
};
const title = (wrapper: VueWrapper) => field(wrapper, t("documents.page.scope.title"));
const fieldText = (wrapper: VueWrapper) => field(wrapper, t("documents.page.scope.fieldText"));

beforeEach(() => {
  vi.restoreAllMocks();
  vi.spyOn(api, "getSpecifications").mockResolvedValue(specificationsOf());
  vi.spyOn(api, "getForm").mockResolvedValue(SCOPE_FORM);
});

afterEach(() => {
  shown?.unmount();
  shown = null;
  document.body.innerHTML = "";
});

describe("a document's applicability on its page", () => {
  it("names each specification's kind, title, field, variants, values and contexts in words", async () => {
    vi.mocked(api.getSpecifications).mockResolvedValue(specificationsOf({ specifications: [valuedSpecification()] }));
    const wrapper = await open();

    const text = wrapper.get("section").text();
    expect(wrapper.get("h2").text()).toBe(t("documents.page.scope.heading"));
    expect(wrapper.get("h3").text()).toBe("Physik");
    for (const said of ["Lehrplan", "Naturwissenschaften", "G8", "EQR 4 (Vorgeschlagen)", "80 Unterrichtsstunden insgesamt (Vorgeschlagen)"]) {
      expect(text).toContain(said);
    }
    const [context] = wrapper.findAll("[data-test=scope-context]");
    expect(context.text()).toBe("Vorgeschlagen Schulbildung · formal · Einrichtung: Gymnasium · Jahrgangsstufe 5–6 (Vorgeschlagen)");
    expect(await violations(wrapper.element)).toEqual([]);
  });

  it("says a rejected context as rejected, by its word beside its tone", async () => {
    const valued = valuedSpecification();
    const [context] = valued.contexts;
    const rejected = { ...valued, contexts: [{ ...context, review_status: "https://w3id.org/wlo/curriculum/vocab#rev_rejected" }] };
    vi.mocked(api.getSpecifications).mockResolvedValue(specificationsOf({ specifications: [rejected] }));
    const wrapper = await open();

    const badge = wrapper.get("[data-test=scope-context] .status-badge");
    expect(badge.text()).toBe("Verworfen");
    expect(badge.classes()).toContain("error");
  });

  it("says what is not there: no field, no values, no context", async () => {
    const wrapper = await open();

    const text = wrapper.get("section").text();
    expect(text).toContain(t("documents.page.scope.none"));
    expect(text).toContain(t("documents.page.scope.noValues"));
    expect(text).toContain(t("documents.page.scope.noContexts"));
  });

  it("says that a document has no specification yet", async () => {
    vi.mocked(api.getSpecifications).mockResolvedValue(specificationsOf({ specifications: [] }));
    const wrapper = await open();

    expect(wrapper.text()).toContain(t("documents.page.scope.noneTitle"));
    expect(wrapper.find("form").exists()).toBe(false);
  });

  it("shows it loading, then a failure with a retry that reads again", async () => {
    vi.mocked(api.getSpecifications).mockRejectedValueOnce(new ApiError("server", 500, "internal", "boom"));
    shown = mount(DocumentScope, { props: { documentId: "d1", sector: "school" }, attachTo: document.body });
    expect(shown.text()).toContain(t("documents.page.scope.loading"));
    await flushPromises();

    expect(shown.get("[role=alert]").text()).toContain(t("documents.page.scope.loadFailed"));
    await shown.get("[role=alert] button").trigger("click");
    await flushPromises();
    expect(shown.find("[role=alert]").exists()).toBe(false);
    expect(shown.get("h3").text()).toBe("Physik");
  });

  it("names its values without their lists' labels where the form did not come", async () => {
    vi.mocked(api.getForm).mockRejectedValue(new ApiError("server", 500, "internal", "boom"));
    vi.mocked(api.getSpecifications).mockResolvedValue(specificationsOf({ specifications: [valuedSpecification()] }));
    const wrapper = await open();

    expect(wrapper.get("[data-test=scope-context]").text()).toContain("sec_school");
  });

  it("is only to be read where the document is closed or not the caller's to change, and says why", async () => {
    vi.mocked(api.getSpecifications).mockResolvedValue(specificationsOf({ editable: false, closed: "frozen" }));
    const frozen = await open();

    expect(frozen.find("form").exists()).toBe(false);
    expect(frozen.text()).toContain(t("documents.page.scope.closed.frozen"));
    frozen.unmount();
    vi.mocked(api.getSpecifications).mockResolvedValue(specificationsOf({ editable: false }));
    const stranger = await open();
    expect(stranger.text()).toContain(t("documents.page.scope.readOnly"));
  });
});

describe("the title and field of a specification", () => {
  it("says the title is required, and names the specification each of its buttons saves", async () => {
    vi.mocked(api.getSpecifications).mockResolvedValue(
      specificationsOf({ specifications: [specificationOf(), specificationOf({ id: "s2", key: "ch", title: "Chemie" })] }),
    );
    const wrapper = await open();

    const input = title(wrapper);
    expect(input.attributes("aria-required")).toBe("true");
    expect(wrapper.get(`#${input.attributes("id")}-hint`).text()).toMatch(/^Pflichtfeld./);
    expect(fieldText(wrapper).attributes("aria-required")).toBeUndefined();
    const names = wrapper.findAll("form button[type=submit]").map((button) => button.attributes("aria-label"));
    // its title and field's, and its values'
    expect(names).toEqual([
      t("documents.page.scope.saveNamed", { title: "Physik" }),
      t("documents.page.scope.valuesSaveNamed", { title: "Physik" }),
      t("documents.page.scope.saveNamed", { title: "Chemie" }),
      t("documents.page.scope.valuesSaveNamed", { title: "Chemie" }),
    ]);
    expect(await violations(wrapper.element)).toEqual([]);
  });

  it("sends only what changed, on the revision read, and shows what was saved", async () => {
    const saved = specificationOf({ field_text: "Naturwissenschaften", revision: 2 });
    vi.spyOn(api, "editSpecification").mockResolvedValue(saved);
    const wrapper = await open();

    await fieldText(wrapper).setValue("Naturwissenschaften");
    await wrapper.get("form").trigger("submit");
    await flushPromises();

    expect(api.editSpecification).toHaveBeenCalledWith("s1", 1, { field_text: "Naturwissenschaften" });
    expect(wrapper.get("form [role=status]").text()).toBe(t("documents.page.scope.saved"));
    expect(wrapper.get("section").text()).toContain("Naturwissenschaften");
  });

  it("sends nothing where nothing changed, and an emptied field as none", async () => {
    vi.mocked(api.getSpecifications).mockResolvedValue(specificationsOf({ specifications: [valuedSpecification()] }));
    vi.spyOn(api, "editSpecification").mockResolvedValue(specificationOf({ revision: 2 }));
    const wrapper = await open();

    await wrapper.get("form").trigger("submit");
    expect(api.editSpecification).not.toHaveBeenCalled();
    expect(wrapper.get("form [role=status]").text()).toBe(t("documents.page.scope.unchanged"));
    await fieldText(wrapper).setValue("  ");
    await wrapper.get("form").trigger("submit");
    await flushPromises();
    expect(api.editSpecification).toHaveBeenCalledWith("s1", 1, { field_text: null });
  });

  it("puts a field's problem at the field and takes the keyboard there, the entry kept", async () => {
    vi.spyOn(api, "editSpecification").mockRejectedValue(
      new ApiError("server", 422, "invalid_field", "no", { field: "title", problem: "required" }),
    );
    const wrapper = await open();
    await title(wrapper).setValue(" ");
    const submit = wrapper.get("form button[type=submit]");
    (submit.element as HTMLElement).focus();

    await wrapper.get("form").trigger("submit");
    await flushPromises();

    const input = title(wrapper);
    expect(input.attributes("aria-invalid")).toBe("true");
    expect(wrapper.get(`#${input.attributes("id")}-error`).text()).toContain(t("documents.tree.problems.required"));
    expect(document.activeElement).toBe(input.element);
    expect(input.element.value).toBe(" ");
  });

  it("shows the specification as it stands where it was changed meanwhile, and says so", async () => {
    const current = specificationOf({ title: "Chemie", revision: 3 });
    vi.spyOn(api, "editSpecification").mockRejectedValue(
      new ApiError("server", 409, "stale_revision", "stale", { current }),
    );
    const wrapper = await open();
    await fieldText(wrapper).setValue("Naturwissenschaften");

    await wrapper.get("form").trigger("submit");
    await flushPromises();

    expect(wrapper.get("h3").text()).toBe("Chemie");
    expect(wrapper.get("form [role=alert]").text()).toContain(t("documents.page.scope.changedMeanwhile"));
    expect(fieldText(wrapper).element.value).toBe("Naturwissenschaften"); // the entry stays
  });

  it("reads the section again where the document was closed meanwhile", async () => {
    vi.spyOn(api, "editSpecification").mockRejectedValue(new ApiError("server", 409, "frozen", "frozen"));
    const wrapper = await open();
    vi.mocked(api.getSpecifications).mockResolvedValue(specificationsOf({ editable: false, closed: "frozen" }));
    await title(wrapper).setValue("Chemie");

    await wrapper.get("form").trigger("submit");
    await flushPromises();

    expect(api.getSpecifications).toHaveBeenCalledTimes(2);
    expect(wrapper.find("form").exists()).toBe(false);
    expect(wrapper.text()).toContain(t("documents.page.scope.closed.frozen"));
  });
});
