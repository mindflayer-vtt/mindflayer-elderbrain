<script setup lang="ts">
interface Job { id: string; kind: string; state: string; createdAt: number; error?: string;
  result?: { archives?: { name: string; time?: string; applianceIdentity?: string; applianceVersion?: string }[]; preview?: { files: number; bytes: number; applianceVersion: string; applianceIdentity?: string; roots?: string[]; createdAt?: string } } }
const { session } = useAdmin();
const jobs = ref<Job[]>([]);
const consent = ref(false);
const encrypt = ref(false);
const password = ref("");
const passwordAgain = ref("");
const consentLabel = computed(() => encrypt.value
  ? "I understand the temporary downtime and will keep the export passphrase safe"
  : "I understand the temporary downtime and unencrypted download");
watch(encrypt, () => { consent.value = false; });
const pending = ref(false);
const error = ref("");
const upload = ref<File>();
const uploadEncrypted = ref(false);
const uploadPassword = ref("");
let uploadedFile: File | undefined;
useUnsavedChanges(() => Boolean(password.value || passwordAgain.value || uploadPassword.value || (upload.value && upload.value !== uploadedFile)));
const confirmed = reactive<Record<string, boolean>>({});
let timer: ReturnType<typeof setInterval> | undefined;
let refreshing = false;
const active = computed(() => jobs.value.some(job => ["queued", "running"].includes(job.state)));
async function refresh() {
  if (refreshing) return;
  refreshing = true;
  try { jobs.value = await $fetch<Job[]>("/elderbrain/api/jobs"); error.value = ""; }
  catch { error.value = "Unable to reach the appliance. A backup may be stopping services; reconnect and sign in again when it finishes."; }
  finally { refreshing = false; }
}
async function create() {
  pending.value = true;
  try {
    const job = await $fetch<Job>("/elderbrain/api/backups", { method: "POST", body: { encrypt: encrypt.value, ...(encrypt.value ? { passphrase: password.value } : {}) },
      headers: { "x-elderbrain-request": "1", "x-csrf-token": session.value.csrf } });
    jobs.value = [job, ...jobs.value]; consent.value = false; password.value = ""; passwordAgain.value = "";
  } catch { error.value = "Unable to confirm backup submission. Refresh job status before retrying."; }
  finally { pending.value = false; }
}
function chooseFile(event: Event) {
  upload.value = (event.target as HTMLInputElement).files?.[0];
  uploadEncrypted.value = upload.value?.name.endsWith(".gpg") ?? false;
  uploadPassword.value = "";
}
async function uploadBackup() {
  if (!upload.value) return;
  const submitted = upload.value;
  pending.value = true;
  try {
    const response = await fetch(`/elderbrain/api/backups/upload${uploadEncrypted.value ? '-encrypted' : ''}`, { method: "POST", body: upload.value,
      headers: { "content-type": "application/octet-stream", "x-elderbrain-request": "1", "x-csrf-token": session.value.csrf } });
    let result = await response.json();
    if (!response.ok) throw new Error(result.error || "Upload failed");
    if (uploadEncrypted.value) {
      result = await $fetch<Job>("/elderbrain/api/backups/preview-encrypted", { method: "POST",
        body: { uploadId: result.uploadId, passphrase: uploadPassword.value },
        headers: { "x-elderbrain-request": "1", "x-csrf-token": session.value.csrf } });
    }
    jobs.value = [result, ...jobs.value];
    uploadedFile = submitted;
  } catch (e) { error.value = e instanceof Error ? e.message : "Upload failed"; }
  finally { pending.value = false; uploadPassword.value = ""; }
}
async function restore(job: Job) {
  if (!confirmed[job.id]) return;
  pending.value = true;
  try {
    const result = await $fetch<Job>(`/elderbrain/api/backups/${job.id}/restore`, { method: "POST", body: { confirm: true },
      headers: { "x-elderbrain-request": "1", "x-csrf-token": session.value.csrf } });
    jobs.value = [result, ...jobs.value]; confirmed[job.id] = false;
  } catch { error.value = "Unable to confirm restore submission. Refresh job status before retrying."; }
  finally { pending.value = false; }
}
async function fetchArchive(name: string) {
  pending.value = true;
  try {
    const job = await $fetch<Job>("/elderbrain/api/borg/fetch", { method: "POST", body: { archive: name },
      headers: { "x-elderbrain-request": "1", "x-csrf-token": session.value.csrf } });
    jobs.value = [job, ...jobs.value];
  } catch { error.value = "Unable to retrieve remote archive"; }
  finally { pending.value = false; }
}
onMounted(() => { void refresh(); timer = setInterval(() => void refresh(), 5000); });
onBeforeUnmount(() => clearInterval(timer));
</script>

