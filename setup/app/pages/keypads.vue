<script setup lang="ts">
definePageMeta({ alias: ["/elderbrain/keypads"] });
const { config, controllers, error, busy, api, perform } = useAppliance("keypads");
</script>
<template>
  <div class="space-y-6">
    <h1 class="text-3xl font-bold">Keypads</h1>
    <HostNetwork compact />
    <UAlert v-if="error" color="error" :title="error" />
    <UCard>
      <template #header><h2 class="text-xl font-semibold">Controllers</h2></template>
      <p v-if="!controllers.length" class="text-muted">No controllers observed.</p>
      <div v-for="controller in controllers" :key="controller.id" class="flex items-center justify-between gap-3 py-3">
        <div>
          <strong>{{ config?.controllers[controller.id]?.name || controller.id }}</strong>
          <p class="text-sm text-muted">{{ controller.connected ? "Connected" : "Disconnected" }} · {{ controller.lastKey || "No activity" }}</p>
        </div>
        <UButton :disabled="busy || !controller.connected" variant="outline" @click="perform(async () => { await api('controllers/' + encodeURIComponent(controller.id) + '/identify', { method: 'POST' }); }, 'Identification colors sent')">Identify</UButton>
      </div>
    </UCard>
    <KeypadSettings />
    <KeypadInstallation />
    <KeypadInventory />
  </div>
</template>
