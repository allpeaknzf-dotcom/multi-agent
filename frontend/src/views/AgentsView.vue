<script setup lang="ts">
import { computed, h, onMounted, ref, watch } from "vue";
import { NButton, useMessage } from "naive-ui";
import { api } from "../api/client";

const message = useMessage();

const tab = ref("agents");
const agents = ref<any[]>([]);
const keys = ref<any[]>([]);
const templates = ref<any[]>([]);

// Agent 表单
const showAgentModal = ref(false);
const editingId = ref<number | null>(null);
const agentForm = ref<any>({
  name: "",
  role_hint: "",
  system_prompt: "",
  provider: "openai",
  model: "",
  key_ref: null,
  base_url: "",
  temperature: 0.7,
  max_tokens: 4096,
  is_global: true,
});

const providerOptions = [
  { label: "OpenAI", value: "openai" },
  { label: "Anthropic (Claude)", value: "anthropic" },
  { label: "火山方舟 (豆包)", value: "volcengine" },
  { label: "OpenRouter", value: "openrouter" },
  { label: "Ollama (本地)", value: "ollama" },
];

const keyOptions = computed(() =>
  keys.value.map((k) => ({
    label: `${k.name}（${k.provider}）`,
    value: k.key_ref,
    base_url: k.base_url,
    provider: k.provider,
    model: k.model,
  }))
);

// Key 表单（新增 / 编辑共用）
const showKeyModal = ref(false);
const editingKeyId = ref<number | null>(null);
const keyForm = ref<any>({ name: "", provider: "openai", model: "", api_key: "", base_url: "" });

async function load() {
  try {
    [agents.value, keys.value, templates.value] = await Promise.all([
      api.listAgents(),
      api.listKeys(),
      api.getTemplates(),
    ]);
  } catch (e: any) {
    message.error(e.message || "加载失败");
  }
}

// ---------- Agent ----------
function openCreateAgent(template?: any) {
  editingId.value = null;
  agentForm.value = {
    name: template?.name || "",
    role_hint: template?.role_hint || "",
    system_prompt: template?.system_prompt || "",
    provider: template?.provider || "openai",
    model: template?.model || "",
    key_ref: null,
    base_url: "",
    temperature: 0.7,
    max_tokens: 4096,
    is_global: true,
  };
  showAgentModal.value = true;
}

function openEditAgent(a: any) {
  editingId.value = a.id;
  agentForm.value = { ...a };
  showAgentModal.value = true;
}

// 选了 Key 后，若 Agent 尚未填 provider/base_url 则自动带出
watch(
  () => agentForm.value.key_ref,
  (ref) => {
    if (!ref) return;
    const opt = keyOptions.value.find((o) => o.value === ref);
    if (!opt) return;
    if (!agentForm.value.provider || agentForm.value.provider === "openai") {
      // 网关 Key（有 base_url）跟随其 provider；官方 Key 保持用户选择
      if (opt.base_url) agentForm.value.provider = opt.provider;
    }
    if (!agentForm.value.model && opt.model) {
      agentForm.value.model = opt.model;
    }
    if (!agentForm.value.base_url && opt.base_url) {
      agentForm.value.base_url = opt.base_url;
    }
  }
);

async function saveAgent() {
  if (!agentForm.value.model.trim()) {
    message.error("请填写模型名（网关模型需与平台一致，例如 deepseek-v4-flash）");
    return;
  }
  if (!agentForm.value.key_ref && agentForm.value.provider !== "ollama") {
    message.error("请选择使用的 API Key（Ollama 除外）");
    return;
  }
  try {
    const body = {
      ...agentForm.value,
      base_url: agentForm.value.base_url || null,
      key_ref: agentForm.value.key_ref || null,
    };
    if (editingId.value) {
      await api.updateAgent(editingId.value, body);
      message.success("Agent 已更新");
    } else {
      await api.createAgent(body);
      message.success("Agent 已创建");
    }
    showAgentModal.value = false;
    load();
  } catch (e: any) {
    message.error(e.message || "保存失败");
  }
}

async function removeAgent(a: any) {
  try {
    await api.deleteAgent(a.id);
    message.success("已删除");
    load();
  } catch (e: any) {
    message.error(e.message || "删除失败");
  }
}

// ---------- Key ----------
function openCreateKey() {
  editingKeyId.value = null;
  keyForm.value = { name: "", provider: "openai", model: "", api_key: "", base_url: "" };
  showKeyModal.value = true;
}

