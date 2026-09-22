from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime, timezone
from typing import Any, Iterator
from uuid import uuid4

import psycopg
from psycopg import Connection
from psycopg.rows import dict_row

from app.config import settings


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


class PostgresConversationStore:
    """PostgreSQL conversation persistence for multi-instance production."""

    def __init__(self, dsn: str | None = None) -> None:
        configured = dsn or settings.postgres_dsn.get_secret_value()
        if not configured:
            raise RuntimeError("POSTGRES_DSN is required for postgres conversation store")
        self.dsn = configured
        self.initialize()

    @contextmanager
    def connect(self) -> Iterator[Connection]:
        with psycopg.connect(
            self.dsn,
            connect_timeout=int(settings.postgres_connect_timeout_seconds),
            row_factory=dict_row,
        ) as connection:
            yield connection

    def ping(self) -> bool:
        try:
            with self.connect() as db:
                row = db.execute("SELECT 1 AS ok").fetchone()
                return bool(row and row["ok"] == 1)
        except Exception:
            return False

    def initialize(self) -> None:
        with self.connect() as db:
            db.execute(
                """
                CREATE TABLE IF NOT EXISTS conversations (
                    id TEXT PRIMARY KEY,
                    username TEXT NOT NULL,
                    title TEXT NOT NULL,
                    mode TEXT NOT NULL DEFAULT 'auto',
                    knowledge_base_id TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
                """
            )
            db.execute(
                """CREATE INDEX IF NOT EXISTS idx_conversations_user_updated
                   ON conversations(username, updated_at DESC)"""
            )
            db.execute(
                """
                CREATE TABLE IF NOT EXISTS messages (
                    id TEXT PRIMARY KEY,
                    conversation_id TEXT NOT NULL REFERENCES conversations(id) ON DELETE CASCADE,
                    role TEXT NOT NULL CHECK(role IN ('user', 'assistant')),
                    content TEXT NOT NULL,
                    status TEXT NOT NULL DEFAULT 'completed'
                        CHECK(status IN ('generating', 'completed', 'failed')),
                    trace_id TEXT,
                    latency_ms DOUBLE PRECISION,
                    created_at TEXT NOT NULL
                )
                """
            )
            db.execute(
                """CREATE INDEX IF NOT EXISTS idx_messages_conversation_created
                   ON messages(conversation_id, created_at ASC)"""
            )
            db.execute(
                """
                CREATE TABLE IF NOT EXISTS message_sources (
                    id BIGSERIAL PRIMARY KEY,
                    message_id TEXT NOT NULL REFERENCES messages(id) ON DELETE CASCADE,
                    citation_index INTEGER,
                    source_type TEXT NOT NULL DEFAULT 'enterprise',
                    title TEXT,
                    file_name TEXT,
                    page INTEGER,
                    content_preview TEXT NOT NULL DEFAULT '',
                    relevance_score DOUBLE PRECISION,
                    knowledge_base_id TEXT,
                    knowledge_base_name TEXT,
                    url TEXT,
                    domain TEXT
                )
                """
            )
            db.execute(
                """CREATE INDEX IF NOT EXISTS idx_sources_message
                   ON message_sources(message_id, citation_index ASC)"""
            )

    def create(
        self,
        *,
        username: str,
        title: str = "新会话",
        mode: str = "auto",
        knowledge_base_id: str | None = None,
    ) -> dict[str, Any]:
        conversation_id = str(uuid4())
        now = utc_now()
        with self.connect() as db:
            db.execute(
                """INSERT INTO conversations
                (id, username, title, mode, knowledge_base_id, created_at, updated_at)
                VALUES (%s, %s, %s, %s, %s, %s, %s)""",
                (conversation_id, username, title.strip() or "新会话", mode, knowledge_base_id, now, now),
            )
        return self.get(conversation_id, username=username)

    def owner(self, conversation_id: str) -> str | None:
        with self.connect() as db:
            row = db.execute(
                "SELECT username FROM conversations WHERE id = %s", (conversation_id,)
            ).fetchone()
        return str(row["username"]) if row else None

    def require_owner(self, conversation_id: str, username: str) -> None:
        owner = self.owner(conversation_id)
        if owner is None:
            raise KeyError("Conversation 不存在")
        if owner != username:
            raise PermissionError("无权访问该会话")

    def list(self, username: str, limit: int = 100) -> list[dict[str, Any]]:
        with self.connect() as db:
            rows = db.execute(
                """
                SELECT c.*,
                       COUNT(m.id) AS message_count,
                       (
                         SELECT content FROM messages lm
                         WHERE lm.conversation_id = c.id
                         ORDER BY lm.created_at DESC LIMIT 1
                       ) AS last_message_preview
                FROM conversations c
                LEFT JOIN messages m ON m.conversation_id = c.id
                WHERE c.username = %s
                GROUP BY c.id
                ORDER BY c.updated_at DESC
                LIMIT %s
                """,
                (username, max(1, min(limit, 200))),
            ).fetchall()
        return [dict(row) for row in rows]

    def get(self, conversation_id: str, *, username: str) -> dict[str, Any]:
        self.require_owner(conversation_id, username)
        with self.connect() as db:
            conversation = db.execute(
                "SELECT * FROM conversations WHERE id = %s", (conversation_id,)
            ).fetchone()
            if conversation is None:
                raise KeyError("Conversation 不存在")
            message_rows = db.execute(
                "SELECT * FROM messages WHERE conversation_id = %s ORDER BY created_at ASC",
                (conversation_id,),
            ).fetchall()
            messages: list[dict[str, Any]] = []
            for row in message_rows:
                message = dict(row)
                sources = db.execute(
                    """SELECT citation_index, source_type, title, file_name, page,
                              content_preview, relevance_score, knowledge_base_id,
                              knowledge_base_name, url, domain
                       FROM message_sources
                       WHERE message_id = %s
                       ORDER BY citation_index ASC, id ASC""",
                    (message["id"],),
                ).fetchall()
                message["sources"] = [dict(item) for item in sources]
                messages.append(message)
        return {**dict(conversation), "messages": messages}

    def update(
        self,
        conversation_id: str,
        *,
        username: str,
        title: str | None = None,
        mode: str | None = None,
        knowledge_base_id: str | None | object = ...,
    ) -> dict[str, Any]:
        self.require_owner(conversation_id, username)
        fields: list[str] = []
        values: list[Any] = []
        if title is not None:
            fields.append("title = %s")
            values.append(title.strip()[:80] or "新会话")
        if mode is not None:
            fields.append("mode = %s")
            values.append(mode)
        if knowledge_base_id is not ...:
            fields.append("knowledge_base_id = %s")
            values.append(knowledge_base_id)
        fields.append("updated_at = %s")
        values.append(utc_now())
        values.append(conversation_id)
        with self.connect() as db:
            db.execute(
                f"UPDATE conversations SET {', '.join(fields)} WHERE id = %s",
                values,
            )
        return self.get(conversation_id, username=username)

    def delete(self, conversation_id: str, *, username: str) -> None:
        self.require_owner(conversation_id, username)
        with self.connect() as db:
            db.execute("DELETE FROM conversations WHERE id = %s", (conversation_id,))

    @staticmethod
    def _insert_sources(
        db: Connection,
        message_id: str,
        sources: list[dict[str, Any]] | None,
    ) -> None:
        for source in sources or []:
            db.execute(
                """INSERT INTO message_sources
                (message_id, citation_index, source_type, title, file_name, page,
                 content_preview, relevance_score, knowledge_base_id,
                 knowledge_base_name, url, domain)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)""",
                (
                    message_id,
                    source.get("citation_index"),
                    source.get("source_type") or "enterprise",
                    source.get("title"),
                    source.get("file_name"),
                    source.get("page"),
                    source.get("content_preview") or "",
                    source.get("relevance_score"),
                    source.get("knowledge_base_id"),
                    source.get("knowledge_base_name"),
                    source.get("url"),
                    source.get("domain"),
                ),
            )

    def add_message(
        self,
        *,
        conversation_id: str,
        username: str,
        role: str,
        content: str,
        status: str = "completed",
        trace_id: str | None = None,
        latency_ms: float | None = None,
        sources: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        self.require_owner(conversation_id, username)
        message_id = str(uuid4())
        now = utc_now()
        with self.connect() as db:
            db.execute(
                """INSERT INTO messages
                (id, conversation_id, role, content, status, trace_id, latency_ms, created_at)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s)""",
                (message_id, conversation_id, role, content, status, trace_id, latency_ms, now),
            )
            self._insert_sources(db, message_id, sources)
            db.execute(
                "UPDATE conversations SET updated_at = %s WHERE id = %s",
                (now, conversation_id),
            )
        return self.get(conversation_id, username=username)["messages"][-1]

    def replace_message(
        self,
        *,
        conversation_id: str,
        message_id: str,
        username: str,
        content: str,
        status: str,
        trace_id: str | None = None,
        latency_ms: float | None = None,
        sources: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        self.require_owner(conversation_id, username)
        now = utc_now()
        with self.connect() as db:
            row = db.execute(
                "SELECT id FROM messages WHERE id = %s AND conversation_id = %s",
                (message_id, conversation_id),
            ).fetchone()
            if row is None:
                raise KeyError("Message 不存在")
            db.execute(
                """UPDATE messages
                   SET content = %s, status = %s, trace_id = %s, latency_ms = %s
                   WHERE id = %s AND conversation_id = %s""",
                (content, status, trace_id, latency_ms, message_id, conversation_id),
            )
            db.execute("DELETE FROM message_sources WHERE message_id = %s", (message_id,))
            self._insert_sources(db, message_id, sources)
            db.execute(
                "UPDATE conversations SET updated_at = %s WHERE id = %s",
                (now, conversation_id),
            )

        detail = self.get(conversation_id, username=username)
        for message in detail["messages"]:
            if message["id"] == message_id:
                return message
        raise KeyError("Message 不存在")

    def maybe_title_from_first_question(
        self, conversation_id: str, *, username: str, question: str
    ) -> None:
        self.require_owner(conversation_id, username)
        with self.connect() as db:
            row = db.execute(
                """SELECT title,
                          (SELECT COUNT(*) FROM messages WHERE conversation_id = %s) AS count
                   FROM conversations WHERE id = %s""",
                (conversation_id, conversation_id),
            ).fetchone()
            if row and row["title"] == "新会话" and int(row["count"] or 0) <= 1:
                normalized = " ".join(question.strip().split())
                title = normalized[:28] + ("…" if len(normalized) > 28 else "")
                db.execute(
                    "UPDATE conversations SET title = %s, updated_at = %s WHERE id = %s",
                    (title or "新会话", utc_now(), conversation_id),
                )
