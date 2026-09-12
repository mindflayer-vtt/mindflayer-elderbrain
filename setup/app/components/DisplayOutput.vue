<script setup lang="ts">
const selected = defineModel<string>({ required: true });
const choice = computed({ get: () => selected.value || "__automatic__", set: value => { selected.value = value === "__automatic__" ? "" : value; } });
const props = defineProps<{ label: string; outputs: { name: string; make: string; model: string; active: boolean; width: number | null; height: number | null; refresh: number | null }[]; unavailable: boolean }>();
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
