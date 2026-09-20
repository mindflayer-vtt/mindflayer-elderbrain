<script setup lang="ts">
import type { DisplayOutput } from "../../shared/types";

const selected = defineModel<string>({ default: "" });
const props = defineProps<{ label: string; output: string; displayId?: string; outputs: DisplayOutput[]; unavailable: boolean }>();
const display = computed(() => (props.displayId && props.outputs.find(item => item.id === props.displayId))
  || props.outputs.find(item => item.name === props.output));
const items = computed(() => {
  const modes = display.value?.modes || [];
  const resolutions = new Map<string, number>();
  for (const mode of modes) {
    const value = `${mode.width}x${mode.height}`;
    resolutions.set(value, Math.max(resolutions.get(value) || 0, mode.refresh));
  }
  const dimensions = (value: string) => {
    const separator = value.indexOf("x");
    return [Number(value.slice(0, separator)), Number(value.slice(separator + 1))] as const;
  };
  const sorted = [...resolutions].sort(([left], [right]) => {
    const [lw, lh] = dimensions(left);
    const [rw, rh] = dimensions(right);
    return rw * rh - lw * lh || rw - lw || rh - lh;
  });
  const highest = sorted[0]?.[0]?.replace("x", "×");
  const result = [{ value: "", label: highest ? `Highest available · ${highest}` : "Highest available" },
    ...sorted.map(([value, refresh]) => ({ value,
      label: `${value.replace("x", "×")} · up to ${(refresh / 1000).toFixed(refresh % 1000 ? 2 : 0)} Hz` }))];
  if (selected.value && !result.some(item => item.value === selected.value)) {
    result.push({ value: selected.value, label: `${selected.value.replace("x", "×")} · unavailable (saved selection)` });
  }
  return result;
});
</script>
<template>
  <UFormField :label="label" description="The highest refresh rate for the selected resolution is used automatically.">
    <USelect v-model="selected" :items="items" value-key="value" :aria-label="label"
      :disabled="unavailable || !display" class="w-full" />
  </UFormField>
</template>
