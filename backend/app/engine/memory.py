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
