<script setup lang="ts">
import { onMounted, ref, computed } from "vue";
import { useRoute, useRouter } from "vue-router";
import { useDialog, useMessage } from "naive-ui";
import { api } from "../api/client";

const route = useRoute();
const router = useRouter();
const message = useMessage();
const dialog = useDialog();

const projectId = Number(route.params.id);
const project = ref<any>(null);
const sessions = ref<any[]>([]);
const agents = ref<any[]>([]);
const loading = ref(false);
const filter = ref<"active" | "archived">("active");
const searchQuery = ref("");

// 新建会话
const showCreate = ref(false);
const newTitle = ref("");
const selectedAgentIds = ref<number[]>([]);
const selectedHostId = ref<number | null>(null);

const hostOptions = computed(() =>
  agents.value
    .filter((a) => selectedAgentIds.value.includes(a.id))
    .map((a) => ({ label: a.name, value: a.id }))
);

const visibleSessions = computed(() =>
  sessions.value.filter((s) => {
    if (filter.value === "active" ? s.status === "archived" : s.status !== "archived") return false;
    const q = searchQuery.value.trim().toLowerCase();
    if (!q) return true;
    return String(s.title || "").toLowerCase().includes(q);
  })
);

const activeCount = computed(
  () => sessions.value.filter((s) => s.status !== "archived").length
);
const archivedCount = computed(
  () => sessions.value.filter((s) => s.status === "archived").length
);

async function load() {
  loading.value = true;
  try {
    project.value = await api.getProject(projectId);
    sessions.value = await api.listSessions(projectId);
    agents.value = await api.listAgents(projectId);
  } catch (e: any) {
    message.error(e.message || "加载失败");
  } finally {
    loading.value = false;
  }
}

async function createSession() {
  if (selectedAgentIds.value.length === 0) {
    message.warning("请至少选择一个 Agent");
    return;
  }
  try {
    const s = await api.createSession({
      project_id: projectId,
      title: newTitle.value || `会话 ${sessions.value.length + 1}`,
      agent_ids: selectedAgentIds.value,
      orchestrator_agent_id: selectedHostId.value,
    });
    message.success("会话已创建");
    showCreate.value = false;
    newTitle.value = "";
    selectedAgentIds.value = [];
    selectedHostId.value = null;
    router.push(`/projects/${projectId}/sessions/${s.id}`);
  } catch (e: any) {
    message.error(e.message || "创建失败");
  }
}

async function toggleArchive(s: any) {
  try {
    const archived = s.status !== "archived";
    await api.archiveSession(s.id, archived);
    message.success(archived ? "会话已归档" : "会话已恢复");
    load();
  } catch (e: any) {
    message.error(e.message || "操作失败");
  }
}

// 项目记忆
const showMemory = ref(false);
const memoryText = ref("");
const savingMemory = ref(false);

async function loadMemory() {
  const p = await api.getProjectMemory(projectId);
  memoryText.value = p.memory || "";
}

async function saveMemory() {
  savingMemory.value = true;
  try {
    await api.updateProjectMemory(projectId, memoryText.value);
    message.success("记忆已保存");
    showMemory.value = false;
  } catch (e: any) {
    message.error(e.message || "保存失败");
  } finally {
    savingMemory.value = false;
  }
}

function removeSession(s: any) {
  dialog.warning({
    title: "删除会话",
    content: `确定删除会话「${s.title}」吗？其下所有消息、任务将一并删除，且不可恢复。`,
    positiveText: "删除",
    negativeText: "取消",
    onPositiveClick: async () => {
      try {
        await api.deleteSession(s.id);
        message.success("已删除");
        load();
      } catch (e: any) {
        message.error(e.message || "删除失败");
      }
    },
  });
}

onMounted(load);
</script>

