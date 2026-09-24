<script setup lang="ts">
import { nextTick, onMounted, ref, computed, watch } from "vue";
import { useRoute, useRouter } from "vue-router";
import { api } from "./api/client";
import NewSessionModal from "./components/NewSessionModal.vue";
import AppLogo from "./components/AppLogo.vue";
import AgentsView from "./views/AgentsView.vue";
import KeysView from "./views/KeysView.vue";
import TemplatesView from "./views/TemplatesView.vue";

const route = useRoute();
const router = useRouter();

function goHome() {
  if (route.path !== "/") router.push("/");
}

const projects = ref<any[]>([]);
const recent = ref<any[]>([]);
const archivedRecent = ref<any[]>([]);
const query = ref("");
const showNew = ref(false);
const showNewProject = ref(false);
const newProjectName = ref("");
const newProjectFolder = ref("");
const showHistory = ref(false);
const historySessions = ref<any[]>([]);
const historyQuery = ref("");
const historyLoading = ref(false);
const showSettings = ref(false);
const settingsTab = ref("archive");

const navGroups = [
  {
    title: "通用",
    items: [{ key: "archive", label: "归档与恢复" }],
  },
  {
    title: "管理",
    items: [
      { key: "agents", label: "Agent 管理" },
      { key: "keys", label: "API Key 管理" },
      { key: "templates", label: "岗位模板" },
    ],
  },
  {
    title: "其他",
    items: [
      { key: "help", label: "功能帮助" },
      { key: "about", label: "关于" },
    ],
  },
];

function onNavClick(key: string) {
  // 管理类直接在右侧内嵌操作，不跳转
  settingsTab.value = key;
}

// 岗位模板页「用此模板新建 Agent」→ 切到 Agent 管理并预填表单
const agentsViewRef = ref<any>(null);
function onUseTemplate(t: any) {
  settingsTab.value = "agents";
  nextTick(() => agentsViewRef.value?.openCreateAgent?.(t));
}
const collapsed = ref<Record<string, boolean>>({ projects: false, recent: false });

const activeProjects = computed(() =>
  projects.value.filter((p) => p.status !== "archived")
);
const archivedProjects = computed(() =>
  projects.value.filter((p) => p.status === "archived")
);

function sessionPath(s: any) {
  return s.project_id
    ? `/projects/${s.project_id}/sessions/${s.id}`
    : `/sessions/${s.id}`;
}
function projectName(id: number | null | undefined) {
  if (id == null) return "";
  const p = projects.value.find((x) => x.id === id);
  return p ? p.name : "";
}
function isActiveSession(s: any) {
  return route.path.endsWith(`/sessions/${s.id}`);
}
function isActiveProject(p: any) {
  return route.path.startsWith(`/projects/${p.id}`);
}

const filteredProjects = computed(() => {
  const q = query.value.trim().toLowerCase();
  if (!q) return activeProjects.value;
  return activeProjects.value.filter(
    (p) =>
      String(p.name || "").toLowerCase().includes(q) ||
      String(p.description || "").toLowerCase().includes(q)
  );
});
const filteredRecent = computed(() => {
  const q = query.value.trim().toLowerCase();
  if (!q) return recent.value;
  return recent.value.filter((s) =>
    String(s.title || "").toLowerCase().includes(q)
  );
});

async function load() {
  try {
    [projects.value, recent.value, archivedRecent.value] = await Promise.all([
      api.listProjects(),
      api.listRecentSessions(),
      api.listRecentSessions(30, true),
    ]);
  } catch (e: any) {
    console.error("加载侧边栏失败", e);
  }
}

// 新建项目（侧边栏「项目」分组右侧 ＋）
async function createProject() {
  const name = newProjectName.value.trim();
  if (!name) return;
  try {
    const p = await api.createProject(name, undefined, newProjectFolder.value.trim() || undefined);
    showNewProject.value = false;
    newProjectName.value = "";
    newProjectFolder.value = "";
    await load();
    router.push(`/projects/${p.id}`);
  } catch (e: any) {
    console.error("创建项目失败", e);
  }
}

// 历史对话管理
async function openHistory() {
  showHistory.value = true;
  historyQuery.value = "";
  await loadHistory();
}
async function loadHistory() {
  historyLoading.value = true;
  try {
    historySessions.value = await api.listAllSessions(500);
  } catch (e: any) {
    console.error("加载历史对话失败", e);
  } finally {
    historyLoading.value = false;
  }
}
const filteredHistory = computed(() => {
  const q = historyQuery.value.trim().toLowerCase();
  if (!q) return historySessions.value;
  return historySessions.value.filter((s) =>
    String(s.title || "").toLowerCase().includes(q)
  );
});
async function restoreHistorySession(s: any) {
  try {
    await api.archiveSession(s.id, false);
    await loadHistory();
  } catch (e: any) {
    console.error("恢复对话失败", e);
  }
}
async function deleteHistorySession(s: any) {
  try {
    await api.deleteSession(s.id);
    await loadHistory();
    load();
  } catch (e: any) {
    console.error("删除对话失败", e);
  }
}
function gotoHistorySession(s: any) {
  showHistory.value = false;
  router.push(sessionPath(s));
}

// 重命名
const renameTarget = ref<any>(null); // { type: 'project'|'session', id, name }
const renameValue = ref("");
const showRename = ref(false);

function startRename(type: "project" | "session", item: any) {
  renameTarget.value = { type, id: item.id, name: item.name || item.title || "" };
  renameValue.value = renameTarget.value.name;
  showRename.value = true;
}
async function confirmRename() {
  if (!renameValue.value.trim() || !renameTarget.value) return;
  try {
    if (renameTarget.value.type === "project") {
      await api.renameProject(renameTarget.value.id, renameValue.value.trim());
    } else {
      await api.renameSession(renameTarget.value.id, renameValue.value.trim());
    }
    showRename.value = false;
    load();
  } catch (e: any) {
    console.error("重命名失败", e);
  }
}