<template>
  <UCard>
    <template #header><h2 class="text-xl font-semibold">Configuration backups</h2></template>
    <div class="space-y-4">
      <UAlert color="warning" title="Backups contain secrets" description="The archive includes account credentials, Wi-Fi settings, identity keys and Foundry data. Choose password encryption to protect the download; otherwise it is unencrypted. Store downloads privately." />
      <p class="text-sm text-muted">Creating a consistent backup temporarily stops Foundry, keypads, displays and this administration app. The host job continues without the browser. You may need to sign in again afterward.</p>
      <UCheckbox v-model="encrypt" label="Password-encrypt the manual export" />
      <div v-if="encrypt" class="space-y-3">
        <UFormField label="Export encryption passphrase"><SecretInput v-model="password" autocomplete="new-password" /></UFormField>
        <UFormField label="Confirm export passphrase"><SecretInput v-model="passwordAgain" autocomplete="new-password" /></UFormField>
        <p class="text-sm text-muted">Use at least 12 characters and keep the passphrase separately. It cannot be recovered from job history. The encrypted download uses .tar.zst.gpg; local plaintext snapshots remain root-private.</p>
      </div>
      <UCheckbox v-model="consent" :label="consentLabel" :aria-label="consentLabel" />
      <UButton :disabled="!consent || active || (encrypt && (password.length < 12 || password !== passwordAgain))" :loading="pending" @click="create">Create configuration backup</UButton>
      <USeparator label="Restore from a manual backup" />
      <UFormField label="Backup archive (.tar.zst or .tar.zst.gpg)"><UInput type="file" accept=".zst,.gpg" :disabled="pending || active" @change="chooseFile" /></UFormField>
      <UCheckbox v-model="uploadEncrypted" label="This backup is password-encrypted" :disabled="pending || active" />
      <UFormField v-if="uploadEncrypted" label="Restore decryption passphrase"><SecretInput v-model="uploadPassword" autocomplete="off" :disabled="pending || active" /></UFormField>
      <UButton :disabled="!upload || active || (uploadEncrypted && uploadPassword.length < 12)" :loading="pending" variant="outline" @click="uploadBackup">Upload and validate backup</UButton>
      <p class="text-sm text-muted">Uploading does not change configuration. Review the validated preview before confirming a restore. Only restore trusted archives from the same appliance software version.</p>
      <UAlert v-if="error" color="warning" title="Backup status unavailable" :description="error" />
      <USeparator label="Remote repository" />
      <BorgSettings :active="active || pending" @changed="refresh" />
      <USeparator label="Job history and restore previews" />
      <p v-if="!jobs.length" class="text-muted">No backup jobs yet.</p>
      <div v-for="job in jobs" :key="job.id" class="border-t border-default pt-3 space-y-2">
        <div class="flex flex-wrap items-center gap-3">
          <strong>{{ job.kind }}</strong>
          <UBadge :color="job.state === 'completed' ? 'success' : ['failed', 'interrupted'].includes(job.state) ? 'error' : 'neutral'">{{ job.state }}</UBadge>
          <span class="text-sm text-muted">{{ new Date(job.createdAt * 1000).toLocaleString() }}</span>
        </div>
        <p v-if="job.error" class="text-sm text-error">{{ job.error }}</p>
        <p v-if="job.result?.preview" class="text-sm text-muted">{{ job.result.preview.files }} files · {{ job.result.preview.bytes }} bytes · version {{ job.result.preview.applianceVersion }}</p>
        <UButton v-if="job.kind === 'backup' && job.state === 'completed'" :href="`/elderbrain/api/backups/${job.id}/download`" external variant="outline">Download .tar.zst</UButton>
        <UButton v-if="job.kind === 'backup-encrypted' && job.state === 'completed'" :href="`/elderbrain/api/backups/${job.id}/download`" external variant="outline">Download encrypted backup</UButton>
        <UButton v-if="job.kind === 'borg-recovery-kit' && job.state === 'completed'" :href="`/elderbrain/api/borg/recovery-kits/${job.id}/download`" external variant="outline">Download recovery kit</UButton>
        <div v-if="['restore-preview', 'restore-preview-encrypted', 'borg-fetch'].includes(job.kind) && job.state === 'completed'" class="space-y-3">
          <p class="text-sm">Appliance: {{ job.result?.preview?.applianceIdentity }} · Created: {{ job.result?.preview?.createdAt }}</p>
          <p class="text-sm">Contents: {{ job.result?.preview?.roots?.join(', ') }}</p>
          <UCheckbox v-model="confirmed[job.id]" label="I trust this archive and confirm replacing configuration, accounts, keys and SSH access" />
          <UButton color="error" :disabled="!confirmed[job.id] || active" :loading="pending" @click="restore(job)">Restore this backup</UButton>
        </div>
        <div v-if="job.result?.archives" class="space-y-2">
          <p v-if="!job.result.archives.length" class="text-sm text-muted">No remote archives found.</p>
          <div v-for="archive in job.result.archives" :key="archive.name" class="flex flex-wrap items-center gap-3">
            <span class="text-sm break-all">{{ archive.name }} · {{ archive.time }}</span>
            <span class="text-sm text-muted">Appliance {{ archive.applianceIdentity || 'unknown' }} · version {{ archive.applianceVersion || 'unknown' }}</span>
            <UButton variant="outline" :disabled="active || pending" @click="fetchArchive(archive.name)">Retrieve restore preview</UButton>
          </div>
        </div>
      </div>
      <p class="text-sm text-muted">Encrypted uploads are decrypted and validated before a restore is offered. Validated plaintext is retained in root-private host storage; passphrases are not saved in job history. Restores create a rollback backup and may require signing in with the archived credentials.</p>
    </div>
  </UCard>
</template>
