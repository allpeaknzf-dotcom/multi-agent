"""会话管理器：消息路由 + 群聊广播 + 主理人派活 + 沙箱执行 的总装车间。

两种协作模式：
- 圆桌模式：用户普通消息广播给所有活跃成员，各自回复（群聊）
- 主理人模式：用户下达任务 -> 主理人拆解 -> 派活 -> 各成员执行 -> 验收 -> 汇总
"""
from __future__ import annotations

import re
import time
from pathlib import Path

from sqlalchemy.orm import Session as DbSession

from ..core.config import ARTIFACT_DIR
from ..models.entities import (
    Agent,
    Artifact,
    ChatSession,
    Message,
    Project,
    SessionMember,
    Task,
)
from ..providers.base import ChatMessage, ProviderError
from ..providers.registry import build_provider
from ..tools.executor.runner import run_code
from .event_bus import EventBus, event_bus
from .memory import build_context
from .orchestrator import OrchestratorService
from .protocol import (
    EVT_AGENT_TYPING,
    EVT_MESSAGE,
    EVT_STATUS,
    EVT_TASK,
    MEMBER_ACTIVE,
    MSG_ARTIFACT,
    MSG_CODE,
    MSG_ORCHESTRATOR,
    MSG_STATUS,
    MSG_SYSTEM,
    MSG_TEXT,
    ROLE_HOST,
    SENDER_AGENT,
    SENDER_SYSTEM,
    SENDER_USER,
    TASK_DONE,
    TASK_REVIEWING,
    TASK_REVISING,
    TASK_RUNNING,
)


