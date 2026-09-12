<script setup lang="ts">
definePageMeta({ alias: ['/elderbrain/system'] });
const { session } = useAdmin();
const checking = ref(false);
const error = ref('');
const result = ref<{ installedHostVersion: string; state: string; release: null | {
  version: string; hostVersion: string; setupVersion: string; notes: string; downtimeSeconds: number; compatible: boolean;
} }>();
async function check() {
  if (checking.value) return;
  checking.value = true;
  error.value = '';
  result.value = undefined;
  try {
    result.value = await $fetch('/elderbrain/api/system/check', { method: 'POST', body: {}, retry: 0, timeout: 40000,
      headers: { 'x-elderbrain-request': '1', 'x-csrf-token': session.value.csrf } });
  } catch { error.value = 'Release check failed. Check the configured release source and network connection, then retry.'; }
  finally { checking.value = false; }
}
</script>
<template>
  <div class="space-y-6">
    <h1 class="text-3xl font-bold">System</h1>
    <UCard>
      <template #header><h2 class="text-xl font-semibold">Elderbrain updates</h2></template>
      <div class="space-y-4">
        <p>Check the configured release source for signed host and Setup versions. Checking does not install software or interrupt Foundry.</p>
        <UButton :loading="checking" :disabled="checking" @click="check">Check for updates</UButton>
        <UAlert v-if="error" color="error" :title="error" />
        <template v-if="result">
          <p>Installed host: {{ result.installedHostVersion }}</p>
          <UAlert v-if="result.state === 'not-configured'" color="warning" title="Release source not configured" description="Configure the appliance release source and trusted public signing key before checking for updates." />
          <template v-if="result.release">
            <h3 class="text-lg font-semibold">Release {{ result.release.version }}</h3>
            <dl class="grid grid-cols-2 gap-2">
              <dt>Host version</dt><dd>{{ result.release.hostVersion }}</dd>
              <dt>Setup version</dt><dd>{{ result.release.setupVersion }}</dd>
              <dt>Expected service downtime</dt><dd>{{ result.release.downtimeSeconds }} seconds</dd>
            </dl>
            <p class="whitespace-pre-wrap break-words">{{ result.release.notes }}</p>
            <UAlert v-if="!result.release.compatible" color="warning" title="This release is incompatible with the installed platform or configuration schema." />
            <UAlert v-else color="info" title="Release signature verified" description="This is release metadata only. Download and preparation controls are not available yet; no update has been installed." />
          </template>
        </template>
      </div>
    </UCard>
  </div>
</template>
