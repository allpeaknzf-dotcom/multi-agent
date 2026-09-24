"""REST + WebSocket 路由。"""
from __future__ import annotations

import uuid
import mimetypes
from pathlib import Path

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session as DbSession

from ..core.config import ARTIFACT_DIR, PROJECTS_DIR
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


@router.get("/api/agent-templates", response_model=list[schemas.TemplateOut])
def list_templates(db: DbSession = Depends(get_session)):
    return (
        db.query(models.AgentTemplate)
        .order_by(models.AgentTemplate.is_builtin.desc(), models.AgentTemplate.id.asc())
        .all()
    )


@router.post("/api/agent-templates", response_model=schemas.TemplateOut)
def create_template(body: schemas.TemplateCreate, db: DbSession = Depends(get_session)):
    # 模板不绑定 Provider/模型，建 Agent 时由所选 Key 自动带出
    t = models.AgentTemplate(
        name=body.name,
        provider="openai",
        model=None,
        role_hint=body.role_hint,
        system_prompt=body.system_prompt,
        is_builtin=0,
    )
    db.add(t)
    db.commit()
    db.refresh(t)
    return t


@router.put("/api/agent-templates/{tid}", response_model=schemas.TemplateOut)
def update_template(
    tid: int,
    body: schemas.TemplateUpdate,
    db: DbSession = Depends(get_session),
):
    t = db.get(models.AgentTemplate, tid)
    if not t:
        raise HTTPException(404, "模板不存在")
    if t.is_builtin:
        raise HTTPException(403, "预置模板仅可查看，不可修改")
    for f in ("name", "role_hint", "system_prompt"):
        v = getattr(body, f)
        if v is not None:
            setattr(t, f, v)
    db.commit()
    db.refresh(t)
    return t


@router.delete("/api/agent-templates/{tid}")
def delete_template(tid: int, db: DbSession = Depends(get_session)):
    t = db.get(models.AgentTemplate, tid)
    if not t:
        raise HTTPException(404, "模板不存在")
    if t.is_builtin:
        raise HTTPException(403, "预置模板仅可查看，不可删除")
    db.delete(t)
    db.commit()
    return {"ok": True}


# ============================================================
# Projects
# ============================================================
@router.post("/api/projects", response_model=schemas.ProjectOut)
def create_project(
    body: schemas.ProjectCreate, db: DbSession = Depends(get_session)
):
    p = models.Project(
        name=body.name,
        description=body.description,
        folder_path=(body.folder_path or "").strip() or None,
    )
    db.add(p)
    db.commit()
    db.refresh(p)
    # 同步创建项目本地文件夹 + README（生成产物自动落盘于此）
    ChatManager(db).ensure_project_folder(p.id, p.name)
    return p


@router.get("/api/projects", response_model=list[schemas.ProjectOut])
def list_projects(db: DbSession = Depends(get_session)):
    return db.query(models.Project).order_by(models.Project.id.desc()).all()


@router.get("/api/projects/{project_id}/path")
def project_folder_path(project_id: int, db: DbSession = Depends(get_session)):
    """返回项目在本地磁盘上的产物文件夹绝对路径（供「打开文件夹」使用）。"""
    manager = ChatManager(db)
    d = manager.ensure_project_folder(project_id)
    return {"ok": True, "path": str(d)}


@router.get("/api/projects/{project_id}", response_model=schemas.ProjectOut)
def get_project(project_id: int, db: DbSession = Depends(get_session)):
    p = db.get(models.Project, project_id)
    if not p:
        raise HTTPException(404, "项目不存在")
    return p


