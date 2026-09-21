"""Pydantic 请求 / 响应模型。"""
from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class ORMBase(BaseModel):
    model_config = ConfigDict(from_attributes=True)


# ---------- Project ----------
class ProjectCreate(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    description: str | None = None
    folder_path: str | None = None  # 可选：绑定的本地产物目录（绝对路径）


class ProjectOut(ORMBase):
    id: int
    name: str
    description: str | None
    status: str
    memory: str | None
    folder_path: str | None
    created_at: datetime


class ProjectMemoryUpdate(BaseModel):
    memory: str


class RenameRequest(BaseModel):
    name: str = Field(min_length=1, max_length=120)


class MoveSessionRequest(BaseModel):
    project_id: int | None = None


# ---------- KeyEntry ----------
class KeyCreate(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    provider: str  # openai/anthropic/volcengine/openrouter/ollama
    model: str | None = None  # 该 Key 的默认模型
    api_key: str
    base_url: str | None = None


class KeyOut(ORMBase):
    id: int
    name: str
    provider: str
    model: str | None
    key_ref: str
    base_url: str | None
    created_at: datetime


class KeyUpdate(BaseModel):
    name: str | None = None
    provider: str | None = None
    model: str | None = None
    api_key: str | None = None
    base_url: str | None = None


# ---------- Agent ----------
class AgentCreate(BaseModel):
    name: str = Field(min_length=1, max_length=80)
    role_hint: str | None = None
    system_prompt: str = ""
    provider: str
    model: str
    key_ref: str | None = None
    base_url: str | None = None
    temperature: float = 0.7
    max_tokens: int = 4096
    is_global: bool = True
    project_id: int | None = None


class AgentOut(ORMBase):
    id: int
    name: str
    role_hint: str | None
    system_prompt: str
    provider: str
    model: str
    key_ref: str | None
    base_url: str | None
    temperature: float
    max_tokens: int
    is_global: bool
    project_id: int | None
    created_at: datetime


# ---------- AgentTemplate ----------
class TemplateCreate(BaseModel):
    name: str = Field(min_length=1, max_length=80)
    role_hint: str | None = None
    system_prompt: str = ""


class TemplateOut(ORMBase):
    id: int
    name: str
    role_hint: str | None
    system_prompt: str
    is_builtin: bool
    created_at: datetime


class TemplateUpdate(BaseModel):
    name: str | None = None
    role_hint: str | None = None
    system_prompt: str | None = None


# ---------- Session ----------
class SessionCreate(BaseModel):
    project_id: int | None = None
    title: str = "新会话"
    agent_ids: list[int] = Field(default_factory=list)
    orchestrator_agent_id: int | None = None


class SessionOut(ORMBase):
    id: int
    project_id: int | None
    title: str
    orchestrator_agent_id: int | None
    status: str
    created_at: datetime


class MemberOut(ORMBase):
    id: int
    session_id: int
    agent_id: int
    role: str
    status: str
    joined_at: datetime


# ---------- Message ----------
class MessageCreate(BaseModel):
    session_id: int
    sender_type: str = "user"  # user/agent/system
    sender_id: int | None = None
    content: str
    msg_type: str = "text"
    recipient: str = "all"  # all / agent:{id}
    meta: dict[str, Any] = Field(default_factory=dict)


class MessageOut(ORMBase):
    id: int
    session_id: int
    sender_type: str
    sender_id: int | None
    sender_name: str
    msg_type: str
    content: str
    recipient: str
    parent_id: int | None
    meta: dict[str, Any]
    created_at: datetime


# ---------- Task ----------
class TaskOut(ORMBase):
    id: int
    session_id: int
    title: str
    description: str
    assignee_agent_id: int | None
    status: str
    parent_task_id: int | None
    result_msg_id: int | None
    round: int
    max_rounds: int
    folder: str | None
    created_at: datetime
    updated_at: datetime


# ---------- Artifact ----------
class ArtifactOut(ORMBase):
    id: int
    session_id: int
    task_id: int | None
    type: str
    name: str
    file_path: str
    language: str | None
    folder: str | None
    meta: dict[str, Any]
    created_at: datetime


# ---------- 业务请求 ----------
class OrchestrateRequest(BaseModel):
    task_description: str


class InviteRequest(BaseModel):
    agent_id: int


class SetOrchestratorRequest(BaseModel):
    agent_id: int


class ArchiveRequest(BaseModel):
    archived: bool


class RunCodeRequest(BaseModel):
    session_id: int
    code: str
    language: str = "python"
    timeout: int = 60
    use_docker: bool = False  # True 时走 Docker L2（本机无 Docker 则自动回退 L1）


class RunCodeOut(BaseModel):
    stdout: str
    stderr: str
    exit_code: int
    timed_out: bool
    duration_ms: int
