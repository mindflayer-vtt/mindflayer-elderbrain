<script setup lang="ts">
defineProps<{ active: boolean }>();
const emit = defineEmits<{ changed: [] }>();
const { session } = useAdmin();
const settings = reactive({ kind: "nfs", host: "", export: "", repository: "elderbrain", user: "borg", port: 22,
  hostKey: "", passphrase: "", enabled: false, onBoot: false, onShutdown: false, beforeUpdate: false,
  updateFailurePolicy: "continue", attemptTimeoutSeconds: 300, schedule: "03:00",
  retention: { daily: 7, weekly: 4, monthly: 6 } });
const configured = ref(false);
const publicKey = ref("");
const pendingBackup = ref<{ state: string; checkpoint?: string; lastFailureAt?: number; pendingCount?: number }>({ state: "none" });
const busy = ref(false);
const error = ref("");
const saved = ref(false);
const initializeConsent = ref(false);
const downtimeConsent = ref(false);
const recoveryConsent = ref(false);
const markSaved = useUnsavedChanges(() => settings);
async function load() {
  try {
    const result = await $fetch<Record<string, unknown>>("/elderbrain/api/borg/settings");
    configured.value = result.configured === true;
    publicKey.value = String(result.sshPublicKey || "");
    pendingBackup.value = (result.pendingBackup as typeof pendingBackup.value) || { state: "none" };
    if (configured.value) {
      const { pendingBackup: _pending, sshPublicKey: _key, configured: _configured, passphraseStored: _stored, ...savedSettings } = result;
      Object.assign(settings, savedSettings, { passphrase: "" });
    }
    markSaved();
  } catch { error.value = "Unable to load remote backup settings"; }
}
async function save() {
  busy.value = true; saved.value = false; error.value = "";
  try {
    const result = await $fetch<{ sshPublicKey?: string }>("/elderbrain/api/borg/settings", { method: "PUT",
      headers: { "x-elderbrain-request": "1", "x-csrf-token": session.value.csrf },
      body: { ...settings, port: Number(settings.port), attemptTimeoutSeconds: Number(settings.attemptTimeoutSeconds), retention: {
        daily: Number(settings.retention.daily), weekly: Number(settings.retention.weekly), monthly: Number(settings.retention.monthly) } } });
    settings.passphrase = ""; configured.value = true; publicKey.value = result.sshPublicKey || ""; saved.value = true;
    markSaved();
  } catch (e) { error.value = (e as { data?: { error?: string } }).data?.error || "Unable to save remote backup settings"; }
  finally { busy.value = false; }
}
async function action(name: string) {
  busy.value = true; error.value = "";
  try {
    await $fetch("/elderbrain/api/borg/" + name, { method: "POST", body: { confirm: name === "init" ? initializeConsent.value : name === "recovery-kit" && recoveryConsent.value },
      headers: { "x-elderbrain-request": "1", "x-csrf-token": session.value.csrf } });
    initializeConsent.value = false; downtimeConsent.value = false; recoveryConsent.value = false; emit("changed");
  } catch (e) { error.value = (e as { data?: { error?: string } }).data?.error || "Unable to start repository job"; }
  finally { busy.value = false; }
}
onMounted(load);
</script>

