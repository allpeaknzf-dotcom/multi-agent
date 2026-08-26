// 与本地编排服务通信的 REST + WebSocket 封装
const BASE = "http://127.0.0.1:8765";

async function req<T>(path: string, options?: RequestInit): Promise<T> {
  const res = await fetch(`${BASE}${path}`, {
    headers: { "Content-Type": "application/json" },
    ...options,
  });
  if (!res.ok) {
    const body = await res.json().catch(() => ({}));
    throw new Error((body as any).detail || `HTTP ${res.status}`);
  }
  return res.json();
}

export const api = {
  // 健康检查
  health: () => req<any>("/api/health"),

  // 项目
  listProjects: () => req<any[]>("/api/projects"),
  createProject: (name: string, description?: string) =>
    req<any>("/api/projects", {
      method: "POST",
      body: JSON.stringify({ name, description }),
    }),
  getProject: (id: number) => req<any>(`/api/projects/${id}`),
  archiveProject: (id: number, archived: boolean) =>
    req<any>(`/api/projects/${id}/archive`, {
      method: "PUT",
      body: JSON.stringify({ archived }),
    }),
  deleteProject: (id: number) => req<any>(`/api/projects/${id}`, { method: "DELETE" }),
  getProjectMemory: (id: number) => req<any>(`/api/projects/${id}/memory`),
  updateProjectMemory: (id: number, memory: string) =>
    req<any>(`/api/projects/${id}/memory`, {
      method: "PUT",
      body: JSON.stringify({ memory }),
    }),
  listSessions: (projectId: number) =>
    req<any[]>(`/api/projects/${projectId}/sessions`),

  // Key 管理
  listKeys: () => req<any[]>("/api/keys"),
  createKey: (body: { name: string; provider: string; model?: string; api_key: string; base_url?: string }) =>
    req<any>("/api/keys", { method: "POST", body: JSON.stringify(body) }),
  updateKey: (id: number, body: any) =>
    req<any>(`/api/keys/${id}`, { method: "PUT", body: JSON.stringify(body) }),
  getKeyValue: (id: number) =>
    req<{ value: string }>(`/api/keys/${id}/value`),
  testKey: (id: number) =>
    req<{ ok: boolean; reply?: string; error?: string }>(`/api/keys/${id}/test`, {
      method: "POST",
    }),
  deleteKey: (id: number) => req<any>(`/api/keys/${id}`, { method: "DELETE" }),

  // Agent
  listAgents: (projectId?: number) =>
    req<any[]>(`/api/agents${projectId ? `?project_id=${projectId}` : ""}`),
  getTemplates: () => req<any[]>("/api/agent-templates"),
  createAgent: (body: any) =>
    req<any>("/api/agents", { method: "POST", body: JSON.stringify(body) }),
  updateAgent: (id: number, body: any) =>
    req<any>(`/api/agents/${id}`, { method: "PUT", body: JSON.stringify(body) }),
  deleteAgent: (id: number) =>
    req<any>(`/api/agents/${id}`, { method: "DELETE" }),

  // 会话
  createSession: (body: any) =>
    req<any>("/api/sessions", { method: "POST", body: JSON.stringify(body) }),
  getSession: (id: number) => req<any>(`/api/sessions/${id}`),
  archiveSession: (id: number, archived: boolean) =>
    req<any>(`/api/sessions/${id}/archive`, {
      method: "PUT",
      body: JSON.stringify({ archived }),
    }),
  deleteSession: (id: number) => req<any>(`/api/sessions/${id}`, { method: "DELETE" }),
  listMembers: (id: number) => req<any[]>(`/api/sessions/${id}/members`),
  listMessages: (id: number) => req<any[]>(`/api/sessions/${id}/messages`),
  listTasks: (id: number) => req<any[]>(`/api/sessions/${id}/tasks`),
  inviteAgent: (id: number, agentId: number) =>
    req<any>(`/api/sessions/${id}/invite`, {
      method: "POST",
      body: JSON.stringify({ agent_id: agentId }),
    }),
  setOrchestrator: (id: number, agentId: number) =>
    req<any>(`/api/sessions/${id}/orchestrator`, {
      method: "POST",
      body: JSON.stringify({ agent_id: agentId }),
    }),
  sendMessage: (id: number, content: string, recipient = "all") =>
    req<any>(`/api/sessions/${id}/messages`, {
      method: "POST",
      body: JSON.stringify({ session_id: id, content, recipient }),
    }),
  orchestrate: (id: number, taskDescription: string) =>
    req<any>(`/api/sessions/${id}/orchestrate`, {
      method: "POST",
      body: JSON.stringify({ task_description: taskDescription }),
    }),
  runCode: (id: number, code: string, language = "python", timeout = 60) =>
    req<any>(`/api/sessions/${id}/run-code`, {
      method: "POST",
      body: JSON.stringify({ session_id: id, code, language, timeout }),
    }),

  // 产物
  listArtifacts: (id: number) => req<any[]>(`/api/sessions/${id}/artifacts`),
  artifactDownloadUrl: (artifactId: number) =>
    `${BASE}/api/artifacts/${artifactId}/download`,
  fetchArtifact: (artifactId: number) => fetch(`${BASE}/api/artifacts/${artifactId}/download`),
};

// WebSocket 实时订阅（群聊消息 / 任务状态 / Agent 状态）
export function connectWS(sessionId: number, onEvent: (evt: any) => void): WebSocket {
  const ws = new WebSocket(`ws://127.0.0.1:8765/ws/${sessionId}`);
  ws.onmessage = (e) => {
    try {
      onEvent(JSON.parse(e.data));
    } catch {
      /* 忽略非 JSON */
    }
  };
  return ws;
}
