#!/usr/bin/env python3
"""项目记忆存量迁移脚本（幂等，可重复执行）。

把旧的 projects.memory（单个追加式大字符串）迁移到新的 project_memories 条目表：
- 按「### YYYY-MM-DD HH:MM · 标题」识别条目边界（正文里的 ### 子标题不会误切）
- 正文为空的条目丢弃，并写入日志（dropped_<时间戳>.log）
- 正文非空条目写入 project_memories（kind=auto, source_task_id=NULL），截断带省略号
- 完成后把旧字段备份为 projects.memory_bak（已存在则跳过）

用法：
    python scripts/migrate_memory.py [--db 数据库路径] [--dry-run]

依赖：仅标准库 + sqlite3（FTS5 需 SQLite >= 3.19）。
"""
from __future__ import annotations

import argparse
import re
import sqlite3
import sys
from datetime import datetime
from pathlib import Path

ENTRY_RE = re.compile(r"^###\s+(\d{4}-\d{2}-\d{2} \d{2}:\d{2})\s*[·•-]?\s*(.+)$", re.M)

DDL_TABLE = """
CREATE TABLE IF NOT EXISTS project_memories (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    project_id     INTEGER NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    kind           VARCHAR(16)  NOT NULL DEFAULT 'auto',
    title          VARCHAR(120) NOT NULL,
    content        TEXT         NOT NULL,
    tags           VARCHAR(255),
    source_task_id INTEGER,
    pinned         INTEGER      NOT NULL DEFAULT 0,
    created_at     DATETIME     NOT NULL,
    updated_at     DATETIME     NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_memories_project ON project_memories(project_id, updated_at DESC);
CREATE INDEX IF NOT EXISTS ix_memories_task   ON project_memories(source_task_id);
"""

DDL_FTS = """
CREATE VIRTUAL TABLE IF NOT EXISTS project_memories_fts USING fts5(
    title, content, tokenize='trigram'
);
"""


def _now() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _truncate(text: str, limit: int) -> str:
    text = (text or "").strip()
    if len(text) <= limit:
        return text
    return text[:limit] + "…"


def _sync_fts(cur: sqlite3.Cursor, memory_id: int, title: str, content: str) -> None:
    cur.execute(
        "DELETE FROM project_memories_fts WHERE rowid = ?",
        (memory_id,),
    )
    cur.execute(
        "INSERT INTO project_memories_fts(rowid, title, content) VALUES(?, ?, ?)",
        (memory_id, title, content),
    )


def _memory_column(cur: sqlite3.Cursor) -> str | None:
    """返回当前项目记忆字段名（memory_bak 优先，兼容已迁移过的库）。"""
    cols = [r[1] for r in cur.execute("PRAGMA table_info(projects)").fetchall()]
    if "memory_bak" in cols:
        return "memory_bak"
    if "memory" in cols:
        return "memory"
    return None