function openEditKey(k: any) {
  editingKeyId.value = k.id;
  keyForm.value = {
    name: k.name,
    provider: k.provider,
    model: k.model || "",
    api_key: "",
    base_url: k.base_url || "",
  };
  // 回显已保存的 Key（明文从钥匙串取回，输入框以密码掩码显示，可点眼睛查看）
  api
    .getKeyValue(k.id)
    .then(({ value }) => {
      keyForm.value.api_key = value || "";
    })
    .catch(() => {
      /* 取不到明文时留空 */
    });
  showKeyModal.value = true;
}

async function saveKey() {
  try {
    if (editingKeyId.value) {
      await api.updateKey(editingKeyId.value, {
        name: keyForm.value.name,
        provider: keyForm.value.provider,
        model: keyForm.value.model || undefined,
        base_url: keyForm.value.base_url || undefined,
        api_key: keyForm.value.api_key || undefined,
      });
      message.success("Key 已更新");
    } else {
      await api.createKey({
        name: keyForm.value.name,
        provider: keyForm.value.provider,
        model: keyForm.value.model || undefined,
        api_key: keyForm.value.api_key,
        base_url: keyForm.value.base_url || undefined,
      });
      message.success("Key 已保存（加密存储到系统钥匙串）");
    }
    showKeyModal.value = false;
    load();
  } catch (e: any) {
    message.error(e.message || "保存失败");
  }
}

async function copyKey(k: any) {
  // 复制一份一模一样的配置：名称加"（复制）"
  try {
    const { value } = await api.getKeyValue(k.id);
    if (!value) {
      message.error("未找到 Key 明文，无法复制");
      return;
    }
    await api.createKey({
      name: `${k.name}（复制）`,
      provider: k.provider,
      model: k.model,
      api_key: value,
      base_url: k.base_url || undefined,
    });
    message.success("已复制为一份相同配置");
    load();
  } catch (e: any) {
    message.error(e.message || "复制失败");
  }
}

const testingKeyId = ref<number | null>(null);
async function testKey(k: any) {
  testingKeyId.value = k.id;
  try {
    const res = await api.testKey(k.id);
    if (res.ok) {
      message.success(`连接正常：${res.reply}`);
    } else {
      message.error(`连接失败：${res.error}`);
    }
  } catch (e: any) {
    message.error(e.message || "测试失败");
  } finally {
    testingKeyId.value = null;
  }
}

async function removeKey(k: any) {
  try {
    await api.deleteKey(k.id);
    message.success("Key 已删除");
    load();
  } catch (e: any) {
    message.error(e.message || "删除失败");
  }
}

onMounted(load);
</script>

