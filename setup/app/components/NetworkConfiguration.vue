<script setup lang="ts">
interface Change { phase: string; id?: string; deadline?: number; confirmation?: string | null; token?: string; warnings?: string[] }
interface Link { name: string; state: string; internal: boolean }
const { session } = useAdmin();
const form = reactive({ interface: '', mode: 'dhcp', address: '', prefix: 24, gateway: '', dns: '' });
const saved = useUnsavedChanges(() => form);
const change = useState<Change>('network-change', () => ({ phase: 'loading' }));
const token = useState('network-change-token', () => '');
const target = useState('network-change-target', () => '');
const confirmedAddress = useState('network-confirmed-address', () => '');
const links = ref<Link[]>([]);
const busy = ref(false);
const unavailable = ref(true);
const message = ref('');
const now = ref(Date.now() / 1000);
const remaining = computed(() => Math.max(0, Math.ceil((change.value.deadline || now.value) - now.value)));
const active = computed(() => !['idle', 'confirmed', 'rolled-back', 'loading'].includes(change.value.phase));
const locked = computed(() => busy.value || unavailable.value || active.value || change.value.phase === 'loading');
const items = computed(() => links.value.filter(link => !link.internal && link.state === 'UP').map(link => ({ label: link.name, value: link.name })));
const ipv4 = (value: string) => /^(?:\d{1,3}\.){3}\d{1,3}$/.test(value) && value.split('.').every(part => Number(part) <= 255);
const confirmationURL = computed(() => ipv4(target.value) ? `https://${target.value}:10444/confirm` : '');
const headers = () => ({ 'x-elderbrain-request': '1', 'x-csrf-token': session.value.csrf });
let polling = false;
let stopped = false;
let timer: ReturnType<typeof setInterval>;
let generation = 0;

async function refresh() {
  if (polling || busy.value) return;
  polling = true;
  const current = generation;
  try {
    const next = await $fetch<Change>('/elderbrain/api/network/change', { timeout: 5000, retry: 0 });
    if (stopped || current !== generation) return;
    change.value = { ...next, warnings: next.warnings || change.value.warnings };
    unavailable.value = false;
    if (next.confirmation) {
      const url = new URL(next.confirmation);
      if (!target.value && document.activeElement?.id !== 'network-confirm-address' && url.protocol === 'https:' && url.port === '10444' && url.pathname === '/confirm' && !url.username && !url.password && ipv4(url.hostname)) target.value = url.hostname;
    }
    if (['confirmed', 'rolled-back', 'idle'].includes(next.phase)) token.value = '';
  } catch { if (!stopped && current === generation) unavailable.value = true; }
  finally { polling = false; }
}
async function start() {
  busy.value = true; generation++; message.value = '';
  confirmedAddress.value = '';
  target.value = form.mode === 'static' ? form.address : '';
  try {
    const result = await $fetch<Change>('/elderbrain/api/network/change', {
      method: 'POST', headers: headers(), retry: 0, timeout: 35000,
      body: { interface: form.interface, mode: form.mode, address: form.address, prefix: Number(form.prefix), gateway: form.gateway,
        dns: form.dns.split(/[\s,]+/).filter(Boolean) },
    });
    token.value = result.token || '';
    change.value = { ...result, token: undefined };
    saved();
  } catch {
    change.value = { phase: 'unknown' };
    unavailable.value = true;
    message.value = 'The result is unknown. Do not retry: the host may already be applying the change. Wait for status or automatic rollback.';
  } finally {
    busy.value = false;
    await nextTick();
    if (token.value && active.value) document.getElementById(form.mode === 'static' ? 'network-confirm-action' : 'network-confirm-address')?.focus();
  }
}
async function confirm() {
  if (!confirmationURL.value || !token.value || !change.value.id) return;
  const destination = confirmationURL.value;
  busy.value = true; generation++; message.value = '';
  try {
    const result = await $fetch<{ phase: string }>(destination, {
      method: 'POST', body: { id: change.value.id, token: token.value },
      credentials: 'omit', redirect: 'error', retry: 0, timeout: 10000,
    });
    if (result.phase !== 'confirmed') throw new Error();
    confirmedAddress.value = new URL(destination).hostname;
    change.value = { ...change.value, phase: 'confirmed' }; token.value = '';
    message.value = 'Network change confirmed. Reconnect to setup at the new appliance address; you may need to log in again.';
  } catch { message.value = 'Confirmation could not be verified. Check the address and certificate connection. Unless confirmation reached the host, it will roll back automatically.'; }
  finally {
    busy.value = false;
    if (confirmedAddress.value) {
      await nextTick();
      document.getElementById('network-reconnect')?.focus();
    }
  }
}
async function cancel() {
  busy.value = true; generation++; message.value = '';
  try {
    change.value = await $fetch<Change>('/elderbrain/api/network/change/cancel', {
      method: 'POST', headers: headers(), body: { id: change.value.id }, retry: 0, timeout: 35000,
    });
    token.value = '';
  } catch { message.value = 'Revert could not be verified. Automatic rollback remains active; reconnect at the original address.'; }
  finally { busy.value = false; }
}
watch(() => session.value.csrf, () => { token.value = ''; confirmedAddress.value = ''; });
onMounted(async () => {
  void refresh();
  timer = setInterval(() => { now.value = Date.now() / 1000; void refresh(); }, 2000);
  try {
    const data = await $fetch<{ interfaces: Link[] }>('/elderbrain/api/network', { timeout: 5000, retry: 0 });
    if (!stopped) links.value = data.interfaces;
  } catch { message.value = 'Interface discovery unavailable. Reload after connectivity is restored.'; }
});
onBeforeUnmount(() => { stopped = true; clearInterval(timer); });
</script>

