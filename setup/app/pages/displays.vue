<script setup lang="ts">
definePageMeta({ alias: ["/elderbrain/displays"] });
const { config, error, busy, saveConfig } = useAppliance("displays");
const { locked: previewLocked } = useDisplayPreview();
const outputs = ref<{ name: string; make: string; model: string; active: boolean; width: number | null; height: number | null; refresh: number | null }[]>([]);
const discoveryError = ref("");
const unavailable = ref(true);
let timer: ReturnType<typeof setInterval>;
let stopped = false;
let pending = false;
async function discover() {
  if (pending) return;
  pending = true;
  try {
    const result = await $fetch<{ outputs: typeof outputs.value; at: number }>("/elderbrain/api/displays", { timeout: 10000, retry: 0 });
    if (!stopped) {
      outputs.value = result.outputs;
      unavailable.value = Date.now() / 1000 - result.at > 20;
      discoveryError.value = unavailable.value ? "Display observations are stale" : "";
    }
  } catch { if (!stopped) { unavailable.value = true; discoveryError.value = "Display discovery unavailable. Saved selections are preserved."; } }
  finally { pending = false; }
}
onMounted(() => { void discover(); timer = setInterval(() => void discover(), 5000); });
onBeforeUnmount(() => { stopped = true; clearInterval(timer); });
</script>
<template>
  <div class="space-y-6">
    <h1 class="text-3xl font-bold">Displays</h1>
    <UAlert v-if="error" color="error" :title="error" />
    <UAlert v-if="discoveryError" color="warning" :title="discoveryError" />
    <UCard v-if="config">
      <template #header><h2 class="text-xl font-semibold">Displays and URLs</h2></template>
      <form class="space-y-5" @submit.prevent="saveConfig">
        <fieldset :disabled="previewLocked || busy" class="space-y-5">
        <UFormField label="Base LAN domain" description="Example: home.example creates foundry.home.example, mindflayer.home.example and elderbrain.home.example."><UInput v-model="config.domain" required class="w-full" /></UFormField>
        <div v-for="(view, index) in config.views" :key="index" class="border border-default rounded p-4 space-y-4">
          <DisplayOutput v-model="view.output" :label="'Output ' + (index + 1)" :outputs="outputs" :unavailable="unavailable" />
          <UFormField :label="'Browser mode ' + (index + 1)"><USelect v-model="view.mode" :items="[{ value: 'admin', label: 'Administration browser' }, { value: 'player', label: 'Player map kiosk' }]" class="w-full" /></UFormField>
          <UFormField v-if="view.mode === 'admin'" :label="'View ' + (index + 1) + ' URL'" description="Foundry URL: opened as the second tab, after Setup."><UInput v-model="view.url" type="url" required class="w-full" /></UFormField>
          <p v-else class="text-muted">Player mode uses this appliance’s local Foundry and the Beamer account configured on the Foundry page. It waits for pairing before opening a browser; credentials are never sent to a custom URL.</p>
          <template v-if="view.mode === 'admin'">
            <div v-for="(_tab, tabIndex) in view.tabs || []" :key="tabIndex" class="flex gap-2 items-end">
              <UFormField :label="`Screen ${index + 1} additional tab ${tabIndex + 1}`" class="flex-1"><UInput v-model="view.tabs![tabIndex]" type="url" required class="w-full" /></UFormField>
              <UButton variant="outline" @click="view.tabs!.splice(tabIndex, 1)">Remove tab</UButton>
            </div>
            <UButton variant="outline" :disabled="(view.tabs?.length || 0) >= 10" @click="(view.tabs ||= []).push('https://')">Add tab</UButton>
          </template>
          <UButton v-if="index === 1" variant="outline" @click="config.views.splice(1, 1)">Remove second screen</UButton>
        </div>
        <UButton v-if="config.views.length < 2" variant="outline" @click="config.views.push({ output: '', url: 'http://foundry.' + config.domain, mode: 'player', tabs: [] })">Add second screen</UButton>
        <UCheckbox v-model="config.configured" label="Configuration complete" />
        <UButton type="submit" :loading="busy">Preview display changes</UButton>
        <p class="text-sm text-muted">After confirmation, the LAN domain updates routing for foundry, mindflayer and elderbrain subdomains. DNS is external: point these names at the appliance in your router or DNS server. Existing custom browser URLs are unchanged. Setup HTTPS still requires trusting the appliance certificate.</p>
        <p class="text-sm text-muted">Preview restarts the browsers. Reopen Setup if needed and confirm within 90 seconds; otherwise the host restores the saved configuration automatically.</p>
        </fieldset>
      </form>
    </UCard>
  </div>
</template>