// 删除确认
const deleteTarget = ref<any>(null);
const showDelete = ref(false);
const deleteFolderCheck = ref(false);
function startDelete(type: "project" | "session", item: any) {
  deleteTarget.value = { type, id: item.id, name: item.name || item.title || "", folder_path: item.folder_path };
  deleteFolderCheck.value = false;
  showDelete.value = true;
}
async function confirmDelete() {
  if (!deleteTarget.value) return;
  try {
    if (deleteTarget.value.type === "project") {
      const r = await api.deleteProject(deleteTarget.value.id, deleteFolderCheck.value);
      window.$message?.success(r.folder_deleted ? "已删除（含本地文件夹）" : "已删除");
    } else {
      await api.deleteSession(deleteTarget.value.id);
      window.$message?.success("已删除");
    }
    showDelete.value = false;
    load();
  } catch (e: any) {
    console.error("删除失败", e);
  }
}

// 归档 / 恢复
async function toggleArchive(type: "project" | "session", item: any) {
  const archived = item.status !== "archived";
  const label = item.name || item.title || "";
  try {
    if (type === "project") {
      await api.archiveProject(item.id, archived);
      // 归档当前正在查看的项目时，跳回主页，避免停留在已归档页面造成"没反应"
      if (archived && route.path.startsWith(`/projects/${item.id}`)) {
        router.push("/");
      }
    } else {
      await api.archiveSession(item.id, archived);
      // 归档当前正在查看的会话时，跳回主页，避免停留在已归档会话造成"没反应"
      if (archived && route.path.endsWith(`/sessions/${item.id}`)) {
        router.push("/");
      }
    }
    load();
    window.$message?.success(archived ? `已归档「${label}」` : `已恢复「${label}」`);
  } catch (e: any) {
    console.error("归档操作失败", e);
    window.$message?.error(archived ? `归档「${label}」失败` : `恢复「${label}」失败`);
  }
}

function projectActions(p: any) {
  return [
    { label: "重命名", key: "rename" },
    { label: p.status === "archived" ? "恢复" : "归档", key: "archive" },
    { label: "删除", key: "delete", type: "error" as const },
  ];
}
function sessionActions(s: any) {
  return [
    { label: "重命名", key: "rename" },
    { label: s.status === "archived" ? "恢复" : "归档", key: "archive" },
    { label: "删除", key: "delete", type: "error" as const },
  ];
}
function onProjectAction(key: string, p: any) {
  if (key === "rename") startRename("project", p);
  else if (key === "archive") toggleArchive("project", p);
  else if (key === "delete") startDelete("project", p);
}
function onSessionAction(key: string, s: any) {
  if (key === "rename") startRename("session", s);
  else if (key === "archive") toggleArchive("session", s);
  else if (key === "delete") startDelete("session", s);
}

// 拖拽：把无项目对话拖进项目
const dragSessionId = ref<number | null>(null);
function onDragStart(s: any) {
  dragSessionId.value = s.id;
}
async function onDropToProject(p: any) {
  if (dragSessionId.value == null) return;
  const sid = dragSessionId.value;
  dragSessionId.value = null;
  try {
    await api.moveSession(sid, p.id);
    load();
  } catch (e: any) {
    console.error("移动对话失败", e);
  }
}

onMounted(load);
watch(() => route.fullPath, load);
</script>

