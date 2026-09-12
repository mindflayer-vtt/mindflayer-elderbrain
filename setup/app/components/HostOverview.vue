<script setup lang="ts">
import type { HostMetrics, Usage } from "../../shared/metrics";
const props = defineProps<{ status: Record<string, unknown> }>();
const metrics = computed(() => props.status as unknown as Partial<HostMetrics>);
const history = computed(() => metrics.value.history || []);
const latest = computed(() => history.value.at(-1));
const now = ref(Date.now() / 1000);
let timer: ReturnType<typeof setInterval>;
onMounted(() => { timer = setInterval(() => { now.value = Date.now() / 1000; }, 1000); });
onBeforeUnmount(() => clearInterval(timer));
const stale = computed(() => !latest.value || now.value - latest.value.at > 20);
const bytes = (value: number) => `${(value / 1024 ** 3).toFixed(1)} GiB`;
const percent = (usage: Usage | null | undefined) => usage && usage.total > 0 ? usage.used / usage.total * 100 : null;
const description = (usage: Usage) => `${bytes(usage.used)} used · ${bytes(usage.free)} available · ${bytes(usage.total)} capacity`;
const cpu = computed(() => history.value.map(point => ({ at: point.at, value: point.cpu })));
const ram = computed(() => history.value.map(point => ({ at: point.at, value: percent(point.ram) })));
const diskHistory = (path: string) => history.value.map(point => ({ at: point.at, value: percent(point.disks.find(disk => disk.path === path)) }));
</script>
<template>
  <div class="space-y-5">
    <UAlert v-if="stale" color="warning" :title="latest ? 'Host metrics are stale' : 'Host metrics unavailable'" description="Waiting for fresh appliance measurements. Old values are not current readings." />
    <p v-if="latest" class="text-sm text-muted">{{ metrics.hostname }} · Uptime {{ metrics.uptime == null ? 'unavailable' : `${Math.floor(metrics.uptime / 3600)}h ${Math.floor(metrics.uptime % 3600 / 60)}m` }} · Last sample {{ new Date(latest.at * 1000).toLocaleTimeString() }}</p>
    <div class="grid sm:grid-cols-2 gap-4">
      <MetricGraph title="CPU usage" :value="stale || latest?.cpu == null ? 'Unavailable' : `${latest.cpu.toFixed(1)}%`" :samples="cpu" />
      <MetricGraph title="RAM usage" :value="stale || !latest?.ram ? 'Unavailable' : `${percent(latest.ram)!.toFixed(1)}%`" :detail="latest?.ram ? description(latest.ram) : undefined" :samples="ram" />
      <MetricGraph v-for="disk in latest?.disks || []" :key="disk.path" :title="`Storage: ${disk.path}`" :value="stale ? 'Unavailable' : `${percent(disk)?.toFixed(1) ?? 'Unavailable'}%`" :detail="description(disk)" :samples="diskHistory(disk.path)" />
    </div>
    <p class="text-sm text-muted">Host measurements every five seconds; up to one hour of history, reset when the management service restarts. Storage graphs measure space, not disk activity.</p>
    <UAlert v-for="message in metrics.errors || []" :key="message" color="warning" :title="message" />
    <UCard>
      <h2 class="text-lg font-semibold mb-3">Host services</h2>
      <div class="flex flex-wrap gap-3"><UBadge v-for="service in metrics.services || []" :key="service.name" :color="stale ? 'neutral' : service.state === 'active' ? 'success' : 'warning'">{{ service.name }}: {{ stale ? 'unknown' : service.state }}</UBadge></div>
      <p class="text-sm text-muted mt-3 break-all">Appliance version: {{ metrics.version || 'Unavailable' }}<br>Server image: {{ metrics.mindflayerServerImage || 'Unavailable' }}</p>
    </UCard>
  </div>
</template>
