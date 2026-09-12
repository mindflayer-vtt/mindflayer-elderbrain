<script setup lang="ts">
definePageMeta({ alias: ["/elderbrain/network"] });
</script>
<template>
  <div class="space-y-6">
    <h1 class="text-3xl font-bold">Network</h1>
    <HostNetwork />
    <NetworkConfiguration />
  </div>
</template>
