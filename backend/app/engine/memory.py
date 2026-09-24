"""项目级记忆。

MVP：基于会话消息历史构建上下文（最近 N 条，按时间正序）。
预留向量库 / 摘要沉淀接口，二期可替换为 RAG。
"""
from __future__ import annotations

import re

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

    import base64
    import mimetypes
    from pathlib import Path

    ctx: list[dict] = []
    for m in rows:
        if m.sender_type == SENDER_SYSTEM:
            continue
        role = "user" if m.sender_type == "user" else "assistant"
        prefix = f"[{m.sender_name}]" if m.sender_name else ""

        # 附件消息：构造多模态
        meta = m.meta or {}
        fp = meta.get("file_path")
        if meta.get("kind") == "attachment" and fp and Path(fp).is_file():
            ext = Path(fp).suffix.lower()
            # 图片：直接读 base64
            if ext in (".png", ".jpg", ".jpeg", ".gif", ".webp"):
                mime = mimetypes.guess_type(fp)[0] or "image/png"
                b64 = base64.b64encode(Path(fp).read_bytes()).decode()
                ctx.append({
                    "role": role,
                    "content": [
                        {"type": "text", "text": f"{prefix} {m.content}".strip()},
                        {"type": "image_url", "image_url": {"url": f"data:{mime};base64,{b64}"}},
                    ],
                })
                continue
            # PDF：前 3 页转 PNG 一起传
            if ext == ".pdf":
                import subprocess, tempfile
                try:
                    with tempfile.TemporaryDirectory(prefix="ma_pdfimg_") as td:
                        subprocess.run(
                            ["pdftoppm", "-png", "-r", "100", "-f", "1", "-l", "3", fp, f"{td}/page"],
                            capture_output=True, timeout=30,
                        )
                        imgs = sorted(Path(td).glob("page-*.png"))[:3]
                        parts = [{"type": "text", "text": f"{prefix} {m.content}".strip()}]
                        for img in imgs:
                            b64 = base64.b64encode(img.read_bytes()).decode()
                            parts.append({"type": "image_url", "image_url": {"url": f"data:image/png;base64,{b64}"}})
                        ctx.append({"role": role, "content": parts})
                        continue
                except Exception:
                    pass

        ctx.append({"role": role, "content": f"{prefix} {m.content}".strip()})
    return ctx


# ============================================================
# 项目记忆条目化（路线 A · 瘦身版）
# ============================================================
from sqlalchemy import text  # noqa: E402

from ..models.entities import ProjectMemory  # noqa: E402

MEMORY_TITLE_MAX = 60       # 标题截断上限（字）
MEMORY_CONTENT_MAX = 600    # 单条正文截断上限（字）
MEMORY_CORE_LIMIT = 1500    # 核心块注入预算（字）
MEMORY_TOTAL_LIMIT = 3000   # 核心 + 检索总预算（字）
MEMORY_SOFT_LIMIT = 1000    # 项目记忆软上限（条，超限仅提示）


def _truncate(text: str, limit: int) -> str:
    """按字截断并追加省略标记；不破坏可读性。"""
    text = (text or "").strip()
    if len(text) <= limit:
        return text
    return text[:limit] + "…"


def _sync_fts(db, memory_id: int, title: str, content: str) -> None:
    """把一条记忆同步进 FTS5 索引（先删旧索引再插入，独立 FTS5 表）。"""
    db.execute(
        text("DELETE FROM project_memories_fts WHERE rowid = :id"),
        {"id": memory_id},
    )
    db.execute(
        text(
            "INSERT INTO project_memories_fts(rowid, title, content) "
            "VALUES(:id, :title, :content)"
        ),
        {"id": memory_id, "title": title, "content": content},
    )


def _remove_fts(db, memory_id: int) -> None:
    """从 FTS5 索引移除一条记忆。"""
    db.execute(
        text("DELETE FROM project_memories_fts WHERE rowid = :id"),
        {"id": memory_id},
    )


