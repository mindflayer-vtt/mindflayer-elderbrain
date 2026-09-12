<script setup lang="ts">
definePageMeta({ alias: ['/elderbrain/system'] });
const { session } = useAdmin();
const checking = ref(false);
const error = ref('');
const confirmUpdate = ref(false);
const confirmDowntime = ref(false);
const submitting = ref(false);
const jobsAvailable = ref(false);
const powerPending = ref(false);
const notice = ref('');
const powerAction = ref<'' | 'reboot' | 'shutdown'>('');
const confirmPower = ref(false);
const jobs = ref<{ id: string; kind: string; state: string; stage?: string; error?: string }[]>([]);
const active = computed(() => powerPending.value || jobs.value.some(job => ['queued', 'running'].includes(job.state)));
let timer: ReturnType<typeof setInterval> | undefined;
let refreshing = false;
let disposed = false;
const result = ref<{ installedHostVersion: string; installedReleaseSequence: number; state: string; release: null | {
  version: string; releaseSequence: number; recoveryApi: number; hostVersion: string; setupVersion: string; notes: string; downtimeSeconds: number; compatible: boolean; manifestSha256: string;
} }>();
async function refreshJobs() {
  if (refreshing) return;
  refreshing = true;
  try {
    const [next, power] = await Promise.all([
      $fetch<typeof jobs.value>('/elderbrain/api/jobs', { retry: 0, timeout: 10000 }),
      $fetch<{ pending: boolean }>('/elderbrain/api/system/power', { retry: 0, timeout: 10000 }),
    ]);
    if (!disposed) { jobs.value = next; powerPending.value = power.pending === true; jobsAvailable.value = true; }
  } catch { if (!disposed) jobsAvailable.value = false; }
  finally { refreshing = false; }
}
function choosePower(action: 'reboot' | 'shutdown') {
  if (!jobsAvailable.value || active.value || submitting.value) return;
  powerAction.value = action;
  confirmPower.value = false;
}
function cancelPower() {
  powerAction.value = '';
  confirmPower.value = false;
}
async function requestPower() {
  if (!powerAction.value || !confirmPower.value || !jobsAvailable.value || active.value || submitting.value) return;
  const action = powerAction.value;
  submitting.value = true;
  try {
    const job = await $fetch<(typeof jobs.value)[number]>('/elderbrain/api/system/power', {
      method: 'POST', retry: 0, timeout: 15000,
      headers: { 'x-elderbrain-request': '1', 'x-csrf-token': session.value.csrf },
      body: { action, confirmPower: true },
    });
    jobs.value = [job, ...jobs.value.filter(value => value.id !== job.id)];
    notice.value = `${action === 'reboot' ? 'Reboot' : 'Shutdown'} accepted. The protected host job will continue if this page disconnects.`;
    cancelPower();
  } catch {
    jobsAvailable.value = false;
    notice.value = 'Power request status is uncertain or was rejected. Wait for host status to reconnect before trying again.';
  } finally { submitting.value = false; }
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
          <p>Installed host: {{ result.installedHostVersion }} — accepted release sequence {{ result.installedReleaseSequence }}</p>
          <UAlert v-if="result.state === 'not-configured'" color="warning" title="Release source not configured" description="Configure the appliance release source and trusted public signing key before checking for updates." />
          <template v-if="result.release">
            <h3 class="text-lg font-semibold">Release {{ result.release.version }}</h3>
            <dl class="grid grid-cols-2 gap-2">
              <dt>Host version</dt><dd>{{ result.release.hostVersion }}</dd>
              <dt>Setup version</dt><dd>{{ result.release.setupVersion }}</dd>
              <dt>Release sequence</dt><dd>{{ result.release.releaseSequence }}</dd>
              <dt>Recovery API</dt><dd>{{ result.release.recoveryApi }}</dd>
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
    <UCard>
      <template #header><h2 class="text-xl font-semibold">Power</h2></template>
      <div class="space-y-4">
        <p>Reboot or shut down the appliance through the protected host job queue. Active updates, restores and configuration transactions block power requests.</p>
        <UAlert color="warning" title="Pre-shutdown backup is not available yet" description="Power requests currently enforce maintenance safety, but do not yet create the planned bounded local checkpoint or remote-backup attempt." />
        <div class="flex flex-wrap gap-3">
          <UButton color="warning" variant="outline" :disabled="submitting || !jobsAvailable || active" @click="choosePower('reboot')">Reboot appliance</UButton>
          <UButton color="error" variant="outline" :disabled="submitting || !jobsAvailable || active" @click="choosePower('shutdown')">Shut down appliance</UButton>
        </div>
        <div v-if="powerAction" class="space-y-3 rounded-lg border border-default p-4">
          <p class="font-semibold">Confirm {{ powerAction }}</p>
          <p>Foundry, Setup and all display browsers will stop. {{ powerAction === 'shutdown' ? 'Someone must physically power the appliance on again.' : 'The page should reconnect after boot.' }}</p>
          <UCheckbox v-model="confirmPower" :label="`I understand and want to ${powerAction} the appliance now.`" />
          <div class="flex flex-wrap gap-3">
            <UButton :color="powerAction === 'shutdown' ? 'error' : 'warning'" :loading="submitting" :disabled="submitting || !confirmPower || !jobsAvailable || active" @click="requestPower">Confirm {{ powerAction }}</UButton>
            <UButton variant="ghost" :disabled="submitting" @click="cancelPower">Cancel</UButton>
          </div>
        </div>
      </div>
    </UCard>
    <UAlert v-if="notice" color="info" :title="notice" />
    <UAlert v-if="!jobsAvailable" color="warning" title="Host job status unavailable" description="Waiting to reconnect. Update and power submission stay disabled until host status is known." />
    <UAlert v-else-if="active" color="info" title="A host operation is active. Wait for it to finish before starting another operation." />
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
    <UCard>
      <template #header><h2 class="text-xl font-semibold">Power jobs</h2></template>
      <UAlert v-if="powerPending" color="warning" title="A reboot or shutdown is pending on this boot." />
      <p v-if="!jobs.some(job => job.kind === 'power')">No power jobs recorded.</p>
      <ul v-else class="space-y-3">
        <li v-for="job in jobs.filter(job => job.kind === 'power')" :key="job.id">
          <p>Power request: {{ job.state }}<span v-if="job.stage"> — {{ job.stage }}</span></p>
          <p class="text-sm break-all">Job {{ job.id }}</p>
          <p v-if="job.error">{{ job.error }}</p>
        </li>
      </ul>
    </UCard>
  </div>
</template>
