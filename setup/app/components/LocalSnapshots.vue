<script setup lang="ts">
const { session } = useAdmin();
type Checkpoint = { id: string; createdAt: number; reason: string };
type Job = { id: string; kind: string; state: string; error?: string };
const checkpoints = ref<Checkpoint[]>([]);
const jobs = ref<Job[]>([]);
const confirmed = ref(false);
const submitting = ref(false);
const available = ref(false);
const notice = ref('');
const retentionEnabled = ref(false);
const retentionKeep = ref(10);
const retentionLoaded = ref(false);
const retentionSaving = ref(false);
const retentionNotice = ref('');
const active = computed(() => jobs.value.some(job => ['queued', 'running'].includes(job.state)));
const checkpointJobs = computed(() => jobs.value.filter(job => job.kind.startsWith('snapshot-')).slice(0, 5));
let timer: ReturnType<typeof setInterval> | undefined;
let loading = false;
let disposed = false;
async function api<T>(route: string, options: Record<string, unknown> = {}) {
  return await $fetch<T>('/elderbrain/api/' + route, { ...options, timeout: 10000, retry: 0,
    headers: { 'x-elderbrain-request': '1', 'x-csrf-token': session.value.csrf } });
}
async function refresh() {
  if (loading) return;
  loading = true;
  try {
    const nextJobs = await api<Job[]>('jobs');
    if (!disposed) jobs.value = nextJobs;
    const nextCheckpoints = await api<Checkpoint[]>('snapshots');
    if (!disposed) { jobs.value = nextJobs; checkpoints.value = nextCheckpoints; available.value = true; notice.value = ''; }
    if (!retentionLoaded.value) {
      const settings = await api<{ enabled: boolean; keep: number }>('snapshots/retention');
      if (!disposed) { retentionEnabled.value = settings.enabled; retentionKeep.value = settings.keep; retentionLoaded.value = true; }
    }
  } catch {
    if (!disposed) { available.value = false; notice.value = 'Checkpoint status unavailable. During capture, Setup briefly disconnects and reconnects automatically. Persistent Btrfs storage is required.'; }
  } finally { loading = false; }
}
async function saveRetention() {
  if (retentionSaving.value) return;
  retentionSaving.value = true;
  try {
    await api('snapshots/retention', { method: 'PUT', body: {
      enabled: retentionEnabled.value, keep: Number(retentionKeep.value), confirmDeletion: retentionEnabled.value } });
    retentionNotice.value = 'Retention saved. No checkpoints deleted now; the policy applies after successful captures.';
  } catch { retentionNotice.value = 'Could not confirm retention settings were saved. Reload to check before retrying.'; }
  finally { retentionSaving.value = false; }
}
async function submit(recover = false) {
  if (!confirmed.value || submitting.value) return;
  submitting.value = true;
  try {
    const job = await api<Job>(recover ? 'snapshots/recover' : 'snapshots', {
      method: 'POST', body: { confirmDowntime: true } });
    jobs.value = [job, ...jobs.value];
    notice.value = 'Host job submitted. Services may pause; this job continues if you close the page.';
  } catch {
    notice.value = 'Request status uncertain or rejected. Wait for the job list to reconnect before retrying; do not submit a duplicate.';
    available.value = false;
  } finally { submitting.value = false; confirmed.value = false; }
}
onMounted(() => { void refresh(); timer = setInterval(() => void refresh(), 5000); });
onBeforeUnmount(() => { disposed = true; clearInterval(timer); });
</script>
<template>
  <UCard>
    <template #header><h2 class="text-xl font-semibold">Local checkpoints</h2></template>
    <div class="space-y-4">
      <p>Read-only checkpoints capture appliance configuration and Foundry data on the data disk. They do not protect against disk failure; keep independent backups.</p>
      <UAlert v-if="notice" color="warning" :title="notice" />
      <UCheckbox v-model="confirmed" label="I agree to briefly pause Foundry, Setup and display browsers." />
      <div class="flex flex-wrap gap-3">
        <UButton :disabled="!confirmed || !available || active" :loading="submitting" @click="submit()">Create checkpoint</UButton>
        <UButton variant="outline" :disabled="!confirmed || active || submitting" @click="submit(true)">Recover interrupted checkpoint job</UButton>
      </div>
      <p v-for="job in checkpointJobs" :key="job.id">{{ job.kind === 'snapshot-create' ? 'Create checkpoint' : 'Recover checkpoint job' }}: {{ job.state }}<span v-if="job.error"> — {{ job.error }}</span></p>
      <p v-if="available && !checkpoints.length" class="text-muted">No local checkpoints yet.</p>
      <ul v-if="checkpoints.length" class="space-y-2">
        <li v-for="checkpoint in checkpoints" :key="checkpoint.id">{{ new Date(checkpoint.createdAt * 1000).toLocaleString() }} — {{ checkpoint.reason }} <span class="font-mono text-xs">{{ checkpoint.id }}</span></li>
      </ul>
      <div v-if="retentionLoaded" class="space-y-3 border-t border-default pt-4">
        <h3 class="font-semibold">Checkpoint retention</h3>
        <UCheckbox v-model="retentionEnabled" label="Automatically delete older unprotected checkpoints after successful captures." />
        <UFormField label="Recent checkpoints to keep" name="checkpoint-retention">
          <UInput v-model.number="retentionKeep" type="number" :min="1" :max="1000" />
        </UFormField>
        <p class="text-sm text-muted">Checkpoints reserved for updates, restores or pending backups are kept in addition to this limit. Saving does not delete anything immediately.</p>
        <UButton variant="outline" :disabled="!available || active || submitting" :loading="retentionSaving" @click="saveRetention">Save checkpoint retention</UButton>
        <p v-if="retentionNotice" role="status">{{ retentionNotice }}</p>
      </div>
      <p class="text-sm text-muted">Selective restore is not available in this build yet.</p>
    </div>
  </UCard>
</template>