<template>
  <div class="page">
    <n-space align="center" style="margin-bottom: 16px">
      <n-button size="small" quaternary @click="router.push('/projects')">← 返回</n-button>
      <div class="page-title" style="margin: 0">{{ project?.name || "项目" }}</div>
      <n-tag v-if="project?.status === 'archived'" size="small">已归档</n-tag>
      <div style="flex: 1"></div>
      <n-button size="small" @click="loadMemory(); showMemory = true">🧠 项目记忆</n-button>
      <n-button size="small" type="primary" @click="showCreate = true">新建会话</n-button>
    </n-space>

    <n-tabs v-model:value="filter" type="line" style="margin-bottom: 12px">
      <n-tab-pane name="active" :tab="`进行中 (${activeCount})`" />
      <n-tab-pane name="archived" :tab="`已归档 (${archivedCount})`" />
    </n-tabs>

    <n-input
      v-model:value="searchQuery"
      placeholder="搜索会话标题…"
      clearable
      size="large"
      style="margin-bottom: 16px"
    >
      <template #prefix>
        <span style="color: #999">🔍</span>
      </template>
    </n-input>

    <n-spin :show="loading">
      <n-empty v-if="!loading && visibleSessions.length === 0" :description="filter === 'active' ? '该项目下还没有会话' : '暂无已归档会话'">
        <template #footer>
          <n-button v-if="filter === 'active'" type="primary" @click="showCreate = true">创建第一个会话</n-button>
        </template>
      </n-empty>

      <div class="session-list">
        <n-card
          v-for="s in visibleSessions"
          :key="s.id"
          hoverable
          class="session-card"
          @click="router.push(`/projects/${projectId}/sessions/${s.id}`)"
        >
          <template #header>
            <div class="session-header">
              <span class="session-title">{{ s.title }}</span>
              <n-dropdown
                trigger="click"
                :options="[
                  { label: s.status === 'archived' ? '恢复' : '归档', key: 'archive' },
                  { label: '删除', key: 'delete', type: 'error' },
                ]"
                @select="(k: string) => (k === 'archive' ? toggleArchive(s) : removeSession(s))"
              >
                <n-button size="small" quaternary circle @click.stop>···</n-button>
              </n-dropdown>
            </div>
          </template>
          <div class="session-meta">
            <n-tag v-if="s.status === 'archived'" size="tiny" type="warning">已归档</n-tag>
            <span>主理人 {{ s.orchestrator_agent_id ? "已指定" : "未指定" }} · {{ new Date(s.created_at).toLocaleString() }}</span>
            <div style="flex: 1"></div>
            <n-button v-if="s.status === 'archived'" size="tiny" type="primary" ghost @click.stop="toggleArchive(s)">
              恢复
            </n-button>
          </div>
        </n-card>
      </div>
    </n-spin>

    <n-modal v-model:show="showCreate" preset="card" title="新建会话（群聊）" style="width: 560px">
      <n-form label-placement="top">
        <n-form-item label="会话标题">
          <n-input v-model:value="newTitle" placeholder="可选，留空自动命名" />
        </n-form-item>
        <n-form-item label="选择参与的 Agent（可多选）">
          <n-checkbox-group v-model:value="selectedAgentIds">
            <n-space vertical>
              <n-checkbox v-for="a in agents" :key="a.id" :value="a.id" :label="`${a.name}（${a.provider} / ${a.model}）`" />
            </n-space>
          </n-checkbox-group>
        </n-form-item>
        <n-form-item label="主理人（负责任务分工与验收）">
          <n-select
            v-model:value="selectedHostId"
            :options="hostOptions"
            placeholder="默认选第一个加入的 Agent"
            clearable
          />
        </n-form-item>
      </n-form>
      <template #footer>
        <n-space justify="end">
          <n-button @click="showCreate = false">取消</n-button>
          <n-button type="primary" @click="createSession">创建</n-button>
        </n-space>
      </template>
    </n-modal>

    <!-- 项目记忆 -->
    <n-modal v-model:show="showMemory" preset="card" title="项目记忆（长期上下文）" style="width: 680px">
      <p style="font-size: 12px; color: #888; margin-bottom: 10px">
        主理人派活完成会自动沉淀结论到这里；Agent 对话时会参考这些历史记忆。你也可以手动编辑补充。
      </p>
      <n-input
        v-model:value="memoryText"
        type="textarea"
        :rows="12"
        placeholder="项目记忆内容（Markdown）…"
      />
      <template #footer>
        <n-space justify="end">
          <n-button @click="showMemory = false">取消</n-button>
          <n-button type="primary" :loading="savingMemory" @click="saveMemory">保存</n-button>
        </n-space>
      </template>
    </n-modal>
  </div>
</template>

<style scoped>
.session-list {
  display: flex;
  flex-direction: column;
  gap: 12px;
}
.session-card {
  cursor: pointer;
}
.session-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
}
.session-title {
  font-size: 15px;
  font-weight: 600;
}
.session-meta {
  font-size: 12px;
  color: #999;
  display: flex;
  align-items: center;
  gap: 8px;
}
</style>
