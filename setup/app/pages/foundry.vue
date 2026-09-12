<script setup lang="ts">
definePageMeta({ alias: ["/elderbrain/foundry"] });
const { error, busy, credentials, api, perform, saveFoundry } = useAppliance("foundry");
</script>
<template>
  <div class="space-y-6">
    <h1 class="text-3xl font-bold">Foundry</h1>
    <UAlert v-if="error" color="error" :title="error" />
    <UCard>
      <template #header><h2 class="text-xl font-semibold">Foundry download</h2></template>
      <p class="text-muted mb-4">Credentials are stored securely and are never returned here.</p>
      <form class="space-y-4" @submit.prevent="saveFoundry">
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
