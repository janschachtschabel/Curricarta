import { readFileSync } from "node:fs";
import { join } from "node:path";

import { flushPromises, mount } from "@vue/test-utils";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import * as api from "@/api";
import App from "@/App.vue";
import { t } from "@/i18n/de";
import { router } from "@/router";
import { clearSession, session, setSession } from "@/session";

import { detail, page } from "./registerEntries";
import { SRC, cssRules, stylesOf } from "./sources";

async function render(path = "/") {
  await router.push(path);
  const wrapper = mount(App, { global: { plugins: [router] }, attachTo: document.body });
  await flushPromises();
  return wrapper;
}

beforeEach(() => {
  vi.restoreAllMocks();
  api.clearToken();
  clearSession();
  vi.spyOn(api, "getInfo").mockResolvedValue({ name: "Curricarta", version: "0.1.0", public_access: "off", max_upload_mb: 50 });
});

afterEach(() => {
  document.body.innerHTML = "";
});

describe("the shell for a visitor", () => {
  it("has one main region, a skip link to it, and the way to sign in", async () => {
    const wrapper = await render();

    expect(wrapper.findAll("main")).toHaveLength(1);
    expect(wrapper.get("a.skip-link").attributes("href")).toBe("#main");
    expect(wrapper.find("nav").exists()).toBe(false);
    expect(wrapper.get("header a[href='/anmelden']").text()).toBe(t("app.signIn"));
  });

  it("offers no second way to sign in on the sign-in page itself", async () => {
    const wrapper = await render("/anmelden");

    expect(wrapper.find("header a[href='/anmelden']").exists()).toBe(false);
  });
});

describe("the shell for an account", () => {
  beforeEach(() => {
    api.setToken("curricarta_token");
    setSession({ id: "0190-a", name: "Erste Admin", roles: ["admin", "redaktion"] });
  });

  it("names its navigation and leads to what the roles open", async () => {
    const wrapper = await render();

    const nav = wrapper.get("nav");
    expect(nav.attributes("aria-label")).toBe(t("app.nav.label"));
    expect(nav.get("a[href='/']").text()).toBe(t("app.nav.start"));
  });

  it("marks where the reader is: the page itself, or the section an entry's page lies in", async () => {
    vi.spyOn(api, "listSources").mockResolvedValue(page([]));
    vi.spyOn(api, "getSource").mockResolvedValue(detail());
    const wrapper = await render("/quellen");
    const link = (href: string) => wrapper.get(`nav a[href='${href}']`);
    expect(link("/quellen").attributes("aria-current")).toBe("page");
    expect(link("/").attributes("aria-current")).toBeUndefined();

    await router.push("/quellen/s1");
    await flushPromises();
    expect(link("/quellen").attributes("aria-current")).toBe("true");
    expect(link("/").attributes("aria-current")).toBeUndefined();

    await router.push("/");
    await flushPromises();
    expect(link("/").attributes("aria-current")).toBe("page");
    expect(link("/quellen").attributes("aria-current")).toBeUndefined();
  });

  it("draws the mark by the state it says: what the eye sees, a screen reader hears", () => {
    const rules = cssRules(stylesOf(readFileSync(join(SRC, "App.vue"), "utf8")));

    const marked = rules.filter(({ selectors }) => selectors.includes(".shell__destination[aria-current]"));

    expect(marked.map(({ body }) => body).join("")).toMatch(/background:\s*var\(--accent-wash\)/);
  });

  it("says who is signed in, in which roles", async () => {
    const wrapper = await render();

    const account = wrapper.get(".shell__account").text();
    expect(account).toContain("Erste Admin");
    expect(account).toContain(t("app.roles.admin"));
    expect(account).toContain(t("app.roles.redaktion"));
  });

  it("signs out: forgets the token and the account, and goes to the sign-in", async () => {
    const wrapper = await render();
    const push = vi.spyOn(router, "push");

    await wrapper.get("button.shell__sign-out").trigger("click");
    await flushPromises();

    expect(api.getToken()).toBeNull();
    expect(session.value).toBeNull();
    expect(push).toHaveBeenCalledWith({ name: "login" });
  });

  it("signs out once the sign-in is reached by the move made anew after a draft was asked about", async () => {
    const wrapper = await render();
    const stay = router.beforeEach(() => false); // asked about, a second move came: this one held
    await wrapper.get("button.shell__sign-out").trigger("click");
    await flushPromises();
    stay();
    expect(api.getToken()).not.toBeNull();

    await router.push({ name: "login" }); // the draft to go: the move made anew

    expect([api.getToken(), session.value]).toEqual([null, null]);
  });

  it("keeps the account where the user, asked, went on elsewhere", async () => {
    const wrapper = await render();
    const stay = router.beforeEach(() => false);
    await wrapper.get("button.shell__sign-out").trigger("click");
    await flushPromises();
    stay();

    await router.push({ name: "sources" });
    await router.push({ name: "login" }); // later, by another way: no sign-out pending any more

    expect(api.getToken()).not.toBeNull();
  });

  it("signs out on the sign-in page itself, where there is no page to leave", async () => {
    const wrapper = await render("/anmelden");

    await wrapper.get("button.shell__sign-out").trigger("click");
    await flushPromises();

    expect([api.getToken(), session.value]).toEqual([null, null]);
  });

  it("stays signed in where the page it would leave keeps the user, a draft asked about", async () => {
    const wrapper = await render();
    const stay = router.beforeEach(() => false); // the leave guard's answer: stay with the draft

    await wrapper.get("button.shell__sign-out").trigger("click");
    await flushPromises();
    stay();

    expect(api.getToken()).not.toBeNull();
    expect(session.value).not.toBeNull();
  });
});


