"""REST + WebSocket 路由。"""
from __future__ import annotations

import uuid
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session as DbSession

from ..core.config import ARTIFACT_DIR
from ..core.db import get_session
from ..core import keyring_store
from ..engine.event_bus import event_bus
from ..engine.manager import ChatManager
from ..engine.templates import AGENT_TEMPLATES
from ..models import entities as models
from ..providers.base import ChatMessage, ProviderError
from ..providers.registry import build_provider
from ..schemas import entities as schemas

router = APIRouter()


@router.get("/api/agent-templates")
def agent_templates() -> list[dict]:
    return AGENT_TEMPLATES


# ============================================================
# Projects
# ============================================================
@router.post("/api/projects", response_model=schemas.ProjectOut)
def create_project(
    body: schemas.ProjectCreate, db: DbSession = Depends(get_session)
):
    p = models.Project(name=body.name, description=body.description)
    db.add(p)
    db.commit()
    db.refresh(p)
    return p


@router.get("/api/projects", response_model=list[schemas.ProjectOut])
def list_projects(db: DbSession = Depends(get_session)):
    return db.query(models.Project).order_by(models.Project.id.desc()).all()


@router.get("/api/projects/{project_id}", response_model=schemas.ProjectOut)
def get_project(project_id: int, db: DbSession = Depends(get_session)):
    p = db.get(models.Project, project_id)
    if not p:
        raise HTTPException(404, "项目不存在")
    return p


@router.delete("/api/projects/{project_id}")
def delete_project(project_id: int, db: DbSession = Depends(get_session)):
    p = db.get(models.Project, project_id)
    if not p:
        raise HTTPException(404, "项目不存在")
    db.delete(p)  # 级联删除会话/消息/任务
    db.commit()
    return {"ok": True}


@router.put("/api/projects/{project_id}/archive", response_model=schemas.ProjectOut)
def archive_project(
    project_id: int,
    body: schemas.ArchiveRequest,
    db: DbSession = Depends(get_session),
):
    p = db.get(models.Project, project_id)
    if not p:
        raise HTTPException(404, "项目不存在")
    p.status = "archived" if body.archived else "active"
    db.commit()
    db.refresh(p)
    return p


# ---------- 项目记忆 ----------
@router.get("/api/projects/{project_id}/memory", response_model=schemas.ProjectOut)
def get_project_memory(project_id: int, db: DbSession = Depends(get_session)):
    p = db.get(models.Project, project_id)
    if not p:
        raise HTTPException(404, "项目不存在")
    return p


@router.put("/api/projects/{project_id}/memory", response_model=schemas.ProjectOut)
def update_project_memory(
    project_id: int,
    body: schemas.ProjectMemoryUpdate,
    db: DbSession = Depends(get_session),
):
    p = db.get(models.Project, project_id)
    if not p:
        raise HTTPException(404, "项目不存在")
    p.memory = body.memory
    db.commit()
    db.refresh(p)
    return p


# ============================================================
# Keys
# ============================================================
@router.post("/api/keys", response_model=schemas.KeyOut)
def create_key(body: schemas.KeyCreate, db: DbSession = Depends(get_session)):
    key_ref = f"{body.provider}:{uuid.uuid4().hex[:12]}"
    keyring_store.save_key(key_ref, body.api_key)
    k = models.KeyEntry(
        name=body.name,
        provider=body.provider,
        model=body.model,
        key_ref=key_ref,
        base_url=body.base_url,
    )
    db.add(k)
    db.commit()
    db.refresh(k)
    return k


@router.get("/api/keys", response_model=list[schemas.KeyOut])
def list_keys(db: DbSession = Depends(get_session)):
    return db.query(models.KeyEntry).order_by(models.KeyEntry.id.desc()).all()


@router.put("/api/keys/{key_id}", response_model=schemas.KeyOut)
def update_key(
    key_id: int,
    body: schemas.KeyUpdate,
    db: DbSession = Depends(get_session),
):
    k = db.get(models.KeyEntry, key_id)
    if not k:
        raise HTTPException(404, "Key 不存在")
    if body.name is not None:
        k.name = body.name
    if body.provider is not None:
        k.provider = body.provider
    if body.model is not None:
        k.model = body.model
    if body.base_url is not None:
        k.base_url = body.base_url
    if body.api_key:
        # 非空才更新钥匙串中的明文
        keyring_store.save_key(k.key_ref, body.api_key)
    db.commit()
    db.refresh(k)
    return k


@router.get("/api/keys/{key_id}/value")
def get_key_value(key_id: int, db: DbSession = Depends(get_session)):
    """获取 Key 明文（本地应用内用于"复制"）。"""
    k = db.get(models.KeyEntry, key_id)
    if not k:
        raise HTTPException(404, "Key 不存在")
    value = keyring_store.get_key(k.key_ref) or ""
    return {"value": value}


@router.delete("/api/keys/{key_id}")
def delete_key(key_id: int, db: DbSession = Depends(get_session)):
    k = db.get(models.KeyEntry, key_id)
    if not k:
        raise HTTPException(404, "Key 不存在")
    keyring_store.delete_key(k.key_ref)
    db.delete(k)
    db.commit()
    return {"ok": True}


