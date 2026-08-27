"""数据库连接与会话管理（SQLite + SQLAlchemy 2.0）。"""
from __future__ import annotations

from sqlalchemy import create_engine, event, inspect, text
from sqlalchemy.orm import DeclarativeBase, sessionmaker

from .config import DB_PATH


class Base(DeclarativeBase):
    """所有 ORM 模型的基类。"""


engine = create_engine(
    f"sqlite:///{DB_PATH}",
    connect_args={"check_same_thread": False},
    echo=False,
)


@event.listens_for(engine, "connect")
def _set_sqlite_pragma(dbapi_connection, connection_record) -> None:
    """每个连接启用 WAL + busy_timeout，支撑并行子任务的并发读写。"""
    cursor = dbapi_connection.cursor()
    try:
        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.execute("PRAGMA busy_timeout=15000")
        cursor.execute("PRAGMA synchronous=NORMAL")
    finally:
        cursor.close()


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
        # 让 project_id 允许为空（支持"无项目直接对话"）。SQLite 无法改列约束，需重建表。
        proj_nullable = True
        for c in insp.get_columns("chat_sessions"):
            if c["name"] == "project_id":
                proj_nullable = c.get("nullable", True)
        if proj_nullable is False:
            with engine.begin() as conn:
                conn.execute(text("PRAGMA foreign_keys=OFF"))
                conn.execute(text("ALTER TABLE chat_sessions RENAME TO chat_sessions_old"))
                conn.execute(
                    text(
                        """
                        CREATE TABLE chat_sessions (
                            id INTEGER NOT NULL PRIMARY KEY,
                            project_id INTEGER REFERENCES projects(id),
                            title VARCHAR(120) DEFAULT '新会话' NOT NULL,
                            orchestrator_agent_id INTEGER REFERENCES agents(id),
                            status VARCHAR(20) DEFAULT 'active' NOT NULL,
                            created_at DATETIME NOT NULL
                        )
                        """
                    )
                )
                conn.execute(
                    text(
                        """
                        INSERT INTO chat_sessions
                            (id, project_id, title, orchestrator_agent_id, status, created_at)
                        SELECT id, project_id, title, orchestrator_agent_id, status, created_at
                        FROM chat_sessions_old
                        """
                    )
                )
                conn.execute(text("DROP TABLE chat_sessions_old"))
                conn.execute(text("PRAGMA foreign_keys=ON"))
    if "key_entries" in insp.get_table_names():
        cols = {c["name"] for c in insp.get_columns("key_entries")}
        if "model" not in cols:
            with engine.begin() as conn:
                conn.execute(
                    text("ALTER TABLE key_entries ADD COLUMN model VARCHAR(120)")
                )
    if "artifacts" in insp.get_table_names():
        cols = {c["name"] for c in insp.get_columns("artifacts")}
        if "folder" not in cols:
            with engine.begin() as conn:
                conn.execute(
                    text("ALTER TABLE artifacts ADD COLUMN folder VARCHAR(200)")
                )
                # 存量平铺产物一次性归入「历史产物」文件夹
                conn.execute(
                    text("UPDATE artifacts SET folder='历史产物' WHERE folder IS NULL")
                )
    if "tasks" in insp.get_table_names():
        cols = {c["name"] for c in insp.get_columns("tasks")}
        if "folder" not in cols:
            with engine.begin() as conn:
                conn.execute(
                    text("ALTER TABLE tasks ADD COLUMN folder VARCHAR(200)")
                )


def _seed_templates() -> None:
    """首次使用时把预置岗位模板写入数据库（仅当表为空时）。"""
    from ..engine.templates import AGENT_TEMPLATES
    from ..models.entities import AgentTemplate

    with SessionLocal() as db:
        if db.query(AgentTemplate).count() > 0:
            return
        for t in AGENT_TEMPLATES:
            db.add(
                AgentTemplate(
                    name=t["name"],
                    provider=t["provider"],
                    model=t["model"],
                    role_hint=t.get("role_hint"),
                    system_prompt=t["system_prompt"],
                    is_builtin=1,
                )
            )
        db.commit()


def init_db() -> None:
    """建表（若不存在）+ 迁移 + 播种预置模板。"""
    from ..models import entities  # noqa: F401  确保所有实体注册到 metadata

    Base.metadata.create_all(bind=engine)
    _migrate()
    _seed_templates()


def get_session():
    """FastAPI 依赖注入用：请求级会话。"""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
