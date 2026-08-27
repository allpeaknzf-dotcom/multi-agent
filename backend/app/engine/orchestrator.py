"""主理人调度状态机核心。

主理人是会话中被指定为"host"的 Agent，负责：
1. plan   —— 把用户任务拆解为子任务（指派给合适成员）
2. review —— 对成员产出做验收（可通过沙箱运行结果辅助判断）
3. merge  —— 汇总全部子任务结果，输出最终方案

所有 LLM 调用通过统一 Provider；结构化输出采用宽松 JSON 解析（支持 ```json 块）。
"""
from __future__ import annotations

import asyncio
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
    MEMBER_ACTIVE,
    MSG_ORCHESTRATOR,
    SENDER_AGENT,
    TASK_DONE,
    TASK_PENDING,
    TASK_REVIEWING,
    TASK_REVISING,
    TASK_RUNNING,
)

# 能力标签 → 关键词映射（用于从 role_hint / system_prompt 推断成员擅长领域）
_TAG_KEYWORDS: dict[str, list[str]] = {
    "后端": ["后端", "服务端", "接口", "数据库", "高并发", "分布式", "api", "中间件", "微服务"],
    "前端": ["前端", "页面", "ui", "组件", "交互", "html", "css", "javascript", "react", "vue"],
    "测试": ["测试", "用例", "质量", "验收", "自动化", "缺陷", "pytest", "qa"],
    "评审": ["评审", "审查", "代码审查", "安全", "review", "把关"],
    "产品": ["产品", "需求", "prd", "产品经理", "用户研究"],
    "项目管理": ["项目经理", "拆解", "排期", "wbs", "风险", "主理人"],
    "运维": ["运维", "部署", "ci", "devops", "发布", "k8s", "docker"],
    "数据分析": ["数据", "分析", "报表", "sql", "etl"],
}

