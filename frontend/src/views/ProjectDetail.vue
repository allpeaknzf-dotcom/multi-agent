<script setup lang="ts">
import { onMounted, ref, computed, h, watch } from "vue";
import { useRoute, useRouter } from "vue-router";
import { useDialog, useMessage } from "naive-ui";
import { api } from "../api/client";
import { useAgentsStore } from "../stores/agents";
import NewSessionModal from "../components/NewSessionModal.vue";

const route = useRoute();
const router = useRouter();
const message = useMessage();
const dialog = useDialog();
const agentsStore = useAgentsStore();

// 注意：必须响应路由参数变化（左侧切换项目时组件复用，id 会变）
let projectId = Number(route.params.id);
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
    if (!agentsStore.agents.length) await agentsStore.load();
    // 获取产物目录真实路径（绑定目录或默认工作区），用于顶部展示
    try {
      const p = await api.projectFolderPath(projectId);
      project.value = { ...project.value, _display_path: p?.path || "" };
    } catch {
      /* 路径获取失败不阻塞页面 */
    }
  } catch (e: any) {
    // 项目不存在（已删除）时提示并回到首页，避免停留在失效页面操作报错
    if (e.message?.includes("404") || e.message?.includes("不存在")) {
      message.error("项目不存在或已被删除");
      router.push("/");
    } else {
      message.error(e.message || "加载失败");
    }
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

// 项目记忆（条目化：列表 + 新增/编辑/置顶/删除）
const showMemory = ref(false);
const memories = ref<any[]>([]);
const memoryLoading = ref(false);
const memoryEditorOpen = ref(false);
const memoryDraft = ref<{ id: number | null; title: string; content: string }>({
  id: null,
  title: "",
  content: "",
});

async function loadMemory() {
  memoryLoading.value = true;
  try {
    memories.value = await api.listMemories(projectId);
  } catch (e: any) {
    message.error(e.message || "加载记忆失败");
  } finally {
    memoryLoading.value = false;
  }
}

function openMemoryEditor(item: any | null) {
  memoryDraft.value = {
    id: item?.id ?? null,
    title: item?.title ?? "",
    content: item?.content ?? "",
  };
  memoryEditorOpen.value = true;
}

async function saveMemoryItem() {
  if (!memoryDraft.value.title.trim() || !memoryDraft.value.content.trim()) {
    message.warning("标题和内容不能为空");
    return;
  }
  memoryLoading.value = true;
  try {
    if (memoryDraft.value.id) {
      await api.updateMemory(memoryDraft.value.id, {
        title: memoryDraft.value.title,
        content: memoryDraft.value.content,
      });
    } else {
      await api.createMemory(projectId, {
        title: memoryDraft.value.title,
        content: memoryDraft.value.content,
      });
    }
    message.success("记忆已保存");
    memoryEditorOpen.value = false;
    await loadMemory();
  } catch (e: any) {
    message.error(e.message || "保存失败");
  } finally {
    memoryLoading.value = false;
  }
}

async function togglePinned(item: any) {
  try {
    await api.updateMemory(item.id, { pinned: !item.pinned });
    await loadMemory();
  } catch (e: any) {
    message.error(e.message || "操作失败");
  }
}

function removeMemory(item: any) {
  dialog.warning({
    title: "删除记忆",
    content: `确定删除「${item.title}」吗？删除后 Agent 将不再参考这条记忆。`,
    positiveText: "删除",
    negativeText: "取消",
    onPositiveClick: async () => {
      try {
        await api.deleteMemory(item.id);
        message.success("已删除");
        await loadMemory();
      } catch (e: any) {
        message.error(e.message || "删除失败");
      }
    },
  });
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

const deleteFolderCheck = ref(false);

// 会话列表项图标背景（按 id 分配柔和渐变色）
const AVATAR_GRADIENTS = [
  "linear-gradient(135deg,#6366f1,#8b5cf6)",
  "linear-gradient(135deg,#0ea5e9,#38bdf8)",
  "linear-gradient(135deg,#f59e0b,#fbbf24)",
  "linear-gradient(135deg,#10b981,#34d399)",
  "linear-gradient(135deg,#f43f5e,#fb7185)",
  "linear-gradient(135deg,#8b5cf6,#d946ef)",
];
function avatarBg(id: number) {
  return AVATAR_GRADIENTS[id % AVATAR_GRADIENTS.length];
}

// 会话主理人名称（由 agent 列表解析）
function hostName(s: any) {
  const a = agentsStore.agents.find((x: any) => x.id === s.orchestrator_agent_id);
  return a?.name || `Agent#${s.orchestrator_agent_id}`;
}

function removeProject() {
  deleteFolderCheck.value = false;
  dialog.warning({
    title: "删除项目",
    content: () =>
      h("div", null, [
        h("div", null, `确定删除项目「${project.value?.name}」吗？其下所有会话、消息、任务将一并删除，且不可恢复。`),
        h(
          "div",
          { style: "margin-top:12px" },
          project.value?.folder_path
            ? h("div", { style: "color:#999;font-size:12px" }, `绑定目录由你管理，删除项目不会影响：${project.value.folder_path}`)
            : h(
                "div",
                null,
                [
                  h(
                    "label",
                    { style: "display:flex;align-items:center;gap:6px;cursor:pointer;font-size:13px" },
                    [
                      h("input", {
                        type: "checkbox",
                        checked: deleteFolderCheck.value,
                        onChange: (e: any) => (deleteFolderCheck.value = e.target.checked),
                      }),
                      h("span", null, "同时删除项目文件夹（含产物）"),
                    ]
                  ),
                  h("div", { style: "color:#999;font-size:12px;margin-top:4px" }, "删除后不可恢复。产物默认保存在 ~/Multi-agent/项目名"),
                ]
              )
        ),
      ]),
    positiveText: "删除",
    negativeText: "取消",
    onPositiveClick: async () => {
      try {
        const r = await api.deleteProject(projectId, deleteFolderCheck.value);
        message.success(
          r.folder_deleted
            ? "已删除（含本地文件夹）"
            : project.value?.folder_path
              ? "已删除（绑定目录已保留）"
              : "已删除"
        );
        router.push("/");
      } catch (e: any) {
        message.error(e.message || "删除失败");
      }
    },
  });
}

onMounted(() => {
  watch(
    () => route.params.id,
    () => {
      projectId = Number(route.params.id);
      showMemory.value = false;
      memoryEditorOpen.value = false;
      load();
    },
    { immediate: true }
  );
});
</script>

<template>
  <div class="pd-page">
    <!-- 顶部：标题 + 路径 + 操作 -->
    <div class="pd-top">
      <div class="pd-left">
        <div class="pd-title">
          {{ project?.name || "项目" }}
          <button class="pd-rename" title="重命名" @click="newName = project?.name || ''; showRename = true">✎</button>
        </div>
        <div class="pd-sub">
          <svg class="pd-sub-icon" viewBox="0 0 16 16" width="13" height="13" fill="none" stroke="currentColor" stroke-width="1.4"><path d="M2.5 3.5h4l1.2 1.5h5.8v7.5h-11z" stroke-linejoin="round"/></svg>
          <span v-if="project?.folder_path" class="pd-path">绑定目录：{{ project.folder_path }}</span>
          <span v-else-if="project?._display_path" class="pd-path">产物保存到 {{ project._display_path }}</span>
          <span v-else class="pd-path">—</span>
          <span v-if="project?.status === 'archived'" class="pd-archived">已归档</span>
        </div>
      </div>
      <div class="pd-right">
        <n-button size="small" quaternary class="pd-btn" @click="openProjectFolder">打开文件夹</n-button>
        <n-button size="small" quaternary class="pd-btn" @click="loadMemory(); showMemory = true">项目记忆</n-button>
        <n-dropdown
          trigger="click"
          :options="[
            { label: project?.status === 'archived' ? '恢复项目' : '归档项目', key: 'archive' },
            { label: '删除项目', key: 'delete', type: 'error' },
          ]"
          @select="(k: string) => (k === 'archive' ? toggleProjectArchive() : removeProject())"
        >
          <n-button size="small" quaternary circle class="pd-btn">···</n-button>
        </n-dropdown>
        <n-button size="small" type="primary" @click="showCreate = true">新建会话</n-button>
      </div>
    </div>

    <!-- 工具栏：状态切换 + 搜索 -->
    <div class="pd-toolbar">
      <div class="pd-tabs">
        <button class="pd-tab" :class="{ on: filter === 'active' }" @click="filter = 'active'">
          进行中 <span class="pd-tab-count">{{ activeCount }}</span>
        </button>
        <button class="pd-tab" :class="{ on: filter === 'archived' }" @click="filter = 'archived'">
          已归档 <span class="pd-tab-count">{{ archivedCount }}</span>
        </button>
      </div>
      <div class="pd-search">
        <svg viewBox="0 0 16 16" width="13" height="13" fill="none" stroke="#9aa0a6" stroke-width="1.6"><circle cx="7" cy="7" r="4.6"/><path d="M10.6 10.6 14 14"/></svg>
        <input v-model="searchQuery" placeholder="搜索会话标题…" />
      </div>
    </div>

    <n-spin :show="loading">
      <n-empty v-if="!loading && visibleSessions.length === 0" :description="filter === 'active' ? '该项目下还没有会话' : '暂无已归档会话'" style="padding: 48px 0">
        <template #footer>
          <n-button v-if="filter === 'active'" type="primary" @click="showCreate = true">创建第一个会话</n-button>
        </template>
      </n-empty>

      <div v-else class="session-list">
        <div
          v-for="s in visibleSessions"
          :key="s.id"
          class="session-row"
          :class="{ archived: s.status === 'archived' }"
          @click="s.status !== 'archived' && router.push(sessionPath(s))"
        >
          <div class="s-icon" :style="{ background: avatarBg(s.id) }">{{ (s.title || "S")[0] }}</div>
          <div class="s-body">
            <div class="s-title">
              {{ s.title }}
              <span v-if="s.status === 'archived'" class="archived-tag">已归档</span>
            </div>
            <div class="s-meta">
              <span class="s-host" :class="{ on: s.orchestrator_agent_id }">
                <svg viewBox="0 0 16 16" width="11" height="11" fill="none" stroke="currentColor" stroke-width="1.5"><path d="M8 1.8a3 3 0 1 1 0 6 3 3 0 0 1 0-6zM2.5 14.2a5.5 5.5 0 0 1 11 0"/></svg>
                主理人{{ s.orchestrator_agent_id ? "：" + hostName(s) : "未指定" }}
              </span>
              <span class="s-time">{{ new Date(s.created_at).toLocaleString() }}</span>
            </div>
          </div>
          <!-- 悬浮只显示 ···，归档/恢复/删除均收纳在菜单里 -->
          <div class="s-actions" @click.stop>
            <n-dropdown
              trigger="click"
              :options="[
                { label: s.status === 'archived' ? '恢复' : '归档', key: 'archive' },
                { label: '删除', key: 'delete', type: 'error' },
              ]"
              @select="(k: string) => (k === 'archive' ? toggleArchive(s) : removeSession(s))"
            >
              <n-button size="tiny" quaternary circle class="s-more">···</n-button>
            </n-dropdown>
          </div>
        </div>
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

    <!-- 项目记忆（条目化列表） -->
    <n-modal v-model:show="showMemory" preset="card" title="项目记忆（长期上下文）" style="width: 720px">
      <p style="font-size: 12px; color: #888; margin-bottom: 10px">
        主理人派活完成会自动沉淀结论到这里；Agent 对话时会参考这些历史记忆。你可以手动新增、编辑、置顶或删除。
      </p>
      <div style="margin-bottom: 10px; text-align: right">
        <n-button size="small" type="primary" @click="openMemoryEditor(null)">＋ 新增记忆</n-button>
      </div>
      <n-spin :show="memoryLoading">
        <n-empty v-if="!memoryLoading && memories.length === 0" description="暂无记忆" style="padding: 24px 0" />
        <n-list v-else style="max-height: 420px; overflow-y: auto">
          <n-list-item v-for="m in memories" :key="m.id">
            <template #prefix>
              <n-tag :type="m.kind === 'manual' ? 'success' : 'info'" size="small" style="margin-right: 8px">
                {{ m.kind === 'manual' ? '手动' : '自动' }}
              </n-tag>
            </template>
            <template #suffix>
              <n-space :size="4">
                <n-button size="tiny" quaternary :title="m.pinned ? '取消置顶' : '置顶'" @click="togglePinned(m)">
                  {{ m.pinned ? '★' : '☆' }}
                </n-button>
                <n-button size="tiny" quaternary title="编辑" @click="openMemoryEditor(m)">✎</n-button>
                <n-button size="tiny" quaternary type="error" title="删除" @click="removeMemory(m)">🗑</n-button>
              </n-space>
            </template>
            <div style="font-weight: 600; font-size: 13px">{{ m.title }}</div>
            <div style="font-size: 12px; color: #666; white-space: pre-wrap; margin-top: 2px">{{ m.content }}</div>
            <div style="font-size: 11px; color: #aaa; margin-top: 4px">{{ m.updated_at }}</div>
          </n-list-item>
        </n-list>
      </n-spin>
      <template #footer>
        <n-space justify="end">
          <n-button @click="showMemory = false">关闭</n-button>
        </n-space>
      </template>
    </n-modal>

    <!-- 记忆编辑弹窗 -->
    <n-modal v-model:show="memoryEditorOpen" preset="card" :title="memoryDraft.id ? '编辑记忆' : '新增记忆'" style="width: 560px">
      <n-input v-model:value="memoryDraft.title" placeholder="标题（建议 ≤60 字）" style="margin-bottom: 10px" />
      <n-input v-model:value="memoryDraft.content" type="textarea" :rows="6" placeholder="记忆内容（建议 ≤600 字）…" />
      <template #footer>
        <n-space justify="end">
          <n-button @click="memoryEditorOpen = false">取消</n-button>
          <n-button type="primary" :loading="memoryLoading" @click="saveMemoryItem">保存</n-button>
        </n-space>
      </template>
    </n-modal>
  </div>
