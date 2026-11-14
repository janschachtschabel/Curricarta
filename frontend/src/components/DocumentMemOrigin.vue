<script setup lang="ts">
/**
 * Where an imported document came from (plan M2-8, B3): the MEM-Schule plan, linked where it is a web
 * address; its attribution and the data's licence as recorded at the import - none while no licence is
 * checked (E14). The wordings' rights are the register entry's, as the source section says.
 */
import type { MemOrigin } from "@/api";
import { t } from "@/i18n/de";
import { isWebAddress } from "@/readableAddress";

defineProps<{ origin: MemOrigin }>();
</script>

<template>
  <section aria-labelledby="document-mem">
    <h2 id="document-mem" tabindex="-1">{{ t("mem.origin.heading") }}</h2>
    <dl class="facts">
      <dt>{{ t("mem.origin.plan") }}</dt>
      <dd>
        <a v-if="isWebAddress(origin.plan_iri)" class="facts__address" :href="origin.plan_iri" rel="noreferrer">
          <bdi>{{ origin.plan_iri }}</bdi>
        </a>
        <bdi v-else class="facts__address">{{ origin.plan_iri }}</bdi>
      </dd>
      <dt>{{ t("mem.origin.attribution") }}</dt>
      <dd><bdi v-if="origin.attribution">{{ origin.attribution }}</bdi><template v-else>{{ t("mem.origin.attributionNone") }}</template></dd>
      <dt>{{ t("mem.origin.licence") }}</dt>
      <dd><bdi v-if="origin.licence">{{ origin.licence }}</bdi><template v-else>{{ t("mem.origin.licenceNone") }}</template></dd>
      <dt>{{ t("mem.origin.rights") }}</dt>
      <dd>{{ t("mem.origin.rightsNote") }}</dd>
    </dl>
  </section>
</template>
