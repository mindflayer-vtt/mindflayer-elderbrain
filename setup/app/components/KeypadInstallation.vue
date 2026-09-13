<script setup lang="ts">
import { installationRecovery } from "../../shared/installation-recovery";
interface USBDevice { id: string; port: string; vendorId: string; productId: string;
  manufacturer: string; product: string; serial: string; chipVerified: false }
const devices = ref<USBDevice[]>([]);
const pending = ref(false);
const error = ref("");
const { session } = useAdmin();
const version = ref("");
const checkingRelease = ref(false);
const releaseError = ref("");
const submitting = ref("");
const adopt = ref(false);
const settings = ref({ revision: 0, ssid: "", serverHost: "", passwordStored: false });
interface InstallJob { id: string; kind: string; state: string; stage?: string; error?: string;
  result?: { deviceId?: string; firmware?: string; revision?: number; firmwareWritten?: boolean } }
const jobs = ref<InstallJob[]>([]);
const active = computed(() => jobs.value.some(job => ["queued", "running"].includes(job.state)));
const installations = computed(() => jobs.value.filter(job => ["keypad-install", "keypad-provision"].includes(job.kind)).slice(0, 5));
const abort = new AbortController();
let timer: ReturnType<typeof setInterval> | undefined;
let refreshing = false;
function message(cause: unknown, fallback: string) {
  const detail = cause as { data?: { error?: string } };
  return detail?.data?.error || fallback;
}
async function checkRelease() {
  checkingRelease.value = true;
  version.value = "";
  try {
    const result = await $fetch<{ version: string }>("/elderbrain/api/keypads/release", { signal: abort.signal });
    version.value = result.version;
    releaseError.value = "";
  } catch (cause) { releaseError.value = message(cause, "Unable to check the latest installable firmware release."); }
  finally { checkingRelease.value = false; }
}
async function refresh() {
  if (refreshing) return;
  refreshing = true;
  try {
    const [nextJobs, nextSettings] = await Promise.all([
      $fetch<InstallJob[]>("/elderbrain/api/jobs", { signal: abort.signal }),
      $fetch<typeof settings.value>("/elderbrain/api/keypad-settings", { signal: abort.signal }),
    ]);
    jobs.value = nextJobs;
    settings.value = nextSettings;
  } catch { error.value = "Unable to refresh installation jobs or saved settings."; }
  finally { refreshing = false; }
}
async function operate(device: USBDevice, kind: "install" | "provision") {
  submitting.value = kind + ":" + device.id;
  error.value = "";
  try {
    const job = await $fetch<InstallJob>("/elderbrain/api/keypads/" + kind, {
      method: "POST", signal: abort.signal,
      body: { usbId: device.id, version: version.value, revision: settings.value.revision, adopt: adopt.value, confirm: true },
      headers: { "x-elderbrain-request": "1", "x-csrf-token": session.value.csrf },
    });
    jobs.value = [job, ...jobs.value];
    adopt.value = false;
  } catch (cause) { error.value = message(cause, `Unable to start ${kind === "install" ? "installation" : "provisioning"}. Refresh before retrying.`); }
  finally { submitting.value = ""; }
}
async function scan() {
  pending.value = true;
  try { devices.value = await $fetch<USBDevice[]>("/elderbrain/api/keypads/usb", { signal: abort.signal }); error.value = ""; }
  catch { devices.value = []; error.value = "Unable to inspect USB devices on the appliance."; }
  finally { pending.value = false; }
}
onMounted(() => { void scan(); void checkRelease(); void refresh(); timer = setInterval(() => void refresh(), 3000); });
onBeforeUnmount(() => { clearInterval(timer); abort.abort(); });
</script>
<template>
  <UCard>
    <template #header><h2 class="text-xl font-semibold">Install or provision a keypad</h2></template>
    <div class="space-y-4">
      <p class="text-sm text-muted">Connect the keypad by USB to the Elderbrain appliance, not to the computer running this browser.</p>
      <UButton :loading="pending" variant="outline" @click="scan">Scan appliance USB ports</UButton>
      <UButton :loading="checkingRelease" variant="outline" @click="checkRelease">Check latest firmware</UButton>
      <UAlert v-if="releaseError" color="warning" :title="releaseError" />
      <p v-if="version" class="text-sm">Selected stable firmware: {{ version }}. The signature, ESP8266 chip and 4 MiB flash will be checked before writing.</p>
      <p v-if="settings.passwordStored" class="text-sm">Saved settings revision {{ settings.revision }}: Wi-Fi {{ settings.ssid }} · Server {{ settings.serverHost }}</p>
      <UAlert v-else color="warning" title="Save central Wi-Fi and appliance settings first" />
      <UCheckbox v-model="adopt" label="Allow adoption of a keypad from another installation" />
      <p class="text-sm text-muted">Local keypad identities are preserved. Adoption assigns a new identity and credentials to a foreign keypad; leave this unchecked unless you intend that change.</p>
      <UAlert v-if="error" color="error" :title="error" />
      <p v-else-if="!pending && !devices.length" class="text-sm text-muted">No USB serial devices found. Check the cable and connection, then scan again.</p>
      <div v-for="device in devices" :key="device.id" class="border border-default rounded p-3 space-y-2">
        <strong>{{ device.product || "USB serial device" }}</strong>
        <p class="text-sm">{{ device.port }} · USB {{ device.vendorId }}:{{ device.productId }} · {{ device.manufacturer }}</p>
        <p class="text-sm text-muted">Serial: {{ device.serial || "Not reported" }} · Chip and flash size not yet verified</p>
        <div class="flex flex-wrap gap-2">
          <UButton :loading="submitting === 'provision:' + device.id" :disabled="!!submitting || active || !version || checkingRelease || !settings.passwordStored || settings.revision < 1" variant="outline" @click="operate(device, 'provision')">Provision settings only {{ device.product || device.port }}</UButton>
          <UButton :loading="submitting === 'install:' + device.id" :disabled="!!submitting || active || !version || checkingRelease || !settings.passwordStored || settings.revision < 1" @click="operate(device, 'install')">Install &amp; provision {{ device.product || device.port }}</UButton>
        </div>
      </div>
      <p class="text-sm text-muted">Provision settings only backs up and inspects provisioning, sends the saved settings over USB, and verifies an authenticated connection. It performs no firmware write; the keypad must already run the selected stable firmware and support protocol v3.</p>
      <p class="text-sm text-muted">Installation resets the selected device, backs up provisioning, writes rBoot and firmware, then sends saved settings and verifies an authenticated connection. Keep USB connected. Some boards may need a physical boot/reset button; this has not yet been verified on hardware.</p>
      <UAlert v-if="active" color="info" title="A host job is active; another keypad operation cannot start yet" />
      <div v-for="job in installations" :key="job.id" class="border border-default rounded p-3 space-y-2">
        <div class="flex flex-wrap gap-2"><strong>{{ job.kind === 'keypad-provision' ? 'Provisioning' : 'Installation' }} {{ job.id.slice(0, 8) }}</strong><UBadge :color="job.state === 'completed' ? 'success' : ['failed', 'interrupted'].includes(job.state) ? 'error' : 'neutral'">{{ job.state }}</UBadge></div>
        <p v-if="job.stage" class="text-sm">Stage: {{ job.stage }}</p>
        <UAlert v-if="job.error" color="error" :title="job.error" />
        <div v-if="['failed', 'interrupted'].includes(job.state)" class="space-y-2">
          <h3 class="font-semibold">Recovery steps</h3>
          <p class="text-sm break-all">Full installation ID: {{ job.id }}</p>
          <ol class="list-decimal pl-5 space-y-1 text-sm">
            <li v-for="step in installationRecovery(job.stage, job.kind !== 'keypad-provision')" :key="step">{{ step }}</li>
          </ol>
          <p class="text-sm text-muted">Recovery records are root-private on the appliance under its state directory, in keypad-installations/{{ job.id }}. They contain credentials; do not paste or upload them into support messages. No automatic resume is performed.</p>
        </div>
        <p v-if="job.state === 'completed'" class="text-sm">Authenticated keypad {{ job.result?.deviceId }} · Firmware {{ job.result?.firmware }} {{ job.result?.firmwareWritten === false ? 'retained' : 'installed' }} · Provisioning revision {{ job.result?.revision }} verified. LED preferences require separate confirmation.</p>
      </div>
    </div>
  </UCard>
</template>