</template>

<style scoped>
.pd-page {
  height: 100%;
  padding: 36px 48px;
  overflow-y: auto;
  background: #fff;
}

/* 顶部 */
.pd-top {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 24px;
}
.pd-title {
  font-size: 24px;
  font-weight: 800;
  letter-spacing: -0.01em;
  color: #101828;
  display: flex;
  align-items: center;
  gap: 8px;
  line-height: 1.3;
}
.pd-rename {
  border: none;
  background: transparent;
  color: #b3b8c2;
  font-size: 15px;
  cursor: pointer;
  padding: 2px 6px;
  border-radius: 6px;
}
.pd-rename:hover {
  color: #6366f1;
  background: #f1f0fe;
}
.pd-sub {
  display: flex;
  align-items: center;
  gap: 7px;
  margin-top: 6px;
  color: #8a8f98;
  font-size: 12.5px;
}
.pd-sub-icon {
  flex: none;
  color: #b3b8c2;
}
.pd-path {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  max-width: 520px;
}
.pd-archived {
  font-size: 11px;
  color: #b4541d;
  background: #fdf1e7;
  border-radius: 4px;
  padding: 1px 7px;
  flex: none;
}
.pd-right {
  display: flex;
  align-items: center;
  gap: 4px;
  flex: none;
}
.pd-btn {
  color: #5f6470;
}

