from __future__ import annotations

import sqlite3
import threading
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass(frozen=True)
class StoredInsight:
    insight_id: str
    session_id: str
    speaker: str
    insight: str
    created_at: str


@dataclass(frozen=True)
class StoredTurn:
    session_id: str
    speaker: str
    content: str
    created_at: str
    request_id: str | None
    model: str | None


class ConversationStore:
    def __init__(self, *, db_path: str) -> None:
        self._db_path = Path(db_path).expanduser().resolve()
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._conn = sqlite3.connect(str(self._db_path), check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        with self._lock:
            self._conn.execute("PRAGMA journal_mode=WAL;")
            self._conn.execute("PRAGMA synchronous=NORMAL;")
            self._create_schema()

    def _create_schema(self) -> None:
        self._conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS chat_sessions (
                session_id TEXT PRIMARY KEY,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                model TEXT NOT NULL,
                system_prompt TEXT
            );

            CREATE TABLE IF NOT EXISTS chat_turns (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id TEXT NOT NULL,
                speaker TEXT NOT NULL,
                content TEXT NOT NULL,
                created_at TEXT NOT NULL,
                request_id TEXT,
                model TEXT,
                FOREIGN KEY(session_id) REFERENCES chat_sessions(session_id)
            );

            CREATE TABLE IF NOT EXISTS chat_insights (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                insight_id TEXT UNIQUE NOT NULL,
                session_id TEXT NOT NULL,
                speaker TEXT NOT NULL,
                insight TEXT NOT NULL,
                created_at TEXT NOT NULL,
                FOREIGN KEY(session_id) REFERENCES chat_sessions(session_id)
            );

            CREATE INDEX IF NOT EXISTS idx_turns_session_created
                ON chat_turns(session_id, created_at);
            CREATE INDEX IF NOT EXISTS idx_insights_session_created
                ON chat_insights(session_id, created_at);
            """
        )
        self._conn.commit()

    def upsert_session(
        self,
        *,
        session_id: str,
        model: str,
        system_prompt: str | None,
    ) -> None:
        now = _utc_now()
        with self._lock:
            self._conn.execute(
                """
                INSERT INTO chat_sessions(session_id, created_at, updated_at, model, system_prompt)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(session_id) DO UPDATE SET
                    updated_at = excluded.updated_at,
                    model = excluded.model,
                    system_prompt = excluded.system_prompt
                """,
                (session_id, now, now, model, system_prompt),
            )
            self._conn.commit()

    def append_turn(
        self,
        *,
        session_id: str,
        speaker: str,
        content: str,
        request_id: str | None,
        model: str | None,
    ) -> int:
        if speaker not in {"me", "you", "system"}:
            raise ValueError(f"Unsupported speaker: {speaker}")
        now = _utc_now()
        with self._lock:
            cursor = self._conn.execute(
                """
                INSERT INTO chat_turns(session_id, speaker, content, created_at, request_id, model)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (session_id, speaker, content, now, request_id, model),
            )
            self._conn.execute(
                "UPDATE chat_sessions SET updated_at = ? WHERE session_id = ?",
                (now, session_id),
            )
            self._conn.commit()
            return int(cursor.lastrowid)

    def add_insight(
        self,
        *,
        session_id: str,
        speaker: str,
        insight: str,
        insight_id: str | None = None,
    ) -> StoredInsight:
        if speaker not in {"me", "you"}:
            raise ValueError(f"Unsupported speaker: {speaker}")
        normalized = insight.strip()
        if not normalized:
            raise ValueError("Insight cannot be empty")
        created_at = _utc_now()
        use_id = insight_id or str(uuid.uuid4())
        with self._lock:
            self._conn.execute(
                """
                INSERT OR IGNORE INTO chat_insights(insight_id, session_id, speaker, insight, created_at)
                VALUES (?, ?, ?, ?, ?)
                """,
                (use_id, session_id, speaker, normalized, created_at),
            )
            self._conn.commit()
        return StoredInsight(
            insight_id=use_id,
            session_id=session_id,
            speaker=speaker,
            insight=normalized,
            created_at=created_at,
        )

    def list_turns(self, *, session_id: str, limit: int = 100) -> list[dict[str, str]]:
        use_limit = max(1, min(limit, 1000))
        with self._lock:
            rows = self._conn.execute(
                """
                SELECT speaker, content, created_at, request_id, model
                FROM chat_turns
                WHERE session_id = ?
                ORDER BY id ASC
                LIMIT ?
                """,
                (session_id, use_limit),
            ).fetchall()
        return [dict(row) for row in rows]

    def search_insights_by_terms(
        self,
        *,
        terms: list[str],
        limit: int = 20,
    ) -> list[StoredInsight]:
        normalized_terms = [
            term.strip().lower()
            for term in terms
            if isinstance(term, str) and len(term.strip()) >= 2
        ]
        if not normalized_terms:
            return []
        use_limit = max(1, min(limit, 200))
        clauses = " OR ".join(["lower(insight) LIKE ?"] * len(normalized_terms))
        params = [f"%{term}%" for term in normalized_terms]
        params.append(use_limit)

        with self._lock:
            rows = self._conn.execute(
                f"""
                SELECT insight_id, session_id, speaker, insight, created_at
                FROM chat_insights
                WHERE {clauses}
                ORDER BY created_at DESC
                LIMIT ?
                """,
                params,
            ).fetchall()
        return [
            StoredInsight(
                insight_id=str(row["insight_id"]),
                session_id=str(row["session_id"]),
                speaker=str(row["speaker"]),
                insight=str(row["insight"]),
                created_at=str(row["created_at"]),
            )
            for row in rows
        ]

    def search_turns_by_terms(
        self,
        *,
        terms: list[str],
        limit: int = 20,
    ) -> list[StoredTurn]:
        normalized_terms = [
            term.strip().lower()
            for term in terms
            if isinstance(term, str) and len(term.strip()) >= 2
        ]
        if not normalized_terms:
            return []
        use_limit = max(1, min(limit, 200))
        clauses = " OR ".join(["lower(content) LIKE ?"] * len(normalized_terms))
        params = [f"%{term}%" for term in normalized_terms]
        params.append(use_limit)
        with self._lock:
            rows = self._conn.execute(
                f"""
                SELECT session_id, speaker, content, created_at, request_id, model
                FROM chat_turns
                WHERE speaker IN ('me', 'you') AND ({clauses})
                ORDER BY created_at DESC
                LIMIT ?
                """,
                params,
            ).fetchall()
        return [
            StoredTurn(
                session_id=str(row["session_id"]),
                speaker=str(row["speaker"]),
                content=str(row["content"]),
                created_at=str(row["created_at"]),
                request_id=str(row["request_id"]) if row["request_id"] else None,
                model=str(row["model"]) if row["model"] else None,
            )
            for row in rows
        ]

    def close(self) -> None:
        with self._lock:
            self._conn.close()

    def __del__(self) -> None:  # pragma: no cover - best effort resource cleanup
        try:
            self.close()
        except Exception:
            return