@router.post("/api/keys/{key_id}/test")
async def test_key(key_id: int, db: DbSession = Depends(get_session)):
    """用该 Key 实际调用一次模型，验证连通性。"""
    k = db.get(models.KeyEntry, key_id)
    if not k:
        raise HTTPException(404, "Key 不存在")
    if not k.model:
        return {
            "ok": False,
            "error": "该 Key 未配置默认模型，请先填写「默认模型」再测试",
        }
    # 构造临时 Agent 用于 Provider 工厂
    tmp = models.Agent(
        name=k.name,
        provider=k.provider,
        model=k.model,
        key_ref=k.key_ref,
        base_url=k.base_url,
    )
    try:
        provider = build_provider(tmp)
        result = await provider.chat(
            [ChatMessage(role="user", content="只回复两个字：正常")],
            max_tokens=32,
            temperature=0,
        )
        return {"ok": True, "reply": result.content.strip()[:200]}
    except ProviderError as exc:
        return {"ok": False, "error": str(exc)}
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "error": f"{type(exc).__name__}: {exc}"}


# ============================================================
# Agents
# ============================================================
@router.post("/api/agents", response_model=schemas.AgentOut)
def create_agent(body: schemas.AgentCreate, db: DbSession = Depends(get_session)):
    if body.key_ref:
        # key_ref 需要对应已存在的 KeyEntry
        key = (
            db.query(models.KeyEntry).filter_by(key_ref=body.key_ref).first()
        )
        if not key:
            raise HTTPException(400, "key_ref 无效，请先创建对应的 API Key")
    a = models.Agent(**body.model_dump())
    db.add(a)
    db.commit()
    db.refresh(a)
    return a


@router.get("/api/agents", response_model=list[schemas.AgentOut])
def list_agents(
    project_id: int | None = None, db: DbSession = Depends(get_session)
):
    q = db.query(models.Agent)
    if project_id is not None:
        q = q.filter((models.Agent.is_global == True) | (models.Agent.project_id == project_id))  # noqa: E712
    return q.order_by(models.Agent.id.desc()).all()


@router.get("/api/agents/{agent_id}", response_model=schemas.AgentOut)
def get_agent(agent_id: int, db: DbSession = Depends(get_session)):
    a = db.get(models.Agent, agent_id)
    if not a:
        raise HTTPException(404, "Agent 不存在")
    return a


@router.put("/api/agents/{agent_id}", response_model=schemas.AgentOut)
def update_agent(
    agent_id: int,
    body: schemas.AgentCreate,
    db: DbSession = Depends(get_session),
):
    a = db.get(models.Agent, agent_id)
    if not a:
        raise HTTPException(404, "Agent 不存在")
    for field, value in body.model_dump().items():
        setattr(a, field, value)
    db.commit()
    db.refresh(a)
    return a


@router.delete("/api/agents/{agent_id}")
def delete_agent(agent_id: int, db: DbSession = Depends(get_session)):
    a = db.get(models.Agent, agent_id)
    if not a:
        raise HTTPException(404, "Agent 不存在")
    db.delete(a)
    db.commit()
    return {"ok": True}


# ============================================================
# Sessions
# ============================================================
@router.post("/api/sessions", response_model=schemas.SessionOut)
async def create_session(
    body: schemas.SessionCreate, db: DbSession = Depends(get_session)
):
    if not db.get(models.Project, body.project_id):
        raise HTTPException(404, "项目不存在")
    s = models.ChatSession(
        project_id=body.project_id,
        title=body.title,
        orchestrator_agent_id=body.orchestrator_agent_id,
    )
    db.add(s)
    db.commit()
    db.refresh(s)

    manager = ChatManager(db)
    for agent_id in body.agent_ids:
        if db.get(models.Agent, agent_id):
            await manager.invite_agent(s.id, agent_id)
    if body.orchestrator_agent_id:
        # 已存在则设为主理人
        s.orchestrator_agent_id = body.orchestrator_agent_id
        db.commit()
        db.refresh(s)
    return s


@router.get("/api/projects/{project_id}/sessions", response_model=list[schemas.SessionOut])
def list_sessions(project_id: int, db: DbSession = Depends(get_session)):
    return (
        db.query(models.ChatSession)
        .filter_by(project_id=project_id)
        .order_by(models.ChatSession.id.desc())
        .all()
    )


@router.get("/api/sessions/{session_id}", response_model=schemas.SessionOut)
def get_session_detail(session_id: int, db: DbSession = Depends(get_session)):
    s = db.get(models.ChatSession, session_id)
    if not s:
        raise HTTPException(404, "会话不存在")
    return s


@router.delete("/api/sessions/{session_id}")
def delete_session(session_id: int, db: DbSession = Depends(get_session)):
    s = db.get(models.ChatSession, session_id)
    if not s:
        raise HTTPException(404, "会话不存在")
    db.delete(s)
    db.commit()
    return {"ok": True}