describe("the shell while an account is held but not loaded", () => {
  // 23.3 px tall, passing 2.5.8 by spacing alone (browser check 2, NIT 9); jsdom lays nothing out
  it("draws its retry tall enough to hit", () => {
    const rules = cssRules(stylesOf(readFileSync(join(SRC, "App.vue"), "utf8")));
    const rule = rules.find(({ selectors }) => selectors.includes(".shell__who .btn.link"));
    expect(rule?.body).toMatch(/min-height:\s*24px/);
  });

  it("offers no sign-in, as if nobody were signed in", async () => {
    api.setToken("curricarta_token");
    vi.spyOn(api, "getMe").mockReturnValue(new Promise(() => undefined));

    const wrapper = await render();

    expect(wrapper.find("header a[href='/anmelden']").exists()).toBe(false);
  });

  it("offers the way out once the account cannot be loaded: a stale token is no dead end", async () => {
    api.setToken("curricarta_token");
    vi.spyOn(api, "getMe").mockRejectedValue(new api.ApiError("server", 429, "too_many_requests", "Too many failed sign-ins; try again later.", {}, 900));
    const wrapper = await render();
    const push = vi.spyOn(router, "push");

    await wrapper.get("header button.shell__sign-out").trigger("click");
    await flushPromises();

    expect(api.getToken()).toBeNull();
    expect(push).toHaveBeenCalledWith({ name: "login" });
  });

  // one failed /me took the navigation away until a reload (UI review m1)
  const ME = { id: "0190-a", name: "Erste Redaktion", roles: ["redaktion"] as api.Role[] };
  const destinations = (wrapper: Awaited<ReturnType<typeof render>>) =>
    wrapper.findAll("nav a").map((link) => link.attributes("href"));

  it("keeps the destinations open to every account while the account cannot be loaded, and says so", async () => {
    api.setToken("curricarta_token");
    vi.spyOn(api, "getMe").mockRejectedValue(new api.ApiError("network", 0));
    vi.spyOn(api, "listSources").mockResolvedValue(page([]));

    const wrapper = await render("/quellen");

    expect(wrapper.get("nav").attributes("aria-label")).toBe(t("app.nav.label"));
    expect(destinations(wrapper)).toEqual(["/", "/quellen"]);
    expect(wrapper.get("[data-test=account-failed]").text()).toContain(t("app.accountFailed"));
  });

  it("loads the account again on the reader's word, the destinations of its roles with it", async () => {
    api.setToken("curricarta_token");
    vi.spyOn(api, "getMe").mockRejectedValueOnce(new api.ApiError("network", 0)).mockResolvedValue(ME);
    vi.spyOn(api, "listSources").mockResolvedValue(page([]));
    const wrapper = await render("/quellen");

    await wrapper.get("[data-test=account-retry]").trigger("click");
    await flushPromises();

    expect(destinations(wrapper)).toEqual(["/", "/quellen", "/lexikon"]);
    expect(wrapper.get(".shell__account").text()).toContain("Erste Redaktion");
    expect(wrapper.find("[data-test=account-failed]").exists()).toBe(false);
  });

  // the notice, its button and "Abmelden" went for the whole request, the keyboard with them (UI review 1, finding 3)
  it("keeps the notice, its button and the way out while it asks again, and says how it went", async () => {
    api.setToken("curricarta_token");
    let answer: (me: typeof ME) => void = () => undefined;
    let refuse: (error: unknown) => void = () => undefined;
    vi.spyOn(api, "getMe")
      .mockRejectedValueOnce(new api.ApiError("network", 0))
      .mockReturnValueOnce(new Promise((_resolve, reject) => (refuse = reject)))
      .mockReturnValueOnce(new Promise((resolve) => (answer = resolve)));
    vi.spyOn(api, "listSources").mockResolvedValue(page([]));
    const wrapper = await render("/quellen");
    const status = wrapper.get("[data-test=account-status]");
    expect(status.attributes("role")).toBe("status");

    const retry = wrapper.get("[data-test=account-retry]");
    (retry.element as HTMLElement).focus();
    await retry.trigger("click");
    await flushPromises();
    // asking: all there, the keyboard where it was, a second press not a second question
    expect(wrapper.find("[data-test=account-failed]").exists()).toBe(true);
    expect(document.activeElement).toBe(retry.element);
    expect(retry.attributes("aria-disabled")).toBe("true");
    expect(wrapper.find(".shell__sign-out").exists()).toBe(true);
    await retry.trigger("click");
    expect(api.getMe).toHaveBeenCalledTimes(2);

    refuse(new api.ApiError("network", 0));
    await flushPromises();
    expect(status.text()).toBe(t("app.accountFailed"));
    expect(document.activeElement).toBe(retry.element);
    expect(retry.attributes("aria-disabled")).toBeUndefined();

    await retry.trigger("click");
    answer(ME);
    await flushPromises();
    expect(status.text()).toBe(t("app.accountLoaded"));
    expect(wrapper.find("[data-test=account-failed]").exists()).toBe(false);
  });

  it("leaves saying it to the start, which says it with its own retry", async () => {
    api.setToken("curricarta_token");
    vi.spyOn(api, "getMe").mockRejectedValue(new api.ApiError("network", 0));

    const wrapper = await render();

    expect(wrapper.find("[data-test=account-failed]").exists()).toBe(false);
    expect(wrapper.text()).toContain(t("start.accountFailed"));
  });

  it("loads the account again on the next move to another page", async () => {
    api.setToken("curricarta_token");
    const me = vi.spyOn(api, "getMe").mockRejectedValueOnce(new api.ApiError("network", 0)).mockResolvedValue(ME);
    vi.spyOn(api, "listSources").mockResolvedValue(page([]));
    const wrapper = await render();

    await router.push("/quellen");
    await flushPromises();

    expect(me).toHaveBeenCalledTimes(2);
    expect(wrapper.get(".shell__account").text()).toContain("Erste Redaktion");
  });
});
