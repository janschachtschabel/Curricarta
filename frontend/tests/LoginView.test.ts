import { readFileSync } from "node:fs";
import { join } from "node:path";

import { flushPromises, mount } from "@vue/test-utils";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import * as api from "@/api";
import { isolate } from "@/bidi";
import { t } from "@/i18n/de";
import { router } from "@/router";
import { clearSession, session, setSession } from "@/session";
import LoginView from "@/views/LoginView.vue";

import { SRC, cssRules, stylesOf } from "./sources";

const TOKEN = "curricarta_" + "t".repeat(43);
const ME: api.Me = { id: "0190-a", name: "Lehrkraft", roles: ["nutzer"] };

async function signIn(typed: string, query: Record<string, string> = {}) {
  await router.push({ name: "login", query });
  const wrapper = mount(LoginView, { global: { plugins: [router] }, attachTo: document.body });
  await wrapper.get("input").setValue(typed);
  await wrapper.get("form").trigger("submit");
  await flushPromises();
  return wrapper;
}

beforeEach(async () => {
  vi.restoreAllMocks();
  api.clearToken();
  clearSession();
  await router.push("/");
});

afterEach(() => {
  document.body.innerHTML = "";
});

describe("signing in", () => {
  it("asks for a token before it asks the server", async () => {
    const check = vi.spyOn(api, "checkToken");

    const wrapper = await signIn("   ");

    expect(wrapper.get("#login-error").text()).toContain(t("login.errors.empty"));
    expect(check).not.toHaveBeenCalled();
  });

  it("says a refused token is not valid, beside the field, and keeps nothing", async () => {
    vi.spyOn(api, "checkToken").mockResolvedValue(null);

    const wrapper = await signIn(TOKEN);

    const field = wrapper.get("input");
    expect(wrapper.get("#login-error").text()).toContain(t("login.errors.invalid"));
    expect(field.attributes("aria-invalid")).toBe("true");
    expect(field.attributes("aria-describedby")).toBe("login-error");
    expect(api.getToken()).toBeNull();
  });

  it("keeps a good token and its account, and goes to the start", async () => {
    const check = vi.spyOn(api, "checkToken").mockResolvedValue(ME);
    const push = vi.spyOn(router, "push");

    await signIn(`  ${TOKEN} `);

    expect(check).toHaveBeenCalledWith(TOKEN);
    expect(api.getToken()).toBe(TOKEN);
    expect(session.value).toEqual(ME);
    expect(push).toHaveBeenLastCalledWith({ name: "start" });
  });

  it("goes back where the visitor was going, if that is a page of this app", async () => {
    vi.spyOn(api, "checkToken").mockResolvedValue(ME);
    const push = vi.spyOn(router, "push");

    await signIn(TOKEN, { ziel: "/konto?x=1" });
    expect(push).toHaveBeenLastCalledWith("/konto?x=1");

    await signIn(TOKEN, { ziel: "//evil.example/" });
    expect(push).toHaveBeenLastCalledWith({ name: "start" });
  });

  it("says how long to wait after too many failures, in minutes", async () => {
    vi.spyOn(api, "checkToken").mockRejectedValue(new api.ApiError("server", 429, "too_many_requests", "x", {}, 900));

    const wrapper = await signIn(TOKEN);

    expect(wrapper.get("#login-error").text()).toContain(t("login.errors.locked", { count: 15 }));
  });

  it("says to try later where the wait is not named", async () => {
    vi.spyOn(api, "checkToken").mockRejectedValue(new api.ApiError("server", 429, "too_many_requests"));

    const wrapper = await signIn(TOKEN);

    expect(wrapper.get("#login-error").text()).toContain(t("login.errors.lockedLater"));
  });

  it("tells a lost connection from a server that failed", async () => {
    vi.spyOn(api, "checkToken").mockRejectedValueOnce(new api.ApiError("network", 0));
    const offline = await signIn(TOKEN);
    expect(offline.get("#login-error").text()).toContain(t("login.errors.network"));

    vi.spyOn(api, "checkToken").mockRejectedValueOnce(new api.ApiError("server", 500, "internal_server_error"));
    const failed = await signIn(TOKEN);
    expect(failed.get("#login-error").text()).toContain(t("login.errors.server"));
  });

  it("shows that it is checking", async () => {
    let answer: (me: api.Me | null) => void = () => undefined;
    vi.spyOn(api, "checkToken").mockReturnValue(new Promise((resolve) => (answer = resolve)));
    await router.push({ name: "login" });
    const wrapper = mount(LoginView, { global: { plugins: [router] } });
    await wrapper.get("input").setValue(TOKEN);

    await wrapper.get("form").trigger("submit");

    const button = wrapper.get("button[type=submit]");
    expect(button.text()).toBe(t("login.checking"));
    answer(null);
    await flushPromises();
    expect(button.text()).toBe(t("login.submit"));
  });
});

