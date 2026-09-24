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
  createProject: (name: string, description?: string, folderPath?: string) =>
    req<any>("/api/projects", {
      method: "POST",
      body: JSON.stringify({ name, description, folder_path: folderPath || null }),
    }),
  getProject: (id: number) => req<any>(`/api/projects/${id}`),
  renameProject: (id: number, name: string) =>
    req<any>(`/api/projects/${id}/rename`, {
      method: "PUT",
      body: JSON.stringify({ name }),
    }),
  archiveProject: (id: number, archived: boolean) =>
    req<any>(`/api/projects/${id}/archive`, {
      method: "PUT",
      body: JSON.stringify({ archived }),
    }),
  deleteProject: (id: number, deleteFolder = false) =>
    req<any>(`/api/projects/${id}?delete_folder=${deleteFolder}`, {
      method: "DELETE",
    }),
  listMemories: (projectId: number) => req<any[]>(`/api/projects/${projectId}/memories`),
  createMemory: (projectId: number, data: { title: string; content: string; tags?: string }) =>
    req<any>(`/api/projects/${projectId}/memories`, {
      method: "POST",
      body: JSON.stringify(data),
    }),
  updateMemory: (memoryId: number, data: { title?: string; content?: string; pinned?: boolean }) =>
    req<any>(`/api/memories/${memoryId}`, {
      method: "PUT",
      body: JSON.stringify(data),
    }),
  deleteMemory: (memoryId: number) =>
    req<any>(`/api/memories/${memoryId}`, { method: "DELETE" }),
  listSessions: (projectId: number) =>
    req<any[]>(`/api/projects/${projectId}/sessions`),
  listRecentSessions: (limit = 30, archived = false) =>
    req<any[]>(`/api/recent-sessions?limit=${limit}&archived=${archived}`),
  listAllSessions: (limit = 500) =>
    req<any[]>(`/api/recent-sessions?limit=${limit}&all_sessions=true`),

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
  probeKey: (id: number) =>
    req<any>(`/api/keys/${id}/probe`, { method: "POST" }),
  updateKeyCapability: (id: number, capability: string) =>
    req<any>(`/api/keys/${id}/capability`, { method: "PUT", body: JSON.stringify({ capability }) }),
  deleteKey: (id: number) => req<any>(`/api/keys/${id}`, { method: "DELETE" }),

  // Agent
  listAgents: (projectId?: number) =>
    req<any[]>(`/api/agents${projectId ? `?project_id=${projectId}` : ""}`),
  getTemplates: () => req<any[]>("/api/agent-templates"),
  createTemplate: (body: any) =>
    req<any>("/api/agent-templates", { method: "POST", body: JSON.stringify(body) }),
  updateTemplate: (id: number, body: any) =>
    req<any>(`/api/agent-templates/${id}`, { method: "PUT", body: JSON.stringify(body) }),
  deleteTemplate: (id: number) =>
    req<any>(`/api/agent-templates/${id}`, { method: "DELETE" }),
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
  renameSession: (id: number, title: string) =>
    req<any>(`/api/sessions/${id}/rename`, {
      method: "PUT",
      body: JSON.stringify({ name: title }),
    }),
  moveSession: (id: number, projectId: number | null) =>
    req<any>(`/api/sessions/${id}/move`, {
      method: "PUT",
      body: JSON.stringify({ project_id: projectId }),
    }),
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
  pauseTask: (id: number) => req<any>(`/api/tasks/${id}/pause`, { method: "POST" }),
  resumeTask: (id: number) => req<any>(`/api/tasks/${id}/resume`, { method: "POST" }),
  runCode: (id: number, code: string, language = "python", timeout = 60) =>
    req<any>(`/api/sessions/${id}/run-code`, {
      method: "POST",
      body: JSON.stringify({ session_id: id, code, language, timeout }),
    }),

  // 产物
  listArtifacts: (id: number, folder?: string) =>
    req<any[]>(
      `/api/sessions/${id}/artifacts${
        folder !== undefined ? `?folder=${encodeURIComponent(folder)}` : ""
      }`
    ),
  listArtifactFolders: (id: number) =>
    req<any>(`/api/sessions/${id}/artifact-folders`),
  projectFolderPath: (projectId: number) =>
    req<{ ok: boolean; path: string }>(`/api/projects/${projectId}/path`),
  deleteArtifact: (artifactId: number) =>
    req<any>(`/api/artifacts/${artifactId}`, {
      method: "DELETE",
    }),
  deleteArtifactFolder: (sessionId: number, folder: string) =>
    req<any>(
      `/api/sessions/${sessionId}/artifact-folders?folder=${encodeURIComponent(folder)}`,
      { method: "DELETE" }
    ),
  artifactDownloadUrl: (artifactId: number) =>
    `${BASE}/api/artifacts/${artifactId}/download`,
  fetchArtifact: (artifactId: number) => fetch(`${BASE}/api/artifacts/${artifactId}/download`),
  // 上传附件（multipart/form-data，供 Agent 作为上下文使用）
  uploadAttachment: async (sessionId: number, file: File) => {
    const fd = new FormData();
    fd.append("file", file);
    const res = await fetch(`${BASE}/api/sessions/${sessionId}/upload`, {
      method: "POST",
      body: fd,
    });
    if (!res.ok) {
      const body = await res.json().catch(() => ({}));
      throw new Error((body as any).detail || `HTTP ${res.status}`);
    }
    return res.json();
  },
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
