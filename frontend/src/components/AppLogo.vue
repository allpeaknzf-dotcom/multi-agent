<script setup lang="ts">
withDefaults(
  defineProps<{
    size?: number;
  }>(),
  { size: 64 }
);
</script>

<template>
  <img
    src="/logo.png"
    :width="size"
    :height="size"
    alt="Multi-agent"
    style="border-radius: 22%; object-fit: contain"
  />
</template>
