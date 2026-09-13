<script setup lang="ts">
const { session, refresh, logout } = useAdmin();
const loaded = ref(false);
const error = ref("");
const menuOpen = ref(false);
const route = useRoute();
const items = computed(() => ["Overview", "Displays", "Foundry", "Keypads", "Network", "Backups", "System", "Logs", "Account"].map(label => {
  const suffix = label === "Overview" ? "" : label.toLowerCase();
  return { label, to: "/elderbrain/" + suffix, active: route.path.replace(/\/$/, "") === ("/elderbrain/" + suffix).replace(/\/$/, "") || route.path === "/" + suffix };
}));
watch(() => route.path, () => { menuOpen.value = false; });
onMounted(async () => {
  try { await refresh(); } catch (e) { error.value = e instanceof Error ? e.message : "Unable to connect"; }
  finally { loaded.value = true; }
});
</script>
<template>
  <UApp>
    <div v-if="!loaded" class="fixed inset-0 flex flex-col items-center justify-center gap-4 bg-[#090b13]" role="status" aria-label="Loading Elderbrain">
      <img src="~/assets/mindflayer.png" alt="" class="h-64 w-64 object-contain" />
      <span class="h-8 w-8 animate-spin rounded-full border-4 border-white/25 border-t-white" aria-hidden="true" />
      <span class="sr-only">Loading Elderbrain…</span>
    </div>
    <UContainer v-else-if="error" class="py-12"><UAlert color="error" :title="error" /></UContainer>
    <template v-else>
      <div v-if="session.authenticated" class="flex items-center justify-between gap-3 p-4 border-b border-default">
        <span class="text-xl font-semibold">Elderbrain</span>
        <UButton v-if="session.ready" class="lg:hidden" variant="outline" :aria-expanded="menuOpen" aria-controls="admin-navigation" @click="menuOpen = !menuOpen">Menu</UButton>
        <UButton variant="outline" @click="confirmDiscardChanges() && logout()">Sign out</UButton>
      </div>
      <AdminAccess v-if="!session.ready" />
      <UContainer v-else class="max-w-7xl lg:flex gap-8 py-6">
        <nav id="admin-navigation" aria-label="Administration" :class="[menuOpen ? 'block' : 'hidden', 'lg:block lg:w-48 lg:shrink-0 mb-6']">
          <UNavigationMenu :items="items" orientation="vertical" class="w-full" />
        </nav>
        <main class="min-w-0 flex-1"><DisplayPreviewNotice /><NuxtPage /></main>
      </UContainer>
    </template>
  </UApp>
</template>
