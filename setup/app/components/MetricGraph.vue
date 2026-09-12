<script setup lang="ts">
const props = defineProps<{ title: string; value: string; detail?: string; samples: { at: number; value: number | null }[] }>();
const line = computed(() => {
  const end = props.samples.at(-1)?.at || 0;
  let connected = false;
  let previous = 0;
  return props.samples.map(point => {
    if (point.at - previous > 10) connected = false;
    previous = point.at;
    if (point.value === null || !Number.isFinite(point.value)) { connected = false; return ""; }
    const x = 36 + 540 * Math.max(0, Math.min(1, (point.at - end + 3600) / 3600));
    const y = 110 - Math.max(0, Math.min(100, point.value));
    const result = `${connected ? 'L' : 'M'}${x.toFixed(2)},${y.toFixed(2)}`;
    connected = true;
    return result;
  }).join(" ");
});
</script>
<template>
  <UCard>
    <h2 class="text-lg font-semibold">{{ title }}</h2>
    <p class="text-2xl font-semibold tabular-nums">{{ value }}</p>
    <p v-if="detail" class="text-sm text-muted">{{ detail }}</p>
    <svg viewBox="0 0 600 140" class="w-full mt-3 text-primary" role="img" :aria-label="`${title}: ${value}. Usage history over the last hour.`">
      <path d="M36 10H576 M36 60H576 M36 110H576" stroke="currentColor" opacity="0.15" fill="none" />
      <g fill="currentColor" font-size="11"><text x="0" y="14">100%</text><text x="8" y="114">0%</text><text x="36" y="132">−60 min</text><text x="550" y="132">Now</text></g>
      <path :d="line" stroke="currentColor" stroke-width="2" fill="none" />
    </svg>
  </UCard>
</template>
