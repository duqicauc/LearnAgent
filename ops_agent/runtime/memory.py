"""长期记忆管理：本地 sqlite 存储，按 user_id 隔离。

每条记忆字段：user_id、type（类型）、content（内容）、summary（总结）、
scope（适用范围）、confidence（可信度）、status（状态）、
valid_from/valid_until（有效时间）、version（版本）。

冲突版本化：同一主题（user_id + type + topic）下写入内容不同的新记忆时，
旧 active 记录标记为 superseded（过时），新记录版本号 = 旧最大版本 + 1。
内容完全相同则幂等返回现有记录，不刷版本。
"""
import json
import re
import sqlite3
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional


class MemoryStatus:
    ACTIVE = "active"       # 生效中
    SUPERSEDED = "superseded"  # 被新版本取代（过时）
    EXPIRED = "expired"     # 超过有效时间


CONFIDENCE_LEVELS = ("low", "medium", "high")


@dataclass
class MemoryRecord:
    """一条长期记忆。"""

    user_id: str
    content: str
    type: str = "fact"
    summary: str = ""
    scope: str = ""
    confidence: str = "medium"
    status: str = MemoryStatus.ACTIVE
    valid_from: Optional[str] = None
    valid_until: Optional[str] = None
    version: int = 1
    topic: str = "general"
    id: Optional[int] = None
    created_at: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "user_id": self.user_id,
            "type": self.type,
            "topic": self.topic,
            "content": self.content,
            "summary": self.summary,
            "scope": self.scope,
            "confidence": self.confidence,
            "status": self.status,
            "valid_from": self.valid_from,
            "valid_until": self.valid_until,
            "version": self.version,
            "created_at": self.created_at,
        }


