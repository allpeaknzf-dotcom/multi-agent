import { defineStore } from "pinia";
import { ref } from "vue";
import { api } from "../api/client";

export const useAgentsStore = defineStore("agents", () => {
  const agents = ref<any[]>([]);
  const keys = ref<any[]>([]);
  const templates = ref<any[]>([]);

  async function load() {
    agents.value = await api.listAgents();
    keys.value = await api.listKeys();
    templates.value = await api.getTemplates();
  }

  return { agents, keys, templates, load };
});
