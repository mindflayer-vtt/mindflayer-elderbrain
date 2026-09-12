<script setup lang="ts">
const layouts = ref<{ label: string; value: string }[]>([]);
const selected = ref<string>();
const active = ref("");
const capability = ref("");
const pending = ref(false);
const error = ref("");
async function load(layout?: string) {
  pending.value = true; error.value = "";
  try {
    const result = await $fetch<{ layouts: typeof layouts.value; active: string[] }>("/elderbrain/api/keyboard", {
      method: layout === undefined ? "GET" : "POST",
      body: layout === undefined ? undefined : { layout },
      headers: { "x-kiosk-keyboard": capability.value, "x-elderbrain-request": "1" },
    });
    layouts.value = result.layouts;
    active.value = result.active.join(", ");
  } catch { error.value = "Could not access the local keyboard. Reopen the kiosk session or use your operating system's keyboard settings."; }
  finally { pending.value = false; }
}
onMounted(async () => {
  const fragment = new URLSearchParams(window.location.hash.slice(1));
  const token = fragment.get("kiosk-keyboard");
  if (token && /^[a-f0-9]{64}$/.test(token)) {
    sessionStorage.setItem("kiosk-keyboard", token);
    history.replaceState(history.state, "", window.location.pathname + window.location.search);
  }
  capability.value = sessionStorage.getItem("kiosk-keyboard") || "";
  if (capability.value) await load();
});
</script>
<template>
  <UFormField label="Keyboard layout" :description="capability ? 'Applies to the appliance keyboard for this kiosk session.' : 'On a remote computer, change the layout in its operating system. This selector is available on the appliance screen.'">
    <USelectMenu v-model="selected" aria-label="Keyboard layout" :items="layouts" value-key="value" :search-input="{ placeholder: 'Search keyboard layouts…' }"
      :placeholder="active || 'Select keyboard layout'" :disabled="!capability || pending" :loading="pending" class="w-full"
      @update:model-value="value => { if (value) load(value); }" />
    <p v-if="active" class="text-sm text-muted" role="status">Active: {{ active }}</p>
    <p v-if="error" class="text-sm text-error" role="alert">{{ error }}</p>
  </UFormField>
</template>
