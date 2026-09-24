<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, ref, watch } from "vue";
import { useRoute, useRouter } from "vue-router";
import { useMessage } from "naive-ui";
import { marked } from "marked";
import DOMPurify from "dompurify";
import { api } from "../api/client";
import { useAgentsStore } from "../stores/agents";
import { useSessionStore } from "../stores/session";

const route = useRoute();
const router = useRouter();
const message = useMessage();
const agentsStore = useAgentsStore();
const store = useSessionStore();

// 注意：必须响应路由参数变化（侧边栏切换会话时组件复用，id 会变）
let sessionId = Number(route.params.sid);
const session = ref<any>(null);
const allAgents = ref<any[]>([]);
const busy = ref(false);
const showInspector = ref(false);
const expandedMessages = ref<Set<number>>(new Set());

const activeMembers = computed(() =>
  store.members.filter((m: any) => m.status === "active")
);
const currentTask = computed(() =>
  store.tasks.find((t: any) => t.status === "running") ||
  store.tasks.find((t: any) => t.status === "pending") ||
  store.tasks[0]
);

// 会话重命名
const showRename = ref(false);
const newTitle = ref("");
async function renameSession() {
  if (!newTitle.value.trim()) return;
  try {
    await api.renameSession(sessionId, newTitle.value.trim());
    session.value.title = newTitle.value.trim();
    message.success("已重命名");
    showRename.value = false;
  } catch (e: any) {
    message.error(e.message || "重命名失败");
  }
}

// 输入
const input = ref("");
const sendTarget = ref("all"); // all / agent:{id}
const recipientOptions = computed(() => [
  { label: "@ 所有人", value: "all" },
  ...store.members
    .filter((m: any) => m.status === "active")
    .map((m: any) => {
      const a = allAgents.value.find((x: any) => x.id === m.agent_id);
      return { label: `@ ${a?.name || m.agent_id}`, value: `agent:${m.agent_id}` };
    }),
]);

// 任务暂停 / 继续
async function pauseTask(t: any) {
  try {
    await api.pauseTask(t.id);
    message.success("任务已暂停");
    store.tasks = await api.listTasks(sessionId);
  } catch (e: any) {
    message.error(e.message || "暂停失败");
  }
}
async function resumeTask(t: any) {
  try {
    message.info("继续执行中…");
    await api.resumeTask(t.id);
    store.tasks = await api.listTasks(sessionId);
    message.success("任务已继续");
  } catch (e: any) {
    message.error(e.message || "继续失败");
  }
}

// 拉人
const showInvite = ref(false);
const inviteAgentIds = ref<number[]>([]);
const notInSessionAgents = computed(() =>
  allAgents.value.filter(
    (a: any) => !store.members.some((m: any) => m.agent_id === a.id && m.status === "active")
  )
);

// 派活
const showTaskInput = ref(false);
const taskInput = ref("");

// 产物（按项目文件夹展示）
const folders = ref<any[]>([]);
const ungrouped = ref(0);
const currentFolder = ref<string | null>(null);
const folderArtifacts = ref<any[]>([]);
const folderLoading = ref(false);
const showArtifact = ref(false);
const viewingArtifact = ref<any>(null);
const artifactContent = ref("");

async function loadArtifacts() {
  const res = await api.listArtifactFolders(sessionId);
  folders.value = res.folders || [];
  ungrouped.value = res.ungrouped || 0;
}

