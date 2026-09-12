<script setup lang="ts">
definePageMeta({ alias: ["/elderbrain/account"] });
</script>
<template>
  <div class="space-y-6">
    <h1 class="text-3xl font-bold">Account</h1>
    <AdminAccess @complete="navigateTo('/elderbrain/')" />
  </div>
</template>
