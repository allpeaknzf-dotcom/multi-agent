"""消息协议常量。"""
from __future__ import annotations

# 消息类型
MSG_TEXT = "text"
MSG_CODE = "code"
MSG_ARTIFACT = "artifact"
MSG_STATUS = "status"
MSG_SYSTEM = "system"
MSG_ORCHESTRATOR = "orchestrator"

# 发送者类型
SENDER_USER = "user"
SENDER_AGENT = "agent"
SENDER_SYSTEM = "system"

# 任务状态
TASK_PENDING = "pending"
TASK_RUNNING = "running"
TASK_REVIEWING = "reviewing"
TASK_REVISING = "revising"
TASK_PAUSED = "paused"
TASK_DONE = "done"
TASK_CANCELLED = "cancelled"

# 会话角色
ROLE_HOST = "host"
ROLE_MEMBER = "member"

# 会话成员状态
MEMBER_ACTIVE = "active"
MEMBER_INVITED = "invited"
MEMBER_LEFT = "left"

# 前端事件类型（WebSocket 下发）
EVT_MESSAGE = "message"
EVT_TASK = "task"
EVT_STATUS = "status"
EVT_AGENT_TYPING = "agent_typing"