<template>
  <n-config-provider :theme-overrides="{ common: { primaryColor: '#6366f1' } }">
    <n-message-provider>
      <n-dialog-provider>
        <div class="shell">
          <aside class="sidebar">
            <div class="sb-brand" title="回到首页" @click="goHome">
              <AppLogo :size="26" />
              <span>Multi-agent</span>
            </div>

            <div class="sb-actions">
              <n-button type="primary" block class="sb-new-btn" @click="showNew = true">
                ＋ 新对话
              </n-button>
            </div>

            <div class="sb-search">
              <n-input
                v-model:value="query"
                placeholder="搜索项目 / 对话…"
                clearable
                size="small"
              >
                <template #prefix>
                  <span class="sb-search-icon">🔍</span>
                </template>
              </n-input>
            </div>

            <div class="sb-groups">
              <!-- 项目分组 -->
              <div class="sb-group">
                <div class="sb-group-title" @click="collapsed.projects = !collapsed.projects">
                  <span>项目</span>
                  <span class="sb-title-right">
                    <span class="sb-add-project" title="新建项目" @click.stop="showNewProject = true">＋</span>
                    <span class="sb-add-project" title="历史对话管理" @click.stop="openHistory">
                      <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="9"/><path d="M12 7v5l3 2"/></svg>
                    </span>
                  </span>
                </div>
                <div v-show="!collapsed.projects" class="sb-group-list">
                  <template v-if="filteredProjects.length">
                    <div
                      v-for="p in filteredProjects"
                      :key="p.id"
                      class="sb-item"
                      :class="{ active: isActiveProject(p), 'sb-drop-zone': true }"
                      @click="router.push(`/projects/${p.id}`)"
                      @dragover.prevent
                      @drop.prevent="onDropToProject(p)"
                    >
                      <span class="sb-item-icon"><svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M22 19a2 2 0 0 1-2 2H4a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h5l2 3h9a2 2 0 0 1 2 2z"/></svg></span>
                      <span class="sb-item-label">{{ p.name }}</span>
                      <span class="sb-item-more" @click.stop>
                        <n-dropdown
                          trigger="click"
                          :options="projectActions(p)"
                          @select="(k: string) => onProjectAction(k, p)"
                        >
                          <n-button size="tiny" quaternary class="sb-more-btn">⋯</n-button>
                        </n-dropdown>
                      </span>
                    </div>
                  </template>
                  <div v-else class="sb-empty">暂无项目</div>
                </div>
              </div>

              <!-- 最近分组 -->
              <div class="sb-group">
                <div class="sb-group-title" @click="collapsed.recent = !collapsed.recent">
                  <span>最近</span>
                  <span class="sb-caret">{{ collapsed.recent ? "▸" : "▾" }}</span>
                </div>
                <div v-show="!collapsed.recent" class="sb-group-list">
                  <template v-if="filteredRecent.length">
                    <div
                      v-for="s in filteredRecent"
                      :key="s.id"
                      class="sb-item sb-drag"
                      :class="{ active: isActiveSession(s) }"
                      :draggable="true"
                      @click="router.push(sessionPath(s))"
                      @dragstart="onDragStart(s)"
                    >
                      <span class="sb-item-icon"><svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z"/></svg></span>
                      <span class="sb-item-label">{{ s.title }}</span>
                      <span class="sb-item-more" @click.stop>
                        <n-dropdown
                          trigger="click"
                          :options="sessionActions(s)"
                          @select="(k: string) => onSessionAction(k, s)"
                        >
                          <n-button size="tiny" quaternary class="sb-more-btn">⋯</n-button>
                        </n-dropdown>
                      </span>
                    </div>
                    <div class="sb-hint">拖拽到左侧项目可归组</div>
                  </template>
                  <div v-else class="sb-empty">暂无独立对话</div>
                </div>
              </div>
            </div>

            <div class="sb-footer">
              <div class="sb-item" @click="showSettings = true">
                <span class="sb-item-icon"><svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="3"/><path d="M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 0 1 0 2.83 2 2 0 0 1-2.83 0l-.06-.06a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0 0 1-2 2 2 2 0 0 1-2-2v-.09A1.65 1.65 0 0 0 9 19.4a1.65 1.65 0 0 0-1.82.33l-.06.06a2 2 0 0 1-2.83 0 2 2 0 0 1 0-2.83l.06-.06a1.65 1.65 0 0 0 .33-1.82 1.65 1.65 0 0 0-1.51-1H3a2 2 0 0 1-2-2 2 2 0 0 1 2-2h.09A1.65 1.65 0 0 0 4.6 9a1.65 1.65 0 0 0-.33-1.82l-.06-.06a2 2 0 0 1 0-2.83 2 2 0 0 1 2.83 0l.06.06a1.65 1.65 0 0 0 1.82.33H9a1.65 1.65 0 0 0 1-1.51V3a2 2 0 0 1 2-2 2 2 0 0 1 2 2v.09a1.65 1.65 0 0 0 1 1.51 1.65 1.65 0 0 0 1.82-.33l.06-.06a2 2 0 0 1 2.83 0 2 2 0 0 1 0 2.83l-.06.06a1.65 1.65 0 0 0-.33 1.82V9a1.65 1.65 0 0 0 1.51 1H21a2 2 0 0 1 2 2 2 2 0 0 1-2 2h-.09a1.65 1.65 0 0 0-1.51 1z"/></svg></span>
                <span class="sb-item-label">设置</span>
              </div>
            </div>
          </aside>

          <main class="sb-main">
            <router-view />
          </main>

          <NewSessionModal v-model:show="showNew" @created="load" />

          <!-- 设置全屏页 -->
          <div v-if="showSettings" class="settings-full">
            <aside class="settings-nav">
              <div class="settings-back" @click="showSettings = false">← 返回应用</div>
              <div v-for="g in navGroups" :key="g.title" class="settings-nav-group">
                <div class="settings-nav-group-title">{{ g.title }}</div>
                <div
                  v-for="item in g.items"
                  :key="item.key"
                  class="settings-nav-item"
                  :class="{ active: settingsTab === item.key }"
                  @click="onNavClick(item.key)"
                >
                  {{ item.label }}
                </div>
              </div>
            </aside>

            <div class="settings-main">
              <!-- 归档与恢复 -->
              <div v-if="settingsTab === 'archive'" class="settings-content">
                <div class="settings-page-title">归档与恢复</div>
                <div class="settings-block">
                  <div class="settings-block-title">已归档项目</div>
                  <div v-if="archivedProjects.length === 0" class="settings-empty">暂无已归档项目</div>
                  <div v-for="p in archivedProjects" :key="p.id" class="settings-row">
                    <div class="settings-row-text">
                      <div class="settings-row-label"><svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" style="vertical-align:-2px;margin-right:4px"><path d="M22 19a2 2 0 0 1-2 2H4a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h5l2 3h9a2 2 0 0 1 2 2z"/></svg>{{ p.name }}</div>
                      <div class="settings-row-desc">归档于 {{ new Date(p.created_at).toLocaleString() }}</div>
                    </div>
                    <div class="settings-row-actions">
                      <n-button size="small" type="primary" ghost @click="toggleArchive('project', p)">恢复</n-button>
                      <n-button size="small" quaternary @click="startDelete('project', p)">删除</n-button>
                    </div>
                  </div>
                </div>
                <div class="settings-block">
                  <div class="settings-block-title">已归档对话</div>
                  <div v-if="archivedRecent.length === 0" class="settings-empty">暂无已归档对话</div>
                  <div v-for="s in archivedRecent" :key="s.id" class="settings-row">
                    <div class="settings-row-text">
                      <div class="settings-row-label"><svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" style="vertical-align:-2px;margin-right:4px"><path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z"/></svg>{{ s.title }}<span v-if="s.project_id != null" class="settings-row-project"> · {{ projectName(s.project_id) }}</span></div>
                      <div class="settings-row-desc">归档于 {{ new Date(s.created_at).toLocaleString() }}</div>
                    </div>
                    <div class="settings-row-actions">
                      <n-button size="small" type="primary" ghost @click="toggleArchive('session', s)">恢复</n-button>
                      <n-button size="small" quaternary @click="startDelete('session', s)">删除</n-button>
                    </div>
                  </div>
                </div>
              </div>

              <!-- 功能帮助 -->
              <div v-else-if="settingsTab === 'help'" class="settings-content about-page">
                <!-- Hero 卡片：项目介绍 -->
                <div class="about-hero">
                  <div class="about-hero-blob about-hero-blob-a"></div>
                  <div class="about-hero-blob about-hero-blob-b"></div>
                  <div class="about-logo">
                    <AppLogo :size="84" />
                  </div>
                  <div class="about-name">Multi-agent · 多 Agent 协作</div>
                  <div class="about-ver">
                    <span class="about-ver-badge">v0.2.0</span>
                  </div>
                  <p class="about-desc">
                    让多个不同 AI Agent 在同一个「群聊」里协作完成任务，指定一个主理人前台收口：
                    简单问题直接答，复杂任务自动拆解派活、验收汇总后告诉你。支持上传图片 / PDF / Office 文档，AI 直接看懂内容。
                  </p>
                </div>

                <!-- 快速上手 -->
                <div class="about-section">
                  <div class="about-section-title">快速上手</div>
                  <div class="help-steps">
                    <div class="help-step">
                      <div class="help-step-num">1</div>
                      <div class="help-step-body">
                        <div class="help-step-title">配置 API Key</div>
                        <div class="help-step-desc">进入「API Key 管理」，为使用的模型（OpenAI / Anthropic / 火山方舟 / OpenRouter）配置 Key，Key 加密保存在系统钥匙串。</div>
                      </div>
                    </div>
                    <div class="help-step">
                      <div class="help-step-num">2</div>
                      <div class="help-step-body">
                        <div class="help-step-title">新建群聊对话</div>
                        <div class="help-step-desc">点击「＋ 新对话」选择参与 Agent，中途可随时把更多 Agent 拉进群。</div>
                      </div>
                    </div>
                    <div class="help-step">
                      <div class="help-step-num">3</div>
                      <div class="help-step-body">
                        <div class="help-step-title">指定主理人并下达任务</div>
                        <div class="help-step-desc">指定任一 Agent 担任主理人，下达任务后自动完成「拆解 → 派活 → 并行/串行执行 → 验收 → 汇总」。</div>
                      </div>
                    </div>
                    <div class="help-step">
                      <div class="help-step-num">4</div>
                      <div class="help-step-body">
                        <div class="help-step-title">查看与导出产物</div>
                        <div class="help-step-desc">沙箱运行代码自动沉淀「源代码 / 运行输出 / 生成的图片文档」，在右侧产物面板查看或下载到本地。</div>
                      </div>
                    </div>
                  </div>
                </div>

                <!-- 核心功能 -->
                <div class="about-section">
                  <div class="about-section-title">使用技巧</div>
                  <div class="help-tips">
                    <div class="help-tip"><span class="help-tip-k">拖拽归组</span>把「最近」里的无项目对话直接拖到左侧项目上，即可归入该项目。</div>
                    <div class="help-tip"><span class="help-tip-k">定向发言</span>输入框内输入 @Agent名（或点击 @ 按钮），可指定某个 Agent 单独回答。</div>
                    <div class="help-tip"><span class="help-tip-k">随时拉人</span>会话进行中可随时把更多 Agent 拉进群，共同参与讨论。</div>
                    <div class="help-tip"><span class="help-tip-k">多轮验收</span>主理人验收不通过时可要求重做，直到产出满意为止。</div>
                    <div class="help-tip"><span class="help-tip-k">编辑记忆</span>项目记忆支持手动增删，把关键结论固化下来供后续对话参考。</div>
                    <div class="help-tip"><span class="help-tip-k">模板导入</span>在「岗位模板」里用内置模板一键生成 Agent，无需从零配置。</div>
                    <div class="help-tip"><span class="help-tip-k">附件上传</span>点输入区 📎 多选文件（最多 10 个），先在待发栏预览/删除，点发送才真正上传。</div>
                    <div class="help-tip"><span class="help-tip-k">多模态看图</span>上传图片 / PDF 后，AI 直接看到内容；PDF 前 3 页转图传视觉模型，扫描版发票也能读。</div>
                    <div class="help-tip"><span class="help-tip-k">Office 预览</span>docx / xlsx / pptx 点击后新标签页打开（后端自动转 PDF），不再是下载。</div>
                  </div>
                </div>

                <!-- 常见问题 -->
                <div class="about-section">
                  <div class="about-section-title">常见问题</div>
                  <n-collapse class="help-faq" arrow-placement="right">
                    <n-collapse-item title="API Key 安全吗？存到哪里？">
                      <div class="help-faq-answer">Key 加密存储在系统钥匙串（Keychain），不落明文，可随时在「API Key 管理」编辑或复制。</div>
                    </n-collapse-item>
                    <n-collapse-item title="代码沙箱的隔离可靠吗？">
                      <div class="help-faq-answer">默认 L1 进程级隔离（资源限制 + 超时 + 独立工作目录），适合大多数场景，但并非绝对沙箱；对敏感任务可在会话中启用 L2 Docker 沙箱（默认禁网 + 只读挂载）。</div>
                    </n-collapse-item>
                    <n-collapse-item title="如何新增自定义 Agent？">
                      <div class="help-faq-answer">进入「Agent 管理」新建，自定义人设、模型与 Key；也可以在「岗位模板」选中模板后一键导入，快速生成。</div>
                    </n-collapse-item>
                    <n-collapse-item title="后端服务是怎么运行的？">
                      <div class="help-faq-answer">桌面客户端内嵌后端 sidecar，启动时自动拉起 FastAPI 服务（监听 127.0.0.1:8765），无需手动操作；开发调试时也可单独运行后端。</div>
                    </n-collapse-item>
                    <n-collapse-item title="产物在哪里查看？">
                      <div class="help-faq-answer">沙箱运行产生的源代码、运行输出、图片文档会自动沉淀到右侧「产物」面板，可在线查看或下载到本地。</div>
                    </n-collapse-item>
                    <n-collapse-item title="上传的附件 AI 能读到吗？支持哪些格式？">
                      <div class="help-faq-answer">图片（png/jpg/gif）AI 直接看图；PDF 前 3 页转图 + 全文文字提取，扫描版也能读；docx/xlsx 自动提取文字；txt/md/py 等文本直接读内容。视频暂不支持识别。</div>
                    </n-collapse-item>
                    <n-collapse-item title="主理人模式和原来有什么区别？">
                      <div class="help-faq-answer">有主理人的会话默认只有主理人回复，不会 7 个 Agent 排队刷屏；简单问题它直接答，复杂任务它在后台拆活派给其他成员，验收后汇总告诉你结果。</div>
                    </n-collapse-item>
                  </n-collapse>
                </div>

                <!-- 技术架构 -->
                <div class="about-section">
                  <div class="about-section-title">技术架构</div>
                  <div class="help-arch">
                    <div class="help-arch-row">
                      <span class="help-arch-key">前端</span>
                      <span class="help-arch-val">Tauri 2 · Vue 3 · Naive UI（桌面壳 + UI）</span>
                    </div>
                    <div class="help-arch-row">
                      <span class="help-arch-key">后端</span>
                      <span class="help-arch-val">Python FastAPI 本地编排服务（随客户端启动，监听 127.0.0.1:8765）</span>
                    </div>
                    <div class="help-arch-subs">
                      <div><b>engine</b>　主理人调度状态机 · 消息路由 · 项目记忆 · 事件总线</div>
                      <div><b>providers</b>　OpenAI · Anthropic · 火山方舟 · OpenRouter 统一适配层</div>
                      <div><b>tools/executor</b>　代码沙箱（L1 本地受限进程 + L2 Docker）</div>
                      <div><b>core</b>　SQLite 存储 + Keychain 加密</div>
                    </div>
                  </div>
                </div>

                <!-- 安全说明 -->
                <div class="about-section">
                  <div class="about-section-title">安全说明</div>
                  <div class="help-safe">
                    <div class="help-safe-item">🔑 <b>API Key</b>：加密存储于系统钥匙串，不落明文。</div>
                    <div class="help-safe-item">🛡 <b>代码沙箱</b>：默认 L1 进程级隔离（资源限制 + 超时 + 独立工作目录），非绝对沙箱；需更强隔离时在会话中启用 Docker（L2，默认禁网 + 只读挂载）。</div>
                  </div>
                </div>
              </div>

              <!-- 关于 -->
              <div v-else-if="settingsTab === 'about'" class="settings-content about-page">
                <!-- Hero 卡片：应用身份 -->
                <div class="about-hero">
                  <div class="about-hero-blob about-hero-blob-a"></div>
                  <div class="about-hero-blob about-hero-blob-b"></div>
                  <div class="about-logo">
                    <AppLogo :size="84" />
                  </div>
                  <div class="about-name">Multi-agent · 多 Agent 协作</div>
                  <div class="about-ver">
                    <span class="about-ver-badge">v0.2.0</span>
                  </div>
                  <p class="about-desc">
                    让多个不同 AI Agent 在同一个「群聊」里协作完成任务，指定一个主理人前台收口：
                    简单问题直接答，复杂任务自动拆解派活、验收汇总后告诉你。支持上传图片 / PDF / Office 文档，AI 直接看懂内容。
                  </p>
                </div>

                <!-- 核心能力 -->
                <div class="about-section">
                  <div class="about-section-title">核心能力</div>
                  <div class="about-feats">
                    <div class="about-feat">
                      <div class="about-feat-icon">
                        <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="10"/><circle cx="12" cy="12" r="6"/><circle cx="12" cy="12" r="2"/></svg>
                      </div>
                      <div class="about-feat-body">
                        <div class="about-feat-title">主理人调度</div>
                        <div class="about-feat-desc">任务拆解 → 派活 → 执行 → 验收 → 汇总</div>
                      </div>
                    </div>
                    <div class="about-feat">
                      <div class="about-feat-icon">
                        <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M17 21v-2a4 4 0 0 0-4-4H5a4 4 0 0 0-4 4v2"/><circle cx="9" cy="7" r="4"/><path d="M23 21v-2a4 4 0 0 0-3-3.87"/><path d="M16 3.13a4 4 0 0 1 0 7.75"/></svg>
                      </div>
                      <div class="about-feat-body">
                        <div class="about-feat-title">多角色协作</div>
                        <div class="about-feat-desc">22 个内置行业顶级岗位，随时拉人进群</div>
                      </div>
                    </div>
                    <div class="about-feat">
                      <div class="about-feat-icon">
                        <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M21.44 11.05l-9.19 9.19a6 6 0 0 1-8.49-8.49l9.19-9.19a4 4 0 0 1 5.66 5.66l-9.2 9.19a2 2 0 0 1-2.83-2.83l8.49-8.48"/></svg>
                      </div>
                      <div class="about-feat-body">
                        <div class="about-feat-title">附件多模态</div>
                        <div class="about-feat-desc">图片 / PDF / Office 文档，AI 直接看懂内容</div>
                      </div>
                    </div>
                    <div class="about-feat">
                      <div class="about-feat-icon">
                        <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><rect x="2" y="2" width="20" height="8" rx="2"/><rect x="2" y="14" width="20" height="8" rx="2"/><line x1="6" y1="6" x2="6.01" y2="6"/><line x1="6" y1="18" x2="6.01" y2="18"/></svg>
                      </div>
                      <div class="about-feat-body">
                        <div class="about-feat-title">多模型接入</div>
                        <div class="about-feat-desc">OpenAI / Anthropic / 火山方舟 / OpenRouter</div>
                      </div>
                    </div>
                    <div class="about-feat">
                      <div class="about-feat-icon">
                        <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M21 16V8a2 2 0 0 0-1-1.73l-7-4a2 2 0 0 0-2 0l-7 4A2 2 0 0 0 3 8v8a2 2 0 0 0 1 1.73l7 4a2 2 0 0 0 2 0l7-4A2 2 0 0 0 21 16z"/><polyline points="3.27 6.96 12 12.01 20.73 6.96"/><line x1="12" y1="22.08" x2="12" y2="12"/></svg>
                      </div>
                      <div class="about-feat-body">
                        <div class="about-feat-title">产物归档</div>
                        <div class="about-feat-desc">沙箱运行沉淀源代码 / 输出 / 图片文档</div>
                      </div>
                    </div>
                    <div class="about-feat">
                      <div class="about-feat-icon">
                        <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M12 2a7 7 0 0 1 7 7c0 2.5-1.3 4.5-3 5.6V17a2 2 0 0 1-2 2h-4a2 2 0 0 1-2-2v-2.4c-1.7-1.1-3-3.1-3-5.6a7 7 0 0 1 7-7z"/><line x1="9" y1="22" x2="15" y2="22"/></svg>
                      </div>
                      <div class="about-feat-body">
                        <div class="about-feat-title">项目记忆</div>
                        <div class="about-feat-desc">关键结论自动沉淀，对话自动参考</div>
                      </div>
                    </div>
                  </div>
                </div>

                <!-- 应用信息 -->
                <div class="about-section">
                  <div class="about-section-title">应用信息</div>
                  <div class="about-info">
                    <div class="about-info-row">
                      <span class="about-info-label">版本</span>
                      <span class="about-info-value">v0.2.0</span>
                    </div>
                    <div class="about-info-row">
                      <span class="about-info-label">应用类型</span>
                      <span class="about-info-value">桌面客户端（macOS）</span>
                    </div>
                    <div class="about-info-row">
                      <span class="about-info-label">前端</span>
                      <span class="about-info-value">Tauri 2 · Vue 3 · Naive UI</span>
                    </div>
                    <div class="about-info-row">
                      <span class="about-info-label">后端</span>
                      <span class="about-info-value">Python FastAPI</span>
                    </div>
                    <div class="about-info-row">
                      <span class="about-info-label">数据存储</span>
                      <span class="about-info-value">SQLite · 系统钥匙串</span>
                    </div>
                  </div>
                </div>

                <div class="about-copy">© 2026 Multi-agent. All rights reserved.</div>
              </div>

              <!-- 管理三个独立页面（Agent / API Key / 岗位模板） -->
              <AgentsView v-else-if="settingsTab === 'agents'" ref="agentsViewRef" @go-templates="settingsTab = 'templates'" />
              <KeysView v-else-if="settingsTab === 'keys'" />
              <TemplatesView v-else-if="settingsTab === 'templates'" @use-template="onUseTemplate" />
            </div>
          </div>

          <!-- 新建项目 -->
          <n-modal v-model:show="showNewProject" preset="card" title="新建项目" style="width: 460px">
            <n-space vertical size="small">
              <n-input
                v-model:value="newProjectName"
                placeholder="项目名称（必填）"
                maxlength="60"
                @keydown.enter.prevent="createProject"
              />
              <n-input
                v-model:value="newProjectFolder"
                placeholder="绑定本地文件夹（可选）：如 /Users/me/projects/my-app 或 D:\work\my-app"
                clearable
              />
              <span class="np-tip">不填则产物保存到默认工作区 ~/Multi-agent/项目名 下；填写后将全部保存到该文件夹。</span>
            </n-space>
            <template #footer>
              <n-space justify="end">
                <n-button @click="showNewProject = false">取消</n-button>
                <n-button type="primary" :disabled="!newProjectName.trim()" @click="createProject">创建</n-button>
              </n-space>
            </template>
          </n-modal>

          <!-- 历史对话管理 -->
          <n-modal v-model:show="showHistory" preset="card" title="历史对话管理" style="width: 560px">
            <n-input
              v-model:value="historyQuery"
              placeholder="搜索历史对话标题…"
              clearable
              size="small"
              style="margin-bottom: 10px"
            />
            <div class="history-list">
              <n-spin :show="historyLoading">
                <div v-if="!historyLoading && filteredHistory.length === 0" class="history-empty">暂无历史对话</div>
                <div
                  v-for="s in filteredHistory"
                  :key="s.id"
                  class="history-item"
                  @click="gotoHistorySession(s)"
                >
                  <span class="history-icon">💬</span>
                  <span class="history-label">{{ s.title || "未命名对话" }}</span>
                  <span v-if="s.project_id" class="history-project">📁 {{ projectName(s.project_id) }}</span>
                  <n-tag v-if="s.status === 'archived'" size="tiny" type="warning">已归档</n-tag>
                  <span class="history-actions" @click.stop>
                    <n-button v-if="s.status === 'archived'" size="tiny" quaternary @click="restoreHistorySession(s)">恢复</n-button>
                    <n-popconfirm @positive-click="deleteHistorySession(s)">
                      <template #trigger>
                        <n-button size="tiny" quaternary type="error">删除</n-button>
                      </template>
                      确定删除对话「{{ s.title }}」？其下消息、任务与产物将一并删除且不可恢复。
                    </n-popconfirm>
                  </span>
                </div>
              </n-spin>
            </div>
          </n-modal>

          <!-- 重命名 -->
          <n-modal v-model:show="showRename" preset="card" :title="`重命名${renameTarget?.type === 'project' ? '项目' : '会话'}`" style="width: 440px">
            <n-input v-model:value="renameValue" placeholder="名称" maxlength="120" @keydown.enter.prevent="confirmRename" />
            <template #footer>
              <n-space justify="end">
                <n-button @click="showRename = false">取消</n-button>
                <n-button type="primary" @click="confirmRename">保存</n-button>
              </n-space>
            </template>
          </n-modal>

          <!-- 删除确认 -->
          <n-modal v-model:show="showDelete" preset="card" :title="`删除${deleteTarget?.type === 'project' ? '项目' : '会话'}`" style="width: 440px">
            <p style="color:#666">
              确定删除{{ deleteTarget?.type === "project" ? "项目" : "会话" }}「<b>{{ deleteTarget?.name }}</b>」吗？
              其下所有消息、任务将一并删除，且不可恢复。
            </p>
            <div v-if="deleteTarget?.type === 'project'" style="margin-top:12px">
              <template v-if="deleteTarget.folder_path">
                <div style="color:#999;font-size:12px">
                  绑定目录由你管理，删除项目不会影响：<b style="color:#666">{{ deleteTarget.folder_path }}</b>
                </div>
              </template>
              <template v-else>
                <label style="display:flex;align-items:center;gap:6px;cursor:pointer;font-size:13px">
                  <input type="checkbox" v-model="deleteFolderCheck" />
                  <span>同时删除项目文件夹（含产物）</span>
                </label>
                <div style="color:#999;font-size:12px;margin-top:4px">删除后不可恢复。未绑定目录的项目产物默认保存在 ~/Multi-agent/{{ deleteTarget.name }}</div>
              </template>
            </div>
            <template #footer>
              <n-space justify="end">
                <n-button @click="showDelete = false">取消</n-button>
                <n-button type="error" @click="confirmDelete">删除</n-button>
              </n-space>
            </template>
          </n-modal>
        </div>
      </n-dialog-provider>
    </n-message-provider>
  </n-config-provider>