@router.delete("/api/projects/{project_id}")
def delete_project(
    project_id: int,
    delete_folder: bool = False,
    db: DbSession = Depends(get_session),
):
    p = db.get(models.Project, project_id)
    if not p:
        raise HTTPException(404, "项目不存在")
    manager = ChatManager(db)
    folder_deleted = False
    if delete_folder:
        folder_deleted = manager.delete_project_folder(project_id)
    # 级联删除前先取本项目记忆 id，删除后清理 FTS 索引（独立表无触发器，避免残留孤儿索引）
    from sqlalchemy import text as _text

    mem_ids = [
        r[0]
        for r in db.execute(
            _text("SELECT id FROM project_memories WHERE project_id = :pid"),
            {"pid": project_id},
        ).all()
    ]
    db.delete(p)  # 级联删除会话/消息/任务/记忆
    db.commit()
    if mem_ids:
        from sqlalchemy import bindparam

        db.execute(
            _text(
                "DELETE FROM project_memories_fts WHERE rowid IN :ids"
            ).bindparams(bindparam("ids", expanding=True)),
            {"ids": tuple(mem_ids)},
        )
        db.commit()
    return {"ok": True, "folder_deleted": folder_deleted}


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


@router.put("/api/projects/{project_id}/rename", response_model=schemas.ProjectOut)
def rename_project(
    project_id: int,
    body: schemas.RenameRequest,
    db: DbSession = Depends(get_session),
):
    p = db.get(models.Project, project_id)
    if not p:
        raise HTTPException(404, "项目不存在")
    old_name = p.name
    p.name = body.name.strip()
    db.commit()
    db.refresh(p)
    # 同步重命名本地项目文件夹（目标已存在则跳过，不丢数据）
    ChatManager(db).rename_project_folder(project_id, old_name, p.name)
    return p


# ============================================================
# Project Memories（条目化：列表 / 新建 manual / 更新 / 删除）
# ============================================================
@router.get(
    "/api/projects/{project_id}/memories",
    response_model=list[schemas.ProjectMemoryOut],
)
def list_project_memories(project_id: int, db: DbSession = Depends(get_session)):
    if not db.get(models.Project, project_id):
        raise HTTPException(404, "项目不存在")
    return (
        db.query(models.ProjectMemory)
        .filter(models.ProjectMemory.project_id == project_id)
        .order_by(
            models.ProjectMemory.pinned.desc(),
            models.ProjectMemory.updated_at.desc(),
        )
        .all()
    )


@router.post(
    "/api/projects/{project_id}/memories",
    response_model=schemas.ProjectMemoryOut,
)
def create_project_memory(
    project_id: int,
    body: schemas.ProjectMemoryCreate,
    db: DbSession = Depends(get_session),
):
    if not db.get(models.Project, project_id):
        raise HTTPException(404, "项目不存在")
    from ..engine.memory import _sync_fts

    entry = models.ProjectMemory(
        project_id=project_id,
        kind="manual",
        title=body.title.strip()[:120] or "未命名",
        content=body.content.strip(),
        tags=body.tags,
    )
    db.add(entry)
    db.commit()
    db.refresh(entry)
    _sync_fts(db, entry.id, entry.title, entry.content)
    db.commit()
    db.refresh(entry)
    return entry


@router.put("/api/memories/{memory_id}", response_model=schemas.ProjectMemoryOut)
def update_project_memory(
    memory_id: int,
    body: schemas.ProjectMemoryUpdate,
    db: DbSession = Depends(get_session),
):
    entry = db.get(models.ProjectMemory, memory_id)
    if not entry:
        raise HTTPException(404, "记忆不存在")
    from ..engine.memory import _sync_fts

    if body.title is not None:
        entry.title = body.title.strip()[:120] or entry.title
    if body.content is not None:
        entry.content = body.content.strip()
    if body.pinned is not None:
        entry.pinned = body.pinned
    db.commit()
    _sync_fts(db, entry.id, entry.title, entry.content)
    db.commit()
    db.refresh(entry)
    return entry


@router.delete("/api/memories/{memory_id}")
def delete_project_memory(memory_id: int, db: DbSession = Depends(get_session)):
    from ..engine.memory import delete_memory_entry

    if not delete_memory_entry(db, memory_id):
        raise HTTPException(404, "记忆不存在")
    return {"ok": True}


