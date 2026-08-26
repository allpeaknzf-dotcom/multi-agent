import { defineStore } from "pinia";
import { ref } from "vue";
import { api, connectWS } from "../api/client";

export const useSessionStore = defineStore("session", () => {
  const messages = ref<any[]>([]);
  const members = ref<any[]>([]);
  const tasks = ref<any[]>([]);
  const statuses = ref<string[]>([]);
  const typing = ref<string[]>([]);

  let ws: WebSocket | null = null;

  function onEvent(evt: any) {
    switch (evt.type) {
      case "message":
        messages.value.push(evt.message);
        break;
      case "task": {
        const i = tasks.value.findIndex((t) => t.id === evt.task.id);
        if (i >= 0) tasks.value[i] = evt.task;
        else tasks.value.push(evt.task);
        break;
      }
      case "status":
        statuses.value.push(evt.content);
        break;
      case "agent_typing":
        if (!typing.value.includes(evt.agent)) typing.value.push(evt.agent);
        break;
    }
  }

  async function load(sessionId: number) {
    messages.value = await api.listMessages(sessionId);
    members.value = await api.listMembers(sessionId);
    tasks.value = await api.listTasks(sessionId);
    statuses.value = [];
  }

  function connect(sessionId: number) {
    disconnect();
    ws = connectWS(sessionId, onEvent);
  }

  function disconnect() {
    if (ws) {
      ws.close();
      ws = null;
    }
  }

  return {
    messages,
    members,
    tasks,
    statuses,
    typing,
    load,
    connect,
    disconnect,
    onEvent,
  };
});