@router.put("/api/sessions/{session_id}/archive", response_model=schemas.SessionOut)
def archive_session(
    session_id: int,
    body: schemas.ArchiveRequest,
    db: DbSession = Depends(get_session),
):
    s = db.get(models.ChatSession, session_id)
    if not s:
        raise HTTPException(404, "会话不存在")
    s.status = "archived" if body.archived else "active"
    db.commit()
    db.refresh(s)
    return s


@router.get("/api/sessions/{session_id}/members", response_model=list[schemas.MemberOut])
def session_members(session_id: int, db: DbSession = Depends(get_session)):
    return (
        db.query(models.SessionMember)
        .filter_by(session_id=session_id)
        .order_by(models.SessionMember.id)
        .all()
    )


@router.get("/api/sessions/{session_id}/messages", response_model=list[schemas.MessageOut])
def session_messages(session_id: int, db: DbSession = Depends(get_session)):
    return (
        db.query(models.Message)
        .filter_by(session_id=session_id)
        .order_by(models.Message.id)
        .all()
    )


@router.get("/api/sessions/{session_id}/tasks", response_model=list[schemas.TaskOut])
def session_tasks(session_id: int, db: DbSession = Depends(get_session)):
    return (
        db.query(models.Task)
        .filter_by(session_id=session_id)
        .order_by(models.Task.id)
        .all()
    )


# ============================================================
# Artifacts（产物）
# ============================================================
@router.get("/api/sessions/{session_id}/artifacts", response_model=list[schemas.ArtifactOut])
def list_artifacts(session_id: int, db: DbSession = Depends(get_session)):
    if not db.get(models.ChatSession, session_id):
        raise HTTPException(404, "会话不存在")
    return (
        db.query(models.Artifact)
        .filter_by(session_id=session_id)
        .order_by(models.Artifact.id.desc())
        .all()
    )


@router.get("/api/artifacts/{artifact_id}/download")
def download_artifact(artifact_id: int, db: DbSession = Depends(get_session)):
    art = db.get(models.Artifact, artifact_id)
    if not art:
        raise HTTPException(404, "产物不存在")
    path = Path(art.file_path).resolve()
    # 只允许访问应用产物目录内的文件，防路径穿越
    if not str(path).startswith(str(ARTIFACT_DIR.resolve())):
        raise HTTPException(403, "非法路径")
    if not path.is_file():
        raise HTTPException(404, "产物文件已丢失")
    return FileResponse(
        path,
        filename=art.name or path.name,
        media_type="application/octet-stream",
    )


@router.post("/api/sessions/{session_id}/invite")
async def invite(
    session_id: int,
    body: schemas.InviteRequest,
    db: DbSession = Depends(get_session),
):
    manager = ChatManager(db)
    await manager.invite_agent(session_id, body.agent_id)
    return {"ok": True}


@router.post("/api/sessions/{session_id}/orchestrator")
async def set_orchestrator(
    session_id: int,
    body: schemas.SetOrchestratorRequest,
    db: DbSession = Depends(get_session),
):
    manager = ChatManager(db)
    await manager.set_orchestrator(session_id, body.agent_id)
    return {"ok": True}


@router.post("/api/sessions/{session_id}/messages", response_model=schemas.MessageOut)
async def send_message(
    session_id: int,
    body: schemas.MessageCreate,
    db: DbSession = Depends(get_session),
):
    manager = ChatManager(db)
    msg = await manager.handle_user_message(
        session_id, body.content, recipient=body.recipient
    )
    return msg


@router.post("/api/sessions/{session_id}/orchestrate")
async def orchestrate(
    session_id: int,
    body: schemas.OrchestrateRequest,
    db: DbSession = Depends(get_session),
):
    manager = ChatManager(db)
    try:
        task = await manager.orchestrate(session_id, body.task_description)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    return {"ok": True, "task_id": task.id}


@router.post("/api/sessions/{session_id}/run-code", response_model=schemas.RunCodeOut)
async def run_code(
    session_id: int,
    body: schemas.RunCodeRequest,
    db: DbSession = Depends(get_session),
):
    manager = ChatManager(db)
    result = await manager.run_code_in_session(
        session_id,
        body.code,
        language=body.language,
        timeout=body.timeout,
        use_docker=False,
    )
    return result


# ============================================================
# WebSocket：订阅会话事件 + 实时发消息
# ============================================================
@router.websocket("/ws/{session_id}")
async def ws_endpoint(ws: WebSocket, session_id: int):
    await ws.accept()
    await event_bus.register(session_id, ws)
    db = next(get_session())
    manager = ChatManager(db)
    try:
        while True:
            data = await ws.receive_json()
            msg_type = data.get("type", "user_message")
            if msg_type == "user_message":
                await manager.handle_user_message(
                    session_id,
                    data.get("content", ""),
                    recipient=data.get("recipient", "all"),
                )
            elif msg_type == "ping":
                await ws.send_json({"type": "pong"})
    except WebSocketDisconnect:
        pass
    finally:
        await event_bus.unregister(session_id, ws)
        db.close()
