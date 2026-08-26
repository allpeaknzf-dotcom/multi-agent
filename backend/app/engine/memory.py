"""项目级记忆。

MVP：基于会话消息历史构建上下文（最近 N 条，按时间正序）。
预留向量库 / 摘要沉淀接口，二期可替换为 RAG。
"""
from __future__ import annotations

from sqlalchemy.orm import Session as DbSession

from ..models.entities import Message
from .protocol import SENDER_SYSTEM

CONTEXT_LIMIT = 40


def build_context(
    db: DbSession,
    session_id: int,
    limit: int = CONTEXT_LIMIT,
) -> list[dict]:
    """构造发给 Agent 的对话上下文（role + content 列表）。"""
    rows = (
        db.query(Message)
        .filter(Message.session_id == session_id)
        .order_by(Message.id.desc())
        .limit(limit)
        .all()
    )
    rows.reverse()

    ctx: list[dict] = []
    for m in rows:
        if m.sender_type == SENDER_SYSTEM:
            continue
        role = "user" if m.sender_type == "user" else "assistant"
        prefix = f"[{m.sender_name}]" if m.sender_name else ""
        ctx.append({"role": role, "content": f"{prefix} {m.content}".strip()})
    return ctx