</template>

<style scoped>
.shell {
  display: flex;
  height: 100vh;
  overflow: hidden;
}
.sidebar {
  width: 250px;
  flex-shrink: 0;
  display: flex;
  flex-direction: column;
  border-right: 1px solid #eceef2;
  background: #f7f8fa;
}
.sb-brand {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 18px 16px 12px;
  font-size: 18px;
  font-weight: 700;
  letter-spacing: 0.5px;
  cursor: pointer;
  user-select: none;
  border-radius: 8px;
}
.sb-brand:hover {
  color: #4f46e5;
}
.sb-actions {
  padding: 0 12px 10px;
}
.sb-new-btn {
  border-radius: 8px;
}
.sb-search {
  padding: 0 12px 10px;
}
.sb-search-icon {
  color: #999;
  font-size: 12px;
}
.sb-groups {
  flex: 1;
  overflow-y: auto;
  padding: 0 8px;
}
.sb-group-title {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 10px 8px 6px;
  font-size: 12px;
  font-weight: 600;
  color: #888;
  cursor: pointer;
  user-select: none;
}
.sb-caret {
  font-size: 10px;
  color: #bbb;
}
.sb-title-right {
  display: flex;
  align-items: center;
  gap: 6px;
}
.sb-add-project {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  font-size: 14px;
  font-weight: 600;
  line-height: 1;
  color: #888;
  padding: 1px 4px;
  border-radius: 4px;
  opacity: 0;
  transition: opacity 0.15s ease, color 0.15s ease, background 0.15s ease;
  cursor: pointer;
}
.sb-add-project:hover {
  color: #4f46e5;
  background: #e8e9fd;
}
.sb-group-title:hover .sb-add-project {
  opacity: 1;
}
.np-tip {
  font-size: 12px;
  color: #999;
  line-height: 1.5;
}
.history-list {
  max-height: 420px;
  overflow-y: auto;
}
.history-item {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 8px 10px;
  border-radius: 6px;
  cursor: pointer;
  font-size: 13px;
}
.history-item:hover {
  background: #eef0f3;
}
.history-icon {
  flex-shrink: 0;
}
.history-label {
  flex: 1;
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.history-project {
  flex-shrink: 0;
  font-size: 12px;
  color: #999;
}
.history-actions {
  flex-shrink: 0;
  display: flex;
  align-items: center;
  gap: 2px;
}
.history-empty {
  padding: 30px 0;
  text-align: center;
  color: #999;
  font-size: 13px;
}
.sb-group-list {
  padding-bottom: 4px;
}
.sb-item {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 7px 8px;
  border-radius: 6px;
  font-size: 13px;
  color: #333;
  cursor: pointer;
  user-select: none;
}
.sb-item:hover {
  background: #eef0f3;
}
.sb-item.active {
  background: #e8e9fd;
  color: #4f46e5;
  font-weight: 600;
}
.sb-item-icon {
  flex-shrink: 0;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 13px;
}
.sb-item-label {
  flex: 1;
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.sb-item-more {
  flex-shrink: 0;
  opacity: 0;
  transition: opacity 0.15s ease;
}
.sb-item:hover .sb-item-more,
.sb-item.active .sb-item-more {
  opacity: 1;
}
.sb-more-btn {
  width: 22px;
  height: 22px;
  min-width: 22px;
  padding: 0;
  font-size: 14px;
  color: inherit;
}
.sb-drag {
  cursor: grab;
}
.sb-drop-zone:hover {
  outline: 1px dashed #6366f1;
  outline-offset: -1px;
}
.sb-hint {
  padding: 4px 8px 8px;
  font-size: 11px;
  color: #bbb;
}
.set-about-copy {
  font-size: 11px;
  color: #bbb;
  margin-top: 12px;
}
/* ChatGPT 风格设置全屏 */
.settings-full {
  position: fixed;
  inset: 0;
  z-index: 2000;
  background: #fff;
  display: flex;
}
.settings-nav {
  width: 220px;
  flex-shrink: 0;
  border-right: 1px solid #eceef2;
  padding: 12px 8px;
  overflow-y: auto;
  background: #f7f8fa;
}
.settings-back {
  font-size: 13px;
  color: #555;
  padding: 8px 10px;
  margin-bottom: 6px;
  cursor: pointer;
  border-radius: 6px;
}
.settings-back:hover {
  background: #f0f1f3;
}
.settings-nav-group-title {
  font-size: 11px;
  font-weight: 600;
  color: #999;
  padding: 12px 10px 4px;
  text-transform: uppercase;
  letter-spacing: 0.3px;
}
.settings-nav-item {
  font-size: 13px;
  color: #333;
  padding: 7px 10px;
  border-radius: 6px;
  cursor: pointer;
  user-select: none;
}
.settings-nav-item:hover {
  background: #f0f1f3;
}
.settings-nav-item.active {
  background: #e8e9fd;
  color: #4f46e5;
  font-weight: 600;
}
.settings-main {
  flex: 1;
  min-width: 0;
  overflow: auto;
  background: #fff;
}
.settings-content {
  padding: 24px 32px;
  max-width: 760px;
}
.settings-page-title {
  font-size: 18px;
  font-weight: 700;
  margin-bottom: 18px;
}
.settings-block {
  margin-bottom: 22px;
}
.settings-block-title {
  font-size: 12px;
  font-weight: 600;
  color: #888;
  margin-bottom: 6px;
  text-transform: uppercase;
  letter-spacing: 0.3px;
}
.settings-row {
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 12px 0;
  border-bottom: 1px solid #f0f1f3;
}
.settings-row-text {
  flex: 1;
  min-width: 0;
}
.settings-row-label {
  font-size: 13px;
  font-weight: 600;
  color: #1f2329;
}
.settings-row-project {
  font-size: 12px;
  font-weight: 400;
  color: #8a8f99;
}
.settings-row-desc {
  font-size: 12px;
  color: #999;
  margin-top: 2px;
  line-height: 1.5;
}
.settings-row-value {
  font-size: 13px;
  color: #666;
  flex-shrink: 0;
}
.settings-row-actions {
  display: flex;
  gap: 4px;
  flex-shrink: 0;
}
.settings-empty {
  font-size: 12px;
  color: #bbb;
  padding: 12px 0;
  border-bottom: 1px solid #f0f1f3;
}
/* ===== 关于页 ===== */
.about-page {
  max-width: 720px;
  margin: 0 auto;
  padding: 32px 40px 40px;
}
.about-hero {
  position: relative;
  overflow: hidden;
  border-radius: 18px;
  border: 1px solid #e6e4ff;
  background: linear-gradient(150deg, #f1f0ff 0%, #fbfaff 55%, #ffffff 100%);
  padding: 40px 36px 34px;
  text-align: center;
}
.about-hero-blob {
  position: absolute;
  border-radius: 50%;
  filter: blur(2px);
  pointer-events: none;
}
.about-hero-blob-a {
  width: 240px;
  height: 240px;
  left: -90px;
  top: -110px;
  background: radial-gradient(circle, rgba(99, 102, 241, 0.18), transparent 70%);
}
.about-hero-blob-b {
  width: 220px;
  height: 220px;
  right: -80px;
  bottom: -100px;
  background: radial-gradient(circle, rgba(139, 92, 246, 0.16), transparent 70%);
}
.about-logo {
  position: relative;
  display: inline-flex;
  margin-bottom: 18px;
}
.about-name {
  position: relative;
  font-size: 21px;
  font-weight: 700;
  color: #1f2329;
  letter-spacing: 0.3px;
}
.about-ver {
  position: relative;
  margin: 10px 0 14px;
}
.about-ver-badge {
  display: inline-block;
  padding: 3px 12px;
  border-radius: 999px;
  background: #e8e9fd;
  color: #4f46e5;
  font-size: 12px;
  font-weight: 600;
  letter-spacing: 0.3px;
}
.about-desc {
  position: relative;
  max-width: 480px;
  margin: 0 auto;
  font-size: 13.5px;
  line-height: 1.75;
  color: #6b7280;
}

.about-section {
  margin-top: 28px;
}
.about-section-title {
  font-size: 16px;
  font-weight: 700;
  color: #1f2329;
  margin-bottom: 14px;
}
.about-feats {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 12px;
}
.about-feat {
  display: flex;
  align-items: flex-start;
  gap: 12px;
  padding: 16px;
  border-radius: 12px;
  border: 1px solid #eceef2;
  background: #fff;
  transition: box-shadow 0.18s ease, border-color 0.18s ease, transform 0.18s ease;
}
.about-feat:hover {
  border-color: #d5d3ff;
  box-shadow: 0 6px 18px rgba(99, 102, 241, 0.08);
  transform: translateY(-1px);
}
.about-feat-icon {
  flex-shrink: 0;
  width: 36px;
  height: 36px;
  border-radius: 10px;
  display: flex;
  align-items: center;
  justify-content: center;
  color: #6366f1;
  background: #f5f5ff;
  border: 1px solid #e8e8ff;
}
.about-feat-title {
  font-size: 13.5px;
  font-weight: 600;
  color: #1f2329;
  margin-bottom: 3px;
}
.about-feat-desc {
  font-size: 12px;
  line-height: 1.6;
  color: #8a8f99;
}

.about-info {
  border: 1px solid #eceef2;
  border-radius: 12px;
  background: #fff;
  overflow: hidden;
}
.about-info-row {
  display: flex;
  align-items: center;
  padding: 11px 16px;
  border-bottom: 1px solid #f0f1f3;
  font-size: 13px;
}
.about-info-row:last-child {
  border-bottom: none;
}
.about-info-label {
  width: 88px;
  flex-shrink: 0;
  color: #8a8f99;
  font-size: 12.5px;
}
.about-info-value {
  color: #1f2329;
  font-weight: 500;
}
.about-copy {
  text-align: center;
  font-size: 11px;
  color: #c2c5cd;
  margin-top: 30px;
}
/* ===== 功能帮助页 ===== */
.help-steps {
  display: flex;
  flex-direction: column;
  gap: 10px;
}
.help-step {
  display: flex;
  align-items: flex-start;
  gap: 12px;
  padding: 14px 16px;
  border-radius: 12px;
  border: 1px solid #eceef2;
  background: #fff;
}
.help-step-num {
  flex-shrink: 0;
  width: 26px;
  height: 26px;
  border-radius: 50%;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 13px;
  font-weight: 700;
  color: #4f46e5;
  background: #e8e9fd;
}
.help-step-title {
  font-size: 13.5px;
  font-weight: 600;
  color: #1f2329;
  margin-bottom: 3px;
}
.help-step-desc {
  font-size: 12.5px;
  line-height: 1.65;
  color: #8a8f99;
}
/* 使用技巧 */
.help-tips {
  display: flex;
  flex-direction: column;
  gap: 8px;
}
.help-tip {
  display: flex;
  align-items: baseline;
  gap: 8px;
  padding: 11px 16px;
  border-radius: 12px;
  border: 1px solid #eceef2;
  background: #fafbff;
  font-size: 13px;
  line-height: 1.65;
  color: #4b5563;
}
.help-tip-k {
  flex-shrink: 0;
  padding: 1px 10px;
  border-radius: 6px;
  background: #e8e9fd;
  color: #4f46e5;
  font-size: 12px;
  font-weight: 600;
}
/* 常见问题 */
.help-faq {
  border: 1px solid #eceef2;
  border-radius: 12px;
  background: #fff;
  padding: 4px 12px;
}
.help-faq-answer {
  font-size: 13px;
  line-height: 1.7;
  color: #6b7280;
}
/* 技术架构 */
.help-arch {
  border: 1px solid #eceef2;
  border-radius: 12px;
  background: #fff;
  overflow: hidden;
}
.help-arch-row {
  display: flex;
  align-items: center;
  padding: 12px 16px;
  border-bottom: 1px solid #f0f1f3;
  font-size: 13px;
  gap: 12px;
}
.help-arch-row:last-of-type {
  border-bottom: 1px solid #f0f1f3;
}
.help-arch-key {
  flex-shrink: 0;
  width: 52px;
  color: #8a8f99;
  font-size: 12.5px;
}
.help-arch-val {
  color: #1f2329;
  font-weight: 500;
}
.help-arch-subs {
  padding: 8px 16px 12px;
  display: flex;
  flex-direction: column;
  gap: 6px;
}
.help-arch-subs div {
  font-size: 12.5px;
  line-height: 1.6;
  color: #6b7280;
}
.help-arch-subs b {
  color: #4f46e5;
  font-weight: 600;
}
/* 安全说明 */
.help-safe {
  border: 1px solid #eceef2;
  border-radius: 12px;
  background: #fff;
  overflow: hidden;
}
.help-safe-item {
  padding: 13px 16px;
  border-bottom: 1px solid #f0f1f3;
  font-size: 13px;
  line-height: 1.7;
  color: #4b5563;
}
.help-safe-item:last-child {
  border-bottom: none;
}
.sb-empty {
  padding: 6px 8px;
  font-size: 12px;
  color: #bbb;
}
.sb-footer {
  border-top: 1px solid #eceef2;
  padding: 8px;
}
.sb-ver {
  padding: 6px 8px 2px;
  font-size: 11px;
  color: #bbb;
}
.sb-main {
  flex: 1;
  min-width: 0;
  overflow: hidden;
}
</style>
