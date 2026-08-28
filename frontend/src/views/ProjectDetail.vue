<script setup lang="ts">
import { onMounted, ref, computed } from "vue";
import { useRoute, useRouter } from "vue-router";
import { useDialog, useMessage } from "naive-ui";
import { api } from "../api/client";
import NewSessionModal from "../components/NewSessionModal.vue";

const route = useRoute();
const router = useRouter();
const message = useMessage();
const dialog = useDialog();

const projectId = Number(route.params.id);
const project = ref<any>(null);
const sessions = ref<any[]>([]);
const loading = ref(false);
const filter = ref<"active" | "archived">("active");
const searchQuery = ref("");

const showCreate = ref(false);

// 重命名
const showRename = ref(false);
const newName = ref("");

async function rename() {
  if (!newName.value.trim()) return;
  try {
    await api.renameProject(projectId, newName.value.trim());
    message.success("已重命名");
    showRename.value = false;
    load();
  } catch (e: any) {
    message.error(e.message || "重命名失败");
  }
}

// 打开项目本地文件夹（产物自动落盘位置）
async function openProjectFolder() {
  try {
    const res = await api.projectFolderPath(projectId);
    if (!res?.path) {
      message.error("未获取到项目路径");
      return;
    }
    if ((window as any).__TAURI_INTERNALS__) {
      const { openPath } = await import("@tauri-apps/plugin-opener");
      await openPath(res.path);
    } else {
      message.info(`项目文件夹：${res.path}`);
    }
  } catch (e: any) {
    message.error(e.message || "打开文件夹失败");
  }
}

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
  } catch (e: any) {
    message.error(e.message || "加载失败");
  } finally {
    loading.value = false;
  }
}

function sessionPath(s: any) {
  return s.project_id
    ? `/projects/${s.project_id}/sessions/${s.id}`
    : `/sessions/${s.id}`;
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

function toggleProjectArchive() {
  dialog.info({
    title: project.value?.status === "archived" ? "恢复项目" : "归档项目",
    content:
      project.value?.status === "archived"
        ? `确定恢复项目「${project.value?.name}」吗？`
        : `归档项目「${project.value?.name}」？归档后仍可在归档中找回。`,
    positiveText: "确定",
    negativeText: "取消",
    onPositiveClick: async () => {
      try {
        const archived = project.value?.status !== "archived";
        await api.archiveProject(projectId, archived);
        message.success(archived ? "已归档" : "已恢复");
        if (archived) {
          // 归档后回主页：同时触发侧边栏刷新，让项目从「项目」分组消失
          router.push("/");
        } else {
          load();
        }
      } catch (e: any) {
        message.error(e.message || "操作失败");
      }
    },
  });
}

function removeProject() {
  dialog.warning({
    title: "删除项目",
    content: `确定删除项目「${project.value?.name}」吗？其下所有会话、消息、任务将一并删除，且不可恢复。`,
    positiveText: "删除",
    negativeText: "取消",
    onPositiveClick: async () => {
      try {
        await api.deleteProject(projectId);
        message.success("已删除");
        router.push("/");
      } catch (e: any) {
        message.error(e.message || "删除失败");
      }
    },
  });
}

onMounted(load);
</script>

<template>
  <div class="pd-page">
    <div class="pd-head">
      <div class="pd-title">
        {{ project?.name || "项目" }}
        <n-button size="tiny" quaternary class="pd-rename-btn" title="重命名" @click="newName = project?.name || ''; showRename = true">✎</n-button>
      </div>
      <n-tag v-if="project?.status === 'archived'" size="small" type="warning">已归档</n-tag>
      <div style="flex: 1"></div>
      <n-button size="small" @click="openProjectFolder">📁 打开文件夹</n-button>
      <n-button size="small" @click="loadMemory(); showMemory = true">🧠 项目记忆</n-button>
      <n-dropdown
        trigger="click"
        :options="[
          { label: project?.status === 'archived' ? '恢复项目' : '归档项目', key: 'archive' },
          { label: '删除项目', key: 'delete', type: 'error' },
        ]"
        @select="(k: string) => (k === 'archive' ? toggleProjectArchive() : removeProject())"
      >
        <n-button size="small" quaternary>···</n-button>
      </n-dropdown>
      <n-button size="small" type="primary" @click="showCreate = true">新建会话</n-button>
    </div>

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
          @click="router.push(sessionPath(s))"
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

    <!-- 新建会话（全局弹窗，预选当前项目） -->
    <NewSessionModal v-model:show="showCreate" :default-project-id="projectId" @created="load" />

    <!-- 重命名项目 -->
    <n-modal v-model:show="showRename" preset="card" title="重命名项目" style="width: 440px">
      <n-input v-model:value="newName" placeholder="项目名称" maxlength="120" @keydown.enter.prevent="rename" />
      <template #footer>
        <n-space justify="end">
          <n-button @click="showRename = false">取消</n-button>
          <n-button type="primary" @click="rename">保存</n-button>
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
.pd-page {
  height: 100%;
  padding: 24px;
  overflow-y: auto;
  background: #fff;
}
.pd-head {
  display: flex;
  align-items: center;
  gap: 10px;
  margin-bottom: 18px;
}
.pd-title {
  font-size: 20px;
  font-weight: 700;
  display: flex;
  align-items: center;
  gap: 4px;
}
.pd-rename-btn {
  font-size: 14px;
  opacity: 0.5;
}
.pd-rename-btn:hover {
  opacity: 1;
}
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