def save_memory_entry(
    db,
    project_id: int,
    *,
    title: str,
    content: str,
    source_task_id: int | None = None,
    kind: str = "auto",
    tags: str | None = None,
) -> tuple[ProjectMemory | None, str | None]:
    """写入一条项目记忆。

    - 空内容直接不落库（空值保护）
    - 标题 / 正文按上限截断并带省略标记
    - auto 条目按 (project_id, title) 去重：同任务重跑（新根任务）命中同标题则更新旧条目
      （Mem0 update 语义），避免重复追加；source_task_id 仅作溯源
    - 超过软上限仅返回提示，不自动删除
    返回 (entry, warning)。
    """
    content = (content or "").strip()
    if not content:
        return None, None
    title = _truncate(title, MEMORY_TITLE_MAX)
    content = _truncate(content, MEMORY_CONTENT_MAX)

    entry = None
    if kind == "auto":
        entry = (
            db.query(ProjectMemory)
            .filter(
                ProjectMemory.project_id == project_id,
                ProjectMemory.title == title,
                ProjectMemory.kind == "auto",
            )
            .first()
        )

    if entry is not None:
        entry.title = title
        entry.content = content
        if source_task_id is not None:
            entry.source_task_id = source_task_id
        if tags is not None:
            entry.tags = tags
        _sync_fts(db, entry.id, entry.title, entry.content)
    else:
        entry = ProjectMemory(
            project_id=project_id,
            kind=kind,
            title=title,
            content=content,
            tags=tags,
            source_task_id=source_task_id,
        )
        db.add(entry)
        db.flush()
        _sync_fts(db, entry.id, entry.title, entry.content)
    db.commit()

    warning = None
    count = (
        db.query(ProjectMemory)
        .filter(ProjectMemory.project_id == project_id)
        .count()
    )
    if count > MEMORY_SOFT_LIMIT:
        warning = (
            f"项目记忆已达 {count} 条，超过软上限 {MEMORY_SOFT_LIMIT}，建议清理。"
        )
    return entry, warning


def delete_memory_entry(db, memory_id: int) -> bool:
    """删除一条记忆（含 FTS 索引）。返回是否真的删除。"""
    entry = db.get(ProjectMemory, memory_id)
    if not entry:
        return False
    _remove_fts(db, entry.id)
    db.delete(entry)
    db.commit()
    return True


def _extract_keywords(query: str) -> tuple[list[str], list[str]]:
    """提取检索关键词。

    返回 (candidates, grams)：
    - candidates：英文/数字词 + 中文连续串，用于「关键词不足则跳过」的门槛判断
    - grams：与 candidates 相同。FTS5 使用 trigram tokenizer，查询词自动按 3-gram
      匹配（中文子串命中），无需手动切分；2 字以内的词天然不命中，符合防噪音预期。
    """
    q = (query or "").strip()
    if not q:
        return [], []
    words = re.findall(r"[a-zA-Z0-9_]{2,}", q)
    cn_runs = re.findall(r"[\u4e00-\u9fa5]{2,}", q)
    grams = words + cn_runs
    return grams, grams


def _search_fts(
    db, project_id: int, query: str, limit: int = 5
) -> list[tuple[int, str, str]]:
    """FTS5（trigram）检索 Top-N，按 bm25 相关度排序；无命中返回空。"""
    candidates, grams = _extract_keywords(query)
    if len(candidates) < 2 or not grams:
        return []
    match_q = " OR ".join(grams)
    rows = db.execute(
        text(
            "SELECT m.id, m.title, m.content, bm25(project_memories_fts) AS score "
            "FROM project_memories_fts f "
            "JOIN project_memories m ON m.id = f.rowid "
            "WHERE project_memories_fts MATCH :q AND m.project_id = :pid "
            "ORDER BY score LIMIT :lim"
        ),
        {"q": match_q, "pid": project_id, "lim": limit},
    ).all()
    if not rows:
        return []
    return [(r.id, r.title, r.content) for r in rows]


def build_memory_blocks(
    db,
    project_id: int | None,
    query: str | None = None,
    backend: str = "fts5",
) -> str:
    """构造注入 Agent system prompt 的「项目记忆」块（分层：核心 + 检索）。

    - 核心块（Core）：pinned + 最近 5 条，始终注入，预算 ≤1500 字
    - 检索块（Archival）：FTS5（trigram）按关键词 Top-5，预算与核心块合计 ≤3000 字；
      关键词 <2 或无命中时不注入（防噪音）
    - backend 可插拔：默认 fts5；将来向量检索（backend="vector"）只换实现
    返回空串表示无记忆可注入。
    """
    if not project_id:
        return ""
    core_rows = (
        db.query(ProjectMemory)
        .filter(ProjectMemory.project_id == project_id)
        .order_by(ProjectMemory.pinned.desc(), ProjectMemory.updated_at.desc())
        .limit(20)
        .all()
    )
    pinned = [m for m in core_rows if m.pinned]
    recent = [m for m in core_rows if not m.pinned][:5]
    core_items = list(dict.fromkeys(pinned + recent))

    blocks: list[str] = []
    used = 0
    core_ids: set[int] = set()
    for m in core_items:
        block = f"- 【{m.title}】{m.content}"
        if used + len(block) > MEMORY_CORE_LIMIT:
            break
        blocks.append(block)
        core_ids.add(m.id)
        used += len(block)

    if backend == "fts5" and query:
        try:
            hits = _search_fts(db, project_id, query, limit=5)
        except Exception:  # noqa: BLE001  FTS 异常不影响主流程
            hits = []
        for mid, title, content in hits:
            if mid in core_ids:
                continue
            block = f"- 【{title}】{content}"
            if used + len(block) > MEMORY_TOTAL_LIMIT:
                break
            blocks.append(block)
            used += len(block)

    if not blocks:
        return ""
    return "【项目记忆（历史结论）】\n" + "\n".join(blocks)