/* 工具栏 */
.pd-toolbar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 16px;
  margin: 28px 0 4px;
  border-bottom: 1px solid #eceef2;
  padding-bottom: 10px;
}
.pd-tabs {
  display: flex;
  gap: 4px;
}
.pd-tab {
  border: none;
  background: transparent;
  font-size: 13.5px;
  font-weight: 500;
  color: #6b7280;
  padding: 6px 12px;
  border-radius: 8px;
  cursor: pointer;
}
.pd-tab:hover {
  background: #f3f4f6;
  color: #111827;
}
.pd-tab.on {
  color: #111827;
  font-weight: 600;
  background: #f1f0fe;
}
.pd-tab-count {
  font-size: 11px;
  color: #9aa0a6;
  margin-left: 3px;
}
.pd-tab.on .pd-tab-count {
  color: #6366f1;
}
.pd-search {
  display: flex;
  align-items: center;
  gap: 7px;
  background: #f5f6f8;
  border-radius: 8px;
  padding: 6px 10px;
  width: 240px;
  flex: none;
}
.pd-search:focus-within {
  background: #fff;
  box-shadow: 0 0 0 2px #e0e7ff;
}
.pd-search input {
  border: none;
  outline: none;
  background: transparent;
  font-size: 13px;
  width: 100%;
  color: #1f2329;
}
.pd-search input::placeholder {
  color: #a8adb5;
}

