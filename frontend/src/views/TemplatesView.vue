<script setup lang="ts">
import { h, onMounted, ref } from "vue";
import { NButton, useMessage } from "naive-ui";
import { api } from "../api/client";

const emit = defineEmits<{ (e: "use-template", t: any): void }>();

const message = useMessage();

const templates = ref<any[]>([]);

const showTemplateModal = ref(false);
const showTemplateView = ref(false);
const viewingTemplate = ref<any>(null);
const editingTemplateId = ref<number | null>(null);
const templateForm = ref<any>({
  name: "",
  provider: "openai",
  model: "",
  role_hint: "",
  system_prompt: "",
});

async function load() {
  try {
    templates.value = await api.getTemplates();
  } catch (e: any) {
    message.error(e.message || "加载失败");
  }
}

function viewTemplate(t: any) {
  viewingTemplate.value = t;
  showTemplateView.value = true;
}

function openCreateTemplate() {
  editingTemplateId.value = null;
  templateForm.value = {
    name: "",
    provider: "openai",
    model: "",
    role_hint: "",
    system_prompt: "",
  };
  showTemplateModal.value = true;
}

function openEditTemplate(t: any) {
  editingTemplateId.value = t.id;
  templateForm.value = {
    name: t.name,
    provider: t.provider,
    model: t.model || "",
    role_hint: t.role_hint || "",
    system_prompt: t.system_prompt || "",
  };
  showTemplateModal.value = true;
}

async function saveTemplate() {
  if (!templateForm.value.name.trim()) {
    message.error("请填写岗位名称");
    return;
  }
  try {
    const body = {
      name: templateForm.value.name.trim(),
      role_hint: templateForm.value.role_hint || undefined,
      system_prompt: templateForm.value.system_prompt || undefined,
    };
    if (editingTemplateId.value) {
      await api.updateTemplate(editingTemplateId.value, body);
      message.success("模板已更新");
    } else {
      await api.createTemplate(body);
      message.success("模板已新增");
    }
    showTemplateModal.value = false;
    await load();
  } catch (e: any) {
    message.error(e.message || "保存失败");
  }
}

async function removeTemplate(t: any) {
  try {
    await api.deleteTemplate(t.id);
    message.success("模板已删除");
    await load();
  } catch (e: any) {
    message.error(e.message || "删除失败");
  }
}

const templateColumns = [
  { title: "名称", key: "name" },
  { title: "角色", key: "role_hint", ellipsis: { tooltip: true } },
  {
    title: "类型",
    key: "is_builtin",
    width: 80,
    render: (row: any) =>
      row.is_builtin
        ? h("span", { style: "color:#999;font-size:12px" }, "预置")
        : h("span", { style: "color:#6366f1;font-size:12px" }, "自定义"),
  },
  {
    title: "操作",
    key: "ops",
    width: 200,
    render: (row: any) =>
      h("div", { style: "display:flex;gap:4px" }, [
        h(
          NButton,
          { size: "small", quaternary: true, onClick: () => viewTemplate(row) },
          { default: () => "查看" }
        ),
        row.is_builtin
          ? null
          : h(
              NButton,
              { size: "small", quaternary: true, onClick: () => openEditTemplate(row) },
              { default: () => "编辑" }
            ),
        row.is_builtin
          ? null
          : h(
              NButton,
              { size: "small", type: "error", quaternary: true, onClick: () => removeTemplate(row) },
              { default: () => "删除" }
            ),
      ].filter(Boolean)),
  },
];

onMounted(load);
</script>

<template>
  <div class="page">
    <div class="page-title">岗位模板</div>

    <n-space justify="space-between" style="margin-bottom: 12px">
      <n-button type="primary" @click="openCreateTemplate">新增模板</n-button>
    </n-space>
    <n-alert type="info" style="margin-bottom: 12px">
      预置模板由系统提供，仅可查看；自定义模板可编辑 / 删除。新建 Agent 时可从模板一键导入。
    </n-alert>
    <n-data-table
      :columns="templateColumns"
      :data="templates"
      :row-key="(r: any) => r.id"
    />

    <!-- 模板表单（新增 / 编辑） -->
    <n-modal v-model:show="showTemplateModal" preset="card" :title="editingTemplateId ? '编辑模板' : '新增模板'" style="width: 560px">
      <n-form label-placement="top">
        <n-form-item label="岗位名称">
          <n-input v-model:value="templateForm.name" placeholder="例如：测试工程师、产品经理" />
        </n-form-item>
        <n-form-item label="角色一句话">
          <n-input v-model:value="templateForm.role_hint" placeholder="擅长什么（例如：测试用例设计、自动化测试）" />
        </n-form-item>
        <n-form-item label="人设 / 系统提示词（岗位技能与交付标准）">
          <n-input v-model:value="templateForm.system_prompt" type="textarea" :rows="6" placeholder="这个岗位的身份、核心技能、工作方式与交付标准" />
        </n-form-item>
      </n-form>
      <template #footer>
        <n-space justify="end">
          <n-button @click="showTemplateModal = false">取消</n-button>
          <n-button type="primary" @click="saveTemplate">保存</n-button>
        </n-space>
      </template>
    </n-modal>

    <!-- 模板查看（预置只读） -->
    <n-modal v-model:show="showTemplateView" preset="card" :title="`模板 · ${viewingTemplate?.name || ''}`" style="width: 620px">
      <n-descriptions
        v-if="viewingTemplate"
        :column="1"
        label-placement="left"
        bordered
        size="small"
        :label-style="{ width: '150px', minWidth: '150px', whiteSpace: 'nowrap' }"
      >
        <n-descriptions-item label="岗位名称">{{ viewingTemplate.name }}</n-descriptions-item>
        <n-descriptions-item label="角色">{{ viewingTemplate.role_hint || "—" }}</n-descriptions-item>
        <n-descriptions-item label="人设 / 系统提示词">
          <div class="tmpl-view-prompt">{{ viewingTemplate.system_prompt }}</div>
        </n-descriptions-item>
      </n-descriptions>
      <template #footer>
        <n-space justify="end">
          <n-button type="primary" @click="emit('use-template', viewingTemplate)">用此模板新建 Agent</n-button>
          <n-button @click="showTemplateView = false">关闭</n-button>
        </n-space>
      </template>
    </n-modal>
  </div>
</template>

<style scoped>
.tmpl-view-prompt {
  font-size: 12px;
  color: #333;
  line-height: 1.8;
  white-space: pre-wrap;
  word-break: break-word;
  max-height: 320px;
  overflow-y: auto;
}
</style>
