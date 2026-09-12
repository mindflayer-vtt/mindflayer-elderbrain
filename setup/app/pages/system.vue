<script setup lang="ts">
definePageMeta({ alias: ['/elderbrain/system'] });
const { session } = useAdmin();
const checking = ref(false);
const error = ref('');
const confirmUpdate = ref(false);
const confirmDowntime = ref(false);
const submitting = ref(false);
const jobsAvailable = ref(false);
const notice = ref('');
const jobs = ref<{ id: string; kind: string; state: string; stage?: string; error?: string }[]>([]);
const active = computed(() => jobs.value.some(job => ['queued', 'running'].includes(job.state)));
let timer: ReturnType<typeof setInterval> | undefined;
let refreshing = false;
let disposed = false;
const result = ref<{ installedHostVersion: string; state: string; release: null | {
  version: string; hostVersion: string; setupVersion: string; notes: string; downtimeSeconds: number; compatible: boolean; manifestSha256: string;
} }>();
async function refreshJobs() {
  if (refreshing) return;
  refreshing = true;
  try {
    const next = await $fetch<typeof jobs.value>('/elderbrain/api/jobs', { retry: 0, timeout: 10000 });
    if (!disposed) { jobs.value = next; jobsAvailable.value = true; }
  } catch { if (!disposed) jobsAvailable.value = false; }
  finally { refreshing = false; }
}
async function update() {
  const release = result.value?.release;
  if (!release?.compatible || !confirmUpdate.value || !confirmDowntime.value || !jobsAvailable.value || active.value || submitting.value) return;
  submitting.value = true;
  try {
    const job = await $fetch<(typeof jobs.value)[number]>('/elderbrain/api/system/update', {
      method: 'POST', retry: 0, timeout: 15000,
      headers: { 'x-elderbrain-request': '1', 'x-csrf-token': session.value.csrf },
      body: { version: release.version, manifestSha256: release.manifestSha256, confirmUpdate: true, confirmDowntime: true },
    });
    jobs.value = [job, ...jobs.value.filter(value => value.id !== job.id)];
    notice.value = 'Update submitted. The host job continues if this page closes. Setup will reconnect after service downtime.';
  } catch {
    jobsAvailable.value = false;
    notice.value = 'Request status uncertain or rejected. Wait for the job list to reconnect and inspect it before retrying.';
  } finally { submitting.value = false; confirmUpdate.value = false; confirmDowntime.value = false; }
}
onMounted(() => { void refreshJobs(); timer = setInterval(() => void refreshJobs(), 5000); });
onBeforeUnmount(() => { disposed = true; clearInterval(timer); });
async function check() {
  if (checking.value) return;
  checking.value = true;
  error.value = '';
  result.value = undefined;
  confirmUpdate.value = false;
  confirmDowntime.value = false;
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
            <template v-else>
              <UAlert color="info" title="Release signature verified" description="Update now downloads and verifies missing artifacts, prepares the runtime and creates a recovery checkpoint before activation. Preparation may take longer than the service downtime estimate." />
              <UCheckbox v-model="confirmUpdate" label="Download and install this signed Elderbrain release." />
              <UCheckbox v-model="confirmDowntime" label="Allow Foundry, Setup and display browsers to stop temporarily." />
              <UButton :loading="submitting" :disabled="submitting || !confirmUpdate || !confirmDowntime || !jobsAvailable || active" @click="update">Update now</UButton>
            </template>
          </template>
        </template>
      </div>
    </UCard>
    <UAlert v-if="notice" color="info" :title="notice" />
    <UAlert v-if="!jobsAvailable" color="warning" title="Host job status unavailable" description="Waiting to reconnect. Update submission stays disabled until host status is known." />
    <UAlert v-else-if="active" color="info" title="A host job is running. Wait for it to finish before starting another update." />
    <UCard>
      <template #header><h2 class="text-xl font-semibold">Update jobs</h2></template>
      <p v-if="!jobs.some(job => job.kind === 'update')">No update jobs recorded.</p>
      <ul v-else class="space-y-3">
        <li v-for="job in jobs.filter(job => job.kind === 'update')" :key="job.id">
          <p>Update: {{ job.state }}<span v-if="job.stage"> — {{ job.stage }}</span></p>
          <p class="text-sm break-all">Job {{ job.id }}</p>
          <p v-if="job.error">{{ job.error }}</p>
        </li>
      </ul>
    </UCard>
  </div>
</template>