<template>
  <div class="page">
    <div class="page-title">Agent 管理</div>

    <n-tabs v-model:value="tab">
      <!-- Agent 列表 -->
      <n-tab-pane name="agents" tab="我的 Agent">
        <n-space justify="space-between" style="margin-bottom: 12px">
          <n-space>
            <n-button type="primary" @click="openCreateAgent()">新建 Agent</n-button>
            <n-dropdown
              trigger="click"
              :options="templates.map((t, i) => ({ label: `导入模板：${t.name}`, key: String(i) }))"
              @select="(key: any) => openCreateAgent(templates[Number(key)])"
            >
              <n-button>从模板导入</n-button>
            </n-dropdown>
          </n-space>
        </n-space>

        <n-empty v-if="agents.length === 0" description="还没有 Agent，点左上角创建" />
        <n-data-table
          v-else
          :columns="[
            { title: '名称', key: 'name' },
            { title: 'Provider', key: 'provider', width: 120 },
            { title: '模型', key: 'model' },
            { title: '角色', key: 'role_hint', ellipsis: { tooltip: true } },
            {
              title: '操作', key: 'ops', width: 140,
              render: (row: any) =>
                h('div', { style: 'display:flex;gap:4px' }, [
                  h(NButton, { size: 'small', quaternary: true, onClick: () => openEditAgent(row) }, { default: () => '编辑' }),
                  h(NButton, { size: 'small', type: 'error', quaternary: true, onClick: () => removeAgent(row) }, { default: () => '删除' }),
                ]),
            },
          ]"
          :data="agents"
          :row-key="(r: any) => r.id"
        />
      </n-tab-pane>

      <!-- Key 管理 -->
      <n-tab-pane name="keys" tab="API Key 管理">
        <n-space justify="space-between" style="margin-bottom: 12px">
          <n-button type="primary" @click="openCreateKey">新增 API Key</n-button>
        </n-space>
        <n-alert type="info" style="margin-bottom: 12px">
          Key 会加密存储到系统钥匙串（macOS Keychain），数据库中不保存明文。
          火山方舟需要在"自定义地址"填写你的专属 endpoint（https://ark.cn-beijing.volces.com/api/v3）。
          若使用 OpenAI 兼容网关，请选择 OpenAI Provider 并填写网关地址。
        </n-alert>
        <n-data-table
          :columns="[
            { title: '名称', key: 'name' },
            { title: 'Provider', key: 'provider', width: 140 },
            { title: '自定义地址', key: 'base_url', ellipsis: { tooltip: true } },
            {
              title: '操作', key: 'ops', width: 260,
              render: (row: any) =>
                h('div', { style: 'display:flex;gap:4px' }, [
                  h(NButton, { size: 'small', quaternary: true, onClick: () => openEditKey(row) }, { default: () => '编辑' }),
                  h(NButton, { size: 'small', quaternary: true, onClick: () => copyKey(row) }, { default: () => '复制' }),
                  h(NButton, { size: 'small', quaternary: true, loading: testingKeyId === row.id, onClick: () => testKey(row) }, { default: () => '测试' }),
                  h(NButton, { size: 'small', type: 'error', quaternary: true, onClick: () => removeKey(row) }, { default: () => '删除' }),
                ]),
            },
          ]"
          :data="keys"
          :row-key="(r: any) => r.id"
        />
      </n-tab-pane>
    </n-tabs>

    <!-- Agent 表单 -->
    <n-modal v-model:show="showAgentModal" preset="card" :title="editingId ? '编辑 Agent' : '新建 Agent'" style="width: 560px">
      <n-form label-placement="top">
        <n-form-item label="名称">
          <n-input v-model:value="agentForm.name" placeholder="例如：Codex 工程师" />
        </n-form-item>
        <n-form-item label="角色一句话">
          <n-input v-model:value="agentForm.role_hint" placeholder="擅长什么" />
        </n-form-item>
        <n-form-item label="人设 / 系统提示词">
          <n-input v-model:value="agentForm.system_prompt" type="textarea" :rows="3" placeholder="这个 Agent 的身份、性格、工作方式" />
        </n-form-item>
        <n-form-item label="Provider">
          <n-select v-model:value="agentForm.provider" :options="providerOptions" />
        </n-form-item>
        <n-form-item label="模型（选了 Key 自动带出，一般无需改）">
          <n-input v-model:value="agentForm.model" placeholder="例如 deepseek-v4-flash / gpt-4o" />
        </n-form-item>
        <n-form-item label="使用的 API Key">
          <n-select v-model:value="agentForm.key_ref" :options="keyOptions" placeholder="Ollama 可留空" clearable />
        </n-form-item>
        <n-form-item label="自定义地址（自动带出）">
          <n-input v-model:value="agentForm.base_url" placeholder="选了 Key 会自动填充" />
        </n-form-item>
      </n-form>
      <template #footer>
        <n-space justify="end">
          <n-button @click="showAgentModal = false">取消</n-button>
          <n-button type="primary" @click="saveAgent">保存</n-button>
        </n-space>
      </template>
    </n-modal>

    <!-- Key 表单 -->
    <n-modal v-model:show="showKeyModal" preset="card" :title="editingKeyId ? '编辑 API Key' : '新增 API Key'" style="width: 560px">
      <n-form label-placement="top">
        <n-form-item label="名称">
          <n-input v-model:value="keyForm.name" placeholder="例如：我的 DeepSeek 网关" />
        </n-form-item>
        <n-form-item label="Provider">
          <n-select v-model:value="keyForm.provider" :options="providerOptions.filter((p) => p.value !== 'ollama')" />
        </n-form-item>
        <n-form-item label="默认模型（新建 Agent 时自动带出）">
          <n-input v-model:value="keyForm.model" placeholder="例如 deepseek-v4-flash / gpt-4o / claude-sonnet-4" />
        </n-form-item>
        <n-form-item label="API Key">
          <n-input v-model:value="keyForm.api_key" type="password" show-password-on="click" :placeholder="editingKeyId ? '已回显保存的 Key，如需修改请直接编辑' : '粘贴你的 Key'" />
        </n-form-item>
        <n-form-item label="自定义地址">
          <n-input v-model:value="keyForm.base_url" placeholder="OpenAI 兼容网关 / 火山方舟填这里" />
        </n-form-item>
      </n-form>
      <template #footer>
        <n-space justify="end">
          <n-button @click="showKeyModal = false">取消</n-button>
          <n-button type="primary" @click="saveKey">保存</n-button>
        </n-space>
      </template>
    </n-modal>
  </div>
</template>
