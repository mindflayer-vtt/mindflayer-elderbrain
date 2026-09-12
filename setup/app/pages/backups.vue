<script setup lang="ts">
definePageMeta({ alias: ["/elderbrain/backups"] });
</script>
<template>
  <div class="space-y-6">
    <h1 class="text-3xl font-bold">Backups</h1>
    <Backups />
    <LocalSnapshots />
  </div>
</template>
