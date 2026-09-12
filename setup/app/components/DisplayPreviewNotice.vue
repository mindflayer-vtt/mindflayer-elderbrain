<script setup lang="ts">
const { preview, unavailable, update } = useDisplayPreview();
const now = ref(Date.now() / 1000);
const error = ref('');
const busy = ref(false);
const container = ref<HTMLElement>();
watch(() => preview.value.phase, async phase => {
  if (phase !== 'pending') return;
  await nextTick();
  const active = document.activeElement;
  if (!active || active === document.body || active.matches(':disabled')) container.value?.querySelector<HTMLButtonElement>('button:not(:disabled)')?.focus();
}, { immediate: true });
let timer: ReturnType<typeof setInterval>;
let polling = false;
let stopped = false;
async function refresh() {
  if (polling || busy.value || stopped) return;
  polling = true;
  try { await update(); } catch { if (!stopped) unavailable.value = true; }
  finally { polling = false; }
}
async function act(action: string) {
  busy.value = true; error.value = '';
  try { await update('/' + action, { id: preview.value.id }); }
  catch { error.value = 'Unable to update preview. It may have expired; refresh status before retrying.'; }
  finally { busy.value = false; void refresh(); }
}
onMounted(() => { void refresh(); timer = setInterval(() => { now.value = Date.now() / 1000; void refresh(); }, 1000); });
onBeforeUnmount(() => { stopped = true; clearInterval(timer); });
</script>
<template>
  <div ref="container" class="space-y-3 mb-5" aria-live="polite">
    <UAlert v-if="unavailable" color="warning" title="Display preview status unavailable" description="Display edits are disabled until status is known. The host watchdog continues independently of this page." />
    <UAlert v-if="error" color="error" :title="error" />
    <UCard v-if="preview.phase === 'pending'">
      <h2 class="text-lg font-semibold">Keep these display settings?</h2>
      <p>Check your screens. Settings revert automatically unless confirmed within {{ Math.max(0, Math.ceil((preview.deadline || 0) - now)) }} seconds.</p>
      <div class="flex flex-wrap gap-3 mt-3">
        <UButton :loading="busy" :disabled="unavailable || (preview.deadline || 0) <= now" @click="act('confirm')">Keep display settings</UButton>
        <UButton :disabled="busy || unavailable" variant="outline" @click="act('cancel')">Revert display settings</UButton>
      </div>
    </UCard>
    <UAlert v-else-if="preview.phase === 'rolling-back'" color="warning" title="Restoring previous display settings…" />
    <UAlert v-else-if="preview.phase === 'rolled-back'" title="Display changes reverted" description="The previous committed configuration is in use." />
    <UAlert v-else-if="preview.phase === 'confirmed'" color="success" title="Configuration saved" />
  </div>
</template>
