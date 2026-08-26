<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from "vue";
import { useRoute, useRouter } from "vue-router";
import { useMessage } from "naive-ui";
import { api } from "../api/client";
import { useAgentsStore } from "../stores/agents";
import { useSessionStore } from "../stores/session";

const route = useRoute();
const router = useRouter();
const message = useMessage();
const agentsStore = useAgentsStore();
const store = useSessionStore();

const sessionId = Number(route.params.sid);
const session = ref<any>(null);
const allAgents = ref<any[]>([]);
const busy = ref(false);

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

// 拉人
const showInvite = ref(false);
const inviteAgentId = ref<number | null>(null);
const notInSessionAgents = computed(() =>
  allAgents.value.filter(
    (a: any) => !store.members.some((m: any) => m.agent_id === a.id && m.status === "active")
  )
);

// 派活
const showTaskInput = ref(false);
const taskInput = ref("");

// 产物
const artifacts = ref<any[]>([]);
const showArtifact = ref(false);
const viewingArtifact = ref<any>(null);
const artifactContent = ref("");

async function loadArtifacts() {
  artifacts.value = await api.listArtifacts(sessionId);
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
  try {
    const res = await api.fetchArtifact(art.id);
    if (!res.ok) {
      message.error("读取失败");
      return;
    }
    artifactContent.value = await res.text();
    viewingArtifact.value = art;
    showArtifact.value = true;
  } catch (e: any) {
    message.error(e.message || "读取失败");
  }
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

// 代码提取
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
  let html = content
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;");
  // 代码块 -> pre
  html = html.replace(
    /```(\w*)\n?([\s\S]*?)```/g,
    (_m, lang: string, code: string) =>
      `<pre class="codeblock"><span class="codelang">${lang || "code"}</span>${code.replace(/\n$/, "")}</pre>`
  );
  // 行内代码
  html = html.replace(/`([^`\n]+)`/g, "<code>$1</code>");
  // 普通文本换行
  html = html.replace(/\n/g, "<br>");
  return html;
}

function avatarColor(id: number): string {
  const colors = ["#6366f1", "#0ea5e9", "#f59e0b", "#10b981", "#ef4444", "#8b5cf6"];
  return colors[id % colors.length];
}

// 成员信息
function agentOf(m: any) {
  return allAgents.value.find((a: any) => a.id === m.agent_id);
}

// 发送
async function send() {
  const content = input.value.trim();
  if (!content || busy.value) return;
  busy.value = true;
  input.value = ""; // 发送瞬间立即清空输入框
  try {
    await api.sendMessage(sessionId, content, sendTarget.value);
    scrollToBottom();
  } catch (e: any) {
    if (!input.value) input.value = content; // 失败则恢复内容方便重发
    message.error(e.message || "发送失败");
  } finally {
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
  if (!inviteAgentId.value) return;
  try {
    await api.inviteAgent(sessionId, inviteAgentId.value);
    message.success("已拉入会话");
    showInvite.value = false;
    inviteAgentId.value = null;
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

// 启动时连接 WS
onMounted(async () => {
  try {
    await load();
  } catch (e: any) {
    message.error(e.message || "加载会话失败");
  }
  store.connect(sessionId);
});

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

function taskStatusLabel(s: string) {
  const map: Record<string, string> = {
    pending: "待派发",
    running: "执行中",
    reviewing: "验收中",
    revising: "退回重做",
    done: "已完成",
    cancelled: "已取消",
  };
  return map[s] || s;
}
</script>

<template>
  <div class="session-wrap">
    <!-- 左：成员 -->
    <aside class="member-panel">
      <div class="panel-title">成员 ({{ store.members.filter((m: any) => m.status === "active").length }})</div>
      <div v-for="m in store.members.filter((mm: any) => mm.status === 'active')" :key="m.id" class="member-item">
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

      <n-button size="small" block dashed style="margin-top: 12px" @click="showInvite = true">
        拉 Agent 进群
      </n-button>

      <!-- 派活 -->
      <div class="task-zone">
        <n-button v-if="!showTaskInput" size="small" type="warning" block @click="showTaskInput = true">
          ⚡ 派活给主理人
        </n-button>
        <div v-else>
          <n-input v-model:value="taskInput" type="textarea" :rows="3" placeholder="描述任务，主理人将拆解并分工" />
          <n-space style="margin-top: 8px" justify="end">
            <n-button size="small" @click="showTaskInput = false">取消</n-button>
            <n-button size="small" type="warning" :loading="busy" @click="startTask">派活</n-button>
          </n-space>
        </div>
      </div>
    </aside>

    <!-- 中：聊天 -->
    <main class="chat-area">
      <div class="chat-head">
        <n-button size="small" quaternary @click="router.push(`/projects/${session?.project_id}`)">←</n-button>
        <div class="chat-title">{{ session?.title || "会话" }}</div>
        <n-tag v-if="session?.orchestrator_agent_id" size="small" type="warning">主理人已就位</n-tag>
      </div>

      <!-- 状态栏 -->
      <div v-if="store.statuses.length" class="status-strip">
        <span v-for="(s, i) in store.statuses.slice(-3)" :key="i" class="status-item">{{ s }}</span>
        <span v-if="store.typing.length" class="status-typing">{{ store.typing.join("、") }} 正在思考…</span>
      </div>

      <div ref="msgBox" class="msg-box">
        <div v-for="m in store.messages" :key="m.id" class="msg-row" :class="m.sender_type">
          <!-- 用户 -->
          <div v-if="m.sender_type === 'user'" class="bubble user-bubble">
            <div class="msg-sender user-sender">我</div>
            <div class="msg-content" v-html="renderContent(m.content)"></div>
          </div>

          <!-- Agent -->
          <div v-else-if="m.sender_type === 'agent'" class="bubble agent-bubble">
            <div class="msg-sender" :style="{ color: avatarColor(m.sender_id || 0) }">
              <n-avatar round size="small" :style="{ background: avatarColor(m.sender_id || 0) }">
                {{ m.sender_name[0] }}
              </n-avatar>
              <span class="sender-name">
                {{ m.sender_name }}
                <n-tag v-if="isHostMsg(m)" size="tiny" type="warning">主理人</n-tag>
              </span>
            </div>
            <div class="msg-content" v-html="renderContent(m.content)"></div>
            <!-- 代码运行 -->
            <div v-if="extractCodeBlocks(m.content).length" class="code-actions">
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

          <!-- 系统 -->
          <div v-else class="sys-bubble">
            <span>{{ m.sender_name }}：{{ m.content }}</span>
          </div>
        </div>
        <div v-if="busy" class="busy-hint">处理中…</div>
      </div>

      <!-- 输入 -->
      <div class="input-area">
        <n-space style="margin-bottom: 6px" align="center">
          <n-select v-model:value="sendTarget" size="small" :options="recipientOptions" style="width: 150px" />
          <n-button v-if="sendTarget !== 'all'" size="small" type="primary" ghost disabled>将只发给指定 Agent</n-button>
          <span v-else style="font-size: 12px; color: #999">或在输入框输入 <code style="background:#f3f4f6;padding:0 4px;border-radius:4px">@Agent名</code> 直接定向</span>
        </n-space>
        <div class="input-row">
          <n-input
            v-model:value="input"
            type="textarea"
            :autosize="{ minRows: 1, maxRows: 12 }"
            placeholder="输入消息，@Agent名 可定向发给某位 Agent，回车发送（Shift+Enter 换行）"
            class="msg-input"
            @keydown.enter.exact.prevent="send"
          />
          <n-button type="primary" :loading="busy" @click="send" class="send-btn">发送</n-button>
        </div>
      </div>
    </main>

    <!-- 右：任务 + 产物 -->
    <aside class="task-panel">
      <div class="panel-title">任务</div>
      <n-empty v-if="store.tasks.length === 0" description="暂无任务" size="small" />
      <div v-for="t in store.tasks" :key="t.id" class="task-item" :class="t.status">
        <div class="task-title">{{ t.title }}</div>
        <div class="task-meta">
          <n-tag size="tiny" :type="t.status === 'done' ? 'success' : t.status === 'running' ? 'info' : t.status === 'revising' ? 'error' : 'default'">
            {{ taskStatusLabel(t.status) }}
          </n-tag>
          <span v-if="t.round"> 第 {{ t.round }}/{{ t.max_rounds }} 轮</span>
        </div>
      </div>

      <div class="artifact-zone">
        <div class="panel-title">产物</div>
        <n-empty v-if="artifacts.length === 0" description="暂无产物（运行代码后生成）" size="small" />
        <div v-for="art in artifacts" :key="art.id" class="artifact-item">
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
          </div>
        </div>
      </div>
    </aside>

    <!-- 拉人弹窗 -->
    <n-modal v-model:show="showInvite" preset="card" title="拉 Agent 进群" style="width: 420px">
      <n-select v-model:value="inviteAgentId" :options="notInSessionAgents.map((a: any) => ({ label: `${a.name}（${a.model}）`, value: a.id }))" placeholder="选择要拉入的 Agent" />
      <template #footer>
        <n-space justify="end">
          <n-button @click="showInvite = false">取消</n-button>
          <n-button type="primary" @click="doInvite">拉入</n-button>
        </n-space>
      </template>
    </n-modal>

    <!-- 产物查看 -->
    <n-modal v-model:show="showArtifact" preset="card" :title="`查看产物 · ${viewingArtifact?.name || ''}`" style="width: 680px">
      <pre class="artifact-preview">{{ artifactContent }}</pre>
      <template #footer>
        <n-space justify="end">
          <n-button @click="showArtifact = false">关闭</n-button>
          <n-button type="primary" @click="showArtifact = false; downloadArtifact(viewingArtifact)">下载</n-button>
        </n-space>
      </template>
    </n-modal>
  </div>
</template>

<style scoped>
.session-wrap {
  display: flex;
  height: 100vh;
}

/* 左栏 */
.member-panel {
  width: 220px;
  border-right: 1px solid #eceef2;
  padding: 16px;
  background: #fff;
  overflow-y: auto;
}
.panel-title {
  font-weight: 600;
  font-size: 13px;
  color: #666;
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
.task-zone {
  margin-top: 16px;
  border-top: 1px solid #eceef2;
  padding-top: 12px;
}

/* 中栏 */
.chat-area {
  flex: 1;
  display: flex;
  flex-direction: column;
  min-width: 0;
}
.chat-head {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 10px 16px;
  border-bottom: 1px solid #eceef2;
  background: #fff;
}
.chat-title {
  flex: 1;
  font-weight: 600;
  font-size: 15px;
}
.status-strip {
  padding: 4px 16px;
  font-size: 12px;
  color: #8b5cf6;
  background: #f5f3ff;
  border-bottom: 1px solid #eceef2;
  display: flex;
  gap: 12px;
  flex-wrap: wrap;
}
.status-typing {
  color: #6366f1;
  font-style: italic;
}
.msg-box {
  flex: 1;
  overflow-y: auto;
  padding: 16px;
  display: flex;
  flex-direction: column;
  gap: 12px;
}
.msg-row {
  display: flex;
  flex-direction: column;
}
.msg-row.user {
  align-items: flex-end;
}
.msg-row.agent {
  align-items: flex-start;
}
.bubble {
  max-width: 78%;
  border-radius: 10px;
  padding: 10px 14px;
}
.user-bubble {
  background: #6366f1;
  color: #fff;
}
.agent-bubble {
  background: #fff;
  border: 1px solid #eceef2;
}
.msg-sender {
  display: flex;
  align-items: center;
  gap: 6px;
  margin-bottom: 6px;
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
  line-height: 1.7;
  word-break: break-word;
}
.sys-bubble {
  align-self: center;
  font-size: 12px;
  color: #888;
  background: #f3f4f6;
  padding: 4px 12px;
  border-radius: 12px;
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
  border-top: 1px solid #eceef2;
  padding: 12px 16px;
  background: #fff;
}
.input-row {
  display: flex;
  align-items: flex-end;
  gap: 8px;
}
.msg-input {
  flex: 1;
}
.send-btn {
  flex-shrink: 0;
  height: 34px;
}

/* 右栏 */
.task-panel {
  width: 240px;
  border-left: 1px solid #eceef2;
  padding: 16px;
  background: #fff;
  overflow-y: auto;
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
.task-meta {
  display: flex;
  align-items: center;
  gap: 6px;
  font-size: 12px;
  color: #888;
}

/* 产物区 */
.artifact-zone {
  margin-top: 18px;
  border-top: 1px solid #eceef2;
  padding-top: 12px;
}
.artifact-item {
  border: 1px solid #eceef2;
  border-radius: 8px;
  padding: 8px;
  margin-bottom: 8px;
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
</style>
