from __future__ import annotations

import sqlite3
import threading
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass(frozen=True)
class StoredInsight:
    insight_id: str
    session_id: str
    actor_id: str
    speaker: str
    insight: str
    created_at: str
    pii_flag: bool
    allow_cross_user: bool
    source_type: str
    quote_text: str | None


@dataclass(frozen=True)
class StoredTurn:
    turn_id: int
    session_id: str
    actor_id: str
    speaker: str
    content: str
    created_at: str
    request_id: str | None
    model: str | None
    pii_flag: bool
    allow_cross_user: bool


@dataclass(frozen=True)
class StoredGroundedEvidence:
    evidence_id: str
    source_type: str
    actor_scope: str
    pii_flag: bool
    label: str
    content: str
    url: str | None
    source_session: str | None
    created_at: str
    confidence: float


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

    def _column_exists(self, table: str, column: str) -> bool:
        rows = self._conn.execute(f"PRAGMA table_info({table})").fetchall()
        return any(str(row["name"]) == column for row in rows)

    def _ensure_column(self, table: str, column: str, ddl_fragment: str) -> None:
        if self._column_exists(table, column):
            return
        self._conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {ddl_fragment}")

    def _create_schema(self) -> None:
        self._conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS chat_sessions (
                session_id TEXT PRIMARY KEY,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                model TEXT NOT NULL,
                system_prompt TEXT,
                actor_id TEXT NOT NULL DEFAULT 'anonymous'
            );

            CREATE TABLE IF NOT EXISTS chat_turns (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id TEXT NOT NULL,
                actor_id TEXT NOT NULL DEFAULT 'anonymous',
                speaker TEXT NOT NULL,
                content TEXT NOT NULL,
                created_at TEXT NOT NULL,
                request_id TEXT,
                model TEXT,
                pii_flag INTEGER NOT NULL DEFAULT 0,
                allow_cross_user INTEGER NOT NULL DEFAULT 1,
                FOREIGN KEY(session_id) REFERENCES chat_sessions(session_id)
            );

            CREATE TABLE IF NOT EXISTS chat_insights (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                insight_id TEXT UNIQUE NOT NULL,
                session_id TEXT NOT NULL,
                actor_id TEXT NOT NULL DEFAULT 'anonymous',
                speaker TEXT NOT NULL,
                insight TEXT NOT NULL,
                created_at TEXT NOT NULL,
                pii_flag INTEGER NOT NULL DEFAULT 0,
                allow_cross_user INTEGER NOT NULL DEFAULT 1,
                source_type TEXT NOT NULL DEFAULT 'insight',
                quote_text TEXT,
                FOREIGN KEY(session_id) REFERENCES chat_sessions(session_id)
            );

            CREATE TABLE IF NOT EXISTS grounded_runs (
                run_id TEXT PRIMARY KEY,
                session_id TEXT NOT NULL,
                actor_id TEXT NOT NULL,
                mode TEXT NOT NULL,
                profile TEXT NOT NULL,
                prompt TEXT NOT NULL,
                started_at TEXT NOT NULL,
                completed_at TEXT,
                status TEXT NOT NULL,
                note TEXT
            );

            CREATE TABLE IF NOT EXISTS grounded_claims (
                claim_id TEXT PRIMARY KEY,
                run_id TEXT NOT NULL,
                claim_text TEXT NOT NULL,
                is_exact_required INTEGER NOT NULL,
                support_status TEXT NOT NULL,
                confidence REAL NOT NULL,
                FOREIGN KEY(run_id) REFERENCES grounded_runs(run_id)
            );

            CREATE TABLE IF NOT EXISTS grounded_evidence (
                evidence_id TEXT PRIMARY KEY,
                run_id TEXT NOT NULL,
                source_type TEXT NOT NULL,
                actor_scope TEXT NOT NULL,
                pii_flag INTEGER NOT NULL DEFAULT 0,
                label TEXT NOT NULL,
                content TEXT NOT NULL,
                url TEXT,
                source_session TEXT,
                created_at TEXT NOT NULL,
                confidence REAL NOT NULL,
                FOREIGN KEY(run_id) REFERENCES grounded_runs(run_id)
            );

            CREATE TABLE IF NOT EXISTS grounded_evidence_links (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                claim_id TEXT NOT NULL,
                evidence_id TEXT NOT NULL,
                support_score REAL NOT NULL,
                used_verbatim INTEGER NOT NULL DEFAULT 0,
                FOREIGN KEY(claim_id) REFERENCES grounded_claims(claim_id),
                FOREIGN KEY(evidence_id) REFERENCES grounded_evidence(evidence_id)
            );

            CREATE INDEX IF NOT EXISTS idx_turns_session_created
                ON chat_turns(session_id, created_at);
            CREATE INDEX IF NOT EXISTS idx_insights_session_created
                ON chat_insights(session_id, created_at);
            CREATE INDEX IF NOT EXISTS idx_runs_session_started
                ON grounded_runs(session_id, started_at);
            CREATE INDEX IF NOT EXISTS idx_claims_run
                ON grounded_claims(run_id);
            CREATE INDEX IF NOT EXISTS idx_evidence_run
                ON grounded_evidence(run_id);
            CREATE INDEX IF NOT EXISTS idx_links_claim
                ON grounded_evidence_links(claim_id);
            """
        )

        # Lightweight migration support for older local DB files.
        self._ensure_column("chat_sessions", "actor_id", "TEXT NOT NULL DEFAULT 'anonymous'")
        self._ensure_column("chat_turns", "actor_id", "TEXT NOT NULL DEFAULT 'anonymous'")
        self._ensure_column("chat_turns", "pii_flag", "INTEGER NOT NULL DEFAULT 0")
        self._ensure_column("chat_turns", "allow_cross_user", "INTEGER NOT NULL DEFAULT 1")
        self._ensure_column("chat_insights", "actor_id", "TEXT NOT NULL DEFAULT 'anonymous'")
        self._ensure_column("chat_insights", "pii_flag", "INTEGER NOT NULL DEFAULT 0")
        self._ensure_column("chat_insights", "allow_cross_user", "INTEGER NOT NULL DEFAULT 1")
        self._ensure_column("chat_insights", "source_type", "TEXT NOT NULL DEFAULT 'insight'")
        self._ensure_column("chat_insights", "quote_text", "TEXT")
        self._conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_turns_actor_created ON chat_turns(actor_id, created_at)"
        )
        self._conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_insights_actor_created ON chat_insights(actor_id, created_at)"
        )

        self._conn.commit()

    def upsert_session(
        self,
        *,
        session_id: str,
        model: str,
        system_prompt: str | None,
        actor_id: str = "anonymous",
    ) -> None:
        now = _utc_now()
        use_actor = (actor_id or "anonymous").strip() or "anonymous"
        with self._lock:
            self._conn.execute(
                """
                INSERT INTO chat_sessions(session_id, created_at, updated_at, model, system_prompt, actor_id)
                VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(session_id) DO UPDATE SET
                    updated_at = excluded.updated_at,
                    model = excluded.model,
                    system_prompt = excluded.system_prompt,
                    actor_id = excluded.actor_id
                """,
                (session_id, now, now, model, system_prompt, use_actor),
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
        actor_id: str = "anonymous",
        pii_flag: bool = False,
        allow_cross_user: bool = True,
    ) -> int:
        if speaker not in {"me", "you", "system"}:
            raise ValueError(f"Unsupported speaker: {speaker}")
        now = _utc_now()
        use_actor = (actor_id or "anonymous").strip() or "anonymous"
        with self._lock:
            cursor = self._conn.execute(
                """
                INSERT INTO chat_turns(
                    session_id, actor_id, speaker, content, created_at, request_id, model, pii_flag, allow_cross_user
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    session_id,
                    use_actor,
                    speaker,
                    content,
                    now,
                    request_id,
                    model,
                    int(bool(pii_flag)),
                    int(bool(allow_cross_user)),
                ),
            )
            self._conn.execute(
                "UPDATE chat_sessions SET updated_at = ?, actor_id = ? WHERE session_id = ?",
                (now, use_actor, session_id),
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
        actor_id: str = "anonymous",
        pii_flag: bool = False,
        allow_cross_user: bool = True,
        source_type: str = "insight",
        quote_text: str | None = None,
    ) -> StoredInsight:
        if speaker not in {"me", "you"}:
            raise ValueError(f"Unsupported speaker: {speaker}")
        normalized = insight.strip()
        if not normalized:
            raise ValueError("Insight cannot be empty")
        created_at = _utc_now()
        use_id = insight_id or str(uuid.uuid4())
        use_actor = (actor_id or "anonymous").strip() or "anonymous"
        with self._lock:
            self._conn.execute(
                """
                INSERT OR IGNORE INTO chat_insights(
                    insight_id, session_id, actor_id, speaker, insight, created_at,
                    pii_flag, allow_cross_user, source_type, quote_text
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    use_id,
                    session_id,
                    use_actor,
                    speaker,
                    normalized,
                    created_at,
                    int(bool(pii_flag)),
                    int(bool(allow_cross_user)),
                    source_type,
                    quote_text,
                ),
            )
            self._conn.commit()
        return StoredInsight(
            insight_id=use_id,
            session_id=session_id,
            actor_id=use_actor,
            speaker=speaker,
            insight=normalized,
            created_at=created_at,
            pii_flag=bool(pii_flag),
            allow_cross_user=bool(allow_cross_user),
            source_type=source_type,
            quote_text=quote_text,
        )

    def list_turns(self, *, session_id: str, limit: int = 100) -> list[dict[str, Any]]:
        use_limit = max(1, min(limit, 1000))
        with self._lock:
            rows = self._conn.execute(
                """
                SELECT id, speaker, content, created_at, request_id, model, actor_id, pii_flag, allow_cross_user
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
        actor_id: str,
        current_session_id: str,
        include_shared: bool = True,
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
        params: list[Any] = [f"%{term}%" for term in normalized_terms]
        params.extend([current_session_id, actor_id])

        if include_shared:
            visibility_clause = "(session_id = ? OR actor_id = ? OR (allow_cross_user = 1 AND pii_flag = 0))"
        else:
            visibility_clause = "(session_id = ? OR actor_id = ?)"

        params.append(use_limit)
        with self._lock:
            rows = self._conn.execute(
                f"""
                SELECT insight_id, session_id, actor_id, speaker, insight, created_at,
                       pii_flag, allow_cross_user, source_type, quote_text
                FROM chat_insights
                WHERE ({clauses}) AND {visibility_clause}
                ORDER BY created_at DESC
                LIMIT ?
                """,
                params,
            ).fetchall()

        return [
            StoredInsight(
                insight_id=str(row["insight_id"]),
                session_id=str(row["session_id"]),
                actor_id=str(row["actor_id"]),
                speaker=str(row["speaker"]),
                insight=str(row["insight"]),
                created_at=str(row["created_at"]),
                pii_flag=bool(row["pii_flag"]),
                allow_cross_user=bool(row["allow_cross_user"]),
                source_type=str(row["source_type"]),
                quote_text=str(row["quote_text"]) if row["quote_text"] else None,
            )
            for row in rows
        ]

    def search_turns_by_terms(
        self,
        *,
        terms: list[str],
        actor_id: str,
        current_session_id: str,
        include_shared: bool = True,
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
        params: list[Any] = [f"%{term}%" for term in normalized_terms]
        params.extend([current_session_id, actor_id])

        if include_shared:
            visibility_clause = "(session_id = ? OR actor_id = ? OR (allow_cross_user = 1 AND pii_flag = 0))"
        else:
            visibility_clause = "(session_id = ? OR actor_id = ?)"

        params.append(use_limit)
        with self._lock:
            rows = self._conn.execute(
                f"""
                SELECT id, session_id, actor_id, speaker, content, created_at, request_id, model,
                       pii_flag, allow_cross_user
                FROM chat_turns
                WHERE speaker IN ('me', 'you')
                  AND ({clauses})
                  AND {visibility_clause}
                ORDER BY created_at DESC
                LIMIT ?
                """,
                params,
            ).fetchall()

        return [
            StoredTurn(
                turn_id=int(row["id"]),
                session_id=str(row["session_id"]),
                actor_id=str(row["actor_id"]),
                speaker=str(row["speaker"]),
                content=str(row["content"]),
                created_at=str(row["created_at"]),
                request_id=str(row["request_id"]) if row["request_id"] else None,
                model=str(row["model"]) if row["model"] else None,
                pii_flag=bool(row["pii_flag"]),
                allow_cross_user=bool(row["allow_cross_user"]),
            )
            for row in rows
        ]

    def start_grounded_run(
        self,
        *,
        run_id: str,
        session_id: str,
        actor_id: str,
        mode: str,
        profile: str,
        prompt: str,
    ) -> None:
        with self._lock:
            self._conn.execute(
                """
                INSERT OR REPLACE INTO grounded_runs(
                    run_id, session_id, actor_id, mode, profile, prompt, started_at, completed_at, status, note
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, NULL, 'running', NULL)
                """,
                (run_id, session_id, actor_id, mode, profile, prompt, _utc_now()),
            )
            self._conn.commit()

    def finish_grounded_run(
        self,
        *,
        run_id: str,
        status: str,
        note: str | None,
    ) -> None:
        with self._lock:
            self._conn.execute(
                """
                UPDATE grounded_runs
                SET completed_at = ?, status = ?, note = ?
                WHERE run_id = ?
                """,
                (_utc_now(), status, note, run_id),
            )
            self._conn.commit()

    def add_grounded_claim(
        self,
        *,
        claim_id: str,
        run_id: str,
        claim_text: str,
        is_exact_required: bool,
        support_status: str,
        confidence: float,
    ) -> None:
        with self._lock:
            self._conn.execute(
                """
                INSERT OR REPLACE INTO grounded_claims(
                    claim_id, run_id, claim_text, is_exact_required, support_status, confidence
                )
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    claim_id,
                    run_id,
                    claim_text,
                    int(bool(is_exact_required)),
                    support_status,
                    float(confidence),
                ),
            )
            self._conn.commit()

    def add_grounded_evidence(
        self,
        *,
        evidence_id: str,
        run_id: str,
        source_type: str,
        actor_scope: str,
        pii_flag: bool,
        label: str,
        content: str,
        url: str | None,
        source_session: str | None,
        confidence: float,
    ) -> None:
        with self._lock:
            self._conn.execute(
                """
                INSERT OR REPLACE INTO grounded_evidence(
                    evidence_id, run_id, source_type, actor_scope, pii_flag,
                    label, content, url, source_session, created_at, confidence
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    evidence_id,
                    run_id,
                    source_type,
                    actor_scope,
                    int(bool(pii_flag)),
                    label,
                    content,
                    url,
                    source_session,
                    _utc_now(),
                    float(confidence),
                ),
            )
            self._conn.commit()

    def link_claim_evidence(
        self,
        *,
        claim_id: str,
        evidence_id: str,
        support_score: float,
        used_verbatim: bool,
    ) -> None:
        with self._lock:
            self._conn.execute(
                """
                INSERT INTO grounded_evidence_links(claim_id, evidence_id, support_score, used_verbatim)
                VALUES (?, ?, ?, ?)
                """,
                (claim_id, evidence_id, float(support_score), int(bool(used_verbatim))),
            )
            self._conn.commit()

    def list_grounded_evidence(self, *, run_id: str, limit: int = 100) -> list[StoredGroundedEvidence]:
        use_limit = max(1, min(limit, 500))
        with self._lock:
            rows = self._conn.execute(
                """
                SELECT evidence_id, source_type, actor_scope, pii_flag, label, content,
                       url, source_session, created_at, confidence
                FROM grounded_evidence
                WHERE run_id = ?
                ORDER BY confidence DESC, created_at DESC
                LIMIT ?
                """,
                (run_id, use_limit),
            ).fetchall()
        return [
            StoredGroundedEvidence(
                evidence_id=str(row["evidence_id"]),
                source_type=str(row["source_type"]),
                actor_scope=str(row["actor_scope"]),
                pii_flag=bool(row["pii_flag"]),
                label=str(row["label"]),
                content=str(row["content"]),
                url=str(row["url"]) if row["url"] else None,
                source_session=str(row["source_session"]) if row["source_session"] else None,
                created_at=str(row["created_at"]),
                confidence=float(row["confidence"]),
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
