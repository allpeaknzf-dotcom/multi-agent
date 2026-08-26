"""主理人调度状态机核心。

主理人是会话中被指定为"host"的 Agent，负责：
1. plan   —— 把用户任务拆解为子任务（指派给合适成员）
2. review —— 对成员产出做验收（可通过沙箱运行结果辅助判断）
3. merge  —— 汇总全部子任务结果，输出最终方案

所有 LLM 调用通过统一 Provider；结构化输出采用宽松 JSON 解析（支持 ```json 块）。
"""
from __future__ import annotations

import json
import re
from typing import Any

from sqlalchemy.orm import Session as DbSession

from ..models.entities import Agent, ChatSession, Message
from ..providers.base import ChatMessage
from ..providers.registry import build_provider
from .event_bus import EventBus, event_bus
from .memory import build_context
from .protocol import (
    EVT_STATUS,
    MSG_ORCHESTRATOR,
    SENDER_AGENT,
    TASK_DONE,
    TASK_PENDING,
    TASK_REVIEWING,
    TASK_REVISING,
    TASK_RUNNING,
)

_PLAN_SYSTEM = (
    "你是本多 Agent 协作会话的主理人（主持人），负责任务拆解与分工。"
    "请把用户任务拆解为 1~5 个清晰、可并行或串行执行的子任务，"
    "每个子任务指派给最合适的成员 Agent（用其名称 assignee 指定）。"
    '只输出 JSON 数组，不要输出任何其他内容，格式：'
    '[{"title": "子任务标题", "description": "详细要求", "assignee": "成员Agent名"}]'
)

_REVIEW_SYSTEM = (
    "你是本会话的主理人，正在验收成员 Agent 的任务产出。"
    "请判断产出是否达到任务要求。若达标，只输出 JSON："
    '{"pass": true, "comment": "通过意见"}'
    "若不达标，只输出 JSON："
    '{"pass": false, "comment": "具体问题与修改意见"}'
    "不要输出其他内容。"
)

_MERGE_SYSTEM = (
    "你是本会话的主理人。所有子任务已由各成员完成，"
    "请把各子任务的结果整合为一份完整、条理清晰的最终交付，"
    "并指出仍需注意的风险点。直接输出最终方案正文。"
)


def _extract_json(text: str) -> Any:
    """从 LLM 输出中提取 JSON（支持 ```json 包裹或纯 JSON）。"""
    text = text.strip()
    fence = re.search(r"```(?:json)?\s*([\s\S]*?)```", text)
    if fence:
        text = fence.group(1).strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        # 尝试截取第一个 [ 到最后一个 ]
        start, end = text.find("["), text.rfind("]")
        if start != -1 and end != -1 and end > start:
            return json.loads(text[start : end + 1])
        raise


class OrchestratorService:
    def __init__(self, db: DbSession, bus: EventBus | None = None) -> None:
        self.db = db
        self.bus = bus or event_bus

    # ---------- 通用 ----------
    async def _call_agent(
        self,
        agent: Agent,
        messages: list[ChatMessage],
        *,
        system: str,
    ) -> str:
        provider = build_provider(agent)
        result = await provider.chat(
            messages,
            system=system,
            temperature=agent.temperature,
            max_tokens=agent.max_tokens,
        )
        return result.content

    async def _status(self, session_id: int, text: str) -> None:
        await self.bus.publish(
            session_id, {"type": EVT_STATUS, "content": text, "ts": _now_iso()}
        )

    # ---------- 1. 拆解 ----------
    async def plan(
        self,
        session: ChatSession,
        host: Agent,
        user_task: str,
    ) -> list[dict[str, str]]:
        await self._status(session.id, f"主理人「{host.name}」正在拆解任务…")
        ctx = build_context(self.db, session.id)
        messages = [
            ChatMessage(role="user", content=f"用户任务：\n{user_task}"),
            ChatMessage(role="user", content="请输出子任务拆解 JSON。"),
        ]
        if ctx:
            ctx_msgs = [
                ChatMessage(role=m["role"], content=m["content"]) for m in ctx[-10:]
            ]
            messages = ctx_msgs + messages

        raw = await self._call_agent(host, messages, system=_PLAN_SYSTEM)
        try:
            plans = _extract_json(raw)
        except Exception:  # noqa: BLE001
            # 拆解失败：退化为单个子任务，由主理人自己执行
            await self._status(session.id, "拆解解析失败，降级为单任务执行。")
            return [
                {
                    "title": "整体任务",
                    "description": user_task,
                    "assignee": host.name,
                }
            ]

        if not isinstance(plans, list) or not plans:
            return [
                {
                    "title": "整体任务",
                    "description": user_task,
                    "assignee": host.name,
                }
            ]

        # 解析 assignee 为 Agent id；找不到则派给主理人自己
        resolved: list[dict[str, Any]] = []
        for p in plans:
            assignee_name = str(p.get("assignee", "")).strip()
            assignee = self._find_agent(session, assignee_name)
            resolved.append(
                {
                    "title": str(p.get("title", "子任务")),
                    "description": str(p.get("description", "")),
                    "assignee": assignee,
                }
            )
        return resolved

    def _find_agent(self, session: ChatSession, name: str) -> Agent:
        """按名称在会话成员里找 Agent，找不到返回主理人。"""
        host = self.db.get(Agent, session.orchestrator_agent_id) if session.orchestrator_agent_id else None
        for m in session.members:
            if m.status != "active":
                continue
            agent = self.db.get(Agent, m.agent_id)
            if agent and (agent.name == name or (host and agent.name == host.name)):
                return agent
        return host or session.members[0].agent_id and self.db.get(Agent, session.members[0].agent_id)

    # ---------- 2. 验收 ----------
    async def review(
        self,
        session: ChatSession,
        host: Agent,
        task: Any,
        result_content: str,
        run_output: str | None = None,
    ) -> tuple[bool, str]:
        prompt = (
            f"子任务：{task.title}\n要求：{task.description}\n\n"
            f"成员产出：\n{result_content[:6000]}"
        )
        if run_output:
            prompt += f"\n\n沙箱运行结果：\n{run_output[:3000]}"
        prompt += "\n\n请给出验收结论 JSON。"

        raw = await self._call_agent(
            host,
            [ChatMessage(role="user", content=prompt)],
            system=_REVIEW_SYSTEM,
        )
        try:
            verdict = _extract_json(raw)
            passed = bool(verdict.get("pass"))
            comment = str(verdict.get("comment", ""))
        except Exception:  # noqa: BLE001
            # 解析失败默认通过，避免死循环
            passed, comment = True, "验收解析失败，按通过处理。"

        task.status = TASK_DONE if passed else TASK_REVISING
        return passed, comment

    # ---------- 3. 汇总 ----------
    async def merge(
        self,
        session: ChatSession,
        host: Agent,
        subtask_results: list[tuple[str, str]],
    ) -> str:
        await self._status(session.id, f"主理人「{host.name}」正在汇总最终方案…")
        block = "\n\n".join(
            f"### {title}\n{content[:4000]}" for title, content in subtask_results
        )
        raw = await self._call_agent(
            host,
            [ChatMessage(role="user", content=f"各子任务结果如下：\n\n{block}")],
            system=_MERGE_SYSTEM,
        )
        return raw


def _now_iso() -> str:
    from datetime import datetime, timezone

    return datetime.now(timezone.utc).isoformat()
