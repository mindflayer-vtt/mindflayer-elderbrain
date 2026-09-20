<script setup lang="ts">
import type { DisplayOutput } from "../../shared/types";
const selected = defineModel<string>({ required: true });
const displayId = defineModel<string>("displayId", { default: "" });
const props = defineProps<{ label: string; outputs: DisplayOutput[]; unavailable: boolean }>();
const choice = computed({
  get: () => selected.value || "__automatic__",
  set: value => {
    selected.value = value === "__automatic__" ? "" : value;
    displayId.value = props.outputs.find(output => output.name === selected.value)?.id || "";
  },
});
watchEffect(() => {
  const output = (displayId.value && props.outputs.find(item => item.id === displayId.value))
    || props.outputs.find(item => item.name === selected.value);
  if (!output) return;
  if (selected.value !== output.name) selected.value = output.name;
  if (output.id && displayId.value !== output.id) displayId.value = output.id;
});
const choices = computed(() => {
  const result = [{ value: "__automatic__", label: "Automatic output" }, ...props.outputs.map(output => ({ value: output.name,
    label: `${output.name} · ${[output.make, output.model].filter(Boolean).join(' ') || 'Monitor'} · ${output.width && output.height ? `${output.width}×${output.height}` : 'No active resolution'} · ${output.active ? 'Active' : 'Inactive'}` }))];
  if (selected.value && !result.some(item => item.value === selected.value)) {
    result.push({ value: selected.value, label: `${selected.value} · ${props.unavailable ? 'Not verified' : 'Disconnected / not detected'} (saved selection)` });
  }
  return result;
});
</script>
<template>
  <UFormField :label="label">
    <USelect v-model="choice" :items="choices" value-key="value" :aria-label="label" :disabled="unavailable" class="w-full" />
  </UFormField>
</template>
