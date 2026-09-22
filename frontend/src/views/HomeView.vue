<script setup lang="ts">
import { ref } from "vue";
import NewSessionModal from "../components/NewSessionModal.vue";
import AppLogo from "../components/AppLogo.vue";

const showNew = ref(false);

const quickCards = [
  {
    title: "让多个 Agent 协作讨论",
    desc: "建一个群聊，各自发表观点，共同得出结论",
    icon: `<svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M17 21v-2a4 4 0 0 0-4-4H5a4 4 0 0 0-4 4v2"/><circle cx="9" cy="7" r="4"/><path d="M23 21v-2a4 4 0 0 0-3-3.87"/><path d="M16 3.13a4 4 0 0 1 0 7.75"/></svg>`
  },
  {
    title: "主理人派活做任务",
    desc: "指定主理人拆解分工，产出方案或代码",
    icon: `<svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="10"/><circle cx="12" cy="12" r="6"/><circle cx="12" cy="12" r="2"/></svg>`
  },
  {
    title: "定向咨询某个 Agent",
    desc: "把问题 @ 给某个成员，单独请教",
    icon: `<svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z"/></svg>`
  },
];
</script>

<template>
  <div class="home">
    <div class="home-inner">
      <div class="home-hero">
        <div class="home-logo">
          <AppLogo :size="64" />
        </div>
        <div class="home-title">让多个 Agent 协作，一起把事办成</div>
        <div class="home-sub">
          新建一个对话，拉入你配置的 Agent 成员，指定主理人派活、辩论、验收，产出方案、代码与文档。
        </div>
        <div class="home-actions">
          <n-button type="primary" size="large" @click="showNew = true">
            <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round" style="vertical-align:-2px;margin-right:4px"><line x1="12" y1="5" x2="12" y2="19"/><line x1="5" y1="12" x2="19" y2="12"/></svg>
            新对话
          </n-button>
        </div>
      </div>

      <div class="home-cards">
        <div
          v-for="c in quickCards"
          :key="c.title"
          class="home-card"
          @click="showNew = true"
        >
          <div class="home-card-icon" v-html="c.icon"></div>
          <div class="home-card-title">{{ c.title }}</div>
          <div class="home-card-desc">{{ c.desc }}</div>
        </div>
      </div>

      <div class="home-tip">左侧「项目」分组管理项目，点击「新对话」即可开始，无需先建项目。</div>
    </div>

    <NewSessionModal v-model:show="showNew" />
  </div>
</template>

<style scoped>
.home {
  height: 100%;
  display: flex;
  align-items: center;
  justify-content: center;
  overflow-y: auto;
  background: linear-gradient(180deg, #fafaff 0%, #ffffff 100%);
}
.home-inner {
  max-width: 680px;
  padding: 40px 32px;
  width: 100%;
}
.home-hero {
  text-align: center;
  margin-bottom: 44px;
}
.home-logo {
  display: inline-flex;
  margin-bottom: 20px;
  border-radius: 16px;
  overflow: hidden;
  box-shadow: 0 8px 24px rgba(99, 102, 241, 0.12);
}
.home-title {
  font-size: 28px;
  font-weight: 700;
  color: #1f2329;
  margin-bottom: 14px;
  letter-spacing: 0.3px;
}
.home-sub {
  font-size: 14.5px;
  color: #6b7280;
  line-height: 1.75;
  margin-bottom: 28px;
  max-width: 480px;
  margin-left: auto;
  margin-right: auto;
}
.home-actions {
  display: flex;
  justify-content: center;
}
.home-cards {
  display: grid;
  grid-template-columns: repeat(3, 1fr);
  gap: 14px;
}
.home-card {
  border: 1px solid #eceef2;
  border-radius: 14px;
  padding: 22px 18px;
  cursor: pointer;
  transition: all 0.2s ease;
  background: #fff;
  text-align: left;
}
.home-card:hover {
  border-color: #c7d2fe;
  box-shadow: 0 8px 24px rgba(99, 102, 241, 0.08);
  transform: translateY(-2px);
}
.home-card-icon {
  width: 40px;
  height: 40px;
  border-radius: 10px;
  display: flex;
  align-items: center;
  justify-content: center;
  color: #6366f1;
  background: #f5f5ff;
  margin-bottom: 14px;
}
.home-card-title {
  font-size: 14px;
  font-weight: 600;
  color: #1f2329;
  margin-bottom: 6px;
}
.home-card-desc {
  font-size: 12.5px;
  color: #8a8f99;
  line-height: 1.6;
}
.home-tip {
  margin-top: 36px;
  text-align: center;
  font-size: 12.5px;
  color: #b0b3bc;
}
</style>