<template>
  <section class="space-y-4">
    <h3 class="text-lg font-semibold">Scheduled remote backups</h3>
    <p class="text-sm text-muted">Borg encrypts remote archives. SSH destinations must support Borg 1, not just SFTP. Verify the remote host key through a trusted channel. Saving settings does not initialize a repository. Network operations are bounded by the configured timeout.</p>
    <form class="space-y-4" @submit.prevent="save">
      <UFormField label="Backup destination type"><USelect v-model="settings.kind" :items="[{ label: 'NFS share', value: 'nfs' }, { label: 'Borg over SSH', value: 'ssh' }]" /></UFormField>
      <UFormField label="Backup server hostname"><UInput v-model="settings.host" required class="w-full" /></UFormField>
      <UFormField v-if="settings.kind === 'nfs'" label="NFS export path"><UInput v-model="settings.export" placeholder="/exports/backups" required class="w-full" /></UFormField>
      <template v-else>
        <div class="grid sm:grid-cols-2 gap-4">
          <UFormField label="Backup SSH user"><UInput v-model="settings.user" required /></UFormField>
          <UFormField label="Backup SSH port"><UInput v-model="settings.port" type="number" min="1" max="65535" required /></UFormField>
        </div>
        <UFormField label="Verified SSH host public key"><UTextarea v-model="settings.hostKey" placeholder="ssh-ed25519 AAAA…" required class="w-full" /></UFormField>
      </template>
      <UFormField :label="settings.kind === 'nfs' ? 'Repository directory within the NFS export' : 'Absolute remote repository path'"><UInput v-model="settings.repository" required class="w-full" /></UFormField>
      <UFormField label="Repository passphrase (blank: keep existing or generate)"><SecretInput v-model="settings.passphrase" autocomplete="new-password" class="w-full" /></UFormField>
      <div class="grid sm:grid-cols-3 gap-4">
        <UFormField v-for="period in (['daily', 'weekly', 'monthly'] as const)" :key="period" :label="`Keep ${period} archives`"><UInput v-model="settings.retention[period]" type="number" min="1" max="3650" required /></UFormField>
      </div>
      <UFormField label="Daily backup time (appliance local time)"><UInput v-model="settings.schedule" type="time" required /></UFormField>
      <UCheckbox v-model="settings.enabled" label="Enable daily backups with temporary appliance downtime" />
      <UCheckbox v-model="settings.onBoot" label="Back up after appliance boot" />
      <UCheckbox v-model="settings.onShutdown" label="Protect and attempt a backup before reboot or shutdown" />
      <UCheckbox v-model="settings.beforeUpdate" label="Attempt a remote backup before installing an update" />
      <UFormField v-if="settings.beforeUpdate" label="If the pre-update remote backup fails">
        <USelect v-model="settings.updateFailurePolicy" :items="[{ label: 'Record the failure and continue updating', value: 'continue' }, { label: 'Block the update', value: 'block' }]" />
      </UFormField>
      <UFormField label="Maximum time for one backup attempt (seconds)">
        <UInput v-model="settings.attemptTimeoutSeconds" type="number" min="30" max="1800" required />
      </UFormField>
      <UButton type="submit" :disabled="active" :loading="busy">Save remote backup settings</UButton>
    </form>
    <UAlert v-if="saved" color="success" title="Remote backup settings saved" />
    <UAlert v-if="!['none', 'completed'].includes(pendingBackup.state)" color="warning" title="A pre-shutdown backup is pending"
      :description="`${pendingBackup.pendingCount || 1} checkpoint${(pendingBackup.pendingCount || 1) === 1 ? ' is' : 's are'} pinned locally. The appliance retries each exact backup generation after boot without discarding newer shutdown captures.${pendingBackup.lastFailureAt ? ' The oldest attempt last failed ' + new Date(pendingBackup.lastFailureAt * 1000).toLocaleString() + '.' : ''}`" />
    <UAlert v-if="error" color="error" title="Remote backup operation failed" :description="error" />
    <div v-if="publicKey" class="space-y-2">
      <p class="text-sm">Install this client public key in the Borg server account’s authorized keys:</p>
      <pre class="text-xs whitespace-pre-wrap break-all">{{ publicKey }}</pre>
    </div>
    <div v-if="configured" class="space-y-3">
      <div class="flex flex-wrap gap-3">
        <UButton variant="outline" :disabled="busy || active" @click="action('test')">Test repository connection</UButton>
        <UButton variant="outline" :disabled="busy || active" @click="action('list')">List remote archives</UButton>
      </div>
      <UCheckbox v-model="initializeConsent" label="I confirm creating an encrypted repository at the saved destination" />
      <UButton :disabled="!initializeConsent || busy || active" variant="outline" @click="action('init')">Initialize repository</UButton>
      <UCheckbox v-model="downtimeConsent" label="I accept temporary downtime for a remote backup now" />
      <UButton :disabled="!downtimeConsent || busy || active" @click="action('backup')">Back up remotely now</UButton>
      <UCheckbox v-model="recoveryConsent" label="I understand the recovery kit contains repository passwords and private keys" />
      <UButton variant="outline" :disabled="!recoveryConsent || busy || active" @click="action('recovery-kit')">Create repository recovery kit</UButton>
    </div>
    <UAlert color="warning" title="Keep the recovery kit offline and private" description="After initializing the repository, create and download its recovery kit from job history. It is an unencrypted JSON file containing the repository passphrase, exported Borg key and SSH credentials. Refresh it whenever repository access changes." />
  </section>
</template>
