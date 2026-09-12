<script setup lang="ts">
definePageMeta({ alias: ["/elderbrain", "/elderbrain/"] });
const { status, error, busy, restart } = useAppliance("overview");
</script>
<template>
  <div class="space-y-6">
    <h1 class="text-3xl font-bold">Overview</h1>
    <UAlert v-if="error" color="error" :title="error" />
    <HostOverview :status="status" />
    <UCard>
      <template #footer>
        <div class="flex flex-wrap gap-3">
          <UButton :disabled="busy" @click="restart('restart-foundry')">Restart Foundry</UButton>
          <UButton :disabled="busy" @click="restart('restart-mindflayer')">Restart Mindflayer</UButton>
          <UButton :disabled="busy" variant="outline" @click="restart('restart-browser-session')">Restart displays</UButton>
        </div>
      </template>
    </UCard>
  </div>
</template>
