from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
import sqlite3
from threading import RLock

from core.domain import (
    AssignmentAudioRecord,
    AssignmentRecord,
    IAssignmentAudioRepository,
    IAssignmentRepository,
)
from infrastructure.sqlite.text_utils import safe_ensure_column, sync_sqlite_sequence


class AssignmentSqliteStore(IAssignmentRepository, IAssignmentAudioRepository):
    def __init__(self, db_path: str | Path) -> None:
        self._db_path = Path(db_path).expanduser().resolve()
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = RLock()
        self._conn = sqlite3.connect(
            self._db_path,
            check_same_thread=False,
            isolation_level=None,
        )
        self._conn.row_factory = sqlite3.Row
        self._ensure_schema()

    @property
    def db_path(self) -> Path:
        return self._db_path

    def save_assignment(
        self,
        *,
        title: str,
        content_original: str,
        content_completed: str,
    ) -> AssignmentRecord:
        title_value = str(title or "").strip() or "Untitled Assignment"
        original_value = str(content_original or "")
        completed_value = str(content_completed or "")
        now_iso = datetime.now(timezone.utc).isoformat()
        with self._lock:
            cursor = self._conn.execute(
                """
                INSERT INTO assignments(
                    title,
                    content_original,
                    content_completed,
                    status,
                    lexicon_coverage_percent,
                    created_at,
                    updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (title_value, original_value, completed_value, "PENDING", 0.0, now_iso, now_iso),
            )
            assignment_id = int(cursor.lastrowid)
            row = self._conn.execute(
                """
                SELECT
                    id,
                    title,
                    content_original,
                    content_completed,
                    status,
                    lexicon_coverage_percent,
                    created_at,
                    updated_at
                FROM assignments
                WHERE id = ?
                LIMIT 1
                """,
                (assignment_id,),
            ).fetchone()
        if row is None:
            raise RuntimeError("Failed to persist assignment record.")
        return self._row_to_record(row)

    def list_assignments(self, *, limit: int = 50, offset: int = 0) -> list[AssignmentRecord]:
        resolved_limit = max(1, int(limit))
        resolved_offset = max(0, int(offset))
        with self._lock:
            rows = self._conn.execute(
                """
                SELECT
                    id,
                    title,
                    content_original,
                    content_completed,
                    status,
                    lexicon_coverage_percent,
                    created_at,
                    updated_at
                FROM assignments
                ORDER BY id DESC
                LIMIT ? OFFSET ?
                """,
                (resolved_limit, resolved_offset),
            ).fetchall()
        return [self._row_to_record(row) for row in rows]

    def get_assignment(self, *, assignment_id: int) -> AssignmentRecord | None:
        safe_assignment_id = int(assignment_id)
        if safe_assignment_id <= 0:
            return None
        with self._lock:
            row = self._conn.execute(
                """
                SELECT
                    id,
                    title,
                    content_original,
                    content_completed,
                    status,
                    lexicon_coverage_percent,
                    created_at,
                    updated_at
                FROM assignments
                WHERE id = ?
                LIMIT 1
                """,
                (safe_assignment_id,),
            ).fetchone()
        if row is None:
            return None
        return self._row_to_record(row)

    def update_assignment_content(
        self,
        *,
        assignment_id: int,
        title: str,
        content_original: str,
        content_completed: str,
    ) -> AssignmentRecord | None:
        safe_assignment_id = int(assignment_id)
        if safe_assignment_id <= 0:
            return None
        title_value = str(title or "").strip() or "Untitled Assignment"
        original_value = str(content_original or "")
        completed_value = str(content_completed or "")
        now_iso = datetime.now(timezone.utc).isoformat()
        with self._lock:
            cursor = self._conn.execute(
                """
                UPDATE assignments
                SET title = ?,
                    content_original = ?,
                    content_completed = ?,
                    updated_at = ?
                WHERE id = ?
                """,
                (title_value, original_value, completed_value, now_iso, safe_assignment_id),
            )
            if int(cursor.rowcount) <= 0:
                return None
            row = self._conn.execute(
                """
                SELECT
                    id,
                    title,
                    content_original,
                    content_completed,
                    status,
                    lexicon_coverage_percent,
                    created_at,
                    updated_at
                FROM assignments
                WHERE id = ?
                LIMIT 1
                """,
                (safe_assignment_id,),
            ).fetchone()
        if row is None:
            return None
        return self._row_to_record(row)

    def delete_assignment(self, *, assignment_id: int) -> bool:
        safe_assignment_id = int(assignment_id)
        if safe_assignment_id <= 0:
            return False
        with self._lock:
            cursor = self._conn.execute(
                """
                DELETE FROM assignments
                WHERE id = ?
                """,
                (safe_assignment_id,),
            )
            deleted = int(cursor.rowcount) > 0
            if deleted:
                self._sync_sqlite_sequence_locked(table_name="assignments")
            return deleted

    def update_assignment_status(
        self,
        *,
        assignment_id: int,
        status: str,
        lexicon_coverage_percent: float | None = None,
    ) -> AssignmentRecord | None:
        safe_assignment_id = int(assignment_id)
        if safe_assignment_id <= 0:
            return None
        status_value = str(status or "").strip().upper() or "PENDING"
        coverage_value = 0.0 if lexicon_coverage_percent is None else float(lexicon_coverage_percent)
        now_iso = datetime.now(timezone.utc).isoformat()
        with self._lock:
            self._conn.execute(
                """
                UPDATE assignments
                SET status = ?,
                    lexicon_coverage_percent = ?,
                    updated_at = ?
                WHERE id = ?
                """,
                (status_value, coverage_value, now_iso, safe_assignment_id),
            )
            row = self._conn.execute(
                """
                SELECT
                    id,
                    title,
                    content_original,
                    content_completed,
                    status,
                    lexicon_coverage_percent,
                    created_at,
                    updated_at
                FROM assignments
                WHERE id = ?
                LIMIT 1
                """,
                (safe_assignment_id,),
            ).fetchone()
        if row is None:
            return None
        return self._row_to_record(row)

    def get_assignment_coverage_stats(self) -> list[dict[str, object]]:
        with self._lock:
            rows = self._conn.execute(
                """
                SELECT title, lexicon_coverage_percent, created_at
                FROM assignments
                ORDER BY created_at DESC
                LIMIT 100
                """
            ).fetchall()
        return [
            {
                "title": str(row["title"] or ""),
                "coverage_pct": float(row["lexicon_coverage_percent"] or 0.0),
                "created_at": str(row["created_at"] or ""),
            }
            for row in rows
        ]

    def bulk_delete_assignments(self, *, ids: list[int]) -> tuple[list[int], list[int]]:
        safe_ids = [int(i) for i in ids if int(i) > 0]
        if not safe_ids:
            return [], []
        placeholders = ",".join("?" * len(safe_ids))
        with self._lock:
            existing_rows = self._conn.execute(
                f"SELECT id FROM assignments WHERE id IN ({placeholders})",
                safe_ids,
            ).fetchall()
            existing_set = {int(row["id"]) for row in existing_rows}
            if existing_set:
                self._conn.execute(
                    f"DELETE FROM assignments WHERE id IN ({placeholders})",
                    safe_ids,
                )
                self._sync_sqlite_sequence_locked(table_name="assignments")
        deleted = [i for i in safe_ids if i in existing_set]
        not_found = [i for i in safe_ids if i not in existing_set]
        return deleted, not_found

    def close(self) -> None:
        with self._lock:
            self._conn.close()

    def save_audio_record(
        self,
        *,
        assignment_id: int,
        audio_path: str,
        audio_format: str,
        voice: str,
        style_preset: str,
        duration_sec: float = 0.0,
        sample_rate: int = 0,
    ) -> AssignmentAudioRecord:
        safe_assignment_id = int(assignment_id)
        if safe_assignment_id <= 0:
            raise ValueError("Invalid assignment id.")
        now_iso = datetime.now(timezone.utc).isoformat()
        with self._lock:
            cursor = self._conn.execute(
                """
                INSERT INTO assignment_audio(
                    assignment_id,
                    audio_path,
                    audio_format,
                    voice,
                    style_preset,
                    duration_sec,
                    sample_rate,
                    created_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    safe_assignment_id,
                    str(audio_path or "").strip(),
                    str(audio_format or "").strip().lower() or "wav",
                    str(voice or "").strip() or "af_heart",
                    str(style_preset or "").strip() or "neutral",
                    max(0.0, float(duration_sec)),
                    max(0, int(sample_rate)),
                    now_iso,
                ),
            )
            record_id = int(cursor.lastrowid)
            row = self._conn.execute(
                """
                SELECT
                    id,
                    assignment_id,
                    audio_path,
                    audio_format,
                    voice,
                    style_preset,
                    duration_sec,
                    sample_rate,
                    created_at
                FROM assignment_audio
                WHERE id = ?
                LIMIT 1
                """,
                (record_id,),
            ).fetchone()
        if row is None:
            raise RuntimeError("Failed to persist assignment audio record.")
        return self._audio_row_to_record(row)

    def get_latest_audio_record(self, *, assignment_id: int) -> AssignmentAudioRecord | None:
        safe_assignment_id = int(assignment_id)
        if safe_assignment_id <= 0:
            return None
        with self._lock:
            row = self._conn.execute(
                """
                SELECT
                    id,
                    assignment_id,
                    audio_path,
                    audio_format,
                    voice,
                    style_preset,
                    duration_sec,
                    sample_rate,
                    created_at
                FROM assignment_audio
                WHERE assignment_id = ?
                ORDER BY id DESC
                LIMIT 1
                """,
                (safe_assignment_id,),
            ).fetchone()
        if row is None:
            return None
        return self._audio_row_to_record(row)

    def delete_audio_records_for_assignment(self, *, assignment_id: int) -> int:
        safe_id = int(assignment_id)
        if safe_id <= 0:
            return 0
        with self._lock:
            cursor = self._conn.execute(
                "DELETE FROM assignment_audio WHERE assignment_id = ?",
                (safe_id,),
            )
            self._conn.commit()
            return int(cursor.rowcount)

    def list_audio_records(
        self,
        *,
        assignment_id: int,
        limit: int = 20,
        offset: int = 0,
    ) -> list[AssignmentAudioRecord]:
        safe_assignment_id = int(assignment_id)
        if safe_assignment_id <= 0:
            return []
        resolved_limit = max(1, int(limit))
        resolved_offset = max(0, int(offset))
        with self._lock:
            rows = self._conn.execute(
                """
                SELECT
                    id,
                    assignment_id,
                    audio_path,
                    audio_format,
                    voice,
                    style_preset,
                    duration_sec,
                    sample_rate,
                    created_at
                FROM assignment_audio
                WHERE assignment_id = ?
                ORDER BY id DESC
                LIMIT ? OFFSET ?
                """,
                (safe_assignment_id, resolved_limit, resolved_offset),
            ).fetchall()
        return [self._audio_row_to_record(row) for row in rows]

    def _ensure_schema(self) -> None:
        with self._lock:
            self._conn.execute(
                """
                CREATE TABLE IF NOT EXISTS assignments (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    title TEXT NOT NULL,
                    content_original TEXT NOT NULL,
                    content_completed TEXT NOT NULL,
                    status TEXT NOT NULL DEFAULT 'PENDING',
                    lexicon_coverage_percent REAL NOT NULL DEFAULT 0.0,
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                )
                """
            )
            self._ensure_column("assignments", "status", "TEXT NOT NULL DEFAULT 'PENDING'")
            self._ensure_column(
                "assignments",
                "lexicon_coverage_percent",
                "REAL NOT NULL DEFAULT 0.0",
            )
            self._conn.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_assignments_created_at
                ON assignments(created_at DESC)
                """
            )
            self._conn.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_assignments_status
                ON assignments(status)
                """
            )
            self._conn.execute(
                """
                CREATE TABLE IF NOT EXISTS assignment_audio (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    assignment_id INTEGER NOT NULL,
                    audio_path TEXT NOT NULL,
                    audio_format TEXT NOT NULL DEFAULT 'wav',
                    voice TEXT NOT NULL DEFAULT 'af_heart',
                    style_preset TEXT NOT NULL DEFAULT 'neutral',
                    duration_sec REAL NOT NULL DEFAULT 0.0,
                    sample_rate INTEGER NOT NULL DEFAULT 0,
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                )
                """
            )
            self._ensure_column(
                "assignment_audio",
                "audio_format",
                "TEXT NOT NULL DEFAULT 'wav'",
            )
            self._ensure_column(
                "assignment_audio",
                "voice",
                "TEXT NOT NULL DEFAULT 'af_heart'",
            )
            self._ensure_column(
                "assignment_audio",
                "style_preset",
                "TEXT NOT NULL DEFAULT 'neutral'",
            )
            self._ensure_column(
                "assignment_audio",
                "duration_sec",
                "REAL NOT NULL DEFAULT 0.0",
            )
            self._ensure_column(
                "assignment_audio",
                "sample_rate",
                "INTEGER NOT NULL DEFAULT 0",
            )
            self._conn.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_assignment_audio_assignment_id_created
                ON assignment_audio(assignment_id, created_at DESC)
                """
            )

    def _ensure_column(self, table_name: str, column_name: str, column_def: str) -> None:
        safe_ensure_column(
            self._conn,
            table_name=table_name,
            column_name=column_name,
            column_def=column_def,
        )

    def _sync_sqlite_sequence_locked(self, *, table_name: str) -> None:
        sync_sqlite_sequence(self._conn, table_name=table_name)

    def _row_to_record(self, row: sqlite3.Row) -> AssignmentRecord:
        return AssignmentRecord(
            id=int(row["id"]),
            title=str(row["title"] or ""),
            content_original=str(row["content_original"] or ""),
            content_completed=str(row["content_completed"] or ""),
            status=str(row["status"] or "PENDING"),
            lexicon_coverage_percent=float(row["lexicon_coverage_percent"] or 0.0),
            created_at=str(row["created_at"] or ""),
            updated_at=str(row["updated_at"] or ""),
        )

    def _audio_row_to_record(self, row: sqlite3.Row) -> AssignmentAudioRecord:
        return AssignmentAudioRecord(
            id=int(row["id"]),
            assignment_id=int(row["assignment_id"]),
            audio_path=str(row["audio_path"] or ""),
            audio_format=str(row["audio_format"] or "wav"),
            voice=str(row["voice"] or "af_heart"),
            style_preset=str(row["style_preset"] or "neutral"),
            duration_sec=float(row["duration_sec"] or 0.0),
            sample_rate=int(row["sample_rate"] or 0),
            created_at=str(row["created_at"] or ""),
        )