// unlike every other form, an empty press left the keyboard on the button, the error an alert the field then read
// again, and the centred card jumped (browser check 2, NIT 10)
describe("a refusal of what was typed", () => {
  async function pressed(typed: string) {
    await router.push({ name: "login" });
    const wrapper = mount(LoginView, { global: { plugins: [router] }, attachTo: document.body });
    await wrapper.get("input").setValue(typed);
    (wrapper.get("button[type=submit]").element as HTMLElement).focus();
    await wrapper.get("form").trigger("submit");
    await flushPromises();
    return wrapper;
  }

  it("takes the keyboard from the button to the field, which reads the error once", async () => {
    const wrapper = await pressed("");

    expect(document.activeElement).toBe(wrapper.get("input").element);
    expect(wrapper.get("input").attributes("aria-describedby")).toBe("login-error");
    expect(wrapper.get("#login-error").text()).toContain(t("login.errors.empty"));
    expect(wrapper.find("[role=alert]").exists()).toBe(false);
    expect(wrapper.get("[data-test=login-status]").text()).toBe("");
  });

  it("says it in the form's status where the keyboard stays in the field", async () => {
    await router.push({ name: "login" });
    const wrapper = mount(LoginView, { global: { plugins: [router] }, attachTo: document.body });
    (wrapper.get("input").element as HTMLElement).focus();
    await wrapper.get("form").trigger("submit");
    await flushPromises();

    expect(document.activeElement).toBe(wrapper.get("input").element);
    const status = wrapper.get("[data-test=login-status]");
    expect(status.attributes("role")).toBe("status");
    expect(status.text()).toBe(t("forms.fieldProblem", { field: t("login.tokenLabel"), problem: t("login.errors.empty") }));
  });

  it("leaves the keyboard on the button where the server failed, and says so in the status", async () => {
    vi.spyOn(api, "checkToken").mockRejectedValue(new api.ApiError("network", 0));
    const wrapper = await pressed(TOKEN);

    expect(document.activeElement).toBe(wrapper.get("button[type=submit]").element);
    expect(wrapper.get("[data-test=login-status]").text()).toBe(t("login.errors.network"));
  });

  it("keeps the card where it was: anchored at its top, not centred", () => {
    const rule = cssRules(stylesOf(readFileSync(join(SRC, "views", "LoginView.vue"), "utf8"))).find(({ selectors }) =>
      selectors.includes(".login"),
    );
    expect(rule?.body).toMatch(/align-items:\s*start/);
    expect(rule?.body).not.toMatch(/place-items:\s*center/);
  });
});

describe("the token's form", () => {
  it.each([["curricarta_" + "t".repeat(42)], ["curricarta_" + "t".repeat(42) + String.fromCodePoint(0x2013)], ["mein-token"]])(
    "is checked before anything is sent: %s",
    async (typed) => {
      // a typo would cost a failed sign-in against the address's limit, shared behind a school's NAT
      const check = vi.spyOn(api, "checkToken");

      const wrapper = await signIn(typed);

      expect(wrapper.get("#login-error").text()).toContain(t("login.errors.malformed"));
      expect(check).not.toHaveBeenCalled();
    },
  );
});

describe("the button while the token is checked", () => {
  it("stays focusable, says it is busy, and takes no second press", async () => {
    // disabled, it would drop the focus it holds, and the keyboard would land on main
    let answer: (me: api.Me | null) => void = () => undefined;
    const check = vi.spyOn(api, "checkToken").mockReturnValue(new Promise((resolve) => (answer = resolve)));
    await router.push({ name: "login" });
    const wrapper = mount(LoginView, { global: { plugins: [router] } });
    await wrapper.get("input").setValue(TOKEN);

    await wrapper.get("form").trigger("submit");
    await wrapper.get("form").trigger("submit");

    const button = wrapper.get("button[type=submit]");
    expect(button.attributes("disabled")).toBeUndefined();
    expect(button.attributes("aria-disabled")).toBe("true");
    expect(check).toHaveBeenCalledTimes(1);
    answer(null);
    await flushPromises();
  });
});

describe("the same refusal twice", () => {
  it("changes what the alert holds, so it is read out again", async () => {
    vi.spyOn(api, "checkToken").mockResolvedValue(null);
    const wrapper = await signIn(TOKEN);
    const first = wrapper.get("#login-error").element.textContent;

    await wrapper.get("form").trigger("submit");
    await flushPromises();

    expect(wrapper.get("#login-error").element.textContent).not.toBe(first);
    expect(wrapper.get("#login-error").text()).toContain(t("login.errors.invalid"));
  });
});

// the sign-in showed its form to a signed-in account as to a visitor (UI review, NIT)
describe("the sign-in for an account signed in already", () => {
  it("says who is signed in and leads to the start, the form there for another account", async () => {
    setSession({ id: "0190-a", name: "Erste Redaktion", roles: ["redaktion"] });
    const wrapper = mount(LoginView, { global: { plugins: [router] } });
    await flushPromises();

    const note = wrapper.get("[data-test=signed-in]");
    expect(note.text()).toContain(t("login.signedIn", { name: isolate("Erste Redaktion") }));
    expect(note.get("a").attributes("href")).toBe("/");
    expect(wrapper.find("form").exists()).toBe(true);
  });

  it("says nothing of it to a visitor", async () => {
    const wrapper = mount(LoginView, { global: { plugins: [router] } });
    await flushPromises();

    expect(wrapper.find("[data-test=signed-in]").exists()).toBe(false);
  });
});
