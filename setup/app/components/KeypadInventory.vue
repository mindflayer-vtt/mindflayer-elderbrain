<script setup lang="ts">
interface Keypad {
  id: string; name: string; seat: string; connection: string; hardware: string | null;
  firmware: string | null; lastSeen: string | null; provisioning: string;
  desiredRevision: number; appliedRevision: number | null;
  appliedProvisioningRevision?: number | null;
  chipMac?: string;
  registration?: string;
  ledPreferences?: { led1: string; led2: string } | null;
  appliedLeds?: { led1: string; led2: string } | null;
}
const { session } = useAdmin();
const records = ref<Keypad[]>([]);
const edits = reactive<Record<string, { name: string; seat: string; ledsEnabled: boolean; led1: string; led2: string }>>({});
const savedEdits: Record<string, string> = {};
useUnsavedChanges(() => Object.entries(edits).some(([id, edit]) => JSON.stringify(edit) !== savedEdits[id]));
const error = ref("");
const toast = useToast();
let timer: ReturnType<typeof setInterval> | undefined;
let pending = false;
let stopped = false;
async function refresh() {
  if (pending || stopped) return;
  pending = true;
  try {
    const response = await $fetch.raw<Keypad[]>("/elderbrain/api/keypads");
    const next = response._data || [];
    if (stopped) return;
    records.value = next;
    for (const record of next) {
      if (!edits[record.id]) {
        edits[record.id] = { name: record.name, seat: record.seat,
          ledsEnabled: !!record.ledPreferences, led1: record.ledPreferences?.led1 || "#ffffff", led2: record.ledPreferences?.led2 || "#ffffff" };
        savedEdits[record.id] = JSON.stringify(edits[record.id]);
      }
    }
    error.value = response.headers.get("x-elderbrain-inventory-source") === "unavailable"
      ? "Server registration inventory is unavailable. Saved keypads are shown; additional registered devices may be missing."
      : response.headers.get("x-elderbrain-installation-source") === "unavailable" ? "Installation receipts are unavailable; previously saved confirmations are shown." : "";
  } catch { error.value = "Unable to refresh keypad inventory"; }
  finally { pending = false; }
}
async function save(record: Keypad) {
  try {
    const edit = edits[record.id]!;
    const submitted = JSON.stringify(edit);
    const result = await $fetch<{ ledDelivery: string }>("/elderbrain/api/keypads/" + encodeURIComponent(record.id), {
      method: "PUT", body: { name: edit.name, seat: edit.seat,
        ledPreferences: edit.ledsEnabled ? { led1: edit.led1, led2: edit.led2 } : null },
      headers: { "x-elderbrain-request": "1", "x-csrf-token": session.value.csrf },
    });
    savedEdits[record.id] = submitted;
    toast.add({ title: "Keypad preferences saved", description: result.ledDelivery === "sent"
      ? "LED command sent; waiting for firmware acknowledgement. Older firmware cannot confirm application."
      : result.ledDelivery === "pending" ? "LED preferences will be sent when the keypad reconnects."
      : "Automatic LED preferences disabled; current colours are unchanged.", color: "success" });
    await refresh();
  } catch { toast.add({ title: "Unable to save keypad", color: "error" }); }
}
onMounted(() => { void refresh(); timer = setInterval(() => void refresh(), 5000); });
onBeforeUnmount(() => { stopped = true; clearInterval(timer); });
</script>
<template>
  <UCard>
    <template #header><h2 class="text-xl font-semibold">Saved keypad inventory</h2></template>
    <div class="space-y-5">
      <UAlert v-if="error" color="error" :title="error" />
      <p v-if="!records.length" class="text-muted">No keypads recorded yet.</p>
      <p class="text-sm text-muted">Server registration means credentials exist on this appliance, not that a keypad has received or applied them. Hardware, firmware and applied settings remain unconfirmed until verified on the device.</p>
      <div v-for="record in records" :key="record.id" class="border border-default rounded p-4 space-y-3">
        <div class="flex flex-wrap gap-3"><strong>{{ record.id }}</strong><UBadge :color="record.connection === 'connected' ? 'success' : 'neutral'">{{ record.connection }}</UBadge><UBadge variant="outline">{{ record.provisioning }}</UBadge></div>
        <p class="text-sm text-muted">Hardware: {{ record.hardware || "Not yet verified" }} · Firmware: {{ record.firmware || "Not yet verified" }} · Last seen: {{ record.lastSeen || "Never" }}</p>
        <p class="text-sm text-muted">Chip MAC: {{ record.chipMac || "Not yet inspected over USB" }}</p>
        <p class="text-sm">Server registration: {{ record.registration || "unknown" }}</p>
        <p class="text-sm">Desired revision {{ record.desiredRevision }} · Applied revision {{ record.appliedRevision ?? "Not confirmed" }} (last confirmed)</p>
        <p class="text-sm">Last verified USB provisioning revision: {{ record.appliedProvisioningRevision ?? "Not confirmed" }}. This does not confirm LED preferences.</p>
        <p v-if="record.appliedLeds" class="text-sm">Firmware-confirmed LEDs: {{ record.appliedLeds.led1 }} / {{ record.appliedLeds.led2 }}<span v-if="record.ledPreferences"> · {{ record.appliedLeds.led1 === record.ledPreferences.led1 && record.appliedLeds.led2 === record.ledPreferences.led2 ? "Matches saved preferences" : "Differs from saved preferences" }}</span></p>
        <p v-else class="text-sm text-muted">LED application not confirmed. Confirmation requires connected protocol-v3 firmware; it does not verify physical light output.</p>
        <form v-if="edits[record.id]" class="flex flex-wrap gap-3 items-end" @submit.prevent="save(record)">
          <UFormField :label="'Name for ' + record.id"><UInput v-model="edits[record.id]!.name" maxlength="80" /></UFormField>
          <UFormField :label="'Seat for ' + record.id"><UInput v-model="edits[record.id]!.seat" maxlength="80" /></UFormField>
          <UCheckbox v-model="edits[record.id]!.ledsEnabled" :label="'Set LED colours for ' + record.id" />
          <template v-if="edits[record.id]!.ledsEnabled">
            <UFormField :label="'LED 1 for ' + record.id"><UInput v-model="edits[record.id]!.led1" type="color" /></UFormField>
            <UFormField :label="'LED 2 for ' + record.id"><UInput v-model="edits[record.id]!.led2" type="color" /></UFormField>
          </template>
          <UButton type="submit" variant="outline">Save keypad preferences</UButton>
        </form>
        <p class="text-sm text-muted">Optional LED colours are sent on save and reconnect. Foundry or Identify can change them later. Disabling this option stops automatic sends; it does not reset current colours.</p>
      </div>
    </div>
  </UCard>
</template>
