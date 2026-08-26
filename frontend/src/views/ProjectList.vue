<script setup lang="ts">
import { onMounted, ref, computed } from "vue";
import { useRouter } from "vue-router";
import { useDialog, useMessage } from "naive-ui";
import { api } from "../api/client";

const router = useRouter();
const message = useMessage();
const dialog = useDialog();

const projects = ref<any[]>([]);
const loading = ref(false);
const filter = ref<"active" | "archived">("active");
const searchQuery = ref("");

const showCreate = ref(false);
const newName = ref("");
const newDesc = ref("");

const visibleProjects = computed(() =>
  projects.value.filter((p) => {
    if (filter.value === "active" ? p.status === "archived" : p.status !== "archived") return false;
    const q = searchQuery.value.trim().toLowerCase();
    if (!q) return true;
    return (
      String(p.name || "").toLowerCase().includes(q) ||
      String(p.description || "").toLowerCase().includes(q)
    );
  })
);

const activeCount = computed(
  () => projects.value.filter((p) => p.status !== "archived").length
);
const archivedCount = computed(
  () => projects.value.filter((p) => p.status === "archived").length
);

async function load() {
  loading.value = true;
  try {
    projects.value = await api.listProjects();
  } catch (e: any) {
    message.error(e.message || "加载项目失败");
  } finally {
    loading.value = false;
  }
}

async function create() {
  if (!newName.value.trim()) return;
  try {
    const p = await api.createProject(newName.value.trim(), newDesc.value);
    message.success("项目已创建");
    showCreate.value = false;
    newName.value = "";
    newDesc.value = "";
    router.push(`/projects/${p.id}`);
  } catch (e: any) {
    message.error(e.message || "创建失败");
  }
}

async function toggleArchive(p: any) {
  try {
    const archived = p.status !== "archived";
    await api.archiveProject(p.id, archived);
    message.success(archived ? "已归档" : "已恢复");
    load();
  } catch (e: any) {
    message.error(e.message || "操作失败");
  }
}

function removeProject(p: any) {
  dialog.warning({
    title: "删除项目",
    content: `确定删除项目「${p.name}」吗？其下所有会话、消息、任务将一并删除，且不可恢复。`,
    positiveText: "删除",
    negativeText: "取消",
    onPositiveClick: async () => {
      try {
        await api.deleteProject(p.id);
        message.success("已删除");
        load();
      } catch (e: any) {
        message.error(e.message || "删除失败");
      }
    },
  });
}

onMounted(load);
</script>

<template>
  <div class="page">
    <div class="page-head">
      <div class="page-title">项目</div>
      <n-button type="primary" @click="showCreate = true">新建项目</n-button>
    </div>

    <n-tabs v-model:value="filter" type="line" style="margin-bottom: 12px">
      <n-tab-pane name="active" :tab="`进行中 (${activeCount})`" />
      <n-tab-pane name="archived" :tab="`已归档 (${archivedCount})`" />
    </n-tabs>

    <n-input
      v-model:value="searchQuery"
      placeholder="搜索项目名称或描述…"
      clearable
      size="large"
      style="margin-bottom: 16px"
    >
      <template #prefix>
        <span style="color: #999">🔍</span>
      </template>
    </n-input>

    <n-spin :show="loading">
      <n-empty v-if="!loading && visibleProjects.length === 0" :description="filter === 'active' ? '还没有项目，点击右上角新建' : '暂无已归档项目'">
        <template #footer>
          <n-button v-if="filter === 'active'" type="primary" @click="showCreate = true">新建项目</n-button>
        </template>
      </n-empty>

      <div class="project-grid">
        <n-card
          v-for="p in visibleProjects"
          :key="p.id"
          hoverable
          class="project-card"
          @click="router.push(`/projects/${p.id}`)"
        >
          <template #header>
            <div class="project-header">
              <span>{{ p.name }}</span>
              <n-dropdown
                trigger="click"
                :options="[
                  { label: p.status === 'archived' ? '恢复' : '归档', key: 'archive' },
                  { label: '删除', key: 'delete', type: 'error' },
                ]"
                @select="(k: string) => (k === 'archive' ? toggleArchive(p) : removeProject(p))"
              >
                <n-button size="small" quaternary circle @click.stop>···</n-button>
              </n-dropdown>
            </div>
          </template>
          <div class="project-desc">{{ p.description || "暂无描述" }}</div>
          <div class="project-meta">
            <n-tag v-if="p.status === 'archived'" size="tiny" type="warning">已归档</n-tag>
            <span>创建于 {{ new Date(p.created_at).toLocaleString() }}</span>
            <div style="flex: 1"></div>
            <n-button v-if="p.status === 'archived'" size="tiny" type="primary" ghost @click.stop="toggleArchive(p)">
              恢复
            </n-button>
          </div>
        </n-card>
      </div>
    </n-spin>

    <n-modal v-model:show="showCreate" preset="card" title="新建项目" style="width: 480px">
      <n-form label-placement="top">
        <n-form-item label="项目名称">
          <n-input v-model:value="newName" placeholder="例如：多Agent协作实验" />
        </n-form-item>
        <n-form-item label="描述（可选）">
          <n-input v-model:value="newDesc" type="textarea" placeholder="这个项目要做什么" />
        </n-form-item>
      </n-form>
      <template #footer>
        <n-space justify="end">
          <n-button @click="showCreate = false">取消</n-button>
          <n-button type="primary" @click="create">创建</n-button>
        </n-space>
      </template>
    </n-modal>
  </div>
</template>

<style scoped>
.page-head {
  display: flex;
  justify-content: space-between;
  align-items: center;
}
.project-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(260px, 1fr));
  gap: 16px;
  margin-top: 16px;
}
.project-card {
  cursor: pointer;
}
.project-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
}
.project-desc {
  color: #666;
  min-height: 40px;
  margin: 8px 0;
}
.project-meta {
  font-size: 12px;
  color: #999;
  display: flex;
  align-items: center;
  gap: 8px;
}
</style>