def migrate(db_path: Path, dry_run: bool = False) -> dict:
    conn = sqlite3.connect(str(db_path))
    conn.execute("PRAGMA foreign_keys=ON")
    cur = conn.cursor()

    # 1. 确保表存在（首次运行会在 init_db 之前）
    cur.executescript(DDL_TABLE)
    cur.executescript(DDL_FTS)

    mem_col = _memory_column(cur)
    if not mem_col:
        print("[迁移] 未找到旧项目记忆字段（memory/memory_bak），无数据可迁移")
        conn.close()
        return {
            "projects_processed": 0,
            "inserted": 0,
            "skipped": 0,
            "dropped": 0,
            "dry_run": dry_run,
        }

    projects = cur.execute(
        f"SELECT id, name, {mem_col} FROM projects "
        f"WHERE {mem_col} IS NOT NULL AND {mem_col} <> ''"
    ).fetchall()

    inserted = 0
    updated = 0
    dropped: list[tuple[int, str, str]] = []  # (project_id, title, reason)
    skipped = 0

    for pid, name, memory in projects:
        # 定位所有条目边界（带时间戳的 ### 标题）
        matches = list(ENTRY_RE.finditer(memory or ""))
        for i, m in enumerate(matches):
            ts = m.group(1)
            raw_title = (m.group(2) or "").strip() or f"迁移条目 {ts}"
            # 正文 = 本标题结束到下一个标题开始
            end = matches[i + 1].start() if i + 1 < len(matches) else len(memory)
            body = memory[m.end() : end].strip()

            title = _truncate(f"{ts} · {raw_title}", 60)
            if not body:
                dropped.append((pid, title, "正文为空"))
                continue

            # 幂等：同项目同标题已存在则跳过
            exists = cur.execute(
                "SELECT id FROM project_memories WHERE project_id=? AND title=? AND kind='auto'",
                (pid, title),
            ).fetchone()
            if exists:
                skipped += 1
                continue

            content = _truncate(body, 600)
            if dry_run:
                continue
            cur.execute(
                "INSERT INTO project_memories"
                "(project_id, kind, title, content, tags, source_task_id, pinned, created_at, updated_at)"
                "VALUES (?, 'auto', ?, ?, NULL, NULL, 0, ?, ?)",
                (pid, title, content, ts + ":00", ts + ":00"),
            )
            mid = cur.lastrowid
            _sync_fts(cur, mid, title, content)
            inserted += 1

        # 2. 备份旧字段（幂等：memory_bak 已存在则跳过）
        if not dry_run and mem_col == "memory":
            cols = [r[1] for r in cur.execute("PRAGMA table_info(projects)").fetchall()]
            if "memory_bak" not in cols:
                cur.execute("ALTER TABLE projects RENAME COLUMN memory TO memory_bak")

    if dry_run:
        conn.rollback()
    else:
        conn.commit()

    # 3. 日志：被丢弃的空条目
    if dropped:
        log_path = db_path.parent / f"memory_migrate_dropped_{datetime.now():%Y%m%d_%H%M%S}.log"
        if not dry_run:
            with open(log_path, "w", encoding="utf-8") as f:
                f.write(f"# 项目记忆迁移：正文为空被丢弃的条目（共 {len(dropped)} 条）\n")
                for pid, title, reason in dropped:
                    f.write(f"[project {pid}] {title} — {reason}\n")
            log_msg = str(log_path)
        else:
            log_msg = "(dry-run，未写日志)"
        print(f"[迁移] 丢弃空条目 {len(dropped)} 条 -> {log_msg}")
    else:
        print("[迁移] 无空条目需要丢弃")

    conn.close()
    return {
        "projects_processed": len(projects),
        "inserted": inserted,
        "skipped": skipped,
        "dropped": len(dropped),
        "dry_run": dry_run,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="项目记忆存量迁移（幂等）")
    parser.add_argument("--db", default=None, help="数据库路径（默认 $MULTIAGENT_DATA_DIR/multiagent.db）")
    parser.add_argument("--dry-run", action="store_true", help="只分析不写入")
    args = parser.parse_args()

    if args.db:
        db_path = Path(args.db).expanduser()
    else:
        data_dir = Path(__import__("os").environ.get(
            "MULTIAGENT_DATA_DIR", str(Path.home() / ".multi-agent")
        ))
        db_path = data_dir / "multiagent.db"

    if not db_path.exists():
        print(f"[迁移] 数据库不存在：{db_path}", file=sys.stderr)
        return 1

    print(f"[迁移] 数据库：{db_path}（{'dry-run' if args.dry_run else '执行'}）")
    stats = migrate(db_path, dry_run=args.dry_run)
    print(f"[迁移] 完成：处理项目 {stats['projects_processed']} 个，"
          f"新增条目 {stats['inserted']}，跳过重复 {stats['skipped']}，"
          f"丢弃空条目 {stats['dropped']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
