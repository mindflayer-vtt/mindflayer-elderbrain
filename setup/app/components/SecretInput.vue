<script setup lang="ts">
defineOptions({ inheritAttrs: false });
const value = defineModel<string>({ default: "" });
const visible = ref(false);
watch(value, (next) => { if (!next) visible.value = false; });
</script>

<template>
  <UInput v-bind="$attrs" v-model="value" :type="visible ? 'text' : 'password'" :ui="{ trailing: 'pe-1' }">
    <template #trailing>
      <UButton type="button" color="neutral" variant="link" size="sm"
        :disabled="Boolean($attrs.disabled)"
        :icon="visible ? 'i-lucide-eye-off' : 'i-lucide-eye'"
        :aria-label="visible ? 'Hide password' : 'Show password'"
        :aria-pressed="visible" @click="visible = !visible" />
    </template>
  </UInput>
</template>