/* 会话列表 */
.session-list {
  padding-top: 4px;
}
.session-row {
  display: flex;
  align-items: center;
  gap: 14px;
  padding: 13px 12px;
  border-radius: 10px;
  cursor: pointer;
  transition: background 0.15s;
}
.session-row:hover {
  background: #f7f8fa;
}
.session-row.archived {
  cursor: default;
}
.session-row.archived .s-title {
  color: #9aa0a6;
}
.s-icon {
  flex: none;
  width: 38px;
  height: 38px;
  border-radius: 10px;
  color: #fff;
  font-size: 15px;
  font-weight: 700;
  display: flex;
  align-items: center;
  justify-content: center;
}
.s-body {
  flex: 1;
  min-width: 0;
}
.s-title {
  font-size: 14.5px;
  font-weight: 600;
  color: #1f2329;
  display: flex;
  align-items: center;
  gap: 8px;
}
.s-title span:first-child {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.archived-tag {
  flex: none;
  font-size: 11px;
  color: #b4541d;
  background: #fdf1e7;
  border-radius: 4px;
  padding: 1px 7px;
}
.s-meta {
  display: flex;
  align-items: center;
  gap: 12px;
  margin-top: 3px;
  font-size: 12px;
  color: #9aa0a6;
}
.s-host {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  color: #9aa0a6;
}
.s-host.on {
  color: #6366f1;
}
.s-time {
  white-space: nowrap;
}
.s-actions {
  display: flex;
  align-items: center;
  gap: 4px;
  flex: none;
  opacity: 0;
  transition: opacity 0.15s;
}
.session-row:hover .s-actions {
  opacity: 1;
}
.s-more {
  color: #9aa0a6;
}
</style>
