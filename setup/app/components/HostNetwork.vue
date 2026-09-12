<script setup lang="ts">
const props = defineProps<{ compact?: boolean }>();
interface Interface {
  name: string; index: number; state: string; internal: boolean; defaultRoute: boolean;
  addresses: { address: string; prefix: number; scope: string; source: string }[]; gateways: string[]; dns: string[];
}
const data = ref<{ at: number; interfaces: Interface[]; errors: string[] }>();
const error = ref("");
const now = ref(Date.now() / 1000);
const toast = useToast();
let pending = false;
let stopped = false;
let timer: ReturnType<typeof setInterval>;
const stale = computed(() => !data.value || now.value - data.value.at > 20 || Boolean(error.value));
const interfaces = computed(() => (data.value?.interfaces || []).filter(item => !props.compact || !item.internal));
async function refresh() {
  if (pending) return;
  pending = true;
  try {
    const next = await $fetch<typeof data.value>("/elderbrain/api/network");
    if (!stopped) { data.value = next; error.value = ""; }
  } catch { if (!stopped) error.value = "Host network discovery unavailable. Previously observed addresses may no longer apply."; }
  finally { pending = false; }
}
async function copy(address: string) {
  try { await navigator.clipboard.writeText(address); toast.add({ title: "Address copied", color: "success" }); }
  catch { toast.add({ title: "Unable to copy. Select and copy the address manually.", color: "warning" }); }
}
onMounted(() => { void refresh(); timer = setInterval(() => { now.value = Date.now() / 1000; void refresh(); }, 5000); });
onBeforeUnmount(() => { stopped = true; clearInterval(timer); });
</script>
<template>
  <UCard>
    <template #header><h2 class="text-xl font-semibold">Current appliance IPv4 addresses</h2></template>
    <div class="space-y-4">
      <p class="text-sm text-muted">Observed on the appliance host, not the setup container. These addresses are separate from those previously provisioned into keypads. Networking changes do not update keypads automatically.</p>
      <UAlert v-if="error || stale" color="warning" :title="error || (data ? 'Network observations are stale' : 'Waiting for host network information')" />
      <UAlert v-for="message in data?.errors || []" :key="message" color="warning" :title="message" />
      <div v-for="item in interfaces" :key="item.index" class="border border-default rounded p-3 space-y-2">
        <div class="flex flex-wrap items-center gap-2"><strong>{{ item.name }}</strong><UBadge variant="subtle">{{ stale ? 'Unknown' : item.state }}</UBadge><UBadge v-if="item.internal" color="neutral">Internal container network</UBadge><UBadge v-else-if="item.defaultRoute" color="neutral">Default route</UBadge></div>
        <p v-if="!item.addresses.length" class="text-sm text-muted">No IPv4 address assigned.</p>
        <div v-for="address in item.addresses" :key="address.address" class="flex flex-wrap items-center gap-2">
          <code class="select-text">{{ address.address }}/{{ address.prefix }}</code><span>{{ address.source }}</span>
          <UButton variant="outline" size="sm" :disabled="stale || item.state !== 'UP'" :aria-label="`Copy ${address.address}`" @click="copy(address.address)">Copy</UButton>
        </div>
        <p v-if="!compact" class="text-sm text-muted">Default gateway: {{ item.gateways.join(', ') || 'None observed' }} · IPv4 DNS: {{ item.dns.join(', ') || 'None observed or unavailable' }}</p>
      </div>
      <p v-if="data && !interfaces.length" class="text-muted">No LAN interfaces observed.</p>
    </div>
  </UCard>
</template>
