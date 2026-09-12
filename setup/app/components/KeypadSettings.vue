<script setup lang="ts">
const { session } = useAdmin();
const toast = useToast();
const settings = reactive({ ssid: "", psk: "", serverHost: "", serverPort: 10443 });
const passwordStored = ref(false);
const revision = ref(0);
const error = ref("");
const busy = ref(false);
const markSaved = useUnsavedChanges(() => settings);
onMounted(async () => {
  try {
    const value = await $fetch<{ ssid: string; serverHost: string; serverPort: number; passwordStored: boolean; revision: number }>("/elderbrain/api/keypad-settings");
    Object.assign(settings, { ssid: value.ssid, serverHost: value.serverHost, serverPort: value.serverPort });
    passwordStored.value = value.passwordStored; revision.value = value.revision;
    markSaved();
  } catch { error.value = "Unable to load keypad settings"; }
});
async function save() {
  busy.value = true; error.value = "";
  try {
    const value = await $fetch<{ revision: number; passwordStored: boolean }>("/elderbrain/api/keypad-settings", {
      method: "PUT", headers: { "x-elderbrain-request": "1", "x-csrf-token": session.value.csrf },
      body: { ...settings, psk: settings.psk || undefined },
    });
    settings.psk = ""; revision.value = value.revision; passwordStored.value = value.passwordStored;
    markSaved();
    toast.add({ title: "Desired keypad settings saved", description: "Keypads still need provisioning to apply these settings.", color: "success" });
  } catch (e) { error.value = (e as { data?: { error?: string } }).data?.error || "Unable to save settings"; }
  finally { busy.value = false; }
}
</script>
<template>
  <UCard>
    <template #header><h2 class="text-xl font-semibold">Central keypad settings</h2></template>
    <form class="space-y-4" @submit.prevent="save">
      <UAlert v-if="error" color="error" :title="error" />
      <UFormField label="Wi-Fi SSID"><UInput v-model="settings.ssid" required class="w-full" /></UFormField>
      <UFormField label="Wi-Fi password" :description="passwordStored ? 'Stored. Leave blank to keep it.' : 'Required for provisioning.'"><SecretInput v-model="settings.psk" autocomplete="new-password" class="w-full" /></UFormField>
      <UFormField label="Appliance address reachable by keypads"><UInput v-model="settings.serverHost" required placeholder="192.168.1.50" class="w-full" /></UFormField>
      <UFormField label="Keypad server port"><UInput v-model.number="settings.serverPort" type="number" min="1" max="65535" required /></UFormField>
      <UButton type="submit" :loading="busy">Save desired settings</UButton>
      <p class="text-sm text-muted">Desired revision {{ revision }}. Saving does not reconfigure devices; applied revisions are tracked separately.</p>
    </form>
  </UCard>
</template>
