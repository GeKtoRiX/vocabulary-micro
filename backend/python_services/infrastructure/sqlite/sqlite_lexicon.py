from __future__ import annotations

from collections import OrderedDict
from array import array
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
import logging
import sqlite3
from threading import RLock
import time
from typing import Dict, List, Optional, Sequence

from infrastructure.config import PipelineSettings

from .index_provider import LexiconIndexProvider
from .lexicon_engine import LexiconEngine
from .mwe_index_provider import MweIndexProvider
from .mwe_second_pass_engine import MweSecondPassEngine
from .table_models import LexiconEntry
from .text_utils import normalize_whitespace, safe_ensure_column

logger = logging.getLogger(__name__)


class SqliteLexicon(LexiconEngine):
    def __init__(
        self,
        db_path: str | Path,
        language: str = "en",
        bert_model_name: str | None = None,
        bert_threshold: float = LexiconEngine.DEFAULT_BERT_THRESHOLD,
        settings: PipelineSettings | None = None,
    ) -> None:
        super().__init__(
            language=language,
            bert_model_name=bert_model_name,
            bert_threshold=bert_threshold,
            settings=settings,
        )
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = RLock()
        self._conn = sqlite3.connect(
            self.db_path,
            check_same_thread=False,
            isolation_level=None,
        )
        self._conn.row_factory = sqlite3.Row
        self._configure_connection()
        self._ensure_schema()
        self._index_provider = LexiconIndexProvider(
            entry_loader=self.iter_entries,
            version_loader=self.get_lexicon_version,
            rebuild_debounce_seconds=self.settings.index_rebuild_debounce_seconds,
        )
        self.bind_index_provider(self._index_provider)
        self._mwe_index_provider = MweIndexProvider(
            version_loader=self.get_mwe_version,
            expression_loader=self.load_mwe_expressions,
            sense_loader=self.load_mwe_senses,
            embedding_loader=self.load_mwe_sense_embeddings,
        )
        self._mwe_second_pass_engine = MweSecondPassEngine(
            settings=self.settings,
            index_provider=self._mwe_index_provider,
        )
        self._request_doc_cache: OrderedDict[str, tuple[str, object]] = OrderedDict()
        self._request_doc_cache_limit = 32

    def _configure_connection(self) -> None:
        with self._lock:
            self._execute_with_retry(f"PRAGMA busy_timeout = {self.settings.sqlite_busy_timeout_ms};")
            self._execute_with_retry("PRAGMA foreign_keys = ON;")
            self._execute_with_retry("PRAGMA synchronous = NORMAL;")
            if self.settings.sqlite_wal_enabled:
                self._execute_with_retry("PRAGMA journal_mode = WAL;")

    def _execute_with_retry(self, sql: str, params: Sequence[object] = ()) -> sqlite3.Cursor:
        deadline = time.monotonic() + max(0.05, self.settings.sqlite_busy_timeout_ms / 1000.0)
        while True:
            try:
                return self._conn.execute(sql, params)
            except sqlite3.OperationalError as exc:
                logger.error(
                    "sqlite_execute_with_retry_operational_error sql=%s",
                    sql,
                    exc_info=True,
                )
                if "locked" not in str(exc).lower() or time.monotonic() >= deadline:
                    raise
                time.sleep(0.01)

    def _ensure_schema(self) -> None:
        with self._write_transaction():
            self._conn.execute(
                """
                CREATE TABLE IF NOT EXISTS lexicon_entries (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    category TEXT NOT NULL,
                    value TEXT NOT NULL,
                    normalized TEXT NOT NULL,
                    source TEXT NOT NULL DEFAULT 'manual',
                    confidence REAL,
                    first_seen_at TEXT,
                    request_id TEXT,
                    example_usage TEXT,
                    status TEXT NOT NULL DEFAULT 'approved',
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    UNIQUE(category, normalized)
                );
                """
            )
            self._ensure_column("lexicon_entries", "source", "TEXT NOT NULL DEFAULT 'manual'")
            self._ensure_column("lexicon_entries", "confidence", "REAL")
            self._ensure_column("lexicon_entries", "first_seen_at", "TEXT")
            self._ensure_column("lexicon_entries", "request_id", "TEXT")
            self._ensure_column("lexicon_entries", "example_usage", "TEXT")
            self._ensure_column("lexicon_entries", "status", "TEXT NOT NULL DEFAULT 'approved'")
            self._ensure_column("lexicon_entries", "reviewed_at", "TEXT")
            self._ensure_column("lexicon_entries", "reviewed_by", "TEXT")
            self._ensure_column("lexicon_entries", "review_note", "TEXT")
            self._ensure_column(
                "lexicon_entries",
                "created_at",
                "TEXT",
            )

            self._conn.execute(
                """
                CREATE TABLE IF NOT EXISTS lexicon_meta (
                    id INTEGER PRIMARY KEY CHECK (id = 1),
                    lexicon_version INTEGER NOT NULL DEFAULT 0,
                    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                );
                """
            )
            self._conn.execute(
                """
                INSERT OR IGNORE INTO lexicon_meta(id, lexicon_version, updated_at)
                VALUES (1, 0, CURRENT_TIMESTAMP);
                """
            )
            self._conn.execute(
                """
                CREATE TABLE IF NOT EXISTS lexicon_categories (
                    name TEXT PRIMARY KEY,
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                );
                """
            )
            self._conn.execute(
                """
                INSERT OR IGNORE INTO lexicon_categories(name)
                SELECT DISTINCT category
                FROM lexicon_entries
                WHERE TRIM(category) <> ''
                """
            )
            self._conn.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_lexicon_entries_category
                ON lexicon_entries(category);
                """
            )
            self._conn.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_lexicon_entries_normalized
                ON lexicon_entries(normalized);
                """
            )
            self._conn.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_lexicon_entries_status
                ON lexicon_entries(status);
                """
            )
            self._conn.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_lexicon_entries_confidence
                ON lexicon_entries(confidence);
                """
            )
            self._conn.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_lexicon_entries_status_category_confidence
                ON lexicon_entries(status, category COLLATE NOCASE, confidence);
                """
            )
            self._conn.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_lexicon_entries_status_source_category_id_desc
                ON lexicon_entries(status, source, category COLLATE NOCASE, id DESC);
                """
            )
            self._conn.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_lexicon_entries_status_category_id_desc
                ON lexicon_entries(status, category COLLATE NOCASE, id DESC);
                """
            )
            self._conn.execute(
                """
                CREATE TRIGGER IF NOT EXISTS trg_lexicon_entries_insert
                AFTER INSERT ON lexicon_entries
                BEGIN
                    UPDATE lexicon_meta
                    SET lexicon_version = lexicon_version + 1,
                        updated_at = CURRENT_TIMESTAMP
                    WHERE id = 1;
                END;
                """
            )
            self._conn.execute(
                """
                CREATE TRIGGER IF NOT EXISTS trg_lexicon_entries_update
                AFTER UPDATE ON lexicon_entries
                BEGIN
                    UPDATE lexicon_meta
                    SET lexicon_version = lexicon_version + 1,
                        updated_at = CURRENT_TIMESTAMP
                    WHERE id = 1;
                END;
                """
            )
            self._conn.execute(
                """
                CREATE TRIGGER IF NOT EXISTS trg_lexicon_entries_delete
                AFTER DELETE ON lexicon_entries
                BEGIN
                    UPDATE lexicon_meta
                    SET lexicon_version = lexicon_version + 1,
                        updated_at = CURRENT_TIMESTAMP
                    WHERE id = 1;
                END;
                """
            )
            self._conn.execute(
                """
                CREATE TABLE IF NOT EXISTS mwe_expressions (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    canonical_form TEXT NOT NULL UNIQUE,
                    expression_type TEXT NOT NULL CHECK(expression_type IN ('phrasal_verb', 'idiom')),
                    base_lemma TEXT NOT NULL DEFAULT '',
                    particle TEXT NOT NULL DEFAULT '',
                    is_separable INTEGER NOT NULL DEFAULT 0,
                    max_gap_tokens INTEGER NOT NULL DEFAULT 4,
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                );
                """
            )
            self._conn.execute(
                """
                CREATE TABLE IF NOT EXISTS mwe_senses (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    expression_id INTEGER NOT NULL REFERENCES mwe_expressions(id) ON DELETE CASCADE,
                    sense_key TEXT NOT NULL,
                    gloss TEXT NOT NULL,
                    usage_label TEXT NOT NULL CHECK(usage_label IN ('literal', 'idiomatic')),
                    example TEXT NOT NULL DEFAULT '',
                    priority INTEGER NOT NULL DEFAULT 0,
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    UNIQUE(expression_id, sense_key)
                );
                """
            )
            self._conn.execute(
                """
                CREATE TABLE IF NOT EXISTS mwe_sense_embeddings (
                    sense_id INTEGER NOT NULL REFERENCES mwe_senses(id) ON DELETE CASCADE,
                    model_name TEXT NOT NULL,
                    model_revision TEXT NOT NULL DEFAULT '',
                    dim INTEGER NOT NULL,
                    embedding_blob BLOB NOT NULL,
                    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    PRIMARY KEY (sense_id, model_name, model_revision)
                );
                """
            )
            self._conn.execute(
                """
                CREATE TABLE IF NOT EXISTS mwe_meta (
                    id INTEGER PRIMARY KEY CHECK (id = 1),
                    mwe_version INTEGER NOT NULL DEFAULT 0,
                    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                );
                """
            )
            self._conn.execute(
                """
                INSERT OR IGNORE INTO mwe_meta(id, mwe_version, updated_at)
                VALUES (1, 0, CURRENT_TIMESTAMP);
                """
            )
            self._conn.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_mwe_senses_expression_id
                ON mwe_senses(expression_id);
                """
            )
            self._conn.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_mwe_expressions_type
                ON mwe_expressions(expression_type);
                """
            )
            self._conn.execute(
                """
                CREATE TRIGGER IF NOT EXISTS trg_mwe_expressions_insert
                AFTER INSERT ON mwe_expressions
                BEGIN
                    UPDATE mwe_meta
                    SET mwe_version = mwe_version + 1,
                        updated_at = CURRENT_TIMESTAMP
                    WHERE id = 1;
                END;
                """
            )
            self._conn.execute(
                """
                CREATE TRIGGER IF NOT EXISTS trg_mwe_expressions_update
                AFTER UPDATE ON mwe_expressions
                BEGIN
                    UPDATE mwe_meta
                    SET mwe_version = mwe_version + 1,
                        updated_at = CURRENT_TIMESTAMP
                    WHERE id = 1;
                END;
                """
            )
            self._conn.execute(
                """
                CREATE TRIGGER IF NOT EXISTS trg_mwe_expressions_delete
                AFTER DELETE ON mwe_expressions
                BEGIN
                    UPDATE mwe_meta
                    SET mwe_version = mwe_version + 1,
                        updated_at = CURRENT_TIMESTAMP
                    WHERE id = 1;
                END;
                """
            )
            self._conn.execute(
                """
                CREATE TRIGGER IF NOT EXISTS trg_mwe_senses_insert
                AFTER INSERT ON mwe_senses
                BEGIN
                    UPDATE mwe_meta
                    SET mwe_version = mwe_version + 1,
                        updated_at = CURRENT_TIMESTAMP
                    WHERE id = 1;
                END;
                """
            )
            self._conn.execute(
                """
                CREATE TRIGGER IF NOT EXISTS trg_mwe_senses_update
                AFTER UPDATE ON mwe_senses
                BEGIN
                    UPDATE mwe_meta
                    SET mwe_version = mwe_version + 1,
                        updated_at = CURRENT_TIMESTAMP
                    WHERE id = 1;
                END;
                """
            )
            self._conn.execute(
                """
                CREATE TRIGGER IF NOT EXISTS trg_mwe_senses_delete
                AFTER DELETE ON mwe_senses
                BEGIN
                    UPDATE mwe_meta
                    SET mwe_version = mwe_version + 1,
                        updated_at = CURRENT_TIMESTAMP
                    WHERE id = 1;
                END;
                """
            )

    def _ensure_column(self, table_name: str, column_name: str, column_def: str) -> None:
        safe_ensure_column(
            self._conn,
            table_name=table_name,
            column_name=column_name,
            column_def=column_def,
        )

    @contextmanager
    def _write_transaction(self):
        with self._lock:
            deadline = time.monotonic() + max(0.05, self.settings.sqlite_busy_timeout_ms / 1000.0)
            while True:
                try:
                    self._conn.execute("BEGIN IMMEDIATE;")
                    break
                except sqlite3.OperationalError as exc:
                    logger.error(
                        "sqlite_begin_immediate_operational_error",
                        exc_info=True,
                    )
                    if "locked" not in str(exc).lower() or time.monotonic() >= deadline:
                        raise
                    time.sleep(0.01)
            try:
                yield
                self._conn.execute("COMMIT;")
            except Exception:
                logger.error("sqlite_write_transaction_failed", exc_info=True)
                try:
                    self._conn.execute("ROLLBACK;")
                except Exception:
                    logger.error("sqlite_write_transaction_rollback_failed", exc_info=True)
                raise

    def get_lexicon_version(self) -> int:
        with self._lock:
            row = self._conn.execute(
                "SELECT lexicon_version FROM lexicon_meta WHERE id = 1;"
            ).fetchone()
        if row is None:
            return 0
        return int(row["lexicon_version"])

    def get_mwe_version(self) -> int:
        with self._lock:
            row = self._conn.execute(
                "SELECT mwe_version FROM mwe_meta WHERE id = 1;"
            ).fetchone()
        if row is None:
            return 0
        return int(row["mwe_version"])

    def list_categories(self) -> List[str]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT DISTINCT category FROM lexicon_entries ORDER BY category ASC"
            ).fetchall()
        return [str(row["category"]) for row in rows]

    def list_registered_categories(self) -> List[str]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT name FROM lexicon_categories ORDER BY name ASC"
            ).fetchall()
        return [str(row["name"]) for row in rows]

    def create_category(self, name: str) -> bool:
        cleaned = normalize_whitespace(name)
        if not cleaned:
            raise ValueError("Category name must not be empty.")
        with self._write_transaction():
            cursor = self._conn.execute(
                """
                INSERT OR IGNORE INTO lexicon_categories(name)
                VALUES (?)
                """,
                (cleaned,),
            )
        return bool(cursor.rowcount and cursor.rowcount > 0)

    def delete_category(self, name: str) -> bool:
        cleaned = normalize_whitespace(name)
        if not cleaned:
            raise ValueError("Category name must not be empty.")
        with self._write_transaction():
            used_row = self._conn.execute(
                """
                SELECT COUNT(*) AS count
                FROM lexicon_entries
                WHERE category = ?
                """,
                (cleaned,),
            ).fetchone()
            used_count = int(used_row["count"]) if used_row is not None else 0
            if used_count > 0:
                raise ValueError(f"Category '{cleaned}' is used by {used_count} entries.")

            cursor = self._conn.execute(
                """
                DELETE FROM lexicon_categories
                WHERE name = ?
                """,
                (cleaned,),
            )
        return bool(cursor.rowcount and cursor.rowcount > 0)

    def iter_entries(self) -> List[LexiconEntry]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT id, category, value FROM lexicon_entries ORDER BY category ASC, normalized ASC"
            ).fetchall()
        return [
            LexiconEntry(
                row=int(row["id"]),
                column=1,
                category=str(row["category"]),
                value=str(row["value"]),
            )
            for row in rows
        ]

    def read_lexicon(self) -> Dict[str, List[str]]:
        data: Dict[str, List[str]] = {}
        for category in self.list_categories():
            with self._lock:
                rows = self._conn.execute(
                    "SELECT value FROM lexicon_entries WHERE category = ? ORDER BY normalized ASC",
                    (category,),
                ).fetchall()
            data[category] = [str(row["value"]) for row in rows]
        return data

    def parse_mwe_text(
        self,
        text: str,
        *,
        request_id: str | None = None,
        top_n: int = 3,
        enabled: bool | None = None,
    ) -> dict[str, object]:
        preparsed_doc = None
        if request_id:
            preparsed_doc = self._pop_cached_request_doc(request_id=request_id, text=text)
        try:
            return self._mwe_second_pass_engine.parse(
                text,
                request_id=request_id,
                top_n=max(1, int(top_n)),
                enabled=enabled,
                preparsed_doc=preparsed_doc,
            )
        finally:
            self.release_request_resources(request_id=request_id)

    def _cache_request_doc(self, *, request_id: str, text: str, doc: object) -> None:
        if not request_id:
            return
        with self._lock:
            self._request_doc_cache[request_id] = (text, doc)
            self._request_doc_cache.move_to_end(request_id)
            while len(self._request_doc_cache) > self._request_doc_cache_limit:
                self._request_doc_cache.popitem(last=False)

    def _pop_cached_request_doc(self, *, request_id: str, text: str) -> object | None:
        with self._lock:
            cached = self._request_doc_cache.pop(request_id, None)
        if cached is None:
            return None
        cached_text, cached_doc = cached
        if cached_text != text:
            return None
        return cached_doc

    def release_request_resources(self, *, request_id: str | None) -> None:
        normalized_request_id = str(request_id or "").strip()
        if not normalized_request_id:
            return
        with self._lock:
            self._request_doc_cache.pop(normalized_request_id, None)
        self._mwe_second_pass_engine.release_request_resources(normalized_request_id)

    def load_mwe_expressions(self) -> list[dict[str, object]]:
        with self._lock:
            rows = self._conn.execute(
                """
                SELECT
                    id,
                    canonical_form,
                    expression_type,
                    base_lemma,
                    particle,
                    is_separable,
                    max_gap_tokens
                FROM mwe_expressions
                ORDER BY canonical_form ASC
                """
            ).fetchall()
        return [
            {
                "id": int(row["id"]),
                "canonical_form": str(row["canonical_form"]),
                "expression_type": str(row["expression_type"]),
                "base_lemma": str(row["base_lemma"] or ""),
                "particle": str(row["particle"] or ""),
                "is_separable": int(row["is_separable"]),
                "max_gap_tokens": int(row["max_gap_tokens"]),
            }
            for row in rows
        ]

    def load_mwe_senses(self) -> list[dict[str, object]]:
        with self._lock:
            rows = self._conn.execute(
                """
                SELECT
                    id,
                    expression_id,
                    sense_key,
                    gloss,
                    usage_label,
                    example,
                    priority
                FROM mwe_senses
                ORDER BY expression_id ASC, priority ASC, id ASC
                """
            ).fetchall()
        return [
            {
                "id": int(row["id"]),
                "expression_id": int(row["expression_id"]),
                "sense_key": str(row["sense_key"]),
                "gloss": str(row["gloss"]),
                "usage_label": str(row["usage_label"]),
                "example": str(row["example"] or ""),
                "priority": int(row["priority"] or 0),
            }
            for row in rows
        ]

    def load_mwe_sense_embeddings(
        self,
        model_name: str,
        model_revision: str | None,
    ) -> dict[int, tuple[float, ...]]:
        revision = model_revision or ""
        with self._lock:
            rows = self._conn.execute(
                """
                SELECT sense_id, dim, embedding_blob
                FROM mwe_sense_embeddings
                WHERE model_name = ? AND model_revision = ?
                ORDER BY sense_id ASC
                """,
                (model_name, revision),
            ).fetchall()
        payload: dict[int, tuple[float, ...]] = {}
        for row in rows:
            sense_id = int(row["sense_id"])
            dim = int(row["dim"])
            blob = row["embedding_blob"]
            if not isinstance(blob, (bytes, bytearray, memoryview)):
                continue
            payload[sense_id] = self._embedding_blob_to_tuple(blob, dim)
        return payload

    def upsert_mwe_expression(
        self,
        *,
        canonical_form: str,
        expression_type: str,
        is_separable: bool = False,
        max_gap_tokens: int = 4,
        base_lemma: str | None = None,
        particle: str | None = None,
    ) -> int:
        normalized = normalize_whitespace(canonical_form).lower()
        if not normalized:
            raise ValueError("canonical_form must not be empty")
        if expression_type not in {"phrasal_verb", "idiom"}:
            raise ValueError("expression_type must be 'phrasal_verb' or 'idiom'")
        with self._write_transaction():
            self._conn.execute(
                """
                INSERT INTO mwe_expressions(
                    canonical_form,
                    expression_type,
                    base_lemma,
                    particle,
                    is_separable,
                    max_gap_tokens
                )
                VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(canonical_form) DO UPDATE SET
                    expression_type = excluded.expression_type,
                    base_lemma = excluded.base_lemma,
                    particle = excluded.particle,
                    is_separable = excluded.is_separable,
                    max_gap_tokens = excluded.max_gap_tokens,
                    updated_at = CURRENT_TIMESTAMP
                """,
                (
                    normalized,
                    expression_type,
                    normalize_whitespace(base_lemma or "").lower(),
                    normalize_whitespace(particle or "").lower(),
                    1 if is_separable else 0,
                    max(1, int(max_gap_tokens)),
                ),
            )
            row = self._conn.execute(
                """
                SELECT id
                FROM mwe_expressions
                WHERE canonical_form = ?
                """,
                (normalized,),
            ).fetchone()
        if row is None:
            raise RuntimeError("Failed to upsert mwe expression")
        self._mwe_index_provider.invalidate()
        return int(row["id"])

    def upsert_mwe_sense(
        self,
        *,
        expression_id: int,
        sense_key: str,
        gloss: str,
        usage_label: str,
        example: str = "",
        priority: int = 0,
    ) -> int:
        cleaned_sense_key = normalize_whitespace(sense_key)
        cleaned_gloss = normalize_whitespace(gloss)
        cleaned_example = normalize_whitespace(example)
        usage = normalize_whitespace(usage_label).lower()
        if usage not in {"literal", "idiomatic"}:
            raise ValueError("usage_label must be 'literal' or 'idiomatic'")
        if not cleaned_sense_key:
            raise ValueError("sense_key must not be empty")
        if not cleaned_gloss:
            raise ValueError("gloss must not be empty")
        with self._write_transaction():
            self._conn.execute(
                """
                INSERT INTO mwe_senses(
                    expression_id,
                    sense_key,
                    gloss,
                    usage_label,
                    example,
                    priority
                )
                VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(expression_id, sense_key) DO UPDATE SET
                    gloss = excluded.gloss,
                    usage_label = excluded.usage_label,
                    example = excluded.example,
                    priority = excluded.priority,
                    updated_at = CURRENT_TIMESTAMP
                """,
                (
                    int(expression_id),
                    cleaned_sense_key,
                    cleaned_gloss,
                    usage,
                    cleaned_example,
                    int(priority),
                ),
            )
            row = self._conn.execute(
                """
                SELECT id
                FROM mwe_senses
                WHERE expression_id = ? AND sense_key = ?
                """,
                (int(expression_id), cleaned_sense_key),
            ).fetchone()
        if row is None:
            raise RuntimeError("Failed to upsert mwe sense")
        self._mwe_index_provider.invalidate()
        return int(row["id"])

    def upsert_mwe_sense_embedding(
        self,
        *,
        sense_id: int,
        model_name: str,
        model_revision: str | None,
        vector: Sequence[float],
    ) -> None:
        values = tuple(float(item) for item in vector)
        if not values:
            raise ValueError("embedding vector must not be empty")
        with self._write_transaction():
            self._conn.execute(
                """
                INSERT INTO mwe_sense_embeddings(
                    sense_id,
                    model_name,
                    model_revision,
                    dim,
                    embedding_blob,
                    updated_at
                )
                VALUES (?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
                ON CONFLICT(sense_id, model_name, model_revision) DO UPDATE SET
                    dim = excluded.dim,
                    embedding_blob = excluded.embedding_blob,
                    updated_at = CURRENT_TIMESTAMP
                """,
                (
                    int(sense_id),
                    str(model_name),
                    str(model_revision or ""),
                    len(values),
                    self._embedding_tuple_to_blob(values),
                ),
            )
        self._mwe_index_provider.invalidate()

    def _embedding_tuple_to_blob(self, values: Sequence[float]) -> bytes:
        payload = array("f", [float(item) for item in values])
        return payload.tobytes()

    def _embedding_blob_to_tuple(self, blob: bytes | bytearray | memoryview, dim: int) -> tuple[float, ...]:
        payload = array("f")
        payload.frombytes(bytes(blob))
        if dim > 0 and len(payload) > dim:
            payload = array("f", payload[:dim])
        return tuple(float(item) for item in payload)

    def _insert_entry_locked(
        self,
        *,
        category: str,
        value: str,
        source: str,
        confidence: float | None,
        request_id: str | None,
        example_usage: str | None,
        status: str | None,
    ) -> tuple[LexiconEntry, bool]:
        cleaned = normalize_whitespace(value)
        if not cleaned:
            raise ValueError("Value must not be empty.")
        normalized = cleaned.lower()
        category_clean = normalize_whitespace(category) or "Auto Added"
        now_iso = datetime.now(timezone.utc).isoformat()
        entry_status = status or ("pending_review" if source == "auto" else "approved")
        cleaned_example_usage = normalize_whitespace(example_usage or "") or None

        self._conn.execute(
            """
            INSERT OR IGNORE INTO lexicon_categories(name)
            VALUES (?)
            """,
            (category_clean,),
        )
        cursor = self._conn.execute(
            """
            INSERT OR IGNORE INTO lexicon_entries(
                category,
                value,
                normalized,
                source,
                confidence,
                first_seen_at,
                request_id,
                example_usage,
                status
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                category_clean,
                cleaned,
                normalized,
                source,
                confidence,
                now_iso,
                request_id,
                cleaned_example_usage,
                entry_status,
            ),
        )
        inserted = bool(cursor.rowcount and cursor.rowcount > 0)
        row = self._conn.execute(
            """
            SELECT id, category, value
            FROM lexicon_entries
            WHERE category = ? AND normalized = ?
            """,
            (category_clean, normalized),
        ).fetchone()
        if row is None:
            raise RuntimeError("Failed to insert lexicon entry into SQLite store.")
        entry = LexiconEntry(
            row=int(row["id"]),
            column=1,
            category=str(row["category"]),
            value=str(row["value"]),
        )
        return entry, inserted

    def add_entry(
        self,
        category: str,
        value: str,
        *,
        source: str = "manual",
        confidence: float | None = None,
        request_id: str | None = None,
        example_usage: str | None = None,
        status: str | None = None,
    ) -> LexiconEntry:
        with self._write_transaction():
            entry, inserted = self._insert_entry_locked(
                category=category,
                value=value,
                source=source,
                confidence=confidence,
                request_id=request_id,
                example_usage=example_usage,
                status=status,
            )
        if inserted and self._index_provider is not None:
            self._index_provider.apply_entry(entry, new_version=self.get_lexicon_version())
        return entry

    def add_entries(
        self,
        entries: Sequence[tuple[str, str]],
        *,
        source: str = "manual",
        confidence: float | None = None,
        request_id: str | None = None,
        example_usage: str | None = None,
        status: str | None = None,
    ) -> list[LexiconEntry]:
        if not entries:
            return []
        rows = [(str(category), str(value)) for category, value in entries]
        inserted_entries: list[tuple[LexiconEntry, bool]] = []
        with self._write_transaction():
            for category, value in rows:
                inserted_entries.append(
                    self._insert_entry_locked(
                        category=category,
                        value=value,
                        source=source,
                        confidence=confidence,
                        request_id=request_id,
                        example_usage=example_usage,
                        status=status,
                    )
                )
        if self._index_provider is not None:
            new_version = self.get_lexicon_version()
            for entry, inserted in inserted_entries:
                if inserted:
                    self._index_provider.apply_entry(entry, new_version=new_version)
        return [entry for entry, _ in inserted_entries]

    def list_entries_by_status(
        self,
        *,
        status: str = "pending_review",
        limit: int = 100,
        offset: int = 0,
    ) -> list[dict[str, object]]:
        query = """
            SELECT
                id,
                category,
                value,
                normalized,
                source,
                confidence,
                first_seen_at,
                request_id,
                example_usage,
                status,
                created_at,
                reviewed_at,
                reviewed_by,
                review_note
            FROM lexicon_entries
            WHERE status = ?
            ORDER BY id ASC
            LIMIT ? OFFSET ?
        """
        with self._lock:
            rows = self._conn.execute(query, (status, max(1, limit), max(0, offset))).fetchall()
        return [self._row_to_entry_dict(row) for row in rows]

    def count_entries_by_status(self) -> dict[str, int]:
        with self._lock:
            rows = self._conn.execute(
                """
                SELECT status, COUNT(*) AS count
                FROM lexicon_entries
                GROUP BY status
                """
            ).fetchall()
        return {str(row["status"]): int(row["count"]) for row in rows}

    def review_entries(
        self,
        entry_ids: list[int],
        *,
        target_status: str,
        reviewer: str | None = None,
        note: str | None = None,
        only_pending: bool = True,
    ) -> int:
        if target_status not in {"approved", "rejected", "pending_review"}:
            raise ValueError("target_status must be one of approved, rejected, pending_review")
        normalized_ids = sorted(set(int(item) for item in entry_ids if int(item) > 0))
        if not normalized_ids:
            return 0
        placeholders = ", ".join(["?"] * len(normalized_ids))
        query = f"""
            UPDATE lexicon_entries
            SET status = ?,
                reviewed_at = ?,
                reviewed_by = ?,
                review_note = ?
            WHERE id IN ({placeholders})
        """
        params: list[object] = [
            target_status,
            datetime.now(timezone.utc).isoformat(),
            normalize_whitespace(reviewer or "") or None,
            normalize_whitespace(note or "") or None,
            *normalized_ids,
        ]
        if only_pending:
            query += " AND status = 'pending_review'"

        with self._write_transaction():
            cursor = self._conn.execute(query, params)
            updated = int(cursor.rowcount)
        return updated

    def review_all_pending(
        self,
        *,
        target_status: str,
        reviewer: str | None = None,
        note: str | None = None,
    ) -> int:
        if target_status not in {"approved", "rejected"}:
            raise ValueError("target_status must be approved or rejected")
        with self._lock:
            rows = self._conn.execute(
                "SELECT id FROM lexicon_entries WHERE status = 'pending_review' ORDER BY id ASC"
            ).fetchall()
        ids = [int(row["id"]) for row in rows]
        return self.review_entries(
            ids,
            target_status=target_status,
            reviewer=reviewer,
            note=note,
            only_pending=True,
        )

    def _row_to_entry_dict(self, row: sqlite3.Row) -> dict[str, object]:
        return {
            "id": int(row["id"]),
            "category": str(row["category"]),
            "value": str(row["value"]),
            "normalized": str(row["normalized"]),
            "source": str(row["source"]),
            "confidence": row["confidence"],
            "first_seen_at": row["first_seen_at"],
            "request_id": row["request_id"],
            "example_usage": row["example_usage"],
            "status": str(row["status"]),
            "created_at": row["created_at"],
            "reviewed_at": row["reviewed_at"],
            "reviewed_by": row["reviewed_by"],
            "review_note": row["review_note"],
        }

    def save(self, path: Optional[str | Path] = None) -> Path:
        if path is None:
            return self.db_path

        target = Path(path)
        if target.resolve() == self.db_path.resolve():
            return self.db_path

        with self._lock:
            with sqlite3.connect(target) as dst:
                self._conn.backup(dst)
        return target

    def close(self) -> None:
        try:
            super().close()
            with self._lock:
                self._request_doc_cache.clear()
                self._conn.close()
        except Exception:
            logger.error("sqlite_close_failed", exc_info=True)

    def __del__(self) -> None:  # pragma: no cover - best-effort cleanup
        self.close()

