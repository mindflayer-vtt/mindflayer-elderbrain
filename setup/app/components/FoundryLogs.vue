<script setup lang="ts">
const { session, refresh: refreshSession } = useAdmin();
const output = ref("");
const error = ref("");
const search = ref("");
const paused = ref(false);
const updated = ref("");
const logView = ref<HTMLElement>();
let timer: ReturnType<typeof setInterval> | undefined;
let pending = false;
let stopped = false;
const visible = computed(() => output.value.split("\n").filter(line => line.toLowerCase().includes(search.value.toLowerCase())).join("\n"));
async function refresh() {
  if (pending || paused.value || stopped) return;
  pending = true;
  try {
    const result = await $fetch<{ output: string; updatedAt: string }>("/elderbrain/api/logs/foundry");
    if (stopped) return;
    output.value = result.output; updated.value = result.updatedAt; error.value = "";
    await nextTick();
    if (logView.value && !paused.value) logView.value.scrollTop = logView.value.scrollHeight;
  } catch (e) {
    const problem = e as { statusCode?: number; data?: { error?: string } };
    if (problem.statusCode === 401 || problem.statusCode === 403) await refreshSession();
    error.value = problem.data?.error || "Unable to read Foundry logs";
  } finally { pending = false; }
}
function toggle() { paused.value = !paused.value; if (!paused.value) void refresh(); }
onMounted(() => { void refresh(); timer = setInterval(() => void refresh(), 2000); });
onBeforeUnmount(() => { stopped = true; clearInterval(timer); });
</script>
<template>
  <UCard>
    <template #header><h2 class="text-xl font-semibold">Foundry logs</h2></template>
    <div class="space-y-4">
      <div class="flex flex-wrap gap-3 items-center">
        <UFormField label="Search logs"><UInput v-model="search" placeholder="Filter recent lines" /></UFormField>
        <UButton variant="outline" @click="toggle">{{ paused ? "Resume logs" : "Pause logs" }}</UButton>
        <UButton v-if="session.ready" to="/elderbrain/api/logs/foundry/download" external variant="outline">Download recent logs</UButton>
      </div>
      <UAlert v-if="error" :title="error" color="error" />
      <pre ref="logView" aria-label="Foundry log output" class="bg-muted rounded p-4 text-xs whitespace-pre-wrap break-all max-h-96 overflow-auto">{{ visible || (search ? "No matching lines" : "Waiting for logs…") }}</pre>
      <p class="text-xs text-muted">Most recent 500 lines, limited to 12 KB. {{ paused ? "Paused" : "Refreshes every two seconds" }}. {{ updated ? "Updated " + new Date(updated).toLocaleTimeString() : "" }}</p>
    </div>
  </UCard>
</template>
