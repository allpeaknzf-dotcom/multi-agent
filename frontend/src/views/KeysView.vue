<script setup lang="ts">
import { h, onMounted, ref } from "vue";
import { NButton, useMessage } from "naive-ui";
import { api } from "../api/client";

const message = useMessage();

const keys = ref<any[]>([]);

const showKeyModal = ref(false);
const editingKeyId = ref<number | null>(null);
const keyForm = ref<any>({ name: "", provider: "openai", model: "", api_key: "", base_url: "" });

const providerOptions = [
  { label: "OpenAI", value: "openai" },
  { label: "Anthropic (Claude)", value: "anthropic" },
  { label: "火山方舟 (豆包)", value: "volcengine" },
  { label: "OpenRouter", value: "openrouter" },
];

async function load() {
  try {
    keys.value = await api.listKeys();
  } catch (e: any) {
    message.error(e.message || "加载失败");
  }
}

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
    <div class="page-title">API Key 管理</div>

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

    <!-- Key 表单 -->
    <n-modal v-model:show="showKeyModal" preset="card" :title="editingKeyId ? '编辑 API Key' : '新增 API Key'" style="width: 560px">
      <n-form label-placement="top">
        <n-form-item label="名称">
          <n-input v-model:value="keyForm.name" placeholder="例如：我的 DeepSeek 网关" />
        </n-form-item>
        <n-form-item label="Provider">
          <n-select v-model:value="keyForm.provider" :options="providerOptions" />
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
