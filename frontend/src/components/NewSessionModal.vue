<script setup lang="ts">
import { ref, computed, watch } from "vue";
import { useRouter } from "vue-router";
import { useMessage } from "naive-ui";
import { api } from "../api/client";

const props = defineProps<{
  show: boolean;
  defaultProjectId?: number | null;
}>();
const emit = defineEmits<{ (e: "update:show", v: boolean): void; (e: "created"): void }>();

const router = useRouter();
const message = useMessage();

const projects = ref<any[]>([]);
const agents = ref<any[]>([]);
const loading = ref(false);
const creating = ref(false);

const newTitle = ref("");
const selectedProjectId = ref<number | null>(null);
const selectedAgentIds = ref<number[]>([]);
const selectedHostId = ref<number | null>(null);

const projectOptions = computed(() => [
  { label: "不在项目中（独立对话）", value: 0 },
  ...projects.value
    .filter((p) => p.status !== "archived")
    .map((p) => ({ label: p.name, value: p.id })),
]);

const hostOptions = computed(() =>
  agents.value
    .filter((a) => selectedAgentIds.value.includes(a.id))
    .map((a) => ({ label: a.name, value: a.id }))
);

watch(
  () => props.show,
  async (v) => {
    if (!v) return;
    newTitle.value = "";
    selectedAgentIds.value = [];
    selectedHostId.value = null;
    selectedProjectId.value = props.defaultProjectId ?? null;
    loading.value = true;
    try {
      [projects.value, agents.value] = await Promise.all([
        api.listProjects(),
        api.listAgents(),
      ]);
    } catch (e: any) {
      message.error(e.message || "加载数据失败");
    } finally {
      loading.value = false;
    }
  }
);

async function create() {
  if (selectedAgentIds.value.length === 0) {
    message.warning("请至少选择一个 Agent");
    return;
  }
  creating.value = true;
  try {
    const pid = selectedProjectId.value || null;
    const s = await api.createSession({
      project_id: pid,
      title: newTitle.value.trim() || "新对话",
      agent_ids: selectedAgentIds.value,
      orchestrator_agent_id: selectedHostId.value,
    });
    message.success("对话已创建");
    emit("update:show", false);
    emit("created");
    if (pid) {
      router.push(`/projects/${pid}/sessions/${s.id}`);
    } else {
      router.push(`/sessions/${s.id}`);
    }
  } catch (e: any) {
    message.error(e.message || "创建失败");
  } finally {
    creating.value = false;
  }
}
</script>

<template>
  <n-modal :show="show" preset="card" title="新对话" style="width: 520px" @update:show="(v: boolean) => emit('update:show', v)">
    <n-spin :show="loading">
      <n-form label-placement="top">
        <n-form-item label="项目（可选，不选则为独立对话）">
          <n-select
            v-model:value="selectedProjectId"
            :options="projectOptions"
            placeholder="选择项目，或保持独立对话"
            clearable
          />
        </n-form-item>
        <n-form-item label="对话标题">
          <n-input v-model:value="newTitle" placeholder="可选，留空自动命名" />
        </n-form-item>
        <n-form-item label="选择参与的 Agent（可多选）">
          <div class="agent-check-list">
            <n-checkbox-group v-model:value="selectedAgentIds">
              <n-space vertical>
                <n-checkbox
                  v-for="a in agents"
                  :key="a.id"
                  :value="a.id"
                  :label="`${a.name}（${a.provider} / ${a.model}）`"
                />
              </n-space>
            </n-checkbox-group>
          </div>
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
    </n-spin>
    <template #footer>
      <n-space justify="end">
        <n-button @click="emit('update:show', false)">取消</n-button>
        <n-button type="primary" :loading="creating" @click="create">创建</n-button>
      </n-space>
    </template>
  </n-modal>
</template>

<style scoped>
.agent-check-list {
  max-height: 200px;
  overflow-y: auto;
  width: 100%;
}
</style>
