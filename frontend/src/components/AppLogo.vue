<script setup lang="ts">
withDefaults(
  defineProps<{
    size?: number;
  }>(),
  { size: 64 }
);
</script>

<template>
  <svg
    :width="size"
    :height="size"
    viewBox="0 0 96 96"
    fill="none"
    xmlns="http://www.w3.org/2000/svg"
    role="img"
    aria-label="Multi-agent 协作 Logo"
  >
    <defs>
      <linearGradient id="ma-bg" x1="0%" y1="0%" x2="100%" y2="100%">
        <stop offset="0%" stop-color="#6366f1" />
        <stop offset="100%" stop-color="#8b5cf6" />
      </linearGradient>
      <linearGradient id="ma-hl" x1="0%" y1="0%" x2="100%" y2="100%">
        <stop offset="0%" stop-color="#ffffff" stop-opacity="0.3" />
        <stop offset="60%" stop-color="#ffffff" stop-opacity="0" />
      </linearGradient>
    </defs>

    <!-- 圆角徽章底 -->
    <rect x="4" y="4" width="88" height="88" rx="22" fill="url(#ma-bg)" />
    <!-- 左上高光 -->
    <rect x="4" y="4" width="88" height="88" rx="22" fill="url(#ma-hl)" />

    <!-- 协作连线 -->
    <g stroke="#ffffff" stroke-width="2.5" stroke-linecap="round" opacity="0.55">
      <line x1="48" y1="47" x2="48" y2="25" />
      <line x1="48" y1="47" x2="27" y2="63" />
      <line x1="48" y1="47" x2="69" y2="63" />
    </g>

    <!-- 三个 Agent 节点 -->
    <g fill="#ffffff">
      <circle cx="48" cy="25" r="7" />
      <circle cx="27" cy="63" r="7" />
      <circle cx="69" cy="63" r="7" />
    </g>
    <g fill="#8b5cf6">
      <circle cx="48" cy="25" r="2.6" />
      <circle cx="27" cy="63" r="2.6" />
      <circle cx="69" cy="63" r="2.6" />
    </g>

    <!-- 中心调度节点 -->
    <circle cx="48" cy="47" r="12.5" fill="#ffffff" />
    <circle cx="48" cy="47" r="5.2" fill="#7c3aed" />
  </svg>
</template>
