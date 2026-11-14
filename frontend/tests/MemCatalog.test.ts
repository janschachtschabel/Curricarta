import { flushPromises, mount, type VueWrapper } from "@vue/test-utils";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { defineComponent } from "vue";

import * as api from "@/api";
import { ApiError } from "@/api";
import MemCatalog from "@/components/MemCatalog.vue";
import { momentFormat, t } from "@/i18n/de";
import { clearSession, setSession } from "@/session";

import { violations } from "./axe";

// the job is followed by JobProgress, its own tests hold it; here it stands in, to end it at will
const Progress = defineComponent({
  name: "JobProgress",
  props: { jobId: { type: String, required: true }, label: { type: String, required: true } },
  emits: ["ended", "gone"],
  template: '<p data-test="job">{{ label }} {{ jobId }}</p>',
});

const DAY = 24 * 60 * 60 * 1000;
let shown: VueWrapper | null = null;

function mountCatalog(readAt: string | null): VueWrapper {
  shown = mount(MemCatalog, { props: { readAt }, attachTo: document.body, global: { stubs: { JobProgress: Progress } } });
  return shown;
}

function asAdmin(): void {
  setSession({ id: "a", name: "Admin", roles: ["admin"] });
}

function asEditor(): void {
  setSession({ id: "r", name: "Redaktion", roles: ["redaktion"] });
}

async function start(wrapper: VueWrapper): Promise<void> {
  await wrapper.get("[data-test=catalog-start]").trigger("click");
  await wrapper.get("[data-test=confirm]").trigger("click");
  await flushPromises();
}

beforeEach(() => {
  vi.restoreAllMocks();
});

afterEach(() => {
  shown?.unmount();
  shown = null;
  clearSession();
});

describe("MEM-Schule's catalogue on the import's section", () => {
  it("never read: the redaktion is told to ask the administration, and starts nothing", async () => {
    asEditor();
    const wrapper = mountCatalog(null);

    expect(wrapper.text()).toContain(t("mem.catalog.never"));
    expect(wrapper.find("[data-test=catalog-start]").exists()).toBe(false);
    expect(await violations(wrapper.html())).toEqual([]);
  });

  it("never read: an admin is offered to read it", () => {
    asAdmin();
    const wrapper = mountCatalog(null);

    expect(wrapper.text()).toContain(t("mem.catalog.neverAdmin"));
    expect(wrapper.get("[data-test=catalog-start]").text()).toBe(t("mem.catalog.start"));
  });

  it("says when it was last read, and an admin may read it again", async () => {
    asAdmin();
    const read = new Date(Date.now() - DAY).toISOString();
    const wrapper = mountCatalog(read);

    const time = wrapper.get("time");
    expect(time.attributes("datetime")).toBe(read);
    expect(time.text()).toBe(momentFormat.format(new Date(read)));
    expect(wrapper.find("[data-test=catalog-old]").exists()).toBe(false);
    expect(wrapper.get("[data-test=catalog-start]").text()).toBe(t("mem.catalog.restart"));
    expect(await violations(wrapper.html())).toEqual([]);
  });

  it("says a catalogue read more than thirty days ago is old, in words and not by colour alone", () => {
    asEditor();
    const wrapper = mountCatalog(new Date(Date.now() - 31 * DAY).toISOString());

    expect(wrapper.get("[data-test=catalog-old]").text()).toContain(t("mem.catalog.old"));
  });

  it("asks before it reads, as it asks MEM-Schule's server", async () => {
    asAdmin();
    const started = vi.spyOn(api, "startMemCatalog");
    const wrapper = mountCatalog(null);

    await wrapper.get("[data-test=catalog-start]").trigger("click");

    expect(wrapper.get("[role=dialog]").text()).toContain(t("mem.catalog.confirmTitle"));
    expect(started).not.toHaveBeenCalled();
  });

  it("follows the reading it started, and says when it is done", async () => {
    asAdmin();
    vi.spyOn(api, "startMemCatalog").mockResolvedValue({ job_id: "j1" });
    const wrapper = mountCatalog(null);

    await start(wrapper);
    expect(wrapper.get("[data-test=job]").text()).toBe(`${t("mem.catalog.jobLabel")} j1`);
    // JobProgress says the job's states: no second line beside it
    expect(wrapper.get(".catalog__status").text()).toBe("");

    wrapper.findComponent(Progress).vm.$emit("ended", { id: "j1", status: "done" });
    await flushPromises();
    expect(wrapper.emitted("read")).toHaveLength(1);
    // its own start line goes with the job: JobProgress says how it ended
    expect(wrapper.get(".catalog__status").text()).toBe("");
    expect(wrapper.get(".catalog__status").classes()).toContain("visually-hidden");
  });

  it("does not say the catalogue was read when its reading failed", async () => {
    asAdmin();
    vi.spyOn(api, "startMemCatalog").mockResolvedValue({ job_id: "j1" });
    const wrapper = mountCatalog(null);
    await start(wrapper);

    wrapper.findComponent(Progress).vm.$emit("ended", { id: "j1", status: "failed" });
    await flushPromises();

    expect(wrapper.emitted("read")).toBeUndefined();
    expect(wrapper.find("[data-test=job]").exists()).toBe(true); // it says why
  });

  it("follows a reading that waits or runs already rather than starting one", async () => {
    asAdmin();
    vi.spyOn(api, "startMemCatalog").mockRejectedValue(
      new ApiError("server", 409, "catalog_running", "running", { job_id: "j0" }),
    );
    const wrapper = mountCatalog(null);

    await start(wrapper);

    expect(wrapper.get("[data-test=job]").text()).toContain("j0");
    expect(wrapper.get(".catalog__status").text()).toBe(t("refusals.catalog_running"));
    expect(wrapper.find("[role=alert]").exists()).toBe(false);
  });

  it("says why it could not start", async () => {
    asAdmin();
    vi.spyOn(api, "startMemCatalog").mockRejectedValue(new ApiError("forbidden", 403, "forbidden", "no"));
    const wrapper = mountCatalog(null);

    await start(wrapper);

    expect(wrapper.get("[role=alert]").text()).toContain(t("mem.catalog.startFailed"));
    expect(wrapper.find("[data-test=job]").exists()).toBe(false);
    expect(await violations(wrapper.html())).toEqual([]);
  });
});