# ② 分工规划系统提示词：先看成员能力清单，再分工，最后只输出子任务 JSON
_PLAN_SYSTEM = (
    "你是本多 Agent 协作会话的主理人（主持人），负责任务拆解与分工。"
    "在开始前，你会收到一份【团队成员能力清单】和【成员能力自述】，"
    "请认真阅读每个人擅长的领域，据此把用户任务拆解为 1~5 个清晰、可并行或串行执行的子任务，"
    "**每个子任务必须指派给清单中实际存在、且能力最匹配该子任务的成员**（用其名称 assignee 指定）。"
    "不要把所有任务都派给主理人自己——优先让最擅长的成员去执行。"
    "你的回复分为两段：\n"
    "第一段【分工说明】：用 2~4 句话简述你把任务切成哪几块、分别派给谁、依据是什么；\n"
    "第二段【子任务】：只输出 JSON 数组，不要其他内容，格式："
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

    # ---------- 1. 拆解（基于成员能力规划） ----------
    async def plan(
        self,
        session: ChatSession,
        host: Agent,
        user_task: str,
    ) -> list[dict[str, Any]]:
        await self._status(
            session.id, f"主理人「{host.name}」正在收集成员能力并拆解任务…"
        )

        # ① 成员能力清单（role_hint + 能力标签）
        roster = self._team_roster(session)
        roster_block = "\n".join(
            f"- {r['name']}（{r['role'] or '通用'}）擅长：{('、'.join(r['tags'])) or '通用'}"
            for r in roster
        ) or "（群内暂无可用成员）"

        # ④ 成员能力自述（动态，并发收集）
        intro_block = await self._collect_self_intros(session)

        ctx = build_context(self.db, session.id)
        plan_input = (
            f"用户任务：\n{user_task}\n\n"
            f"【团队成员能力清单】\n{roster_block}\n\n"
            f"【成员能力自述】\n{intro_block or '（无）'}\n\n"
            "请先给出【分工说明】，再输出【子任务】JSON 数组。"
        )
        messages = [ChatMessage(role="user", content=plan_input)]
        if ctx:
            ctx_msgs = [
                ChatMessage(role=m["role"], content=m["content"]) for m in ctx[-10:]
            ]
            messages = ctx_msgs + messages

        # 首次规划
        raw = await self._call_agent(host, messages, system=_PLAN_SYSTEM)
        plans = self._extract_plans(raw)
        if not plans:
            await self._status(session.id, "拆解解析失败，降级为单任务执行。")
            return self._fallback_plan(host, user_task)

        # ③ 人岗匹配校验；不通过则带着提示重试一次
        resolved, bad_names = self._resolve_plans(session, plans)
        if bad_names:
            await self._status(
                session.id,
                f"指派校验未通过：{('、'.join(bad_names))} 不在成员名单，重新规划…",
            )
            retry_input = (
                plan_input
                + f"\n\n注意：上次指派了不在名单中的成员：{('、'.join(bad_names))}。"
                "assignee 必须是【团队成员能力清单】中存在的成员名称，请修正后重新输出。"
            )
            raw2 = await self._call_agent(
                host,
                messages[:-1] + [ChatMessage(role="user", content=retry_input)],
                system=_PLAN_SYSTEM,
            )
            resolved, bad_names = self._resolve_plans(
                session, self._extract_plans(raw2)
            )

        # 仍无法匹配 → 回退主理人并提示
        if not resolved or bad_names:
            await self._status(
                session.id, "仍无法将子任务匹配到群内成员，降级由主理人统一执行。"
            )
            return self._fallback_plan(host, user_task)
        return resolved

    @staticmethod
    def _extract_plans(raw: str) -> list[dict[str, Any]]:
        try:
            plans = _extract_json(raw)
        except Exception:  # noqa: BLE001
            return []
        if not isinstance(plans, list) or not plans:
            return []
        return plans

    @staticmethod
    def _fallback_plan(host: Agent, user_task: str) -> list[dict[str, Any]]:
        return [
            {
                "title": "整体任务",
                "description": user_task,
                "assignee": host,
            }
        ]

    # ---------- 成员能力 ----------
    def _team_roster(self, session: ChatSession) -> list[dict[str, Any]]:
        """① 生成成员能力清单（名称/角色/能力标签）。"""
        roster: list[dict[str, Any]] = []
        for m in session.members:
            if m.status != MEMBER_ACTIVE:
                continue
            agent = self.db.get(Agent, m.agent_id)
            if not agent:
                continue
            roster.append(
                {
                    "name": agent.name,
                    "role": agent.role_hint or "",
                    "tags": self._infer_tags(agent),
                }
            )
        return roster

    @staticmethod
    def _infer_tags(agent: Agent) -> list[str]:
        """从名称 + 角色定位（role_hint）推断成员擅长领域标签；
        role_hint 为空时退而用 system_prompt 前段推断。"""
        text = f"{agent.name or ''} {agent.role_hint or ''}".lower()
        tags = [
            tag
            for tag, keys in _TAG_KEYWORDS.items()
            if any(k in text for k in keys)
        ]
        if tags:
            return tags
        text2 = (agent.system_prompt or "")[:300].lower()
        return [
            tag
            for tag, keys in _TAG_KEYWORDS.items()
            if any(k in text2 for k in keys)
        ]

    async def _collect_self_intros(self, session: ChatSession) -> str:
        """④ 并发收集每个成员基于自身人设的能力自述。"""
        members = [
            self.db.get(Agent, m.agent_id)
            for m in session.members
            if m.status == MEMBER_ACTIVE
        ]
        members = [a for a in members if a]
        if not members:
            return ""

        async def _intro(agent: Agent) -> str:
            try:
                provider = build_provider(agent)
                result = await provider.chat(
                    [
                        ChatMessage(
                            role="user",
                            content="请用 2~3 句话介绍你擅长做什么、最适合承接哪一类任务（基于你的角色设定）。",
                        )
                    ],
                    system=agent.system_prompt,
                    temperature=0.3,
                    max_tokens=300,
                )
                return f"- {agent.name}：{result.content.strip()[:200]}"
            except Exception:  # noqa: BLE001
                return f"- {agent.name}：{agent.role_hint or '通用'}"

        try:
            lines = await asyncio.gather(*[_intro(a) for a in members])
            return "\n".join(lines)
        except Exception:  # noqa: BLE001
            return ""

    def _resolve_plans(
        self, session: ChatSession, plans: list[dict[str, Any]]
    ) -> tuple[list[dict[str, Any]], list[str]]:
        """③ 把 assignee 名称解析为成员 Agent；无法匹配的收集起来（不静默 fallback）。"""
        resolved: list[dict[str, Any]] = []
        bad: list[str] = []
        for p in plans:
            name = str(p.get("assignee", "")).strip()
            agent = self._find_agent(session, name)
            if agent is None:
                bad.append(name or "?")
                continue
            resolved.append(
                {
                    "title": str(p.get("title", "子任务")),
                    "description": str(p.get("description", "")),
                    "assignee": agent,
                }
            )
        return resolved, bad

    def _find_agent(self, session: ChatSession, name: str) -> Agent | None:
        """按名称在活跃成员里找 Agent（先精确，再唯一包含）；找不到返回 None（不静默回退）。"""
        name = (name or "").strip()
        if not name:
            return None
        agents = [
            self.db.get(Agent, m.agent_id)
            for m in session.members
            if m.status == MEMBER_ACTIVE
        ]
        agents = [a for a in agents if a]
        exact = [a for a in agents if a.name == name]
        if exact:
            return exact[0]
        sub = [a for a in agents if name in a.name]
        if len(sub) == 1:
            return sub[0]
        return None

    # ---------- 2. 验收 ----------
    async def review(
        self,
        session: ChatSession,
        host: Agent,
        task: Any,
        result_content: str,
        run_output: str | None = None,
        peer_comment: str | None = None,
    ) -> tuple[bool, str]:
        prompt = (
            f"子任务：{task.title}\n要求：{task.description}\n\n"
            f"成员产出：\n{result_content[:6000]}"
        )
        if peer_comment:
            prompt += f"\n\n评审者意见（供参考，不必然全盘采纳）：\n{peer_comment[:2000]}"
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