# ============================================================
# Keys
# ============================================================
async def _auto_detect_capability(k: models.KeyEntry) -> str | None:
    """新增/编辑后自动探测模型能力。"""
    import httpx as _httpx
    import base64 as _b64
    if not k.model:
        return None
    api_key = keyring_store.get_key(k.key_ref) or ""
    base_url = k.base_url
    if k.provider == "openrouter":
        base_url = base_url or "https://openrouter.ai/api/v1"
    elif k.provider == "ollama":
        base_url = base_url or "http://127.0.0.1:11434/v1"
    if not base_url:
        return None
    headers = {"Authorization": f"Bearer {api_key}"} if api_key else {}
    caps = {"文本"}
    statuses = []
    try:
        async with _httpx.AsyncClient(timeout=20) as client:
            async def _test(blocks):
                try:
                    r = await client.post(
                        base_url.rstrip("/") + "/chat/completions",
                        headers={**headers, "Content-Type": "application/json"},
                        json={"model": k.model, "messages": [{"role": "user", "content": blocks}], "max_tokens": 5},
                    )
                    return r.status_code
                except Exception:
                    return -1
            tiny_png = "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8/5+hHgAHggJ/PchI7wAAAABJRU5ErkJggg=="
            s1 = await _test([{"type": "text", "text": "hi"}, {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{tiny_png}"}}])
            statuses.append(s1)
            if s1 == 200:
                caps.add("图片")
            s2 = await _test([{"type": "text", "text": "hi"}, {"type": "input_audio", "input_audio": {"data": "UklRQgAAAAAAAAAAPmRhdGEAAAAAAAAAAAAA", "format": "wav"}}])
            statuses.append(s2)
            if s2 == 200:
                caps.add("音频")
            s3 = await _test([{"type": "text", "text": "hi"}, {"type": "video_url", "video_url": {"url": "data:video/mp4;base64,AAAAHGZ0eXBpc292MQAAAGlzb21pc28xMjAxAAAA"}}])
            statuses.append(s3)
            if s3 == 200:
                caps.add("视频")
        # 如果所有请求都失败（非200且非400不支持媒体），说明Key/模型异常
        all_fail = all(s in (-1, 401, 403, 404) for s in statuses if s is not None)
        if all_fail and not any(s == 200 for s in statuses):
            return "异常"
        if "图片" in caps or "音频" in caps or "视频" in caps:
            return "+".join(sorted(caps))
        return "文本"
    except Exception:
        return "异常"


@router.post("/api/keys", response_model=schemas.KeyOut)
async def create_key(body: schemas.KeyCreate, db: DbSession = Depends(get_session)):
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
    # 自动探测能力
    cap = await _auto_detect_capability(k)
    if cap:
        k.capability = cap
        db.commit()
        db.refresh(k)
    return k


def _detect_capability(provider: str, model: str | None) -> str:
    """根据 provider+model 粗判模型能力。"""
    if not model:
        return "未指定"
    m = model.lower()

    # 1) 明确的代码模型
    if any(k in m for k in ["coder", "code-", "-code", "starcoder", "deepseek-code"]):
        return "代码"

    # 2) 明确的多模态（视觉/VL）
    vision_kw = [
        "vision", "-vl", "vl-", "vl ", "qwen-vl", "glm-4v", "internvl", "step-1v",
        "4o", "4-turbo", "gpt-4.1", "gpt-4o", "gpt-5",
        "claude-3", "claude-4",
        "gemini", "o1", "o3", "o4",
        "doubao-1-5", "doubao-vision", "doubao-seed",
        "deepseek-vl",
    ]
    if any(k in m for k in vision_kw):
        return "多模态"

    # 3) deepseek 系列细分
    if "deepseek" in m:
        if "vl" in m:
            return "多模态"
        if "reasoner" in m or "r1" in m:
            return "推理"
        if "coder" in m:
            return "代码"
        return "纯文本"

    # 4) qwen 系列细分
    if "qwen" in m:
        if "vl" in m:
            return "多模态"
        return "纯文本"

    # 5) glm 系列细分
    if "glm" in m:
        if "4v" in m or "-v" in m:
            return "多模态"
        return "纯文本"

    # 6) 纯文本经典模型
    text_kw = ["gpt-3.5", "text-", "-text", "llama", "mistral", "yi-",
               "phi-", "gemma", "command"]
    if any(k in m for k in text_kw):
        return "纯文本"

    return "通用"


@router.get("/api/keys", response_model=list[schemas.KeyOut])
def list_keys(db: DbSession = Depends(get_session)):
    rows = db.query(models.KeyEntry).order_by(models.KeyEntry.id.desc()).all()
    result = []
    for k in rows:
        d = schemas.KeyOut.model_validate(k).model_dump()
        # 优先用探测后存的 capability，没探测过用规则判断
        d["capability"] = k.capability or _detect_capability(k.provider, k.model)
        result.append(schemas.KeyOut(**d))
    return result


# 已知模型能力表（来自各厂商官方文档）
KNOWN_MODEL_CAPABILITIES: dict[str, str] = {
    # OpenAI
    "gpt-4o": "多模态", "gpt-4o-mini": "多模态", "gpt-4o-2024-05-13": "多模态",
    "gpt-4-turbo": "多模态", "gpt-4-turbo-preview": "多模态",
    "gpt-4.1": "多模态", "gpt-4.1-mini": "多模态", "gpt-4.1-nano": "多模态",
    "gpt-5": "多模态", "gpt-5-mini": "多模态", "gpt-5-nano": "多模态",
    "o1": "推理", "o1-mini": "推理", "o1-preview": "推理",
    "o3": "推理", "o3-mini": "推理", "o4-mini": "推理",
    "gpt-3.5-turbo": "纯文本", "gpt-3.5-turbo-16k": "纯文本",
    # Anthropic
    "claude-3-opus-20240229": "多模态", "claude-3-sonnet-20240229": "多模态",
    "claude-3-haiku-20240307": "多模态",
    "claude-3-5-sonnet-20241022": "多模态", "claude-3-5-sonnet-20240620": "多模态",
    "claude-3-5-haiku-20241022": "多模态",
    "claude-3-7-sonnet-20250219": "多模态",
    "claude-sonnet-4-20250514": "多模态", "claude-opus-4-20250514": "多模态",
    # 火山方舟/豆包
    "doubao-1-5-pro-32k-250115": "多模态", "doubao-1-5-pro-256k-250115": "多模态",
    "doubao-1-5-lite-32k-250115": "多模态", "doubao-1-5-lite-4k-250115": "多模态",
    "doubao-pro-32k": "多模态", "doubao-pro-128k": "多模态",
    "doubao-vision-pro": "多模态", "doubao-vision-lite": "多模态",
    # DeepSeek
    "deepseek-chat": "纯文本", "deepseek-reasoner": "推理",
    "deepseek-coder": "代码",
    # 通义千问
    "qwen-max": "纯文本", "qwen-max-0919": "纯文本",
    "qwen-plus": "纯文本", "qwen-turbo": "纯文本",
    "qwen-vl-max": "多模态", "qwen-vl-plus": "多模态",
    "qwen2.5-72b-instruct": "纯文本",
    # 智谱
    "glm-4-plus": "纯文本", "glm-4": "纯文本", "glm-4-air": "纯文本",
    "glm-4v": "多模态", "glm-4v-plus": "多模态",
}


@router.post("/api/keys/{key_id}/probe")
async def probe_key(key_id: int, db: DbSession = Depends(get_session)):
    """调 GET {base_url}/models 查询该 Key 可用模型，并识别能力。"""
    import httpx
    k = db.get(models.KeyEntry, key_id)
    if not k:
        raise HTTPException(404, "Key 不存在")

    api_key = keyring_store.get_key(k.key_ref) or ""
    base_url = k.base_url
    if k.provider == "openrouter":
        base_url = base_url or "https://openrouter.ai/api/v1"
    elif k.provider == "ollama":
        base_url = base_url or "http://127.0.0.1:11434/v1"

    if not base_url:
        raise HTTPException(400, "该 provider 需配置自定义 base_url")

    headers = {"Authorization": f"Bearer {api_key}"} if api_key else {}
    url = base_url.rstrip("/") + "/models"

    try:
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.get(url, headers=headers)
            resp.raise_for_status()
            data = resp.json()
    except Exception as e:
        raise HTTPException(502, f"查询失败: {e}")

    def _modality_to_cap(modality: str) -> str | None:
        """把 API 返回的 modality 字符串转成我们的能力标签。"""
        if not modality:
            return None
        m = modality.lower()
        if "image" in m or "vision" in m or "audio" in m or "video" in m:
            return "多模态"
        if "text" in m and "->text" in m:
            return "纯文本"
        return None

    # 解析模型列表
    models_list = []
    if isinstance(data, dict) and "data" in data:
        items = data["data"]
    elif isinstance(data, list):
        items = data
    else:
        items = []

    for m in items:
        if not isinstance(m, dict):
            continue
        mid = m.get("id") or m.get("name") or ""
        # 1) 优先用 API 返回的 modality 字段（OpenRouter 等）
        modality = None
        arch = m.get("architecture") or {}
        if isinstance(arch, dict):
            modality = arch.get("modality") or arch.get("input_modalities")
        if not modality:
            modality = m.get("modality") or m.get("input_modalities")
        if isinstance(modality, list):
            modality = "+".join(modality)
        cap = _modality_to_cap(modality)
        # 2) 用网关返回的 model_type / description 判断
        if not cap:
            ml = mid.lower()
            model_type = (m.get("model_type") or "").lower()
            desc = (m.get("description") or "").lower()
            # 多模态优先（id 或 description 明确提到视觉/图片）
            if any(k in ml for k in ["vision", "vl", "4o", "4-turbo", "claude-3", "claude-4", "claude-opus", "claude-sonnet", "gemini", "gpt-5", "gpt-4.1", "glm-4v", "internvl", "step-1v"]):
                cap = "多模态"
            elif any(k in desc for k in ["vision", "image input", "multimodal", "visual understanding", "图片", "视觉"]):
                cap = "多模态"
            # 代码：id 明确含 coder/code，或 model_type 是 code
            elif "coder" in ml or ml.endswith("-code") or model_type == "code":
                cap = "代码"
            # 推理
            elif "reasoner" in ml or "r1" in ml or "o1" in ml or "o3" in ml or "thinking" in desc:
                cap = "推理"
            # 默认纯文本
            elif "llm" in model_type or model_type == "":
                cap = "纯文本"
        # 3) 查已知表
        if not cap:
            cap = KNOWN_MODEL_CAPABILITIES.get(mid)
        # 4) 关键词兜底
        if not cap:
            cap = _detect_capability(k.provider, mid)
        models_list.append({"id": mid, "capability": cap})

    # 对当前默认模型，确定最终能力
    current_cap = None
    if k.model:
        current_cap = KNOWN_MODEL_CAPABILITIES.get(k.model)
        if not current_cap:
            for m in models_list:
                if m["id"] == k.model:
                    current_cap = m["capability"]
                    break
        if not current_cap:
            current_cap = _detect_capability(k.provider, k.model)

        # 真实探测：分别测试图片/音频/视频支持
        caps = set(["文本"])  # 文本默认支持
        try:
            import base64
            vision_url = base_url.rstrip("/") + "/chat/completions"

            async def _test(content_blocks):
                try:
                    async with httpx.AsyncClient(timeout=20) as client:
                        resp = await client.post(
                            vision_url,
                            headers={**headers, "Content-Type": "application/json"},
                            json={
                                "model": k.model,
                                "messages": [{"role": "user", "content": content_blocks}],
                                "max_tokens": 5,
                            },
                        )
                        return resp.status_code, resp.text.lower()
                except Exception:
                    return None, ""

            # 1x1 PNG
            tiny_png = "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8/5+hHgAHggJ/PchI7wAAAABJRU5ErkJggg=="
            sc, etext = await _test([
                {"type": "text", "text": "hi"},
                {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{tiny_png}"}},
            ])
            if sc == 200:
                caps.add("图片")
            elif sc and any(k in etext for k in ["image", "vision", "图片"]):
                pass  # 不支持图片

            # 1 秒极小 WAV（16字节静音头 + 0 数据）
            # 用 data:audio/wav;base64 测试
            tiny_wav = "UklRQgAAAAAAAAAAPmRhdGEAAAAAAAAAAAAA"
            sc2, etext2 = await _test([
                {"type": "text", "text": "hi"},
                {"type": "input_audio", "input_audio": {"data": tiny_wav, "format": "wav"}},
            ])
            if sc2 == 200:
                caps.add("音频")

            # 视频：用 data:video/mp4 测试（极小字节）
            tiny_mp4 = "AAAAHGZ0eXBpc292MQAAAGlzb21pc28xMjAxAAAA"
            sc3, etext3 = await _test([
                {"type": "text", "text": "hi"},
                {"type": "video_url", "video_url": {"url": f"data:video/mp4;base64,{tiny_mp4}"}},
            ])
            if sc3 == 200:
                caps.add("视频")

            # 探测成功（至少图片或音频或视频有一个 200），用探测结果
            if "图片" in caps or "音频" in caps or "视频" in caps:
                current_cap = "+".join(sorted(caps))
        except Exception:
            pass  # 探测失败保持原判断

    # 存库
    if current_cap:
        k.capability = current_cap
        db.commit()

    return {
        "key_id": key_id,
        "default_model": k.model,
        "default_capability": current_cap,
        "models": models_list,
        "total": len(models_list),
    }


@router.put("/api/keys/{key_id}/capability")
def update_key_capability(key_id: int, body: dict, db: DbSession = Depends(get_session)):
    k = db.get(models.KeyEntry, key_id)
    if not k:
        raise HTTPException(404, "Key 不存在")
    k.capability = body.get("capability")
    db.commit()
    return {"ok": True, "capability": k.capability}


@router.put("/api/keys/{key_id}", response_model=schemas.KeyOut)
async def update_key(
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
    # 模型或 Key 变了，重新自动探测
    if body.model or body.api_key or body.base_url:
        cap = await _auto_detect_capability(k)
        if cap:
            k.capability = cap
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
    if body.project_id is not None and not db.get(models.Project, body.project_id):
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
    # 成员列表 + 主理人（主理人如果没选进成员，自动加上）
    invite_ids = list(body.agent_ids)
    if body.orchestrator_agent_id and body.orchestrator_agent_id not in invite_ids:
        invite_ids.append(body.orchestrator_agent_id)
    for agent_id in invite_ids:
        if db.get(models.Agent, agent_id):
            await manager.invite_agent(s.id, agent_id)
    if body.orchestrator_agent_id:
        s.orchestrator_agent_id = body.orchestrator_agent_id
        db.commit()
        db.refresh(s)
    return s


@router.get("/api/recent-sessions", response_model=list[schemas.SessionOut])
def list_recent_sessions(
    limit: int = 30,
    archived: bool = False,
    all_sessions: bool = False,
    db: DbSession = Depends(get_session),
):
    """archived=false 返回进行中的独立对话（侧边栏「最近」）；archived=true 返回所有已归档会话（含项目内）；
    all_sessions=true 返回全部会话（历史对话管理用）。"""
    q = db.query(models.ChatSession)
    if all_sessions:
        pass
    elif archived:
        # 归档列表：包含项目内会话，方便在「归档与恢复」里统一找回
        q = q.filter(models.ChatSession.status == "archived")
    else:
        # 最近：仅独立对话（无项目归属）
        q = q.filter(
            models.ChatSession.project_id.is_(None),
            models.ChatSession.status != "archived",
        )
    return (
        q.order_by(models.ChatSession.created_at.desc(), models.ChatSession.id.desc())
        .limit(limit)
        .all()
    )


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


@router.put("/api/sessions/{session_id}/rename", response_model=schemas.SessionOut)
def rename_session(
    session_id: int,
    body: schemas.RenameRequest,
    db: DbSession = Depends(get_session),
):
    s = db.get(models.ChatSession, session_id)
    if not s:
        raise HTTPException(404, "会话不存在")
    s.title = body.name.strip() or s.title
    db.commit()
    db.refresh(s)
    return s


@router.put("/api/sessions/{session_id}/move", response_model=schemas.SessionOut)
def move_session(
    session_id: int,
    body: schemas.MoveSessionRequest,
    db: DbSession = Depends(get_session),
):
    s = db.get(models.ChatSession, session_id)
    if not s:
        raise HTTPException(404, "会话不存在")
    if body.project_id is not None and not db.get(models.Project, body.project_id):
        raise HTTPException(404, "项目不存在")
    s.project_id = body.project_id
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
    tasks = db.query(models.Task).filter_by(session_id=session_id).order_by(models.Task.id).all()
    result = []
    for t in tasks:
        d = schemas.TaskOut.model_validate(t).model_dump()
        if t.assignee_agent_id:
            agent = db.get(models.Agent, t.assignee_agent_id)
            d["assignee_name"] = agent.name if agent else None
        result.append(schemas.TaskOut(**d))
    return result


# ============================================================
# Artifacts（产物）
# ============================================================
@router.get("/api/sessions/{session_id}/artifacts", response_model=list[schemas.ArtifactOut])
def list_artifacts(
    session_id: int,
    folder: str | None = None,
    db: DbSession = Depends(get_session),
):
    if not db.get(models.ChatSession, session_id):
        raise HTTPException(404, "会话不存在")
    q = db.query(models.Artifact).filter_by(session_id=session_id)
    if folder is not None:
        if folder == "":
            q = q.filter(models.Artifact.folder.is_(None))
        else:
            q = q.filter_by(folder=folder)
    return q.order_by(models.Artifact.id.desc()).all()


@router.get("/api/sessions/{session_id}/artifact-folders")
def list_artifact_folders(session_id: int, db: DbSession = Depends(get_session)):
    """按项目文件夹分组统计产物（右侧面板按文件夹展示）。"""
    if not db.get(models.ChatSession, session_id):
        raise HTTPException(404, "会话不存在")
    manager = ChatManager(db)
    return manager.list_artifact_folders(session_id)


@router.get("/api/artifacts/{artifact_id}/download")
def download_artifact(artifact_id: int, db: DbSession = Depends(get_session)):
    art = db.get(models.Artifact, artifact_id)
    if not art:
        raise HTTPException(404, "产物不存在")
    path = Path(art.file_path).resolve()
    # 只允许访问项目产物目录 / 旧产物目录内的文件，防路径穿越
    if not (
        str(path).startswith(str(PROJECTS_DIR.resolve()))
        or str(path).startswith(str(ARTIFACT_DIR.resolve()))
    ):
        raise HTTPException(403, "非法路径")
    if not path.is_file():
        raise HTTPException(404, "产物文件已丢失")
    # 按文件扩展名推断 MIME（图片/视频/PDF 返回真实类型，浏览器才能内嵌预览；其余回退 octet-stream）
    fname = art.name or path.name
    mime, _ = mimetypes.guess_type(fname)
    # 图片/视频/PDF 用 inline 让浏览器内嵌渲染；其他用 attachment 触发下载
    inlineable = mime and (
        mime.startswith("image/") or mime.startswith("video/") or mime == "application/pdf"
    )
    return FileResponse(
        path,
        filename=fname,
        media_type=mime or "application/octet-stream",
        content_disposition_type="inline" if inlineable else "attachment",
    )


import os
import subprocess
import tempfile


# Office 文档（docx/xlsx/pptx 等）用 LibreOffice 转 PDF 后内嵌预览
_OFFICE_SUFFIXES = {".docx", ".xlsx", ".pptx", ".odt", ".ods", ".odp", ".rtf", ".csv"}


@router.get("/api/artifacts/{artifact_id}/preview")
def preview_artifact(artifact_id: int, db: DbSession = Depends(get_session)):
    """预览接口：图片/视频/PDF 直接走 download；Office 文档用 LibreOffice 转 PDF 后返回。"""
    art = db.get(models.Artifact, artifact_id)
    if not art:
        raise HTTPException(404, "产物不存在")
    path = Path(art.file_path).resolve()
    if not path.is_file():
        raise HTTPException(404, "产物文件已丢失")

    ext = path.suffix.lower()
    # 非 Office 文档：直接重定向到 download（浏览器自己处理）
    if ext not in _OFFICE_SUFFIXES:
        return FileResponse(
            path,
            filename=art.name or path.name,
            media_type=mimetypes.guess_type(art.name or path.name)[0] or "application/octet-stream",
            content_disposition_type="inline",
        )

    # Office 文档：用 LibreOffice headless 转 PDF
    with tempfile.TemporaryDirectory(prefix="ma_preview_") as tmp:
        out = Path(tmp) / "preview.pdf"
        try:
            proc = subprocess.run(
                [
                    "soffice", "--headless", "--convert-to", "pdf",
                    "--outdir", tmp, str(path),
                ],
                capture_output=True, text=True, timeout=60,
            )
        except Exception as exc:  # noqa: BLE001
            raise HTTPException(500, f"文档预览转换失败: {exc}") from exc
        # soffice 输出文件名 = 原文件名换后缀
        generated = Path(tmp) / (path.stem + ".pdf")
        if not generated.is_file():
            raise HTTPException(500, f"文档转换失败: {proc.stderr[-300:]}")
        # 读进内存再返回（TemporaryDirectory 退出后文件会被删，不能用 FileResponse 惰性读）
        from fastapi.responses import Response
        from urllib.parse import quote
        pdf_name = path.stem + ".pdf"
        return Response(
            content=generated.read_bytes(),
            media_type="application/pdf",
            headers={
                "Content-Disposition": f"inline; filename*=utf-8''{quote(pdf_name)}",
            },
        )


@router.delete("/api/artifacts/{artifact_id}")
def delete_artifact(artifact_id: int, db: DbSession = Depends(get_session)):
    """删除单个产物（数据库记录 + 磁盘文件）。"""
    manager = ChatManager(db)
    if not manager.delete_artifact(artifact_id):
        raise HTTPException(404, "产物不存在")
    return {"ok": True}


@router.delete("/api/sessions/{session_id}/artifact-folders")
def delete_artifact_folder(
    session_id: int, folder: str, db: DbSession = Depends(get_session)
):
    """删除整个项目文件夹（含其下所有产物）。folder 走 query 参数，以支持「日期/产物名」多级名称。"""
    manager = ChatManager(db)
    n = manager.delete_artifact_folder(session_id, folder)
    if n == 0:
        raise HTTPException(404, "文件夹不存在或无产物")
    return {"ok": True, "deleted": n}


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


@router.post("/api/sessions/{session_id}/upload")
async def upload_attachment(
    session_id: int,
    file: UploadFile = File(...),
    db: DbSession = Depends(get_session),
):
    """上传文件/图片附件到当前对话：保存到产物目录「上传附件/」，并作为上下文消息供 Agent 读取。"""
    if not db.get(models.ChatSession, session_id):
        raise HTTPException(404, "会话不存在")
    manager = ChatManager(db)
    try:
        art = manager.save_uploaded_attachment(session_id, file)
    except OSError as exc:
        raise HTTPException(500, f"保存附件失败: {exc}") from exc
    return {
        "id": art.id,
        "name": art.name,
        "type": art.type,
        "folder": art.folder,
        "file_path": art.file_path,
        "size": art.meta.get("size"),
    }


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


@router.post("/api/tasks/{task_id}/pause")
def pause_task(task_id: int, db: DbSession = Depends(get_session)):
    task = db.get(models.Task, task_id)
    if not task:
        raise HTTPException(404, "任务不存在")
    if task.status != "running":
        raise HTTPException(400, "仅执行中的任务可暂停")
    task.status = "paused"
    # 同根任务下的执行中子任务一并暂停
    if task.parent_task_id:
        db.query(models.Task).filter(
            models.Task.parent_task_id == task.parent_task_id,
            models.Task.status == "running",
        ).update({"status": "paused"})
    db.commit()
    db.refresh(task)
    return {"ok": True, "status": task.status}


@router.post("/api/tasks/{task_id}/resume")
async def resume_task(task_id: int, db: DbSession = Depends(get_session)):
    task = db.get(models.Task, task_id)
    if not task:
        raise HTTPException(404, "任务不存在")
    if task.status != "paused":
        raise HTTPException(400, "仅已暂停的任务可继续")
    manager = ChatManager(db)
    try:
        task = await manager.orchestrate(task.session_id, task.title, root_id=task.id)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    return {"ok": True, "task_id": task.id, "status": task.status}


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
        use_docker=body.use_docker,
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