class MemoryManager:
    """长期记忆管理器：sqlite 持久化，按 user_id 隔离，冲突自动版本化。"""

    def __init__(self, db_path: Path) -> None:
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    # ---- 建表 ----

    def _init_db(self) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS memories (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id TEXT NOT NULL,
                    type TEXT NOT NULL DEFAULT 'fact',
                    topic TEXT NOT NULL DEFAULT 'general',
                    content TEXT NOT NULL,
                    summary TEXT DEFAULT '',
                    scope TEXT DEFAULT '',
                    confidence TEXT DEFAULT 'medium',
                    status TEXT DEFAULT 'active',
                    valid_from TEXT,
                    valid_until TEXT,
                    version INTEGER DEFAULT 1,
                    created_at TEXT
                )
                """
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_user_status "
                "ON memories(user_id, status)"
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_group "
                "ON memories(user_id, type, topic)"
            )

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    @staticmethod
    def _now() -> str:
        return datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    # ---- 保存 ----

    def save(
        self,
        user_id: str,
        content: str,
        type: str = "fact",
        summary: str = "",
        scope: str = "",
        confidence: str = "medium",
        valid_until: Optional[str] = None,
        topic: str = "general",
    ) -> MemoryRecord:
        """保存一条长期记忆。

        冲突处理：同 (user_id, type, topic) 存在内容不同的 active 记忆时，
        先将其标记为 superseded（过时），再以新版本写入。
        内容与现有 active 记录完全相同 → 幂等返回，不产生新版本。
        """
        if not content or not content.strip():
            raise ValueError("记忆内容不能为空")
        if confidence not in CONFIDENCE_LEVELS:
            raise ValueError(
                f"confidence 必须是 {'/'.join(CONFIDENCE_LEVELS)}"
            )

        now = self._now()
        with self._connect() as conn:
            # 先惰性过期本用户记忆
            self._expire(user_id, conn)

            rows = conn.execute(
                "SELECT * FROM memories WHERE user_id=? AND type=? AND topic=?"
                " AND status=? ORDER BY version DESC",
                (user_id, type, topic, MemoryStatus.ACTIVE),
            ).fetchall()

            # 内容相同 → 幂等返回现有记录
            for row in rows:
                if row["content"] == content:
                    return self._row_to_record(row)

            # 冲突：同主题存在内容不同的 active 记录 → 全部标为过时
            if rows:
                ids = [row["id"] for row in rows]
                placeholders = ",".join("?" * len(ids))
                conn.execute(
                    f"UPDATE memories SET status=? WHERE id IN ({placeholders})",
                    (MemoryStatus.SUPERSEDED, *ids),
                )

            # 计算新版本号（同组历史最大版本 + 1）
            max_row = conn.execute(
                "SELECT MAX(version) AS v FROM memories "
                "WHERE user_id=? AND type=? AND topic=?",
                (user_id, type, topic),
            ).fetchone()
            version = (max_row["v"] or 0) + 1

            cursor = conn.execute(
                "INSERT INTO memories "
                "(user_id, type, topic, content, summary, scope, confidence,"
                " status, valid_from, valid_until, version, created_at) "
                "VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                (
                    user_id,
                    type,
                    topic,
                    content,
                    summary,
                    scope,
                    confidence,
                    MemoryStatus.ACTIVE,
                    now,
                    valid_until,
                    version,
                    now,
                ),
            )
            record = MemoryRecord(
                id=cursor.lastrowid,
                user_id=user_id,
                type=type,
                topic=topic,
                content=content,
                summary=summary,
                scope=scope,
                confidence=confidence,
                status=MemoryStatus.ACTIVE,
                valid_from=now,
                valid_until=valid_until,
                version=version,
                created_at=now,
            )
            return record

    # ---- 查询 ----

    def query(
        self,
        user_id: str,
        keyword: Optional[str] = None,
        type: Optional[str] = None,
        scope: Optional[str] = None,
        limit: int = 20,
    ) -> List[MemoryRecord]:
        """检索某用户当前生效（active 且未过期）的记忆。"""
        with self._connect() as conn:
            self._expire(user_id, conn)
            sql = (
                "SELECT * FROM memories WHERE user_id=? AND status=?"
            )
            params: List[Any] = [user_id, MemoryStatus.ACTIVE]

            if type:
                sql += " AND type=?"
                params.append(type)
            if scope:
                sql += " AND scope=?"
                params.append(scope)
            if keyword:
                sql += " AND (content LIKE ? OR summary LIKE ? OR topic LIKE ?)"
                like = f"%{keyword}%"
                params.extend([like, like, like])
            sql += " ORDER BY version DESC, id DESC LIMIT ?"
            params.append(limit)
            rows = conn.execute(sql, params).fetchall()
            return [self._row_to_record(r) for r in rows]

    def list_all(
        self, user_id: str, status: Optional[str] = None
    ) -> List[MemoryRecord]:
        """列出某用户全部记忆（含历史版本），可按状态过滤。"""
        with self._connect() as conn:
            self._expire(user_id, conn)
            if status:
                rows = conn.execute(
                    "SELECT * FROM memories WHERE user_id=? AND status=? "
                    "ORDER BY id DESC",
                    (user_id, status),
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT * FROM memories WHERE user_id=? ORDER BY id DESC",
                    (user_id,),
                ).fetchall()
            return [self._row_to_record(r) for r in rows]

    def get(self, user_id: str, memory_id: int) -> Optional[MemoryRecord]:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM memories WHERE user_id=? AND id=?",
                (user_id, memory_id),
            ).fetchone()
            return self._row_to_record(row) if row else None

    def invalidate(self, user_id: str, memory_id: int) -> bool:
        """手动将某条记忆标记为过时（superseded）。"""
        with self._connect() as conn:
            cursor = conn.execute(
                "UPDATE memories SET status=? WHERE user_id=? AND id=? "
                "AND status=?",
                (MemoryStatus.SUPERSEDED, user_id, memory_id,
                 MemoryStatus.ACTIVE),
            )
            return cursor.rowcount > 0

    # ---- 内部 ----

    def _expire(
        self, user_id: str, conn: sqlite3.Connection
    ) -> None:
        """惰性过期：将超过有效时间的 active 记忆标记为 expired。"""
        now = self._now()
        conn.execute(
            "UPDATE memories SET status=? WHERE user_id=? AND status=? "
            "AND valid_until IS NOT NULL AND valid_until < ?",
            (MemoryStatus.EXPIRED, user_id, MemoryStatus.ACTIVE, now),
        )

    @staticmethod
    def _row_to_record(row: sqlite3.Row) -> MemoryRecord:
        return MemoryRecord(
            id=row["id"],
            user_id=row["user_id"],
            type=row["type"],
            topic=row["topic"],
            content=row["content"],
            summary=row["summary"],
            scope=row["scope"],
            confidence=row["confidence"],
            status=row["status"],
            valid_from=row["valid_from"],
            valid_until=row["valid_until"],
            version=row["version"],
            created_at=row["created_at"],
        )

    def export(self, user_id: str) -> List[Dict[str, Any]]:
        """导出某用户全部记忆（供审计/备份）。"""
        return [r.to_dict() for r in self.list_all(user_id)]

    # 预留：未来可接入 embedding 做语义检索
    @staticmethod
    def _tokenize(text: str) -> List[str]:
        words = re.findall(r"[A-Za-z_]{2,}", text.lower())
        return words