// 打开项目本地文件夹（产物落盘位置）
async function openProjectFolder() {
  const projectId = session.value?.project_id;
  if (!projectId) {
    message.info("独立会话的产物保存在 ~/Multi-agent/未分组/ 下，可前往本地查看");
    return;
  }
  try {
    const res = await api.projectFolderPath(projectId);
    if (!res?.path) {
      message.error("未获取到项目路径");
      return;
    }
    // 桌面端（Tauri）用系统文件管理器打开；浏览器环境提示路径
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

async function toggleFolder(folder: string) {
  if (currentFolder.value === folder) {
    currentFolder.value = null;
    folderArtifacts.value = [];
    return;
  }
  currentFolder.value = folder;
  folderLoading.value = true;
  try {
    folderArtifacts.value = await api.listArtifacts(sessionId, folder);
  } catch (e: any) {
    message.error(e.message || "加载产物失败");
    folderArtifacts.value = [];
  } finally {
    folderLoading.value = false;
  }
}

async function removeArtifact(art: any) {
  try {
    await api.deleteArtifact(art.id);
    message.success("已删除");
    folderArtifacts.value = folderArtifacts.value.filter((a) => a.id !== art.id);
    await loadArtifacts();
  } catch (e: any) {
    message.error(e.message || "删除失败");
  }
}

async function removeArtifactFolder(folder: string) {
  try {
    const res = await api.deleteArtifactFolder(sessionId, folder);
    message.success(`已删除文件夹（${res.deleted ?? 0} 个文件）`);
    if (currentFolder.value === folder) {
      currentFolder.value = null;
      folderArtifacts.value = [];
    }
    await loadArtifacts();
  } catch (e: any) {
    message.error(e.message || "删除失败");
  }
}

async function downloadArtifact(art: any) {
  try {
    const res = await api.fetchArtifact(art.id);
    if (!res.ok) {
      message.error("下载失败");
      return;
    }
    const blob = await res.blob();
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = art.name || "artifact";
    document.body.appendChild(a);
    a.click();
    a.remove();
    URL.revokeObjectURL(url);
  } catch (e: any) {
    message.error(e.message || "下载失败");
  }
}

async function viewArtifact(art: any) {
  const url = artifactMediaUrl(art);
  // PDF/Office/图片/视频：新窗口打开
  if (isPdfArtifact(art) || art.type === "image" || art.type === "video") {
    window.open(url, "_blank");
    return;
  }
  // 文本文件：弹窗内显示
  viewingArtifact.value = art;
  try {
    const res = await api.fetchArtifact(art.id);
    if (!res.ok) {
      message.error("读取失败");
      return;
    }
    artifactContent.value = await res.text();
    showArtifact.value = true;
  } catch (e: any) {
    message.error(e.message || "读取失败");
  }
}

// 图片/视频产物的下载地址（同源直接内嵌）
const OFFICE_PREVIEW_EXTS = new Set([".pdf", ".docx", ".xlsx", ".pptx", ".odt", ".ods", ".odp", ".rtf"]);

function artifactMediaUrl(art: any) {
  const url = api.artifactDownloadUrl(art.id);
  const fn = (art?.name || "").toLowerCase();
  // office 文件走 /preview（后端转 PDF）
  if (OFFICE_PREVIEW_EXTS.has(fn.slice(fn.lastIndexOf("."))) && !fn.endsWith(".pdf")) {
    return url.replace(/\/download$/, "/preview");
  }
  return url;
}
// 判断是否 PDF/Office 可内嵌预览
function isPdfArtifact(art: any) {
  if (!art?.name) return false;
  const fn = art.name.toLowerCase();
  return OFFICE_PREVIEW_EXTS.has(fn.slice(fn.lastIndexOf(".")));
}
// 对话里的附件消息：点击预览（复用产物查看弹窗）
const OFFICE_EXTS = new Set([".docx", ".xlsx", ".pptx", ".odt", ".ods", ".odp", ".rtf", ".csv"]);

function previewAttachment(m: any) {
  const fn = (m.meta.file_name || "").toLowerCase();
  // PDF / Office 文档：新标签页打开（PDF 原生查看器，Office 由后端转 PDF）
  if (fn.endsWith(".pdf") || OFFICE_EXTS.has(fn.slice(fn.lastIndexOf(".")))) {
    const isOffice = OFFICE_EXTS.has(fn.slice(fn.lastIndexOf(".")));
    const url = isOffice
      ? `${api.artifactDownloadUrl(m.meta.artifact_id).replace(/\/download$/, "/preview")}`
      : api.artifactDownloadUrl(m.meta.artifact_id);
    window.open(url, "_blank");
    return;
  }
  viewingArtifact.value = {
    id: m.meta.artifact_id,
    name: m.meta.file_name,
    type: m.meta.artifact_type,
  };
  if (m.meta.artifact_type === "image" || m.meta.artifact_type === "video") {
    artifactContent.value = "";
  } else if (OFFICE_PREVIEW_EXTS.has(fn.slice(fn.lastIndexOf(".")))) {
    // PDF/Office 走 iframe，不读文本
    artifactContent.value = "";
  } else {
    api.fetchArtifact(m.meta.artifact_id).then(async (r) => {
      artifactContent.value = await r.text();
    });
  }
  showArtifact.value = true;
}

function artifactTypeLabel(t: string) {
  const map: Record<string, string> = {
    code: "代码",
    doc: "文档",
    image: "图片",
    text: "文本",
    video: "视频",
    other: "其他",
  };
  return map[t] || t;
}

// 提取消息里的代码块（供气泡上的复制/运行按钮使用）
function extractCodeBlocks(content: string): { lang: string; code: string }[] {
  const blocks: { lang: string; code: string }[] = [];
  const re = /```(\w*)\n?([\s\S]*?)```/g;
  let m: RegExpExecArray | null;
  while ((m = re.exec(content))) {
    blocks.push({ lang: m[1] || "python", code: m[2].replace(/\n$/, "") });
  }
  return blocks;
}

function renderContent(content: string): string {
  // 交给 marked 渲染完整 markdown，XSS 防护由 DOMPurify 兜底
  const raw = marked.parse(content, { gfm: true, breaks: true }) as string;
  return DOMPurify.sanitize(raw);
}

function messageNeedsCollapse(content: string): boolean {
  return content.length > 280 || /```|\|.+\||^#{1,3}\s/m.test(content);
}

function messagePreview(content: string): string {
  const plain = content
    .replace(/```[\s\S]*?```/g, "[代码内容]")
    .replace(/\|.+\|/g, "[表格内容]")
    .replace(/^#{1,6}\s*/gm, "")
    .replace(/^\s*[-*+]\s+/gm, "")
    .replace(/^\s*\d+[.)]\s+/gm, "")
    .replace(/\n{3,}/g, "\n\n")
    .replace(/\s+/g, " ")
    .trim();
  return plain.length > 180 ? `${plain.slice(0, 180).trimEnd()}…` : plain;
}

function isSandboxStatus(status: string): boolean {
  return /^沙箱[：:]/.test(status);
}

function isMessageExpanded(id: number): boolean {
  return expandedMessages.value.has(id);
}

function toggleMessageExpansion(id: number) {
  const next = new Set(expandedMessages.value);
  if (next.has(id)) next.delete(id);
  else next.add(id);
  expandedMessages.value = next;
}

function avatarColor(id: number): string {
  const colors = ["#6366f1", "#0ea5e9", "#f59e0b", "#10b981", "#ef4444", "#8b5cf6"];
  return colors[id % colors.length];
}

// 成员信息
function agentOf(m: any) {
  return allAgents.value.find((a: any) => a.id === m.agent_id);
}

// 成员悬浮提示（自研 fixed 浮层，不依赖 Naive 浮层组件，避免 WebView 渲染冻结）
const tipVisible = ref(false);
const tipContent = ref<{ name: string; role: string; prompt: string; isHost: boolean } | null>(null);
const tipLeft = ref(0);
const tipTop = ref(0);
let tipTimer: ReturnType<typeof setTimeout> | null = null;
function showMemberTip(m: any, e: MouseEvent) {
  const a = agentOf(m);
  tipContent.value = {
    name: a?.name || `Agent#${m.agent_id}`,
    role: a?.role_hint || "",
    prompt: a?.system_prompt || "",
    isHost: m.role === "host",
  };
  const rect = (e.currentTarget as HTMLElement).getBoundingClientRect();
  const w = 300;
  // 信息面板在右侧，提示优先放到成员行左边，避免遮挡右侧的操作菜单。
  const preferredLeft = rect.left - w - 12;
  tipLeft.value = preferredLeft >= 8
    ? preferredLeft
    : Math.min(rect.right + 12, window.innerWidth - w - 12);
  tipTop.value = Math.max(8, Math.min(rect.top, window.innerHeight - 220));
  tipVisible.value = true;
  if (tipTimer) {
    clearTimeout(tipTimer);
    tipTimer = null;
  }
}
function hideMemberTip() {
  if (tipTimer) clearTimeout(tipTimer);
  tipTimer = setTimeout(() => {
    tipVisible.value = false;
  }, 200);
}
// 附件收集：选择文件先进入待发栏（最多 10 个），点「发送」时才一起上传发出
const MAX_FILES = 10;
const uploading = ref(false);
const fileInput = ref<HTMLInputElement | null>(null);
const pendingFiles = ref<File[]>([]);

function addFiles(e: any) {
  const files: File[] = Array.from(e.target?.files || []);
  if (!files.length) return;
  const room = MAX_FILES - pendingFiles.value.length;
  if (room <= 0) {
    message.warning(`最多上传 ${MAX_FILES} 个文件`);
  } else if (files.length > room) {
    message.warning(`最多上传 ${MAX_FILES} 个文件，已保留前 ${room} 个`);
  }
  pendingFiles.value.push(...files.slice(0, room));
  if (fileInput.value) fileInput.value.value = "";
}

function removePendingFile(i: number) {
  pendingFiles.value.splice(i, 1);
}

const IMG_EXT = [".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp", ".svg", ".ico"];
function isImageFile(f: File) {
  const ext = "." + (f.name.split(".").pop() || "").toLowerCase();
  return IMG_EXT.includes(ext);
}
function fmtSize(n: number) {
  if (n < 1024) return `${n} B`;
  if (n < 1024 * 1024) return `${(n / 1024).toFixed(1)} KB`;
  return `${(n / 1024 / 1024).toFixed(1)} MB`;
}

// 发送：先上传待发附件（最多 10 个），再发送文字
async function send() {
  const content = input.value.trim();
  const files = pendingFiles.value;
  if (busy.value) return;
  if (!content && files.length === 0) return;
  busy.value = true;
  uploading.value = true;
  try {
    // 1. 上传附件（后端各插一条「📎 上传了附件」上下文消息）
    for (const f of files) {
      await api.uploadAttachment(sessionId, f);
    }
    pendingFiles.value = [];
    // 2. 发送文字（仅附件时跳过，附件消息已进上下文）
    if (content) {
      input.value = "";
      await api.sendMessage(sessionId, content, sendTarget.value);
    }
    scrollToBottom();
    await load();
  } catch (e: any) {
    message.error(e.message || "发送失败");
  } finally {
    uploading.value = false;
    busy.value = false;
  }
}

// 派活
async function startTask() {
  const desc = taskInput.value.trim();
  if (!desc || busy.value) return;
  busy.value = true;
  try {
    await api.orchestrate(sessionId, desc);
    taskInput.value = "";
    showTaskInput.value = false;
  } catch (e: any) {
    message.error(e.message || "派活失败");
  } finally {
    busy.value = false;
  }
}

// 拉人
async function doInvite() {
  const ids = inviteAgentIds.value;
  if (!ids.length) return;
  try {
    for (const id of ids) {
      await api.inviteAgent(sessionId, id);
    }
    message.success(`已拉入 ${ids.length} 个 Agent`);
    showInvite.value = false;
    inviteAgentIds.value = [];
    await reloadMembers();
  } catch (e: any) {
    message.error(e.message || "拉人失败");
  }
}

// 设主理人
async function setHost(agentId: number) {
  try {
    await api.setOrchestrator(sessionId, agentId);
    message.success("已设置主理人");
    await load();
  } catch (e: any) {
    message.error(e.message || "设置失败");
  }
}

// 运行代码
async function runCodeBlock(lang: string, code: string) {
  try {
    message.info(`沙箱运行 ${lang}…`);
    await api.runCode(sessionId, code, lang === "sh" || lang === "bash" ? "shell" : lang, 60);
    loadArtifacts();
  } catch (e: any) {
    message.error(e.message || "运行失败");
  }
}

// 滚动
const msgBox = ref<HTMLElement | null>(null);
function scrollToBottom() {
  nextTick(() => {
    if (msgBox.value) msgBox.value.scrollTop = msgBox.value.scrollHeight;
  });
}

// 初始化
async function load() {
  session.value = await api.getSession(sessionId);
  await store.load(sessionId);
  if (!agentsStore.agents.length) await agentsStore.load();
  allAgents.value = agentsStore.agents;
  await reloadMembers();
  loadArtifacts();
  scrollToBottom();
}

async function reloadMembers() {
  store.members = await api.listMembers(sessionId);
}

// 启动时连接 WS；路由参数变化（切换会话）时重连并重载
watch(
  () => route.params.sid,
  () => {
    sessionId = Number(route.params.sid);
    store.disconnect();
    store.messages = [];
    store.statuses = [];
    store.tasks = [];
    load()
      .catch((e: any) => message.error(e.message || "加载会话失败"))
      .finally(() => {
        store.connect(sessionId);
      });
  },
  { immediate: true }
);

onBeforeUnmount(() => {
  store.disconnect();
});

// 新消息 / 状态到达时自动滚到底部
watch(
  () => [store.messages.length, store.statuses.length],
  () => scrollToBottom()
);

// 消息显示辅助
const isHostMsg = (m: any) =>
  m.sender_type === "agent" &&
  session.value?.orchestrator_agent_id === m.sender_id;

function parseAC(json: string) {
  try { return JSON.parse(json) || []; } catch { return []; }
}
function taskStatusLabel(s: string) {
  const map: Record<string, string> = {
    pending: "待派发",
    running: "执行中",
    reviewing: "验收中",
    revising: "退回重做",
    paused: "已暂停",
    done: "已完成",
    cancelled: "已取消",
  };
  return map[s] || s;
}
</script>

<template>
  <div class="session-wrap">
    <main class="chat-area">
      <div class="chat-head">
        <button class="header-icon back-btn" type="button" title="返回项目" aria-label="返回项目" @click="router.push(session?.project_id ? `/projects/${session.project_id}` : '/')">
          <svg viewBox="0 0 24 24" aria-hidden="true"><path d="m15 18-6-6 6-6" /></svg>
        </button>
        <div class="chat-title">
          <span v-if="session?.project_id" class="project-crumb">{{ session?.project_name || "项目" }}</span>
          <span>{{ session?.title || "会话" }}</span>
          <button class="header-icon chat-rename-btn" type="button" title="重命名" aria-label="重命名" @click="newTitle = session?.title || ''; showRename = true">
            <svg viewBox="0 0 24 24" aria-hidden="true"><path d="M12 20h9" /><path d="M16.5 3.5a2.1 2.1 0 0 1 3 3L8 18l-4 1 1-4Z" /></svg>
          </button>
        </div>
        <div class="chat-head-actions">
          <span class="sync-state"><i></i>已同步</span>
          <button class="header-icon" :class="{ active: showInspector }" type="button" title="会话信息" aria-label="会话信息" @click="showInspector = !showInspector">
            <svg viewBox="0 0 24 24" aria-hidden="true"><circle cx="12" cy="12" r="9" /><path d="M12 11v5" /><path d="M12 8h.01" /></svg>
          </button>
        </div>
      </div>

      <!-- 重命名会话 -->
      <n-modal v-model:show="showRename" preset="card" title="重命名会话" style="width: 440px">
        <n-input v-model:value="newTitle" placeholder="会话标题" maxlength="120" @keydown.enter.prevent="renameSession" />
        <template #footer>
          <n-space justify="end">
            <n-button @click="showRename = false">取消</n-button>
            <n-button type="primary" @click="renameSession">保存</n-button>
          </n-space>
        </template>
      </n-modal>

      <!-- 状态栏 -->
      <div v-if="store.statuses.length || store.typing.length" class="status-strip">
        <span v-if="store.statuses.filter(isSandboxStatus).length" class="status-item">已完成 {{ store.statuses.filter(isSandboxStatus).length }} 次代码运行</span>
        <span v-for="(s, i) in store.statuses.filter((item: string) => !isSandboxStatus(item)).slice(-2)" :key="i" class="status-item">{{ s }}</span>
        <span v-if="store.typing.length" class="status-typing">{{ store.typing.join("、") }} 正在思考…</span>
      </div>

      <div v-if="currentTask" class="task-context">
        <span class="task-status" :class="`status-${currentTask.status}`">
          <i></i>
          {{ taskStatusLabel(currentTask.status) }}
        </span>
        <span class="task-context-title">{{ currentTask.title }}</span>
      </div>

      <div ref="msgBox" class="msg-box">
        <div v-for="m in store.messages" :key="m.id" class="msg-row" :class="m.sender_type">
          <!-- 用户 -->
          <div v-if="m.sender_type === 'user'" class="message user-message">
            <div class="user-avatar">我</div>
            <div class="message-body">
              <div class="msg-sender user-sender">我</div>
              <div class="bubble user-bubble">
                <div v-if="m.meta?.kind === 'attachment'" class="msg-attachment">
                  <img
                    v-if="m.meta.artifact_type === 'image'"
                    :src="api.artifactDownloadUrl(m.meta.artifact_id)"
                    class="att-thumb"
                    @click="previewAttachment(m)"
                  />
                  <div v-else class="att-file" @click="previewAttachment(m)">
                    <span class="att-icon">{{ m.meta.artifact_type === 'video' ? '🎬' : '📄' }}</span>
                    <span class="att-name">{{ m.meta.file_name }}</span>
                  </div>
                </div>
                <div v-else class="msg-content" v-html="renderContent(m.content)"></div>
              </div>
            </div>
          </div>

          <!-- Agent -->
          <div v-else-if="m.sender_type === 'agent'" class="message agent-message">
            <n-avatar round size="small" class="agent-avatar" :style="{ background: avatarColor(m.sender_id || 0) }">
                {{ m.sender_name[0] }}
            </n-avatar>
            <div class="message-body">
              <div class="msg-sender" :style="{ color: avatarColor(m.sender_id || 0) }">
              <span class="sender-name">
                {{ m.sender_name }}
                <n-tag v-if="isHostMsg(m)" size="tiny" type="warning">主理人</n-tag>
              </span>
              </div>
              <div class="bubble agent-bubble" :class="{ 'is-summary': messageNeedsCollapse(m.content) && !isMessageExpanded(m.id) }">
                <div
                  class="msg-content"
                  v-html="renderContent(messageNeedsCollapse(m.content) && !isMessageExpanded(m.id) ? messagePreview(m.content) : m.content)"
                ></div>
                <button
                  v-if="messageNeedsCollapse(m.content)"
                  class="expand-message"
                  type="button"
                  @click="toggleMessageExpansion(m.id)"
                >
                  {{ isMessageExpanded(m.id) ? "收起完整内容" : "查看完整内容" }}
                </button>
                <div v-if="isMessageExpanded(m.id) && extractCodeBlocks(m.content).length" class="code-actions">
                  <n-button
                    v-for="(b, i) in extractCodeBlocks(m.content)"
                    :key="i"
                    size="tiny"
                    type="primary"
                    ghost
                    @click="runCodeBlock(b.lang, b.code)"
                  >
                    ▶ 运行 {{ b.lang || "代码" }}
                  </n-button>
                </div>
              </div>
            </div>
          </div>

          <!-- 系统 -->
          <div v-else class="sys-bubble">
            <span>{{ m.sender_name }}：{{ m.content }}</span>
          </div>
        </div>
        <div v-if="busy" class="busy-hint">处理中…</div>
      </div>

      <!-- 输入 -->
      <div class="input-area">
        <div v-if="pendingFiles.length" class="pending-files">
          <div v-for="(f, i) in pendingFiles" :key="i" class="pending-file">
            <span class="pf-icon">{{ isImageFile(f) ? '🖼' : '📄' }}</span>
            <span class="pf-name">{{ f.name }}</span>
            <span class="pf-size">{{ fmtSize(f.size) }}</span>
            <span class="pf-del" title="移除" @click="removePendingFile(i)">✕</span>
          </div>
        </div>
        <div class="input-row">
          <input
            ref="fileInput"
            type="file"
            multiple
            accept="*/*"
            style="display: none"
            @change="addFiles"
          />
          <div class="composer-tools">
            <n-button size="small" quaternary :loading="uploading" title="上传文件/图片（作为上下文供 Agent 读取）" class="at-btn attachment-btn" @click="fileInput?.click()">
              <span class="paperclip-icon" aria-hidden="true"></span>
            </n-button>
            <n-popselect
              v-model:value="sendTarget"
              :options="recipientOptions"
              trigger="click"
              placement="top-start"
              size="small"
              virtual-scroll
            >
              <button type="button" class="target-select" title="选择消息接收人">
                <span class="mention-icon">@</span>{{ sendTarget === "all" ? "所有成员" : "指定成员" }}<span class="target-chevron">⌄</span>
              </button>
            </n-popselect>
          </div>
          <n-input
            v-model:value="input"
            type="textarea"
            :autosize="{ minRows: 2, maxRows: 12 }"
            placeholder="补充任务、追问结果，或 @ 指定成员…"
            class="msg-input"
            @keydown.enter.exact.prevent="send"
          />
          <div class="composer-footer">
            <span class="composer-hint">Enter 发送 · Shift + Enter 换行</span>
            <n-button type="primary" :loading="busy" @click="send" class="send-btn">
              <span>发送</span>
              <svg viewBox="0 0 24 24" aria-hidden="true"><path d="m5 12 14-7-4 14-3-5-5-2Z" /><path d="m12 12 3-3" /></svg>
            </n-button>
          </div>
        </div>
      </div>
    </main>

    <aside v-if="showInspector" class="inspector-panel">
      <div class="inspector-head">
        <span>会话信息</span>
        <n-button size="small" quaternary title="关闭信息面板" @click="showInspector = false">×</n-button>
      </div>

      <div class="panel-section panel-third members-section">
        <div class="panel-title">成员 ({{ activeMembers.length }})</div>
        <div class="panel-scroll">
          <div
            v-for="m in activeMembers"
            :key="m.id"
            class="member-item"
            @mouseenter="showMemberTip(m, $event)"
            @mouseleave="hideMemberTip"
          >
            <n-avatar :style="{ background: avatarColor(m.agent_id) }" round size="small">
              {{ (agentOf(m)?.name || "A")[0] }}
            </n-avatar>
            <div class="member-info">
              <div class="member-name">
                {{ agentOf(m)?.name || `Agent#${m.agent_id}` }}
                <n-tag v-if="m.role === 'host'" size="tiny" type="warning">主理人</n-tag>
              </div>
              <div class="member-sub">{{ agentOf(m)?.model || "" }}</div>
            </div>
            <n-dropdown
              v-if="m.role !== 'host'"
              trigger="click"
              :options="[{ label: '设为主理人', key: 'host' }]"
              @select="setHost(m.agent_id)"
            >
              <n-button size="tiny" quaternary>···</n-button>
            </n-dropdown>
          </div>
        </div>
        <n-button size="small" block dashed class="invite-agent-btn" @click="showInvite = true">拉 Agent 进群</n-button>
      </div>

      <div class="panel-section panel-third">
        <div class="panel-title panel-title-actions">
          <span>任务</span>
          <n-button v-if="!showTaskInput" size="tiny" quaternary title="派活给主理人" @click="showTaskInput = true">+</n-button>
        </div>
        <div v-if="showTaskInput" class="task-composer">
          <n-input v-model:value="taskInput" type="textarea" :rows="2" placeholder="描述任务" />
          <n-space size="small" style="margin-top: 6px" justify="end">
            <n-button size="tiny" @click="showTaskInput = false">取消</n-button>
            <n-button size="tiny" type="warning" :loading="busy" @click="startTask">派活</n-button>
          </n-space>
        </div>
        <div class="panel-scroll">
          <n-empty v-if="store.tasks.length === 0" description="暂无任务" size="small" />
          <div v-for="t in store.tasks" :key="t.id" class="task-item" :class="t.status">
            <div class="task-title">{{ t.title }}</div>
            <div class="task-meta">
              <n-tag size="tiny" :type="t.status === 'done' ? 'success' : t.status === 'running' ? 'info' : t.status === 'revising' || t.status === 'paused' ? 'warning' : 'default'">
                {{ taskStatusLabel(t.status) }}
              </n-tag>
              <span v-if="t.assignee_name" class="task-assignee">👤 {{ t.assignee_name }}</span>
              <span v-if="t.round">第 {{ t.round }}/{{ t.max_rounds }} 轮</span>
              <n-button v-if="t.status === 'running'" size="tiny" quaternary @click="pauseTask(t)">暂停</n-button>
              <n-button v-else-if="t.status === 'paused'" size="tiny" type="primary" ghost @click="resumeTask(t)">继续</n-button>
            </div>
            <!-- 验收标准预览 -->
            <div v-if="t.acceptance_criteria" class="task-ac">
              <div v-for="(ac, i) in parseAC(t.acceptance_criteria)" :key="i" class="task-ac-line">
                <span :class="ac.level === 'P0' ? 'ac-p0' : 'ac-p1'">[{{ ac.level }}]</span>
                {{ ac.text }}
              </div>
            </div>
          </div>
        </div>
      </div>

      <div class="panel-section panel-third">
        <div class="panel-title" style="display: flex; justify-content: space-between; align-items: center;">
          <span>产物</span>
          <n-space size="small">
            <n-button size="tiny" quaternary @click="openProjectFolder">打开文件夹</n-button>
          </n-space>
        </div>
        <div class="panel-scroll">
          <n-empty v-if="folders.length === 0" description="暂无产物（运行代码后生成）" size="small" />
          <div v-for="f in folders" :key="f.folder" class="folder-item">
            <div class="folder-row" @click="toggleFolder(f.folder)">
              <n-tooltip trigger="hover" placement="top">
                <template #trigger>
                  <span class="folder-name">📁 {{ f.folder }}</span>
                </template>
                {{ f.count }} 个文件
              </n-tooltip>
              <n-popconfirm
                @positive-click="removeArtifactFolder(f.folder)"
                positive-text="删除"
                negative-text="取消"
              >
                <template #trigger>
                  <span class="folder-del-btn" @click.stop>✕</span>
                </template>
                确认删除整个文件夹「{{ f.folder }}」及其 {{ f.count }} 个文件？此操作不可恢复。
              </n-popconfirm>
            </div>
            <div v-if="currentFolder === f.folder" class="folder-files" :class="{ loading: folderLoading }">
              <n-empty v-if="folderArtifacts.length === 0" description="空文件夹" size="small" />
              <div v-for="art in folderArtifacts" :key="art.id" class="artifact-item">
                <div class="artifact-name" :title="art.name">{{ art.name }}</div>
                <div class="task-meta">
                  <n-tag size="tiny" :type="art.type === 'image' ? 'success' : art.type === 'code' ? 'info' : art.type === 'doc' ? 'warning' : 'default'">
                    {{ artifactTypeLabel(art.type) }}
                  </n-tag>
                  <span>{{ new Date(art.created_at).toLocaleTimeString() }}</span>
                </div>
                <div class="artifact-actions">
                  <n-button size="tiny" @click="viewArtifact(art)">查看</n-button>
                  <n-button size="tiny" type="primary" @click="downloadArtifact(art)">下载</n-button>
                  <n-popconfirm
                    @positive-click="removeArtifact(art)"
                    positive-text="删除"
                    negative-text="取消"
                  >
                    <template #trigger>
                      <n-button size="tiny" type="error" quaternary>删除</n-button>
                    </template>
                    确认删除该产物文件「{{ art.name }}」？此操作不可恢复。
                  </n-popconfirm>
                </div>
              </div>
            </div>
          </div>
        </div>
      </div>
    </aside>

    <!-- 拉人弹窗 -->
    <n-modal v-model:show="showInvite" preset="card" title="拉 Agent 进群" style="width: 460px">
      <n-select
        v-model:value="inviteAgentIds"
        :options="notInSessionAgents.map((a: any) => ({ label: `${a.name}（${a.model}）`, value: a.id }))"
        multiple
        filterable
        clearable
        placeholder="选择要拉入的 Agent（可多选）"
        :max-tag-count="3"
      />
      <div v-if="notInSessionAgents.length === 0" style="font-size: 12px; color: #999; margin-top: 8px">
        所有 Agent 都已在会话中
      </div>
      <template #footer>
        <n-space justify="end">
          <n-button @click="showInvite = false">取消</n-button>
          <n-button type="primary" :disabled="inviteAgentIds.length === 0" @click="doInvite">
            拉入{{ inviteAgentIds.length ? `（${inviteAgentIds.length}）` : "" }}
          </n-button>
        </n-space>
      </template>
    </n-modal>

    <!-- 产物查看 -->
    <n-modal v-model:show="showArtifact" preset="card" :title="`查看产物 · ${viewingArtifact?.name || ''}`" style="width: 760px">
      <img
        v-if="viewingArtifact?.type === 'image'"
        :src="artifactMediaUrl(viewingArtifact)"
        :alt="viewingArtifact?.name"
        class="artifact-img"
      />
      <video
        v-else-if="viewingArtifact?.type === 'video'"
        :src="artifactMediaUrl(viewingArtifact)"
        controls
        autoplay
        class="artifact-video"
      />
      <iframe
        v-else-if="isPdfArtifact(viewingArtifact)"
        :src="artifactMediaUrl(viewingArtifact)"
        class="artifact-pdf"
      />
      <pre v-else class="artifact-preview">{{ artifactContent }}</pre>
      <template #footer>
        <n-space justify="end">
          <n-button @click="showArtifact = false">关闭</n-button>
          <n-button type="primary" @click="showArtifact = false; downloadArtifact(viewingArtifact)">下载</n-button>
        </n-space>
      </template>
    </n-modal>

    <!-- 成员悬浮提示（fixed 定位，不依赖浮层组件） -->
    <div
      v-if="tipVisible"
      class="member-tip-fixed"
      :style="{ left: tipLeft + 'px', top: tipTop + 'px' }"
    >
      <div class="member-tip-title">
        {{ tipContent?.name }}
        <span v-if="tipContent?.isHost" class="member-tip-host">主理人</span>
      </div>
      <div v-if="tipContent?.role" class="member-tip-line"><b>角色</b>：{{ tipContent.role }}</div>
      <div v-if="tipContent?.prompt" class="member-tip-line"><b>人设 / 系统提示</b>：{{ tipContent.prompt }}</div>
      <div v-if="!tipContent?.role && !tipContent?.prompt" class="member-tip-empty">
        这个 Agent 还没设置人设 / 系统提示词，<br />可以去「Agent 管理」里编辑补充哦～
      </div>
    </div>
  </div>
</template>

<style scoped>
.session-wrap {
  display: flex;
  height: 100vh;
  overflow: hidden;
  background: #f8f9fb;
}

.panel-title {
  font-weight: 600;
  font-size: 13px;
  color: #454a54;
  margin-bottom: 10px;
}
.member-item {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 6px 0;
}
.member-info {
  flex: 1;
  min-width: 0;
}
.member-name {
  font-size: 13px;
  display: flex;
  align-items: center;
  gap: 4px;
}
.member-sub {
  font-size: 11px;
  color: #999;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
/* 成员悬浮提示（fixed 定位，独立于容器 overflow，不依赖浮层组件） */
.member-tip-fixed {
  position: fixed;
  z-index: 2000;
  width: 300px;
  max-height: 70vh;
  overflow-y: auto;
  background: #2b2f36;
  border-radius: 10px;
  padding: 12px 14px;
  box-shadow: 0 8px 24px rgba(0, 0, 0, 0.22);
  font-size: 12px;
  line-height: 1.7;
  color: rgba(255, 255, 255, 0.92);
  pointer-events: none;
}
.member-tip-title {
  font-weight: 600;
  font-size: 13px;
  margin-bottom: 6px;
  color: #fff;
}
.member-tip-host {
  margin-left: 6px;
  font-size: 11px;
  color: #f0a020;
  font-weight: 600;
}
.member-tip-line {
  margin-bottom: 4px;
  white-space: pre-wrap;
  word-break: break-word;
}
.member-tip-line b {
  color: #63e2b7;
  font-weight: 600;
}
.member-tip-empty {
  color: rgba(255, 255, 255, 0.65);
  padding: 4px 0;
}
.chat-area {
  flex: 1;
  display: flex;
  flex-direction: column;
  min-width: 0;
  background: #fff;
}
.chat-head {
  display: flex;
  align-items: center;
  gap: 8px;
  min-height: 58px;
  padding: 0 24px;
  border-bottom: 1px solid #eceef2;
  background: #fff;
}
.header-icon {
  width: 28px;
  height: 28px;
  flex: 0 0 auto;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  padding: 0;
  border: 0;
  border-radius: 4px;
  background: transparent;
  color: #6d7884;
  cursor: pointer;
}
.header-icon:hover,
.header-icon.active { background: #eef1f4; color: #2563eb; }
.header-icon svg {
  width: 16px;
  height: 16px;
  fill: none;
  stroke: currentColor;
  stroke-width: 1.8;
  stroke-linecap: round;
  stroke-linejoin: round;
}
.back-btn { margin-right: 2px; }
.chat-title {
  flex: 1;
  font-weight: 600;
  font-size: 15px;
  display: flex;
  align-items: center;
  gap: 2px;
  min-width: 0;
  overflow: hidden;
}
.chat-title > span:first-child {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.project-crumb {
  color: #8a909a;
  font-weight: 500;
}
.project-crumb::after {
  content: "/";
  margin-left: 8px;
  color: #c4c8ce;
}
.chat-head-actions {
  display: inline-flex;
  align-items: center;
  gap: 4px;
}
.sync-state {
  display: inline-flex;
  align-items: center;
  gap: 5px;
  margin-right: 6px;
  color: #8a909a;
  font-size: 12px;
}
.sync-state i {
  width: 6px;
  height: 6px;
  border-radius: 50%;
  background: #18a66a;
}
.chat-rename-btn {
  width: 25px;
  height: 25px;
  opacity: 0.5;
}
.chat-rename-btn svg { width: 13px; height: 13px; }
.chat-rename-btn:hover {
  opacity: 1;
}
.status-strip {
  padding: 6px max(28px, calc((100% - 800px) / 2));
  font-size: 12px;
  color: #718295;
  background: #f8fafc;
  border-bottom: 1px solid #edf0f3;
  display: flex;
  gap: 12px;
  flex-wrap: wrap;
}
.status-typing {
  color: #6366f1;
  font-style: italic;
}
.task-context {
  display: flex;
  align-items: center;
  gap: 8px;
  max-width: none;
  width: 100%;
  box-sizing: border-box;
  margin: 0;
  padding: 13px max(28px, calc((100% - 800px) / 2));
  border: 0;
  border-bottom: 1px solid #e4e8ed;
  border-radius: 0;
  color: #3f4650;
  font-size: 13px;
  background: #fff;
}
.task-status {
  flex: 0 0 auto;
  display: inline-flex;
  align-items: center;
  gap: 5px;
  border-radius: 4px;
  padding: 3px 7px;
  background: #ecf8f4;
  color: #087f67;
  font-size: 11px;
  font-weight: 600;
  line-height: 1.4;
}
.task-status i {
  width: 6px;
  height: 6px;
  border-radius: 50%;
  background: currentColor;
}
.task-status.status-paused { background: #fff7e8; color: #ad6800; }
.task-status.status-done { background: #eef8f1; color: #238636; }
.task-status.status-cancelled { background: #f4f5f6; color: #7d8792; }
.task-context-title {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  color: #17212b;
  font-size: 14px;
  font-weight: 600;
}
.msg-box {
  flex: 1;
  overflow-y: auto;
  padding: 20px max(28px, calc((100% - 800px) / 2)) 172px;
  display: flex;
  flex-direction: column;
  gap: 0;
}
.msg-row {
  display: block;
}
.message {
  display: flex;
  align-items: flex-start;
  gap: 10px;
  max-width: 100%;
}
.message-body {
  min-width: 0;
  max-width: 670px;
}
.user-avatar {
  display: inline-flex;
  width: 30px;
  height: 30px;
  flex: 0 0 auto;
  align-items: center;
  justify-content: center;
  border-radius: 6px;
  background: #485d78;
  color: #fff;
  font-size: 11px;
  font-weight: 600;
}
.agent-avatar { flex: 0 0 auto; }
.user-message { flex-direction: row; }
.user-message .message-body { display: block; }
.user-message .msg-sender { margin-left: 0; }
.bubble {
  width: fit-content;
  max-width: 100%;
  border-radius: 6px;
  padding: 9px 12px;
}
.user-bubble {
  background: transparent;
  border: 0;
  color: #344250;
  padding: 0;
}
.user-bubble .user-sender {
  color: #5064a4;
}
.agent-bubble {
  background: transparent;
  border: 0;
  box-shadow: none;
  padding: 0;
}
.agent-bubble.is-summary {
  background: transparent;
  border: 0;
  box-shadow: none;
  padding: 0;
}
.agent-bubble { color: #2d3138; }
.msg-sender {
  display: flex;
  align-items: center;
  gap: 6px;
  margin: 2px 0 8px;
  font-weight: 600;
  font-size: 13px;
}
.user-sender {
  color: #c7d2fe;
}
.sender-name {
  display: inline-flex;
  align-items: center;
  gap: 4px;
}
.msg-content {
  color: #344250;
  font-size: 13px;
  line-height: 1.8;
  word-break: break-word;
}
.agent-bubble :deep(pre) {
  max-width: 660px;
  box-sizing: border-box;
  overflow-x: auto;
  border: 1px solid #1c2842;
  border-radius: 7px;
  background: #101a2e;
  padding: 14px;
}
.agent-bubble :deep(pre code) {
  color: #dce6f7;
  font-size: 12px;
  line-height: 1.65;
}
.agent-bubble :deep(table) {
  display: block;
  max-width: 660px;
  overflow-x: auto;
  font-size: 12px;
}
.agent-bubble :deep(p) { margin: 0 0 10px; }
.agent-bubble :deep(p:last-child) { margin-bottom: 0; }
.agent-bubble :deep(h1), .agent-bubble :deep(h2), .agent-bubble :deep(h3) { margin: 16px 0 8px; color: #24303e; }
.agent-bubble :deep(ul), .agent-bubble :deep(ol) { margin: 7px 0; padding-left: 22px; }
.agent-bubble :deep(blockquote) { margin: 10px 0; padding-left: 10px; border-left: 3px solid #b9cdf0; color: #566473; }
.agent-bubble :deep(code) { border-radius: 3px; background: #eef1f5; color: #32526f; padding: 2px 4px; font-size: 11px; }
.expand-message {
  margin-top: 8px;
  border: 0;
  background: transparent;
  color: #3171c5;
  padding: 2px 0;
  font-size: 12px;
  cursor: pointer;
}
.expand-message:hover { color: #174f9e; text-decoration: underline; }
.sys-bubble {
  margin: 0 0 8px 40px;
  max-width: 670px;
  overflow: hidden;
  color: #8b949e;
  font-family: monospace;
  font-size: 10.5px;
  line-height: 1.5;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.code-actions {
  margin-top: 8px;
  display: flex;
  gap: 8px;
  flex-wrap: wrap;
}
.busy-hint {
  text-align: center;
  color: #999;
  font-size: 12px;
}

/* 输入 */
.input-area {
  position: absolute;
  right: 0;
  bottom: 0;
  left: 0;
  z-index: 3;
  border-top: 0;
  padding: 25px max(28px, calc((100% - 800px) / 2)) 18px;
  background: linear-gradient(to bottom, rgba(250,251,252,0), #fafbfc 20%);
}
.chat-area { position: relative; }
.input-row {
  display: flex;
  flex-direction: column;
  align-items: stretch;
  gap: 0;
  border: 1px solid #cfd7df;
  border-radius: 7px;
  box-shadow: 0 8px 22px rgba(23,33,43,.08);
  min-height: 106px;
  padding: 7px 10px 8px;
  background: #fff;
}
.input-row:focus-within {
  border-color: #6594d3;
  box-shadow: 0 0 0 3px #eaf2ff, 0 8px 22px rgba(23,33,43,.08);
}
.msg-input {
  width: 100%;
  flex: 0 0 auto;
  order: 2;
}
.msg-input :deep(.n-input-wrapper) { padding: 2px 2px 0; }
.msg-input :deep(.n-input__textarea-el) { font-size: 13px; line-height: 1.6; min-height: 42px !important; }
.msg-input :deep(.n-input) { background: transparent; }
.msg-input :deep(.n-input__border),
.msg-input :deep(.n-input__state-border) { display: none; }
.target-btn,
.at-btn {
  flex-shrink: 0;
  height: 24px;
  width: 24px;
  padding: 0;
  font-size: 13px;
  font-weight: 500;
}
.attachment-btn { color: #718092; }
.paperclip-icon {
  display: inline-block;
  width: 9px;
  height: 15px;
  border: 1.6px solid currentColor;
  border-radius: 6px;
  transform: rotate(-42deg);
  position: relative;
}
.paperclip-icon::after {
  content: "";
  position: absolute;
  inset: 2px;
  border: 1.4px solid currentColor;
  border-radius: 4px;
}
.send-btn {
  flex-shrink: 0;
  height: 27px;
  font-size: 11px;
}
.send-btn :deep(.n-button__content) { gap: 5px; }
.send-btn svg {
  width: 13px;
  height: 13px;
  fill: none;
  stroke: currentColor;
  stroke-width: 1.8;
  stroke-linecap: round;
  stroke-linejoin: round;
}
.target-select {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  border: 0;
  background: transparent;
  color: #65717e;
  font-size: 11px;
  padding: 3px 5px;
  white-space: nowrap;
}
.mention-icon { color: #3470c1; font-weight: 700; font-size: 13px; line-height: 1; }
.target-chevron { color: #84909c; font-size: 12px; margin-left: 1px; line-height: 1; }
.composer-tools {
  display: flex;
  align-items: center;
  gap: 2px;
  min-height: 26px;
  flex: 0 0 auto;
}
.composer-footer {
  display: flex;
  order: 3;
  align-items: center;
  justify-content: space-between;
  margin-top: 2px;
}
.composer-hint {
  color: #a1aab3;
  font-family: monospace;
  font-size: 10px;
}

.inspector-panel {
  width: 300px;
  border-left: 1px solid #eceef2;
  background: #fff;
  display: flex;
  flex-direction: column;
  height: 100%;
  overflow: hidden;
}
.inspector-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  min-height: 56px;
  padding: 0 14px 0 16px;
  border-bottom: 1px solid #eceef2;
  font-size: 14px;
  font-weight: 600;
}
.panel-section {
  padding: 14px 16px;
}
.panel-third {
  flex: 1;
  min-height: 0;
  display: flex;
  flex-direction: column;
  padding-bottom: 12px;
  overflow: hidden;
}
.panel-third + .panel-third {
  border-top: 1px solid #eceef2;
}
.panel-title-actions {
  display: flex;
  align-items: center;
  justify-content: space-between;
  flex: 0 0 auto;
}
.panel-scroll {
  flex: 1;
  min-height: 0;
  overflow-y: auto;
  padding-right: 2px;
}
.invite-agent-btn {
  flex: 0 0 auto;
  margin-top: 10px;
}
.task-composer {
  flex: 0 0 auto;
  margin-bottom: 8px;
}
.task-item {
  padding: 8px;
  border: 1px solid #eceef2;
  border-radius: 8px;
  margin-bottom: 8px;
}
.task-item.running {
  border-color: #0ea5e9;
}
.task-item.revising {
  border-color: #ef4444;
}
.task-item.done {
  border-color: #10b981;
}
.task-title {
  font-size: 13px;
  margin-bottom: 4px;
}

.task-assignee { font-size: 11px; color: #888; }
.task-ac { margin-top: 4px; padding: 4px 6px; background: rgba(0,0,0,0.03); border-radius: 4px; font-size: 11px; line-height: 1.5; }
.task-ac-line { display: flex; gap: 4px; }
.ac-p0 { color: #d4380d; font-weight: 600; }
.ac-p1 { color: #d48806; }
.task-meta {
  display: flex;
  align-items: center;
  gap: 6px;
  font-size: 12px;
  color: #888;
}

/* 产物项 */
.artifact-item {
  border: 1px solid #eceef2;
  border-radius: 8px;
  padding: 8px;
  margin-bottom: 8px;
}
/* 产物文件夹 */
.folder-item {
  margin-bottom: 8px;
}
.folder-row {
  position: relative;
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 8px;
  border: 1px solid #eceef2;
  border-radius: 8px;
  padding: 8px 10px;
  cursor: pointer;
  transition: background 0.15s;
}
.folder-row:hover {
  background: #f5f7fa;
}
.folder-name {
  font-size: 13px;
  font-weight: 600;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
/* 删除图标：悬浮提示，不占布局 */
.folder-del-btn {
  position: absolute;
  right: 2px;
  top: 50%;
  transform: translateY(-50%);
  opacity: 0;
  border: none;
  background: transparent;
  color: #d03050;
  font-size: 14px;
  line-height: 1;
  cursor: pointer;
  padding: 2px 5px;
  border-radius: 4px;
  transition: opacity 0.15s, background 0.15s;
  z-index: 5;
}
.folder-row:hover .folder-del-btn {
  opacity: 1;
}
.folder-del-btn:hover {
  background: #fdecee;
}
.folder-files {
  margin-top: 6px;
  padding: 6px;
  background: #fafbfc;
  border-radius: 8px;
}
.folder-files.loading {
  opacity: 0.6;
}
.artifact-name {
  font-size: 12px;
  font-family: monospace;
  margin-bottom: 4px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.artifact-actions {
  display: flex;
  gap: 6px;
  margin-top: 6px;
}
.artifact-preview {
  max-height: 60vh;
  overflow: auto;
  background: #0d1117;
  color: #e6edf3;
  border-radius: 8px;
  padding: 12px;
  font-size: 12px;
  white-space: pre-wrap;
  word-break: break-all;
}
.pending-files {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
  padding: 4px 2px 8px;
}
.pending-file {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  max-width: 260px;
  background: #f5f5fa;
  border: 1px solid #e8e8f0;
  border-radius: 6px;
  padding: 3px 8px;
  font-size: 12px;
}
.pf-icon { flex: none; }
.pf-name {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  color: #333;
}
.pf-size { flex: none; color: #999; }
.pf-del {
  flex: none;
  cursor: pointer;
  color: #bbb;
  font-size: 12px;
  padding: 0 2px;
  line-height: 1;
}
.pf-del:hover { color: #e5484d; }
.artifact-img {
  max-width: 100%;
  max-height: 70vh;
  border-radius: 6px;
  display: block;
  margin: 0 auto;
}
.artifact-video {
  width: 100%;
  max-height: 70vh;
  border-radius: 6px;
  background: #000;
}

.msg-attachment { margin: 2px 0; }
.att-thumb {
  max-width: 220px; max-height: 220px; border-radius: 8px;
  cursor: pointer; display: block; object-fit: cover;
  border: 1px solid rgba(0,0,0,.08);
}
.att-file {
  display: inline-flex; align-items: center; gap: 8px;
  padding: 8px 12px; background: rgba(255,255,255,.6);
  border: 1px solid rgba(0,0,0,.08); border-radius: 8px;
  cursor: pointer; font-size: 13px; max-width: 260px;
}
.att-file:hover { background: rgba(0,0,0,.04); }
.att-icon { font-size: 18px; }
.att-name { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }

.artifact-pdf {
  width: 100%; height: 70vh; border: none; border-radius: 6px; background: #fff;
}

@media (max-width: 900px) {
  .inspector-panel {
    width: min(320px, 42vw);
  }
  .sync-state { display: none; }
}

@media (max-width: 640px) {
  .chat-head { padding: 0 10px; }
  .project-crumb { display: none; }
  .task-context { width: calc(100% - 24px); margin-top: 10px; }
  .msg-box { padding: 16px 12px; }
  .input-area { padding: 10px 12px 12px; }
  .inspector-panel {
    position: absolute;
    z-index: 20;
    right: 0;
    top: 0;
    width: min(340px, 88vw);
    box-shadow: -8px 0 24px rgba(24, 32, 48, 0.12);
  }
}
</style>
