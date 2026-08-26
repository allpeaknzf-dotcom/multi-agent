<script setup lang="ts">
import { useRoute } from "vue-router";

const route = useRoute();
const navItems = [
  { label: "项目", to: "/projects" },
  { label: "Agent 管理", to: "/agents" },
];
</script>

<template>
  <n-config-provider :theme-overrides="{ common: { primaryColor: '#6366f1' } }">
    <n-message-provider>
      <n-dialog-provider>
        <n-layout has-sider style="height: 100vh">
          <n-layout-sider bordered :width="180" collapse-mode="width" :collapsed-width="64" :collapsed="false">
            <div class="app-brand">Multi-agent</div>
            <n-menu
              :value="route.path.startsWith('/agents') ? 'agents' : 'projects'"
              :options="navItems.map((i) => ({ key: i.to, label: i.label }))"
              @update:value="(key: string) => ($router as any).push(key)"
            />
            <div class="app-footer">v0.1.0 · M1</div>
          </n-layout-sider>
          <n-layout-content>
            <router-view />
          </n-layout-content>
        </n-layout>
      </n-dialog-provider>
    </n-message-provider>
  </n-config-provider>
</template>

<style scoped>
.app-brand {
  padding: 18px 16px;
  font-size: 18px;
  font-weight: 700;
  letter-spacing: 0.5px;
}
.app-footer {
  position: absolute;
  bottom: 12px;
  left: 16px;
  font-size: 12px;
  color: #999;
}
</style>
