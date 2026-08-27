<script setup lang="ts">
import { ref } from "vue";
import NewSessionModal from "../components/NewSessionModal.vue";

const showNew = ref(false);

const quickCards = [
  { icon: "💡", title: "让多个 Agent 协作讨论", desc: "建一个群聊，各自发表观点，共同得出结论" },
  { icon: "🛠", title: "主理人派活做任务", desc: "指定主理人拆解分工，产出方案或代码" },
  { icon: "💬", title: "定向咨询某个 Agent", desc: "把问题 @ 给某个成员，单独请教" },
];
</script>

<template>
  <div class="home">
    <div class="home-inner">
      <div class="home-hero">
        <div class="home-title">让多个 Agent 协作，一起把事办成</div>
        <div class="home-sub">
          新建一个对话，拉入你配置的 Agent 成员，指定主理人派活、辩论、验收，产出方案、代码与文档。
        </div>
        <div class="home-actions">
          <n-button type="primary" size="large" @click="showNew = true">＋ 新对话</n-button>
        </div>
      </div>

      <div class="home-cards">
        <div
          v-for="c in quickCards"
          :key="c.title"
          class="home-card"
          @click="showNew = true"
        >
          <div class="home-card-icon">{{ c.icon }}</div>
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
  background: #fff;
}
.home-inner {
  max-width: 640px;
  padding: 40px 32px;
  width: 100%;
}
.home-hero {
  text-align: center;
  margin-bottom: 40px;
}
.home-title {
  font-size: 26px;
  font-weight: 700;
  color: #1f2329;
  margin-bottom: 14px;
  letter-spacing: 0.3px;
}
.home-sub {
  font-size: 14px;
  color: #777;
  line-height: 1.7;
  margin-bottom: 26px;
}
.home-cards {
  display: grid;
  grid-template-columns: repeat(3, 1fr);
  gap: 14px;
}
.home-card {
  border: 1px solid #eceef2;
  border-radius: 10px;
  padding: 18px 14px;
  cursor: pointer;
  transition: all 0.15s ease;
  background: #fafbfc;
}
.home-card:hover {
  border-color: #6366f1;
  background: #f5f5ff;
  transform: translateY(-1px);
}
.home-card-icon {
  font-size: 22px;
  margin-bottom: 10px;
}
.home-card-title {
  font-size: 14px;
  font-weight: 600;
  color: #1f2329;
  margin-bottom: 6px;
}
.home-card-desc {
  font-size: 12px;
  color: #999;
  line-height: 1.5;
}
.home-tip {
  margin-top: 32px;
  text-align: center;
  font-size: 12px;
  color: #bbb;
}
</style>
