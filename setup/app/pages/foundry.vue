<script setup lang="ts">
definePageMeta({ alias: ["/elderbrain/foundry"] });
const { error, busy, credentials, api, perform, saveFoundry } = useAppliance("foundry");
type FoundryAdministrator = { managed: boolean; accessKey?: string; resetRequired: boolean; restarted?: { ok: boolean } };
const administrator = ref<FoundryAdministrator>();
const confirmReset = ref(false);
async function loadAdministrator() {
  try { administrator.value = await api<FoundryAdministrator>("foundry/admin-key"); }
  catch (failure) { error.value = failure instanceof Error ? failure.message : "Foundry administrator access is unavailable"; }
}
async function saveAndStartFoundry() {
  await saveFoundry();
  await loadAdministrator();
}
function resetAdministrator() {
  return perform(async () => {
    const result = await api<FoundryAdministrator>("foundry/admin-key", { method: "POST", body: { confirmReset: confirmReset.value } });
    administrator.value = result;
    confirmReset.value = false;
    if (result.restarted && !result.restarted.ok) throw new Error("Access key saved, but Foundry could not restart. Restart Foundry before using it.");
  }, "Foundry administrator access key reset");
}
onMounted(loadAdministrator);
</script>
<template>
  <div class="space-y-6">
    <h1 class="text-3xl font-bold">Foundry</h1>
    <UAlert v-if="error" color="error" :title="error" />
    <UCard>
      <template #header><h2 class="text-xl font-semibold">Foundry administrator access</h2></template>
      <template v-if="administrator?.managed && administrator.accessKey">
        <p class="text-muted mb-4">Use this Elderbrain-managed access key on Foundry's Administration sign-in page. It is separate from world Gamemaster passwords.</p>
        <UFormField label="Foundry administrator access key">
          <SecretInput :model-value="administrator.accessKey" readonly autocomplete="off" class="w-full" />
        </UFormField>
      </template>
      <UAlert v-else-if="administrator?.resetRequired" color="warning" title="Foundry already has an administrator access key that cannot be recovered. Reset it to replace it with an Elderbrain-managed key." />
      <p v-else class="text-muted">An Elderbrain-managed 12-word access key will be generated before Foundry starts for the first time.</p>
      <div v-if="administrator" class="mt-4 space-y-3">
        <UCheckbox v-model="confirmReset" label="I understand this replaces the current Foundry administrator access key." />
        <UButton color="warning" variant="outline" :disabled="!confirmReset || busy" :loading="busy" @click="resetAdministrator">
          {{ administrator.managed ? "Regenerate access key" : "Reset and manage access key" }}
        </UButton>
      </div>
    </UCard>
    <UCard>
      <template #header><h2 class="text-xl font-semibold">Foundry download</h2></template>
      <p class="text-muted mb-4">Credentials are stored securely and are never returned here.</p>
      <form class="space-y-4" @submit.prevent="saveAndStartFoundry">
        <UFormField label="Account email"><UInput v-model="credentials.username" autocomplete="username" class="w-full" /></UFormField>
        <UFormField label="Password"><SecretInput v-model="credentials.password" autocomplete="new-password" class="w-full" /></UFormField>
        <USeparator label="or" />
        <UFormField label="Timed release URL"><UInput v-model="credentials.releaseUrl" type="url" class="w-full" /></UFormField>
        <div class="flex flex-wrap gap-3">
          <UButton type="submit" :loading="busy">Save credentials</UButton>
          <UButton variant="outline" :disabled="busy" @click="perform(async () => { await api('foundry/credentials', { method: 'DELETE' }); }, 'Credentials removed')">Remove stored credentials</UButton>
        </div>
      </form>
    </UCard>
    <BeamerConfiguration />
  </div>
</template>
