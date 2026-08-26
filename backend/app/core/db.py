"""数据库连接与会话管理（SQLite + SQLAlchemy 2.0）。"""
from __future__ import annotations

from sqlalchemy import create_engine, inspect, text
from sqlalchemy.orm import DeclarativeBase, sessionmaker

from .config import DB_PATH


class Base(DeclarativeBase):
    """所有 ORM 模型的基类。"""


engine = create_engine(
    f"sqlite:///{DB_PATH}",
    connect_args={"check_same_thread": False},
    echo=False,
)

SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


def _migrate() -> None:
    """轻量迁移：为旧库补充新增列。"""
    insp = inspect(engine)
    if "projects" in insp.get_table_names():
        cols = {c["name"] for c in insp.get_columns("projects")}
        if "status" not in cols:
            with engine.begin() as conn:
                conn.execute(
                    text("ALTER TABLE projects ADD COLUMN status VARCHAR(20) DEFAULT 'active'")
                )
        if "memory" not in cols:
            with engine.begin() as conn:
                conn.execute(
                    text("ALTER TABLE projects ADD COLUMN memory TEXT DEFAULT ''")
                )
    if "chat_sessions" in insp.get_table_names():
        cols = {c["name"] for c in insp.get_columns("chat_sessions")}
        if "status" not in cols:
            with engine.begin() as conn:
                conn.execute(
                    text("ALTER TABLE chat_sessions ADD COLUMN status VARCHAR(20) DEFAULT 'active'")
                )
    if "key_entries" in insp.get_table_names():
        cols = {c["name"] for c in insp.get_columns("key_entries")}
        if "model" not in cols:
            with engine.begin() as conn:
                conn.execute(
                    text("ALTER TABLE key_entries ADD COLUMN model VARCHAR(120)")
                )


def init_db() -> None:
    """建表（若不存在）+ 迁移。"""
    from .. import models  # noqa: F401  确保模型被注册

    Base.metadata.create_all(bind=engine)
    _migrate()


def get_session():
    """FastAPI 依赖注入用：请求级会话。"""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