<template>
  <UCard>
    <template #header><h2 class="text-xl font-semibold">Configure appliance IPv4</h2></template>
    <div class="space-y-4">
      <UAlert v-if="unavailable" color="warning" title="Network change status unavailable" description="New changes are disabled. A pending change still has its host-side rollback timer." />
      <UAlert v-if="message" color="warning" :title="message" />
      <UAlert v-if="change.phase === 'rolled-back'" color="success" title="Original network configuration restored" />
      <UAlert v-if="change.phase === 'confirmed'" color="success" title="Network configuration confirmed" />
      <div v-if="change.phase === 'confirmed' && ipv4(confirmedAddress)" class="space-y-2">
        <a id="network-reconnect" :href="`https://${confirmedAddress}/elderbrain/network`" target="_blank" rel="noopener noreferrer" class="underline">Open setup at {{ confirmedAddress }}</a>
        <p class="text-sm text-muted">A new IP address requires a fresh sign-in. No password, session or confirmation token is included in this link.</p>
      </div>
      <form class="space-y-4" @submit.prevent="start">
        <fieldset :disabled="locked" class="space-y-4">
          <UFormField label="Network interface" required><USelect v-model="form.interface" :items="items" placeholder="Select an active interface" aria-label="Network interface" class="w-full" /></UFormField>
          <UFormField label="IPv4 mode"><USelect v-model="form.mode" :items="[{ label: 'Automatic (DHCP)', value: 'dhcp' }, { label: 'Manual (static IPv4)', value: 'static' }]" aria-label="IPv4 mode" /></UFormField>
          <template v-if="form.mode === 'static'">
            <UFormField label="IPv4 address" required><UInput v-model="form.address" aria-label="IPv4 address" required placeholder="192.168.1.20" /></UFormField>
            <UFormField label="Prefix length" required><UInput v-model="form.prefix" type="number" min="1" max="32" required aria-label="Prefix length" /></UFormField>
            <UFormField label="Gateway (optional)"><UInput v-model="form.gateway" aria-label="Gateway" placeholder="192.168.1.1" /></UFormField>
          </template>
          <UFormField label="IPv4 DNS servers (optional)" description="Separate addresses with commas or spaces. Empty uses DHCP DNS in automatic mode; in static mode no manual IPv4 DNS is added."><UInput v-model="form.dns" aria-label="IPv4 DNS servers" class="w-full" /></UFormField>
          <p class="text-sm text-muted">Changes can disconnect this browser. Confirm through the new address within 120 seconds or the host restores the original configuration. Keypads are not updated automatically. With networkd and DHCPv6 enabled, custom DHCP DNS also changes DHCPv6 DNS acceptance.</p>
          <UButton type="submit" :disabled="!form.interface || (form.mode === 'static' && !ipv4(form.address))" :loading="busy">Apply with timed rollback</UButton>
        </fieldset>
      </form>
      <section v-if="active" class="border border-warning rounded p-4 space-y-3" aria-label="Pending network change">
        <h3 class="font-semibold">Network change: {{ change.phase }}</h3>
        <p v-if="change.deadline" role="status">{{ remaining > 0 ? `${remaining} seconds until rollback deadline` : 'Deadline reached; waiting for verified host status' }}</p>
        <p>Keep this tab open. The one-time confirmation token is kept only in this page session; reloading loses it and requires waiting for rollback.</p>
        <UAlert v-for="warning in change.warnings || []" :key="warning" color="warning" :title="warning" />
        <UFormField label="New appliance IPv4" description="For DHCP, use the newly assigned address from the local appliance screen or your router if this browser loses contact."><UInput id="network-confirm-address" v-model="target" aria-label="New appliance IPv4" /></UFormField>
        <a v-if="confirmationURL" :href="confirmationURL.replace('/confirm', '/')" target="_blank" rel="noopener noreferrer" class="underline">Check secure connection at the new address</a>
        <p class="text-sm text-muted">The new endpoint uses this appliance's existing CA. Trust that CA before confirming; do not bypass an unexpected certificate identity.</p>
        <div class="flex flex-wrap gap-2">
          <UButton id="network-confirm-action" :disabled="busy || !token || !confirmationURL || !change.id || remaining === 0" @click="confirm">Confirm through new address</UButton>
          <UButton variant="outline" :disabled="busy || !change.id" @click="cancel">Revert now</UButton>
        </div>
      </section>
    </div>
  </UCard>
</template>
