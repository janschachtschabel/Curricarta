<script setup lang="ts">
import { nextTick, ref } from "vue";
import { RouterLink, useRoute, useRouter } from "vue-router";

import { ApiError, checkToken, looksLikeToken, setToken } from "@/api";
import { isolate } from "@/bidi";
import AppIcon from "@/components/AppIcon.vue";
import { focusIsFree } from "@/focusRescue";
import { requiredLabel } from "@/formWords";
import { t } from "@/i18n/de";
import { sayAnew } from "@/liveRegion";
import { RETURN_PARAM, returnTarget } from "@/returnTarget";
import { session, setSession } from "@/session";

const router = useRouter();
const route = useRoute();

const token = ref("");
const error = ref("");
// what the error says where the keyboard does not go to the field (fieldRefusal.ts has the same rule)
const status = ref("");
const checking = ref(false);
const submit = ref<HTMLElement | null>(null);
const field = ref<HTMLElement | null>(null);

/** Why the token could not be checked. Past too many failures the server answers 429 with the wait. */
function signInFailure(failure: unknown): string {
  if (!(failure instanceof ApiError)) return t("login.errors.server");
  if (failure.kind === "network") return t("login.errors.network");
  if (failure.status !== 429) return t("login.errors.server");
  return failure.retryAfter === undefined
    ? t("login.errors.lockedLater")
    : t("login.errors.locked", { count: Math.max(1, Math.ceil(failure.retryAfter / 60)) });
}

/** The refusal to show; the same one again is read out again (liveRegion.ts). One of what was typed (`atField`)
 * takes the keyboard to the field from the button or from nothing, as in every other form, and the field reads
 * it; resting elsewhere, or where the server failed, the status says it - read once either way. */
async function refuse(message: string, atField = true): Promise<void> {
  error.value = sayAnew(error.value, message);
  status.value = "";
  await nextTick();
  if (atField && (document.activeElement === submit.value || focusIsFree())) field.value?.focus();
  else {
    const words = atField ? t("forms.fieldProblem", { field: t("login.tokenLabel"), problem: message }) : message;
    status.value = sayAnew(status.value, words);
  }
}

async function onSubmit(): Promise<void> {
  if (checking.value) return; // the button stays focusable while busy, so it can be pressed again
  const candidate = token.value.trim();
  if (!candidate) return refuse(t("login.errors.empty"));
  // a typo is said here: sent, it would count against the address's failure limit
  if (!looksLikeToken(candidate)) return refuse(t("login.errors.malformed"));

  checking.value = true;
  try {
    const me = await checkToken(candidate);
    if (!me) return refuse(t("login.errors.invalid"));
    error.value = "";
    setToken(candidate);
    // the check answered with the account: the shell needs not ask again
    setSession(me);
    await router.push(returnTarget(route.query[RETURN_PARAM]) ?? { name: "start" });
  } catch (failure) {
    await refuse(signInFailure(failure), false);
  } finally {
    checking.value = false;
  }
}
</script>

<template>
  <!-- A `div`, not a `main`: App.vue renders the page's one main region around
       the router view, and a second one would give the skip link two targets. -->
  <div class="login">
    <section class="login__card card" aria-labelledby="login-heading">
      <h1 id="login-heading" class="login__heading">{{ t("login.heading") }}</h1>
      <p class="login__intro">{{ t("login.intro") }}</p>
      <!-- reached while signed in: who that is, and the way on; the form stays for another account -->
      <p v-if="session" class="login__intro" data-test="signed-in">
        {{ t("login.signedIn", { name: isolate(session.name) }) }}
        <RouterLink :to="{ name: 'start' }">{{ t("login.toStart") }}</RouterLink>
      </p>

      <form class="login__form" novalidate @submit.prevent="onSubmit">
        <div class="field">
          <label for="token">{{ requiredLabel(t("login.tokenLabel")) }}</label>
          <!-- autocomplete off: on a school's shared computers no password manager is to offer
               the token to the next person; pasting it stays possible (WCAG 3.3.8) -->
          <input
            id="token"
            ref="field"
            aria-required="true"
            v-model="token"
            type="password"
            autocomplete="off"
            spellcheck="false"
            :aria-invalid="error ? true : undefined"
            :aria-describedby="error ? 'login-error' : undefined"
          />
        </div>

        <p v-if="error" id="login-error" class="field__error login__error">
          <AppIcon name="warning" /> {{ error }}
        </p>

        <!-- aria-disabled, not disabled: a disabled button drops the focus it holds -->
        <button ref="submit" type="submit" class="btn primary login__submit" :aria-disabled="checking || undefined">
          {{ checking ? t("login.checking") : t("login.submit") }}
        </button>
      </form>
      <!-- always in the page, so what it says is read -->
      <p class="visually-hidden" role="status" data-test="login-status">{{ status }}</p>
    </section>
  </div>
</template>

<style scoped>
/* Across the middle, a little down from the top rather than pinned to a corner: the form is four lines long.
   Anchored at its top, not centred, so an error line appearing under the field does not move the field. */
.login {
  display: grid;
  justify-items: center;
  align-items: start;
  padding: max(var(--space-3), 12vh) var(--space-3) var(--space-3);
}

.login__card {
  inline-size: 100%;
  max-inline-size: 26rem;
  margin: 0;
  padding: var(--space-3);
  box-shadow: var(--shadow-1);
}

.login__heading {
  font-size: var(--step-2);
}

.login__intro {
  margin: 0 0 var(--space-3);
  color: var(--text-muted);
  font-size: var(--step--1);
}

.login__form {
  display: flex;
  flex-direction: column;
  gap: var(--space-1);
}

.login__submit {
  /* The one action on the page: the full width of the card. */
  inline-size: 100%;
  min-height: 44px;
}

/* The icon repeats what the words say; neither is carried by colour alone. */
.login__error {
  display: flex;
  align-items: center;
  gap: var(--space-1);
}
</style>
