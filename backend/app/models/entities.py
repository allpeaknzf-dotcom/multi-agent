"""Multi-agent 全部 ORM 实体（SQLite）。"""
from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import (
    JSON,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from ..core.db import Base


def _now() -> datetime:
    return datetime.now(timezone.utc)


class Project(Base):
    """项目：记忆隔离的边界。"""

    __tablename__ = "projects"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(String(20), default="active")  # active/archived
    memory: Mapped[str] = mapped_column(Text, default="")  # 项目级长期记忆（markdown）
    folder_path: Mapped[str | None] = mapped_column(String(500), nullable=True)  # 绑定的本地产物目录（可选）
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now)

    sessions: Mapped[list["ChatSession"]] = relationship(
        back_populates="project", cascade="all, delete-orphan"
    )


class KeyEntry(Base):
    """用户配置的 API Key 条目（明文存系统钥匙串，此处仅存引用）。"""

    __tablename__ = "key_entries"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    provider: Mapped[str] = mapped_column(String(40), nullable=False)
    model: Mapped[str | None] = mapped_column(String(120), nullable=True)  # 该 Key 的默认模型
    key_ref: Mapped[str] = mapped_column(String(120), nullable=False)
    base_url: Mapped[str | None] = mapped_column(String(500), nullable=True)
    capability: Mapped[str | None] = mapped_column(String(40), nullable=True)  # 探测后的能力
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now)


class Agent(Base):
    """Agent 定义：人设 + 模型 + Key 引用。支持全局 / 项目级。"""

    __tablename__ = "agents"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(80), nullable=False)
    role_hint: Mapped[str | None] = mapped_column(String(200), nullable=True)
    system_prompt: Mapped[str] = mapped_column(Text, default="")
    provider: Mapped[str] = mapped_column(String(40), nullable=False)  # openai/anthropic/volcengine/openrouter/ollama
    model: Mapped[str] = mapped_column(String(120), nullable=False)
    key_ref: Mapped[str | None] = mapped_column(String(120), nullable=True)  # KeyEntry 引用
    base_url: Mapped[str | None] = mapped_column(String(500), nullable=True)
    temperature: Mapped[float] = mapped_column(Float, default=0.7)
    max_tokens: Mapped[int] = mapped_column(Integer, default=4096)
    is_global: Mapped[bool] = mapped_column(Integer, default=1)
    project_id: Mapped[int | None] = mapped_column(
        ForeignKey("projects.id"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now)


class AgentTemplate(Base):
    """Agent 模板：预置 + 用户自定义，支持增删改查。"""

    __tablename__ = "agent_templates"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(80), nullable=False)
    provider: Mapped[str] = mapped_column(String(40), default="openai")
    model: Mapped[str | None] = mapped_column(String(120), nullable=True)
    role_hint: Mapped[str | None] = mapped_column(String(200), nullable=True)
    system_prompt: Mapped[str] = mapped_column(Text, default="")
    is_builtin: Mapped[bool] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=_now, onupdate=_now)


class ChatSession(Base):
    """会话（群聊）。"""

    __tablename__ = "chat_sessions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    project_id: Mapped[int | None] = mapped_column(
        ForeignKey("projects.id"), nullable=True
    )
    title: Mapped[str] = mapped_column(String(120), default="新会话")
    orchestrator_agent_id: Mapped[int | None] = mapped_column(
        ForeignKey("agents.id"), nullable=True
    )
    status: Mapped[str] = mapped_column(String(20), default="active")  # active/archived
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now)

    project: Mapped["Project"] = relationship(back_populates="sessions")
    members: Mapped[list["SessionMember"]] = relationship(
        back_populates="session", cascade="all, delete-orphan"
    )
    messages: Mapped[list["Message"]] = relationship(
        back_populates="session", cascade="all, delete-orphan"
    )
    tasks: Mapped[list["Task"]] = relationship(
        back_populates="session", cascade="all, delete-orphan"
    )


class SessionMember(Base):
    """会话成员（哪个 Agent 参与了哪个会话，含角色）。"""

    __tablename__ = "session_members"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    session_id: Mapped[int] = mapped_column(
        ForeignKey("chat_sessions.id"), nullable=False
    )
    agent_id: Mapped[int] = mapped_column(ForeignKey("agents.id"), nullable=False)
    role: Mapped[str] = mapped_column(String(20), default="member")  # host/member
    status: Mapped[str] = mapped_column(String(20), default="active")  # active/invited/left
    joined_at: Mapped[datetime] = mapped_column(DateTime, default=_now)

    session: Mapped["ChatSession"] = relationship(back_populates="members")


class Message(Base):
    """会话消息（含 @ 目标、类型、元数据）。"""

    __tablename__ = "messages"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    session_id: Mapped[int] = mapped_column(
        ForeignKey("chat_sessions.id"), nullable=False
    )
    sender_type: Mapped[str] = mapped_column(String(20), nullable=False)  # user/agent/system
    sender_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    sender_name: Mapped[str] = mapped_column(String(80), default="")
    msg_type: Mapped[str] = mapped_column(
        String(20), default="text"
    )  # text/code/artifact/status/system/orchestrator
    content: Mapped[str] = mapped_column(Text, default="")
    recipient: Mapped[str] = mapped_column(String(120), default="all")  # all / agent:{id}
    parent_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    meta: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now)

    session: Mapped["ChatSession"] = relationship(back_populates="messages")


class Task(Base):
    """主理人派发的子任务（支持父子任务、验收轮次）。"""

    __tablename__ = "tasks"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    session_id: Mapped[int] = mapped_column(
        ForeignKey("chat_sessions.id"), nullable=False
    )
    title: Mapped[str] = mapped_column(String(200), default="")
    description: Mapped[str] = mapped_column(Text, default="")
    assignee_agent_id: Mapped[int | None] = mapped_column(
        ForeignKey("agents.id"), nullable=True
    )
    status: Mapped[str] = mapped_column(
        String(20), default="pending"
    )  # pending/running/reviewing/revising/done/cancelled
    parent_task_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    result_msg_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    round: Mapped[int] = mapped_column(Integer, default=0)
    max_rounds: Mapped[int] = mapped_column(Integer, default=3)
    folder: Mapped[str | None] = mapped_column(String(200), nullable=True)
    acceptance_criteria: Mapped[str | None] = mapped_column(Text, nullable=True)  # JSON: [{id, level, text}]
    rework_log: Mapped[str | None] = mapped_column(Text, nullable=True)  # JSON: [{round, ac, issue, fix, priority}]
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=_now, onupdate=_now)

    session: Mapped["ChatSession"] = relationship(back_populates="tasks")


class Artifact(Base):
    """产物：代码 / 文档 / 图片 / 视频 等。"""

    __tablename__ = "artifacts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    session_id: Mapped[int] = mapped_column(
        ForeignKey("chat_sessions.id"), nullable=False
    )
    task_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    type: Mapped[str] = mapped_column(String(20), default="code")  # code/doc/image/video/other
    name: Mapped[str] = mapped_column(String(200), default="")
    file_path: Mapped[str] = mapped_column(String(500), default="")
    language: Mapped[str | None] = mapped_column(String(40), nullable=True)
    folder: Mapped[str | None] = mapped_column(String(200), nullable=True)
    meta: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now)
