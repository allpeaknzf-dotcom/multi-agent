<script setup lang="ts">
import { computed, h, onMounted, ref, watch } from "vue";
import { NButton, useMessage } from "naive-ui";
import { api } from "../api/client";

const emit = defineEmits<{ (e: "go-templates"): void }>();

const message = useMessage();

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

onMounted(load);

// 供父组件（岗位模板页"用此模板新建 Agent"）调用
defineExpose({ openCreateAgent });
</script>

<template>
  <div class="page">
    <div class="page-title">Agent 管理</div>

    <n-space justify="space-between" style="margin-bottom: 12px">
      <n-space>
        <n-button type="primary" @click="openCreateAgent()">新建 Agent</n-button>
        <n-dropdown
          trigger="click"
          :options="templates.map((t, i) => ({ label: t.name, key: String(i) }))"
          @select="(key: any) => openCreateAgent(templates[Number(key)])"
        >
          <n-button>从模板导入</n-button>
        </n-dropdown>
        <n-button @click="emit('go-templates')">模板管理</n-button>
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
  </div>
</template>
