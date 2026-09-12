<script setup lang="ts">
const { api, perform, busy } = useAppliance("foundry");
const form = reactive({ worldId: "", username: "Beamer", password: "" });
const saved = useUnsavedChanges(() => form);
const status = ref<{ state: string; worldId: string; username?: string; userId?: string; views?: { index: number; state: string }[] }>();
const error = ref("");
const labels: Record<string, string> = { ready: "Player display connected", "pairing-required": "Pairing required",
  "pending-verification": "Awaiting login verification", unavailable: "Kiosk status unavailable or stale",
  "world-not-running": "Selected world is not running", "module-unavailable": "Mindflayer module unavailable",
  "review-required": "Beamer account requires permission review", "unsupported-version": "Foundry version not supported",
  "origin-mismatch": "Unexpected Foundry address", "login-failed": "Beamer login failed",
  "canvas-unavailable": "Foundry canvas unavailable", stopped: "Player browser stopped",
  "display-disconnected": "No connected player display" };
let timer: ReturnType<typeof setInterval> | undefined;
let refreshing = false;
let disposed = false;
async function refresh() {
  if (refreshing) return;
  refreshing = true;
  try { const value = await api<typeof status.value>("foundry/beamer"); if (!disposed) { status.value = value; error.value = ""; } }
  catch { error.value = "Beamer configuration is unavailable."; if (status.value) status.value = { ...status.value, state: "unavailable", views: [] }; }
  finally { refreshing = false; }
}
onMounted(() => { void refresh(); timer = setInterval(() => void refresh(), 5000); });
onBeforeUnmount(() => { disposed = true; if (timer) clearInterval(timer); });
async function save() {
  await perform(async () => {
    status.value = await api("foundry/beamer", { method: "PUT", body: { ...form } });
    form.password = ""; saved(); error.value = "";
  }, "Beamer credentials saved; login verification is still required");
}
async function remove() {
  await perform(async () => {
    status.value = await api("foundry/beamer", { method: "DELETE" });
    form.password = ""; saved(); error.value = "";
  }, "Stored Beamer credentials removed; Foundry user unchanged");
}
</script>
<template>
  <UCard>
    <template #header><h2 class="text-xl font-semibold">Beamer display login</h2></template>
    <div class="space-y-4">
      <UAlert v-if="error" color="error" :title="error" />
      <UAlert v-if="status" :color="status.state === 'ready' ? 'success' : 'warning'" :title="labels[status.state] || 'Kiosk status unavailable'" description="Status is checked every five seconds. Saving credentials alone does not confirm a successful login." />
      <p v-if="status?.worldId">World {{ status.worldId }}, user {{ status.username || 'existing ID-based pairing' }}.</p>
      <p v-for="view in status?.views || []" :key="view.index">Screen {{ view.index + 1 }}: {{ labels[view.state] || 'Unavailable' }}</p>
      <p class="text-muted">First create or explicitly adopt a dedicated Player using Mindflayer’s Beamer display user settings in Foundry. Enter that world ID, username and existing password below. The username must match exactly and be unique. This never changes the Foundry user's password.</p>
      <form class="space-y-4" @submit.prevent="save">
        <UFormField label="Foundry world ID"><UInput v-model="form.worldId" required pattern="[A-Za-z0-9_-]{1,128}" class="w-full" /></UFormField>
        <UFormField label="Beamer username"><UInput v-model="form.username" required maxlength="128" autocomplete="username" class="w-full" /></UFormField>
        <UFormField label="Beamer password"><SecretInput v-model="form.password" required minlength="12" maxlength="256" autocomplete="new-password" class="w-full" /></UFormField>
        <div class="flex flex-wrap gap-3">
          <UButton type="submit" :loading="busy">Save for verification</UButton>
          <UButton v-if="status?.worldId" variant="outline" :disabled="busy" @click="remove">Remove stored Beamer credentials</UButton>
        </div>
      </form>
    </div>
  </UCard>
</template>
