"""会话管理器：消息路由 + 群聊广播 + 主理人派活 + 沙箱执行 的总装车间。

两种协作模式：
- 圆桌模式：用户普通消息广播给所有活跃成员，各自回复（群聊）
- 主理人模式：用户下达任务 -> 主理人拆解 -> 派活 -> 各成员执行 -> 验收 -> 汇总
"""
from __future__ import annotations

import asyncio
import re
import shutil
import time
from datetime import datetime
from pathlib import Path
from typing import Any

from sqlalchemy.orm import Session as DbSession

from ..core.config import ARTIFACT_DIR, PROJECTS_DIR
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
    TASK_PAUSED,
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
        folder: str | None = None,
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
        # [代码产物化] 自动落盘：成员代码消息里的代码块自动保存为产物文件
        if sender_type == SENDER_AGENT and msg_type != MSG_SYSTEM:
            art_ids = self._persist_code_from_message(
                session.id,
                content,
                msg_type,
                task_id=(meta or {}).get("task_id"),
                folder=folder,
            )
            if art_ids:
                m.meta = {**(m.meta or {}), "artifact_ids": art_ids}
                self.db.commit()
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
        root_id: int | None = None,
    ) -> Task:
        """派活/续跑：root_id 为空则新建根任务；否则从暂停处继续（跳过已完成子任务）。"""
        session = self._get_session(session_id)
        host = self._get_host(session)
        if not host:
            raise ValueError("该会话尚未设置主理人，请先指定主理人再派活。")

        done_titles: set[str] = set()
        if root_id is not None:
            # 续跑：加载已暂停的根任务，置回执行中
            root = self.db.get(Task, root_id)
            if not root:
                raise ValueError("任务不存在")
            root.status = TASK_RUNNING
            self.db.commit()
            await self._push_task(session.id, root)
            done_titles = {
                c.title
                for c in self.db.query(Task)
                .filter(Task.parent_task_id == root.id)
                .all()
                if c.status == TASK_DONE
            }
            await self._status(session, "任务已恢复，继续执行剩余子任务…")
        else:
            root = Task(
                session_id=session.id,
                title=task_description,
                description=task_description,
                assignee_agent_id=host.id,
                status=TASK_RUNNING,
                folder=self._make_folder(task_description),
            )
            self.db.add(root)
            self.db.commit()
            self.db.refresh(root)
            await self._push_task(session.id, root)
            await self._status(
                session,
                f"用户下达任务，主理人「{host.name}」接管。"
                f"已为该项目创建产物文件夹「{root.folder}」。",
            )

        # 1. 拆解
        plans = await self.orch.plan(session, host, task_description)

        # 2. 并行执行所有子任务 + 验收（互不依赖的子任务并发跑）
        pending_plans = [p for p in plans if p["title"] not in done_titles]
        if pending_plans:
            await self._status(
                session,
                f"共 {len(pending_plans)} 个子任务，并行派发给各成员执行…",
            )

        async def _run_one(plan: dict):
            # 每个子任务在独立 DB 会话中执行，避免并行写冲突
            return await self._execute_subtask(root, plan, session.id)

        outcomes = await asyncio.gather(
            *[_run_one(p) for p in pending_plans],
            return_exceptions=True,
        )

        results_map: dict[int, tuple[str, str]] = {}
        paused = self._task_paused(root.id)
        for idx, o in enumerate(outcomes):
            if isinstance(o, Exception):
                await self._status(session, f"子任务执行异常：{o}")
                continue
            title, content, status = o
            if content:
                results_map[idx] = (title, content)
            if status == TASK_PAUSED:
                paused = True
        results = [results_map[i] for i in sorted(results_map)]

        # 任一路径被暂停则整条流程暂停
        if paused:
            root.status = TASK_PAUSED
            self.db.commit()
            await self._push_task(session.id, root)
            await self._status(session, "任务已暂停，可点「继续」恢复。")
            return root

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

    async def _execute_subtask(
        self, root: Task, plan: dict, session_id: int
    ) -> tuple[str, str, str]:
        """在独立 DB 会话中执行单个子任务（并行安全）。

        返回 (title, content, status)；status==paused 表示整体流程应暂停。
        流程：执行 -> 产出 -> 沙箱运行（代码）-> 交叉评审 -> 主理人验收（可退回重做）。
        """
        from ..core.db import SessionLocal

        db = SessionLocal()
        try:
            mgr = ChatManager(db, self.bus)
            session = db.get(ChatSession, session_id)
            host = mgr._get_host(session)
            assignee = plan["assignee"]
            if not session or not assignee:
                return (plan["title"], "", TASK_DONE)

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
            db.add(task)
            db.commit()
            db.refresh(task)
            await mgr._push_task(session.id, task)
            await mgr._status(
                session, f"派发子任务「{task.title}」给「{assignee.name}」…"
            )

            content = ""
            for rnd in range(1, task.max_rounds + 1):
                if mgr._task_paused(root.id) or mgr._task_paused(task.id):
                    task.status = TASK_PAUSED
                    db.commit()
                    await mgr._push_task(session.id, task)
                    await mgr._status(
                        session, f"子任务「{task.title}」已暂停，可稍后继续。"
                    )
                    break
                task.round = rnd
                db.commit()
                try:
                    content = await mgr._ask_agent(session, assignee, "", task=task)
                except ProviderError as exc:
                    mgr._save_and_push(
                        session,
                        sender_type=SENDER_SYSTEM,
                        sender_id=None,
                        sender_name="系统",
                        content=f"Agent「{assignee.name}」执行失败：{exc}",
                        msg_type=MSG_SYSTEM,
                    )
                    break

                # 产出入库（代码或文本）
                msg_type = MSG_CODE if mgr._looks_like_code(content) else MSG_TEXT
                mgr._save_and_push(
                    session,
                    sender_type=SENDER_AGENT,
                    sender_id=assignee.id,
                    sender_name=assignee.name,
                    content=content,
                    msg_type=msg_type,
                    parent_id=root.id,
                    meta={"task_id": task.id},
                    folder=root.folder,
                )

                # [优化2] 代码类产出先跑沙箱，用运行结果辅助验收
                run_output = None
                if mgr._looks_like_code(content):
                    run_output = await mgr._run_subtask_code(session, content)

                # [优化3] 交叉评审：请一名非执行者成员审阅产出
                peer_comment = await mgr._peer_review(
                    session, host, assignee, task, content, run_output
                )

                # 主理人验收（结合运行结果 + 评审意见）
                task.status = TASK_REVIEWING
                db.commit()
                await mgr._push_task(session.id, task)
                passed, comment = await mgr.orch.review(
                    session,
                    host,
                    task,
                    content,
                    run_output=run_output,
                    peer_comment=peer_comment,
                )
                if passed:
                    task.status = TASK_DONE
                    db.commit()
                    await mgr._push_task(session.id, task)
                    await mgr._status(session, f"子任务「{task.title}」验收通过。")
                    break
                # 未通过：退回
                task.status = TASK_REVISING
                db.commit()
                await mgr._push_task(session.id, task)
                await mgr._status(
                    session,
                    f"子任务「{task.title}」未通过验收（第 {rnd} 轮）：{comment}",
                )
                if rnd >= task.max_rounds:
                    break

            return (task.title, content, task.status)
        finally:
            db.close()

    async def _run_subtask_code(self, session: ChatSession, code: str) -> str | None:
        """[优化2] 把子任务代码产出放到沙箱运行，返回可读的运行结果摘要。"""
        try:
            result = await run_code(code, language="python", timeout=60, use_docker=False)
        except Exception as exc:  # noqa: BLE001
            return f"运行失败：{exc}"
        summary = (
            f"（沙箱运行 · {result.duration_ms}ms"
            + (" · 超时" if result.timed_out else "")
            + f" · 退出码 {result.exit_code}）\n"
            f"--- stdout ---\n{result.stdout[:2000]}\n"
            f"--- stderr ---\n{result.stderr[:1500]}"
        )
        self._save_and_push(
            session,
            sender_type=SENDER_SYSTEM,
            sender_id=None,
            sender_name="沙箱",
            content=summary,
            msg_type=MSG_STATUS,
        )
        return summary

    async def _peer_review(
        self,
        session: ChatSession,
        host: Agent | None,
        assignee: Agent,
        task: Task,
        content: str,
        run_output: str | None,
    ) -> str | None:
        """[优化3] 请一名非执行者、非主理人的成员评审产出，返回评审意见（无合适评审者返回 None）。"""
        members = self._active_members(session)
        reviewers = [
            a
            for a in members
            if a.id != assignee.id and (not host or a.id != host.id)
        ]
        if not reviewers:
            return None
        # 优先选名称带审查/评审/审阅/测试/质检的成员，否则取第一个
        reviewer = next(
            (
                a
                for a in reviewers
                if any(k in a.name for k in ("审查", "评审", "审阅", "测试", "质检"))
            ),
            reviewers[0],
        )
        try:
            prompt = (
                "请作为评审者对该子任务的产出做质量评审（如代码审查、方案审阅），"
                "简明扼要地指出问题与改进建议。\n"
                f"子任务：{task.title}\n要求：{task.description}\n\n"
                f"产出：\n{content[:6000]}"
            )
            if run_output:
                prompt += f"\n\n运行结果：\n{run_output[:2000]}"
            comment = await self._ask_agent(session, reviewer, prompt)
            self._save_and_push(
                session,
                sender_type=SENDER_AGENT,
                sender_id=reviewer.id,
                sender_name=reviewer.name,
                content=f"【评审意见】{comment}",
                msg_type=MSG_TEXT,
                parent_id=task.id,
                meta={"task_id": task.id, "kind": "peer_review"},
            )
            return comment
        except Exception:  # noqa: BLE001  评审失败不阻塞流程
            return None

    def _task_paused(self, task_id: int) -> bool:
        """实时从数据库读取任务状态（跨请求会话），判断是否被暂停。"""
        from sqlalchemy import select

        status = self.db.execute(
            select(Task.status).where(Task.id == task_id)
        ).scalar()
        return status == TASK_PAUSED

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

    # 代码块语言 → 扩展名（用于代码产物命名）
    _LANG_EXT = {
        "python": "py", "py": "py",
        "javascript": "js", "js": "js", "node": "js",
        "typescript": "ts", "ts": "ts",
        "html": "html", "htm": "html",
        "css": "css",
        "shell": "sh", "bash": "sh", "sh": "sh",
        "java": "java", "go": "go", "rust": "rs", "rs": "rs",
        "c": "c", "cpp": "cpp",
        "json": "json", "sql": "sql",
        "markdown": "md", "md": "md", "text": "txt", "txt": "txt",
    }

    @staticmethod
    def _extract_code_blocks(content: str) -> list[dict[str, str]]:
        """提取消息文本里的所有 ```lang ... ``` 代码块。"""
        blocks: list[dict[str, str]] = []
        for m in re.finditer(r"```([\w+-]*)\s*\n(.*?)```", content, re.DOTALL):
            blocks.append(
                {"language": (m.group(1) or "").strip(), "code": m.group(2).strip()}
            )
        return blocks

    def _persist_code_from_message(
        self,
        session_id: int,
        content: str,
        msg_type: str,
        task_id: int | None = None,
        folder: str | None = None,
    ) -> list[int]:
        """从消息内容提取代码块并保存为产物文件；返回新增 Artifact id 列表。"""
        blocks = self._extract_code_blocks(content)
        if not blocks and msg_type == MSG_CODE:
            blocks = [{"language": "python", "code": content}]
        if not blocks:
            return []
        ts = int(time.time())
        seen: set[str] = set()
        art_ids: list[int] = []
        art_dir = self._folder_art_dir(session_id, folder, "code")
        for i, b in enumerate(blocks):
            code = b["code"]
            if not code or code in seen:
                continue
            seen.add(code)
            lang = (b["language"] or "").lower()
            ext = self._LANG_EXT.get(lang, "txt")
            name = f"code_{ts}_{i}.{ext}"
            path = art_dir / name
            try:
                path.write_text(code, encoding="utf-8")
            except OSError:
                continue
            art = self._persist_artifact(
                session_id,
                type="code",
                name=name,
                file_path=str(path),
                language=lang or None,
                task_id=task_id,
                folder=folder,
                meta={"kind": "extracted", "source": "auto"},
            )
            art_ids.append(art.id)
        return art_ids

    def list_artifact_folders(self, session_id: int) -> dict[str, Any]:
        """按文件夹分组统计产物，供右侧面板按文件夹展示。"""
        from sqlalchemy import func

        rows = (
            self.db.query(
                Artifact.folder,
                func.count(Artifact.id),
                func.max(Artifact.created_at),
            )
            .filter(Artifact.session_id == session_id)
            .group_by(Artifact.folder)
            .all()
        )
        folders = []
        for folder, count, updated_at in rows:
            if not folder:
                continue
            folders.append(
                {
                    "folder": folder,
                    "count": count,
                    "updated_at": updated_at,
                }
            )
        folders.sort(key=lambda x: x["updated_at"] or datetime.min, reverse=True)
        ungrouped = (
            self.db.query(Artifact)
            .filter(
                Artifact.session_id == session_id,
                Artifact.folder.is_(None),
            )
            .count()
        )
        return {"folders": folders, "ungrouped": ungrouped}

    @staticmethod
    def _is_managed_path(path: Path) -> bool:
        """产物文件只允许位于项目目录或旧产物目录内，防路径穿越。"""
        resolved = str(path.resolve())
        return resolved.startswith(str(PROJECTS_DIR.resolve())) or resolved.startswith(
            str(ARTIFACT_DIR.resolve())
        )

    def delete_artifact(self, artifact_id: int) -> bool:
        """删除单个产物（数据库记录 + 磁盘文件）。"""
        art = self.db.get(Artifact, artifact_id)
        if not art:
            return False
        path = Path(art.file_path).resolve()
        if self._is_managed_path(path) and path.is_file():
            try:
                path.unlink()
            except OSError:
                pass
        self.db.delete(art)
        self.db.commit()
        return True

    def delete_artifact_folder(self, session_id: int, folder: str) -> int:
        """删除整个项目文件夹（含其下所有产物文件 + 数据库记录）。"""
        # 防路径穿越：允许「日期/产物名」多级，但拒绝非法字符与上级引用
        if (
            not folder
            or "\\" in folder
            or ".." in folder
            or folder.startswith("/")
            or folder.endswith("/")
        ):
            return 0
        arts = (
            self.db.query(Artifact)
            .filter_by(session_id=session_id, folder=folder)
            .all()
        )
        n = 0
        for art in arts:
            path = Path(art.file_path).resolve()
            if self._is_managed_path(path) and path.is_file():
                try:
                    path.unlink()
                except OSError:
                    pass
            self.db.delete(art)
            n += 1
        self.db.commit()
        # 尝试删除已清空的文件夹目录（含分类子目录）
        root = self._resolve_folder_dir(session_id, folder)
        try:
            if root.is_dir():
                for sub in sorted(root.iterdir(), reverse=True):
                    if sub.is_dir() and not any(sub.iterdir()):
                        sub.rmdir()
                if not any(root.iterdir()):
                    root.rmdir()
        except OSError:
            pass
        return n

    # ---------- 项目磁盘文件夹 ----------
    def ensure_project_folder(self, project_id: int, name: str | None = None) -> Path:
        """创建（或复用）项目对应的本地文件夹，并写入 README 索引。"""
        project = self.db.get(Project, project_id)
        if not project:
            raise ValueError("项目不存在")
        name = name or project.name
        d = PROJECTS_DIR / self._safe_dir_name(name)
        d.mkdir(parents=True, exist_ok=True)
        readme = d / "README.md"
        if not readme.exists():
            try:
                readme.write_text(
                    f"# {name}\n\n"
                    "> 本目录由 Multi-agent 自动创建，项目内生成的代码 / 文档 / 图片 / 运行输出会自动保存到此处。\n\n"
                    f"- 创建时间：{datetime.now().strftime('%Y-%m-%d %H:%M')}\n",
                    encoding="utf-8",
                )
            except OSError:
                pass
        return d

    def project_folder_path(self, project_id: int) -> Path | None:
        """返回项目对应的本地文件夹绝对路径（不存在时为 None）。"""
        project = self.db.get(Project, project_id)
        if not project:
            return None
        return PROJECTS_DIR / self._safe_dir_name(project.name)

    def rename_project_folder(self, project_id: int, old_name: str, new_name: str) -> None:
        """重命名项目时同步重命名本地文件夹（目标已存在则跳过，不丢数据）。"""
        old = PROJECTS_DIR / self._safe_dir_name(old_name)
        new = PROJECTS_DIR / self._safe_dir_name(new_name)
        if old == new or not old.exists() or not old.is_dir():
            return
        if new.exists():
            return
        try:
            old.rename(new)
        except OSError:
            pass

    @staticmethod
    def _safe_dir_name(name: str) -> str:
        """把项目/任务名转成安全的本地文件夹名（去掉路径分隔符与非法字符）。"""
        s = re.sub(r'[\\/:*?"<>|\r\n\t]+', "_", (name or "").strip())
        s = s.strip(" .")[:80] or "未命名"
        return s

    def _project_root(self, session_id: int) -> Path:
        """产物根目录：项目内会话 -> ~/Multi-agent/{项目名}；独立会话 -> ~/Multi-agent/未分组/session_{id}。"""
        session = self.db.get(ChatSession, session_id)
        if session and session.project_id:
            project = self.db.get(Project, session.project_id)
            if project:
                return PROJECTS_DIR / self._safe_dir_name(project.name)
        return PROJECTS_DIR / "未分组" / f"session_{session_id}"

    def _session_art_dir(self, session_id: int) -> Path:
        d = self._project_root(session_id)
        d.mkdir(parents=True, exist_ok=True)
        return d

    def _resolve_folder_dir(self, session_id: int, folder: str | None) -> Path:
        """把「日期/产物名」等多级任务文件夹解析为项目下的磁盘路径（逐级清洗，防路径穿越）。"""
        base = self._session_art_dir(session_id)
        if not folder:
            return base
        parts = [self._safe_dir_name(x) for x in str(folder).split("/") if x]
        if not parts:
            return base
        return base.joinpath(*parts)

    def _folder_art_dir(
        self, session_id: int, folder: str | None, subtype: str | None = None
    ) -> Path:
        """返回产物目录；按「项目/日期/产物名」归组，subtype 进一步分类（code/docs/output/images）。"""
        d = self._resolve_folder_dir(session_id, folder)
        if subtype:
            d = d / subtype
        d.mkdir(parents=True, exist_ok=True)
        return d

    # 常见的任务动词前缀，生成短文件夹名时去掉
    _VERB_PREFIXES = (
        "开发一个", "实现一个", "设计一个", "搭建一个", "生成一个", "构建一个",
        "做一个", "写一个", "搞一个", "制作一个", "创建一个", "做一个",
        "开发", "实现", "设计", "搭建", "生成", "构建", "编写", "创建",
        "制作", "完成", "帮我", "请", "给一个", "写", "做",
    )

    def _dated_folder(self, name: str) -> str:
        """把产物/任务名挂到当天日期下，形成「日期/名称」两级文件夹。"""
        return f"{datetime.now().strftime('%Y-%m-%d')}/{name}"

    def _make_folder(self, title: str) -> str:
        """生成「日期/产物名」两级任务文件夹名（日期=派活当天；去动词前缀+截短；同日重名自动加序号）。"""
        t = re.sub(r"[^\w\u4e00-\u9fff]+", "", title or "")
        for p in self._VERB_PREFIXES:
            if t.startswith(p):
                t = t[len(p):]
                break
        base = t[:8] or "任务"
        existing = {
            f[0]
            for f in self.db.query(Task.folder)
            .filter(Task.folder.isnot(None))
            .all()
        }
        date = datetime.now().strftime("%Y-%m-%d")
        name = base
        n = 2
        while f"{date}/{name}" in existing:
            name = f"{base}({n})"
            n += 1
        return f"{date}/{name}"

    def _persist_artifact(
        self,
        session_id: int,
        *,
        type: str,
        name: str,
        file_path: str,
        language: str | None = None,
        task_id: int | None = None,
        folder: str | None = None,
        meta: dict | None = None,
    ) -> Artifact:
        art = Artifact(
            session_id=session_id,
            task_id=task_id,
            type=type,
            name=name,
            file_path=file_path,
            language=language,
            folder=folder,
            meta=meta or {},
        )
        self.db.add(art)
        self.db.commit()
        self.db.refresh(art)
        return art

    def _save_code_artifact(
        self,
        session_id: int,
        code: str,
        language: str,
        task_id: int | None = None,
        folder: str | None = None,
    ) -> Artifact:
        ext = {"python": "py", "node": "js", "shell": "sh", "sh": "sh"}.get(
            language, "txt"
        )
        ts = int(time.time())
        name = f"code_{ts}.{ext}"
        path = self._folder_art_dir(session_id, folder, "code") / name
        path.write_text(code, encoding="utf-8")
        return self._persist_artifact(
            session_id,
            type="code",
            name=name,
            file_path=str(path),
            language=language,
            task_id=task_id,
            folder=folder,
            meta={"kind": "source"},
        )

    def _save_output_artifact(
        self,
        session_id: int,
        result: object,
        task_id: int | None = None,
        folder: str | None = None,
    ) -> Artifact:
        text = (
            f"--- stdout ---\n{result.stdout}\n"
            f"--- stderr ---\n{result.stderr}\n\n"
            f"exit_code={result.exit_code} timed_out={result.timed_out} "
            f"duration_ms={result.duration_ms}"
        )
        ts = int(time.time())
        name = f"output_{ts}.txt"
        path = self._folder_art_dir(session_id, folder, "output") / name
        path.write_text(text, encoding="utf-8")
        return self._persist_artifact(
            session_id,
            type="text",
            name=name,
            file_path=str(path),
            task_id=task_id,
            folder=folder,
            meta={
                "kind": "run_output",
                "exit_code": result.exit_code,
                "duration_ms": result.duration_ms,
            },
        )

    _ART_SUBTYPE_DIR = {
        "image": "images",
        "doc": "docs",
        "code": "code",
        "other": "other",
    }

    def _scan_workdir_artifacts(
        self, session_id: int, workdir: str | None, folder: str | None = None
    ) -> list[Artifact]:
        """登记沙箱工作目录里由代码生成的附加文件（图片/文档等），并复制到项目产物目录。"""
        if not workdir:
            return []
        excluded = ("main.py", "main.js", "main.sh")
        created: list[Artifact] = []
        try:
            for p in Path(workdir).iterdir():
                if p.is_file() and p.name not in excluded:
                    suffix = p.suffix.lower()
                    art_type = self._ART_TYPE_BY_SUFFIX.get(suffix, "other")
                    subtype = self._ART_SUBTYPE_DIR.get(art_type, "other")
                    dest_dir = self._folder_art_dir(session_id, folder, subtype)
                    dest = dest_dir / p.name
                    try:
                        shutil.copy2(p, dest)
                    except OSError:
                        dest = p.resolve()  # 复制失败则回退到原文件（仍可读）
                    created.append(
                        self._persist_artifact(
                            session_id,
                            type=art_type,
                            name=p.name,
                            file_path=str(dest),
                            folder=folder,
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

        # 产物沉淀：源代码 / 运行输出 / 沙箱生成的附加文件（归入当天「运行测试」文件夹）
        run_folder = self._dated_folder("运行测试")
        try:
            self._save_code_artifact(session.id, code, language, folder=run_folder)
            self._save_output_artifact(session.id, result, folder=run_folder)
            self._scan_workdir_artifacts(session.id, result.workdir, folder=run_folder)
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