class ChatManager:
    def __init__(self, db: DbSession, bus: EventBus | None = None) -> None:
        self.db = db
        self.bus = bus or event_bus
        self.orch = OrchestratorService(db, bus)

    # ---------- 查询辅助 ----------
    def _get_session(self, session_id: int) -> ChatSession:
        s = self.db.get(ChatSession, session_id)
        if not s:
            raise ValueError(f"会话不存在: {session_id}")
        return s

    def _active_members(self, session: ChatSession) -> list[Agent]:
        agents: list[Agent] = []
        for m in session.members:
            if m.status != MEMBER_ACTIVE:
                continue
            agent = self.db.get(Agent, m.agent_id)
            if agent:
                agents.append(agent)
        return agents

    def _get_host(self, session: ChatSession) -> Agent | None:
        if not session.orchestrator_agent_id:
            return None
        return self.db.get(Agent, session.orchestrator_agent_id)

    # ---------- 消息持久化 + 推送 ----------
    def _save_and_push(
        self,
        session: ChatSession,
        *,
        sender_type: str,
        sender_id: int | None,
        sender_name: str,
        content: str,
        msg_type: str = MSG_TEXT,
        recipient: str = "all",
        parent_id: int | None = None,
        meta: dict | None = None,
    ) -> Message:
        m = Message(
            session_id=session.id,
            sender_type=sender_type,
            sender_id=sender_id,
            sender_name=sender_name,
            msg_type=msg_type,
            content=content,
            recipient=recipient,
            parent_id=parent_id,
            meta=meta or {},
        )
        self.db.add(m)
        self.db.commit()
        self.db.refresh(m)
        self._push_message(m)
        return m

    def _push_message(self, m: Message) -> None:
        import asyncio

        payload = {
            "type": EVT_MESSAGE,
            "message": {
                "id": m.id,
                "session_id": m.session_id,
                "sender_type": m.sender_type,
                "sender_id": m.sender_id,
                "sender_name": m.sender_name,
                "msg_type": m.msg_type,
                "content": m.content,
                "recipient": m.recipient,
                "parent_id": m.parent_id,
                "meta": m.meta,
                "created_at": m.created_at.isoformat() if m.created_at else None,
            },
        }
        asyncio.create_task(self.bus.publish(m.session_id, payload))

    async def _push_task(self, session_id: int, task: Task) -> None:
        await self.bus.publish(
            session_id,
            {
                "type": EVT_TASK,
                "task": {
                    "id": task.id,
                    "session_id": task.session_id,
                    "title": task.title,
                    "description": task.description,
                    "assignee_agent_id": task.assignee_agent_id,
                    "status": task.status,
                    "parent_task_id": task.parent_task_id,
                    "round": task.round,
                    "max_rounds": task.max_rounds,
                },
            },
        )

    async def _status(self, session: ChatSession, text: str) -> None:
        await self.bus.publish(
            session.id,
            {"type": EVT_STATUS, "content": text},
        )

    # ---------- 单 Agent 对话 ----------
    async def _ask_agent(
        self,
        session: ChatSession,
        agent: Agent,
        input_text: str,
        *,
        task: Task | None = None,
    ) -> str:
        await self.bus.publish(
            session.id,
            {"type": EVT_AGENT_TYPING, "agent_id": agent.id, "agent": agent.name},
        )

        ctx = build_context(self.db, session.id, limit=30)
        messages = [
            ChatMessage(role=m["role"], content=m["content"]) for m in ctx
        ]
        if task:
            messages.append(
                ChatMessage(
                    role="user",
                    content=(
                        f"[主理人派给你的任务] {task.title}\n"
                        f"任务要求：{task.description}\n"
                        "请完成任务并给出结果。"
                    ),
                )
            )
        messages.append(ChatMessage(role="user", content=input_text))

        provider = build_provider(agent)

        # 注入项目长期记忆，让 Agent 感知历史结论
        system = agent.system_prompt
        project = self.db.get(Project, session.project_id)
        if project and project.memory:
            memory_block = f"【项目长期记忆（历史结论）】\n{project.memory[:4000]}"
            system = (
                f"{system}\n\n{memory_block}" if system else memory_block
            )

        result = await provider.chat(
            messages,
            system=system,
            temperature=agent.temperature,
            max_tokens=agent.max_tokens,
        )
        return result.content

    # ---------- 用户消息入口（圆桌 / @ 指定） ----------
    async def handle_user_message(
        self,
        session_id: int,
        content: str,
        recipient: str = "all",
    ) -> Message:
        session = self._get_session(session_id)
        user_msg = self._save_and_push(
            session,
            sender_type=SENDER_USER,
            sender_id=None,
            sender_name="我",
            content=content,
            recipient=recipient,
        )

        members = self._active_members(session)
        if not members:
            self._save_and_push(
                session,
                sender_type=SENDER_SYSTEM,
                sender_id=None,
                sender_name="系统",
                content="会话中还没有 Agent，请先拉入成员。",
                msg_type=MSG_SYSTEM,
            )
            return user_msg

        # 解析文本中的 @Agent名 / @所有人 -> 定向投递
        if recipient in ("all", "") and content:
            parsed = self._parse_at_mention(content, members)
            if parsed:
                recipient, content = parsed

        # 解析 @agent:{id}
        if recipient.startswith("agent:"):
            target_id = int(recipient.split(":", 1)[1])
            target = next((a for a in members if a.id == target_id), None)
            if not target:
                return user_msg
            reply = await self._ask_agent(session, target, content)
            self._save_and_push(
                session,
                sender_type=SENDER_AGENT,
                sender_id=target.id,
                sender_name=target.name,
                content=reply,
                parent_id=user_msg.id,
            )
            return user_msg

        # 广播：逐个成员回复（串行，避免 SQLite 并发写）
        for agent in members:
            try:
                reply = await self._ask_agent(session, agent, content)
                self._save_and_push(
                    session,
                    sender_type=SENDER_AGENT,
                    sender_id=agent.id,
                    sender_name=agent.name,
                    content=reply,
                    parent_id=user_msg.id,
                )
            except ProviderError as exc:
                self._save_and_push(
                    session,
                    sender_type=SENDER_SYSTEM,
                    sender_id=None,
                    sender_name="系统",
                    content=f"Agent「{agent.name}」调用失败：{exc}",
                    msg_type=MSG_SYSTEM,
                    parent_id=user_msg.id,
                )
        return user_msg

    # ---------- 主理人派活 ----------
    async def orchestrate(
        self,
        session_id: int,
        task_description: str,
    ) -> Task:
        session = self._get_session(session_id)
        host = self._get_host(session)
        if not host:
            raise ValueError("该会话尚未设置主理人，请先指定主理人再派活。")

        root = Task(
            session_id=session.id,
            title=task_description,
            description=task_description,
            assignee_agent_id=host.id,
            status=TASK_RUNNING,
        )
        self.db.add(root)
        self.db.commit()
        self.db.refresh(root)
        await self._push_task(session.id, root)

        await self._status(session, f"用户下达任务，主理人「{host.name}」接管。")

        # 1. 拆解
        plans = await self.orch.plan(session, host, task_description)
        results: list[tuple[str, str]] = []

        # 2. 逐子任务执行 + 验收
        for idx, plan in enumerate(plans, start=1):
            assignee = plan["assignee"]
            task = Task(
                session_id=session.id,
                title=plan["title"],
                description=plan["description"],
                assignee_agent_id=assignee.id,
                parent_task_id=root.id,
                status=TASK_RUNNING,
                round=0,
                max_rounds=3,
            )
            self.db.add(task)
            self.db.commit()
            self.db.refresh(task)
            await self._push_task(session.id, task)
            await self._status(
                session,
                f"[{idx}/{len(plans)}] 派发子任务「{task.title}」给「{assignee.name}」…",
            )

            content = ""
            passed = False
            for rnd in range(1, task.max_rounds + 1):
                task.round = rnd
                self.db.commit()
                try:
                    content = await self._ask_agent(
                        session, assignee, "", task=task
                    )
                except ProviderError as exc:
                    self._save_and_push(
                        session,
                        sender_type=SENDER_SYSTEM,
                        sender_id=None,
                        sender_name="系统",
                        content=f"Agent「{assignee.name}」执行失败：{exc}",
                        msg_type=MSG_SYSTEM,
                    )
                    break

                # 产出入库（代码或文本）
                msg_type = MSG_CODE if self._looks_like_code(content) else MSG_TEXT
                self._save_and_push(
                    session,
                    sender_type=SENDER_AGENT,
                    sender_id=assignee.id,
                    sender_name=assignee.name,
                    content=content,
                    msg_type=msg_type,
                    parent_id=root.id,
                    meta={"task_id": task.id},
                )

                # 验收
                task.status = TASK_REVIEWING
                self.db.commit()
                await self._push_task(session.id, task)
                passed, comment = await self.orch.review(
                    session, host, task, content
                )
                if passed:
                    task.status = TASK_DONE
                    self.db.commit()
                    await self._push_task(session.id, task)
                    await self._status(
                        session,
                        f"子任务「{task.title}」验收通过。",
                    )
                    break
                # 未通过：退回
                task.status = TASK_REVISING
                self.db.commit()
                await self._push_task(session.id, task)
                await self._status(
                    session,
                    f"子任务「{task.title}」未通过验收（第 {rnd} 轮）：{comment}",
                )
                if rnd >= task.max_rounds:
                    break

            if content:
                results.append((task.title, content))

        # 3. 汇总
        if results:
            final = await self.orch.merge(session, host, results)
            self._save_and_push(
                session,
                sender_type=SENDER_AGENT,
                sender_id=host.id,
                sender_name=f"{host.name}（主理人）",
                content=final,
                msg_type=MSG_ORCHESTRATOR,
                parent_id=root.id,
                meta={"task_id": root.id},
            )
            # 沉淀到项目记忆
            self._save_project_memory(session, task_description, final)

        root.status = TASK_DONE
        self.db.commit()
        await self._push_task(session.id, root)
        await self._status(session, "任务流程结束。")
        return root

    @staticmethod
    def _looks_like_code(content: str) -> bool:
        markers = ("```", "def ", "function ", "class ", "import ", "#!/", "const ", "let ")
        return any(mk in content for mk in markers)

    @staticmethod
    def _parse_at_mention(
        content: str, members: list[Agent]
    ) -> tuple[str, str] | None:
        """解析 '... @Agent名 ...' 或 '@所有人' -> (recipient, 去掉@后的正文)。"""
        m = re.search(r"@([^\s，。,.!！?？@、]+)", content)
        if not m:
            return None
        name = m.group(1).strip()
        cleaned = re.sub(r"@[^\s，。,.!！?？@、]+", "", content, count=1).strip()
        if name in ("所有人", "all", "everyone", "全体"):
            return ("all", cleaned or content)
        target = next((a for a in members if a.name == name), None)
        if not target:
            return None
        return (f"agent:{target.id}", cleaned or content)

    # ---------- 产物沉淀 ----------
    _ART_TYPE_BY_SUFFIX = {
        ".png": "image",
        ".jpg": "image",
        ".jpeg": "image",
        ".gif": "image",
        ".webp": "image",
        ".svg": "image",
        ".md": "doc",
        ".txt": "doc",
        ".html": "doc",
        ".htm": "doc",
        ".json": "doc",
        ".csv": "doc",
        ".pdf": "doc",
        ".py": "code",
        ".js": "code",
        ".ts": "code",
        ".sh": "code",
        ".go": "code",
        ".rs": "code",
        ".java": "code",
        ".c": "code",
        ".cpp": "code",
    }

    def _session_art_dir(self, session_id: int) -> Path:
        d = ARTIFACT_DIR / f"session_{session_id}"
        d.mkdir(parents=True, exist_ok=True)
        return d

    def _persist_artifact(
        self,
        session_id: int,
        *,
        type: str,
        name: str,
        file_path: str,
        language: str | None = None,
        task_id: int | None = None,
        meta: dict | None = None,
    ) -> Artifact:
        art = Artifact(
            session_id=session_id,
            task_id=task_id,
            type=type,
            name=name,
            file_path=file_path,
            language=language,
            meta=meta or {},
        )
        self.db.add(art)
        self.db.commit()
        self.db.refresh(art)
        return art

    def _save_code_artifact(
        self, session_id: int, code: str, language: str, task_id: int | None = None
    ) -> Artifact:
        ext = {"python": "py", "node": "js", "shell": "sh", "sh": "sh"}.get(
            language, "txt"
        )
        ts = int(time.time())
        name = f"code_{ts}.{ext}"
        path = self._session_art_dir(session_id) / name
        path.write_text(code, encoding="utf-8")
        return self._persist_artifact(
            session_id,
            type="code",
            name=name,
            file_path=str(path),
            language=language,
            task_id=task_id,
            meta={"kind": "source"},
        )

    def _save_output_artifact(
        self, session_id: int, result: object, task_id: int | None = None
    ) -> Artifact:
        text = (
            f"--- stdout ---\n{result.stdout}\n"
            f"--- stderr ---\n{result.stderr}\n\n"
            f"exit_code={result.exit_code} timed_out={result.timed_out} "
            f"duration_ms={result.duration_ms}"
        )
        ts = int(time.time())
        name = f"output_{ts}.txt"
        path = self._session_art_dir(session_id) / name
        path.write_text(text, encoding="utf-8")
        return self._persist_artifact(
            session_id,
            type="text",
            name=name,
            file_path=str(path),
            task_id=task_id,
            meta={
                "kind": "run_output",
                "exit_code": result.exit_code,
                "duration_ms": result.duration_ms,
            },
        )

    def _scan_workdir_artifacts(
        self, session_id: int, workdir: str | None
    ) -> list[Artifact]:
        """登记沙箱工作目录里由代码生成的附加文件（图片/文档等）。"""
        if not workdir:
            return []
        excluded = ("main.py", "main.js", "main.sh")
        created: list[Artifact] = []
        try:
            for p in Path(workdir).iterdir():
                if p.is_file() and p.name not in excluded:
                    suffix = p.suffix.lower()
                    art_type = self._ART_TYPE_BY_SUFFIX.get(suffix, "other")
                    created.append(
                        self._persist_artifact(
                            session_id,
                            type=art_type,
                            name=p.name,
                            file_path=str(p.resolve()),
                            meta={
                                "kind": "sandbox_file",
                                "size": p.stat().st_size,
                            },
                        )
                    )
        except OSError:
            pass
        return created

    # ---------- 项目记忆 ----------
    def _save_project_memory(
        self, session: ChatSession, task_title: str, result_text: str
    ) -> None:
        project = self.db.get(Project, session.project_id)
        if not project:
            return
        from datetime import datetime

        ts = datetime.now().strftime("%Y-%m-%d %H:%M")
        excerpt = result_text.strip()[:600]
        entry = f"\n\n### {ts} · {task_title}\n{excerpt}"
        project.memory = ((project.memory or "").rstrip() + entry)[:20000]
        self.db.commit()

    # ---------- 沙箱运行 ----------
    async def run_code_in_session(
        self,
        session_id: int,
        code: str,
        language: str = "python",
        timeout: int = 60,
        use_docker: bool = False,
    ) -> dict:
        session = self._get_session(session_id)
        result = await run_code(code, language=language, timeout=timeout, use_docker=use_docker)

        # 产物沉淀：源代码 / 运行输出 / 沙箱生成的附加文件
        try:
            self._save_code_artifact(session.id, code, language)
            self._save_output_artifact(session.id, result)
            self._scan_workdir_artifacts(session.id, result.workdir)
        except Exception:  # noqa: BLE001  产物登记失败不影响运行结果
            self.db.rollback()

        text = (
            f"（沙箱运行 · {language} · {result.duration_ms}ms"
            + (" · 超时" if result.timed_out else "")
            + f" · 退出码 {result.exit_code}）\n"
            f"--- stdout ---\n{result.stdout}\n"
            f"--- stderr ---\n{result.stderr}"
        )
        self._save_and_push(
            session,
            sender_type=SENDER_SYSTEM,
            sender_id=None,
            sender_name="沙箱",
            content=text,
            msg_type=MSG_STATUS,
        )
        return {
            "stdout": result.stdout,
            "stderr": result.stderr,
            "exit_code": result.exit_code,
            "timed_out": result.timed_out,
            "duration_ms": result.duration_ms,
        }

    # ---------- 成员管理 ----------
    async def invite_agent(self, session_id: int, agent_id: int) -> SessionMember:
        session = self._get_session(session_id)
        if self.db.get(Agent, agent_id) is None:
            raise ValueError("Agent 不存在")
        exists = (
            self.db.query(SessionMember)
            .filter_by(session_id=session_id, agent_id=agent_id)
            .first()
        )
        if exists:
            if exists.status != MEMBER_ACTIVE:
                exists.status = MEMBER_ACTIVE
                self.db.commit()
            return exists

        member = SessionMember(
            session_id=session_id, agent_id=agent_id, role=ROLE_HOST if not session.orchestrator_agent_id else "member"
        )
        self.db.add(member)
        self.db.commit()
        self.db.refresh(member)
        agent = self.db.get(Agent, agent_id)
        if agent:
            self._save_and_push(
                session,
                sender_type=SENDER_SYSTEM,
                sender_id=None,
                sender_name="系统",
                content=f"Agent「{agent.name}」已加入会话。",
                msg_type=MSG_SYSTEM,
            )
            if not session.orchestrator_agent_id:
                session.orchestrator_agent_id = agent_id
                self.db.commit()
                await self._status(
                    session,
                    f"会话暂无主理人，已自动指定「{agent.name}」为主理人（可改）。",
                )
        return member

    async def set_orchestrator(self, session_id: int, agent_id: int) -> None:
        session = self._get_session(session_id)
        if self.db.get(Agent, agent_id) is None:
            raise ValueError("Agent 不存在")
        session.orchestrator_agent_id = agent_id
        for m in session.members:
            m.role = ROLE_HOST if m.agent_id == agent_id else "member"
        self.db.commit()
        agent = self.db.get(Agent, agent_id)
        if agent:
            await self._status(session, f"已将「{agent.name}」设为主理人。")
