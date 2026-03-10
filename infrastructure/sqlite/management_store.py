from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
import re
import sqlite3
from threading import RLock

from core.domain import (
    CategoryMutationResult,
    EDITABLE_ENTRY_STATUSES,
    LexiconDeleteRequest,
    LexiconEntryRecord,
    LexiconMutationResult,
    LexiconQuery,
    LexiconSearchResult,
    LexiconUpdateRequest,
)
from infrastructure.sqlite.text_utils import sync_sqlite_sequence


SQLITE_ENTRY_HEADERS = (
    "id",
    "category",
    "value",
    "normalized",
    "source",
    "confidence",
    "first_seen_at",
    "request_id",
    "status",
    "created_at",
    "reviewed_at",
    "reviewed_by",
    "review_note",
)
ALLOWED_SQLITE_STATUS_FILTERS = {"all", "approved", "pending_review", "rejected"}
ALLOWED_SQLITE_SOURCE_FILTERS = {"all", "manual", "auto"}
ALLOWED_SQLITE_SORT_COLUMNS = set(SQLITE_ENTRY_HEADERS)
ALLOWED_SQLITE_SORT_DIRECTIONS = {"asc", "desc"}


class SqliteLexiconManagementStore:
    _SORT_PROFILE_INDEX_WITH_SOURCE = "idx_lexicon_entries_status_source_category_id_desc"
    _SORT_PROFILE_INDEX_NO_SOURCE = "idx_lexicon_entries_status_category_id_desc"

    @dataclass(frozen=True, slots=True)
    class _SummarySnapshot:
        total_rows: int
        counts_by_status: dict[str, int]
        available_categories: list[str]
        lexicon_version: int | None
        updated_at: str | None

    def __init__(self, db_path: Path) -> None:
        self._db_path = Path(db_path)
        self._summary_cache_lock = RLock()
        self._summary_cache_stamp: tuple[int, int] | None = None
        self._summary_cache: SqliteLexiconManagementStore._SummarySnapshot | None = None
        self._index_availability_cache: dict[str, bool] = {}

    def search_entries(self, query: LexiconQuery) -> LexiconSearchResult:
        safe_status = self._safe_status_filter(query.status)
        safe_limit = self._sanitize_limit(query.limit)
        safe_offset = self._sanitize_offset(query.offset)
        safe_category_filter = self._safe_text_filter(query.category_filter)
        safe_value_filter = self._safe_text_filter(query.value_filter)
        safe_source_filter = self._safe_source_filter(query.source_filter)
        safe_request_filter = self._safe_text_filter(query.request_filter)
        safe_id_min = self._sanitize_optional_positive_int(query.id_min)
        safe_id_max = self._sanitize_optional_positive_int(query.id_max)
        if safe_id_min is not None and safe_id_max is not None and safe_id_min > safe_id_max:
            safe_id_min, safe_id_max = safe_id_max, safe_id_min
        safe_reviewed_by_filter = self._safe_text_filter(query.reviewed_by_filter)
        safe_confidence_min = self._sanitize_optional_float(query.confidence_min)
        safe_confidence_max = self._sanitize_optional_float(query.confidence_max)
        if (
            safe_confidence_min is not None
            and safe_confidence_max is not None
            and safe_confidence_min > safe_confidence_max
        ):
            safe_confidence_min, safe_confidence_max = safe_confidence_max, safe_confidence_min
        safe_sort_by = self._safe_sort_column(query.sort_by)
        safe_sort_direction = self._safe_sort_direction(query.sort_direction)

        if not self._db_path.exists():
            return LexiconSearchResult(
                rows=[],
                total_rows=0,
                filtered_rows=0,
                counts_by_status={},
                available_categories=["Auto Added"],
                message=f"SQLite file not found: {self._db_path.resolve()}",
                status_filter=safe_status,
                limit=safe_limit,
                offset=safe_offset,
                category_filter=safe_category_filter,
                value_filter=safe_value_filter,
                source_filter=safe_source_filter,
                request_filter=safe_request_filter,
                id_min=safe_id_min,
                id_max=safe_id_max,
                reviewed_by_filter=safe_reviewed_by_filter,
                confidence_min=safe_confidence_min,
                confidence_max=safe_confidence_max,
                sort_by=safe_sort_by,
                sort_direction=safe_sort_direction,
            )

        try:
            with sqlite3.connect(self._db_path) as conn:
                conn.row_factory = sqlite3.Row
                conn.execute("PRAGMA query_only = ON;")

                table_reference = "lexicon_entries"
                forced_index_name = self._resolve_forced_sort_profile_index_name(
                    conn=conn,
                    status_filter=safe_status,
                    source_filter=safe_source_filter,
                    category_filter=safe_category_filter,
                    value_filter=safe_value_filter,
                    request_filter=safe_request_filter,
                    id_min=safe_id_min,
                    id_max=safe_id_max,
                    reviewed_by_filter=safe_reviewed_by_filter,
                    sort_by=safe_sort_by,
                    sort_direction=safe_sort_direction,
                )
                if forced_index_name:
                    table_reference = (
                        f"lexicon_entries INDEXED BY {forced_index_name}"
                    )

                sql = f"""
                    SELECT
                        id,
                        category,
                        value,
                        normalized,
                        source,
                        confidence,
                        first_seen_at,
                        request_id,
                        status,
                        created_at,
                        reviewed_at,
                        reviewed_by,
                        review_note
                    FROM {table_reference}
                """
                where_clauses: list[str] = []
                params: list[object] = []
                if safe_status != "all":
                    where_clauses.append("status = ?")
                    params.append(safe_status)
                if safe_source_filter != "all":
                    where_clauses.append("source = ?")
                    params.append(safe_source_filter)
                if safe_category_filter:
                    where_clauses.append("category = ? COLLATE NOCASE")
                    params.append(safe_category_filter)
                if safe_value_filter:
                    where_clauses.append("(value LIKE ? OR normalized LIKE ?)")
                    params.append(f"%{safe_value_filter}%")
                    params.append(f"%{safe_value_filter.lower()}%")
                if safe_request_filter:
                    where_clauses.append("request_id LIKE ?")
                    params.append(f"%{safe_request_filter}%")
                if safe_id_min is not None:
                    where_clauses.append("id >= ?")
                    params.append(safe_id_min)
                if safe_id_max is not None:
                    where_clauses.append("id <= ?")
                    params.append(safe_id_max)
                if safe_reviewed_by_filter:
                    where_clauses.append("reviewed_by LIKE ?")
                    params.append(f"%{safe_reviewed_by_filter}%")
                if safe_confidence_min is not None:
                    where_clauses.append("confidence >= ?")
                    params.append(safe_confidence_min)
                if safe_confidence_max is not None:
                    where_clauses.append("confidence <= ?")
                    params.append(safe_confidence_max)
                if where_clauses:
                    sql += " WHERE " + " AND ".join(where_clauses)

                sql += f" ORDER BY {safe_sort_by} {safe_sort_direction.upper()} LIMIT ? OFFSET ?"
                params.append(safe_limit)
                params.append(safe_offset)

                rows = conn.execute(sql, tuple(params)).fetchall()
                records = [self._row_to_entry_record(row) for row in rows]
                snapshot = self._get_summary_snapshot(conn)

            return LexiconSearchResult(
                rows=records,
                total_rows=snapshot.total_rows,
                filtered_rows=len(records),
                counts_by_status=snapshot.counts_by_status,
                available_categories=snapshot.available_categories,
                message=f"Loaded {len(records)} row(s) from {self._db_path.name}.",
                lexicon_version=snapshot.lexicon_version,
                updated_at=snapshot.updated_at,
                status_filter=safe_status,
                limit=safe_limit,
                offset=safe_offset,
                category_filter=safe_category_filter,
                value_filter=safe_value_filter,
                source_filter=safe_source_filter,
                request_filter=safe_request_filter,
                id_min=safe_id_min,
                id_max=safe_id_max,
                reviewed_by_filter=safe_reviewed_by_filter,
                confidence_min=safe_confidence_min,
                confidence_max=safe_confidence_max,
                sort_by=safe_sort_by,
                sort_direction=safe_sort_direction,
            )
        except sqlite3.Error as exc:
            return LexiconSearchResult(
                rows=[],
                total_rows=0,
                filtered_rows=0,
                counts_by_status={},
                available_categories=["Auto Added"],
                message=f"Failed to read SQLite data: {exc}",
                status_filter=safe_status,
                limit=safe_limit,
                offset=safe_offset,
                category_filter=safe_category_filter,
                value_filter=safe_value_filter,
                source_filter=safe_source_filter,
                request_filter=safe_request_filter,
                id_min=safe_id_min,
                id_max=safe_id_max,
                reviewed_by_filter=safe_reviewed_by_filter,
                confidence_min=safe_confidence_min,
                confidence_max=safe_confidence_max,
                sort_by=safe_sort_by,
                sort_direction=safe_sort_direction,
            )

    def get_entry(self, entry_id: int) -> LexiconEntryRecord | None:
        safe_entry_id = self._parse_entry_id(entry_id)
        if safe_entry_id <= 0 or not self._db_path.exists():
            return None
        try:
            with sqlite3.connect(self._db_path) as conn:
                conn.row_factory = sqlite3.Row
                row = conn.execute(
                    """
                    SELECT
                        id,
                        category,
                        value,
                        normalized,
                        source,
                        confidence,
                        first_seen_at,
                        request_id,
                        status,
                        created_at,
                        reviewed_at,
                        reviewed_by,
                        review_note
                    FROM lexicon_entries
                    WHERE id = ?
                    """,
                    (safe_entry_id,),
                ).fetchone()
            if row is None:
                return None
            return self._row_to_entry_record(row)
        except sqlite3.Error:
            return None

    def update_entry(self, request: LexiconUpdateRequest) -> LexiconMutationResult:
        safe_entry_id = self._parse_entry_id(request.entry_id)
        safe_status = self._safe_edit_status(request.status)
        safe_category = self._normalize_category_name(request.category)
        safe_value = self._normalize_entry_value(request.value)
        if safe_entry_id <= 0:
            return LexiconMutationResult(success=False, message="Update skipped: select a valid entry first.")
        if not safe_value:
            return LexiconMutationResult(success=False, message="Update skipped: value must not be empty.")
        if not safe_category:
            return LexiconMutationResult(success=False, message="Update skipped: category must not be empty.")
        if not self._db_path.exists():
            return LexiconMutationResult(
                success=False,
                message=f"Update failed: SQLite file not found: {self._db_path.resolve()}",
            )

        try:
            with sqlite3.connect(self._db_path) as conn:
                conn.row_factory = sqlite3.Row
                self._ensure_category_table(conn)
                categories = self._list_categories_with_connection(conn)
                if safe_category not in categories:
                    return LexiconMutationResult(
                        success=False,
                        message=(
                            f"Update skipped: category '{safe_category}' does not exist. "
                            "Use 'Add Category' first."
                        ),
                    )

                current = conn.execute(
                    """
                    SELECT reviewed_at, reviewed_by, review_note
                    FROM lexicon_entries
                    WHERE id = ?
                    """,
                    (safe_entry_id,),
                ).fetchone()
                if current is None:
                    return LexiconMutationResult(
                        success=False,
                        message=f"Update skipped: entry id={safe_entry_id} not found.",
                    )

                if safe_status == "pending_review":
                    reviewed_at: str | None = None
                    reviewed_by: str | None = None
                    review_note: str | None = None
                else:
                    reviewed_at = (
                        str(current["reviewed_at"])
                        if current["reviewed_at"]
                        else datetime.now(timezone.utc).isoformat()
                    )
                    reviewed_by = str(current["reviewed_by"]) if current["reviewed_by"] else "ui"
                    review_note = str(current["review_note"]) if current["review_note"] else None

                cursor = conn.execute(
                    """
                    UPDATE lexicon_entries
                    SET category = ?,
                        value = ?,
                        normalized = ?,
                        status = ?,
                        reviewed_at = ?,
                        reviewed_by = ?,
                        review_note = ?
                    WHERE id = ?
                    """,
                    (
                        safe_category,
                        safe_value,
                        safe_value.lower(),
                        safe_status,
                        reviewed_at,
                        reviewed_by,
                        review_note,
                        safe_entry_id,
                    ),
                )
                conn.commit()
                affected = int(cursor.rowcount if cursor.rowcount is not None else 0)
            if affected <= 0:
                return LexiconMutationResult(
                    success=False,
                    message=f"Update skipped: entry id={safe_entry_id} not found.",
                    affected_count=0,
                )
            self._invalidate_summary_cache()
            return LexiconMutationResult(
                success=True,
                message=f"Updated entry id={safe_entry_id}.",
                affected_count=affected,
            )
        except sqlite3.IntegrityError as exc:
            return LexiconMutationResult(success=False, message=f"Update failed (constraint): {exc}")
        except sqlite3.Error as exc:
            return LexiconMutationResult(success=False, message=f"Update failed: {exc}")

    def delete_entries(self, request: LexiconDeleteRequest) -> LexiconMutationResult:
        normalized_ids: list[int] = []
        seen: set[int] = set()
        for value in request.entry_ids:
            safe = self._parse_entry_id(value)
            if safe <= 0 or safe in seen:
                continue
            seen.add(safe)
            normalized_ids.append(safe)
        if not normalized_ids:
            return LexiconMutationResult(success=False, message="Delete skipped: select a valid entry first.")
        if not self._db_path.exists():
            return LexiconMutationResult(
                success=False,
                message=f"Delete failed: SQLite file not found: {self._db_path.resolve()}",
            )

        placeholders = ", ".join(["?"] * len(normalized_ids))
        try:
            with sqlite3.connect(self._db_path) as conn:
                cursor = conn.execute(
                    f"DELETE FROM lexicon_entries WHERE id IN ({placeholders})",
                    tuple(normalized_ids),
                )
                deleted = int(cursor.rowcount if cursor.rowcount is not None else 0)
                if deleted > 0:
                    self._sync_sqlite_sequence(conn, table_name="lexicon_entries")
                conn.commit()
            if deleted <= 0:
                return LexiconMutationResult(
                    success=False,
                    message=f"Delete skipped: no matching entries for ids={normalized_ids}.",
                    affected_count=0,
                )
            self._invalidate_summary_cache()
            if len(normalized_ids) == 1:
                message = f"Deleted entry id={normalized_ids[0]}."
            else:
                message = f"Deleted {deleted} selected rows."
            return LexiconMutationResult(success=True, message=message, affected_count=deleted)
        except sqlite3.Error as exc:
            return LexiconMutationResult(success=False, message=f"Delete failed: {exc}")

    def list_categories(self) -> list[str]:
        if not self._db_path.exists():
            return ["Auto Added"]
        try:
            with sqlite3.connect(self._db_path) as conn:
                conn.row_factory = sqlite3.Row
                self._ensure_category_table(conn)
                return self._list_categories_with_connection(conn)
        except sqlite3.Error:
            return ["Auto Added"]

    def create_category(self, name: str) -> CategoryMutationResult:
        cleaned_name = str(name).strip()
        if not cleaned_name:
            return CategoryMutationResult(
                categories=self.list_categories(),
                message="Category name must not be empty.",
            )
        try:
            with sqlite3.connect(self._db_path) as conn:
                self._ensure_category_table(conn)
                cursor = conn.execute(
                    """
                    INSERT OR IGNORE INTO lexicon_categories(name)
                    VALUES (?)
                    """,
                    (cleaned_name,),
                )
                conn.commit()
                created = bool(cursor.rowcount and cursor.rowcount > 0)
        except sqlite3.Error as exc:
            return CategoryMutationResult(categories=self.list_categories(), message=f"Add category failed: {exc}")

        if created:
            self._invalidate_summary_cache()
            message = f"Created category '{cleaned_name}'."
        else:
            message = f"Category '{cleaned_name}' already exists."
        return CategoryMutationResult(categories=self.list_categories(), message=message)

    def delete_category(self, name: str) -> CategoryMutationResult:
        cleaned_name = str(name).strip()
        if not cleaned_name:
            return CategoryMutationResult(
                categories=self.list_categories(),
                message="Category name must not be empty.",
            )
        try:
            with sqlite3.connect(self._db_path) as conn:
                conn.row_factory = sqlite3.Row
                self._ensure_category_table(conn)
                usage_row = conn.execute(
                    """
                    SELECT COUNT(*) AS count
                    FROM lexicon_entries
                    WHERE category = ?
                    """,
                    (cleaned_name,),
                ).fetchone()
                usage_count = int(usage_row["count"]) if usage_row is not None else 0
                if usage_count > 0:
                    return CategoryMutationResult(
                        categories=self.list_categories(),
                        message=f"Delete category skipped: '{cleaned_name}' is used by {usage_count} entries.",
                    )

                cursor = conn.execute(
                    """
                    DELETE FROM lexicon_categories
                    WHERE name = ?
                    """,
                    (cleaned_name,),
                )
                conn.commit()
                deleted = bool(cursor.rowcount and cursor.rowcount > 0)
        except sqlite3.Error as exc:
            return CategoryMutationResult(
                categories=self.list_categories(),
                message=f"Delete category failed: {exc}",
            )

        if deleted:
            self._invalidate_summary_cache()
            message = f"Deleted category '{cleaned_name}'."
        else:
            message = f"Category '{cleaned_name}' not found."
        return CategoryMutationResult(categories=self.list_categories(), message=message)

    def get_statistics(self) -> dict[str, object]:
        try:
            with sqlite3.connect(self._db_path) as conn:
                conn.row_factory = sqlite3.Row
                conn.execute("PRAGMA query_only = ON;")

                total_row = conn.execute("SELECT COUNT(*) AS cnt FROM lexicon_entries").fetchone()
                total = int(total_row["cnt"]) if total_row else 0

                status_rows = conn.execute(
                    "SELECT status, COUNT(*) AS cnt FROM lexicon_entries GROUP BY status ORDER BY cnt DESC"
                ).fetchall()

                source_rows = conn.execute(
                    "SELECT source, COUNT(*) AS cnt FROM lexicon_entries GROUP BY source ORDER BY cnt DESC"
                ).fetchall()

                category_rows = conn.execute(
                    "SELECT category, COUNT(*) AS cnt FROM lexicon_entries"
                    " GROUP BY category ORDER BY cnt DESC LIMIT 50"
                ).fetchall()

            return {
                "total_entries": total,
                "counts_by_status": {str(r["status"] or ""): int(r["cnt"]) for r in status_rows},
                "counts_by_source": {str(r["source"] or ""): int(r["cnt"]) for r in source_rows},
                "categories": [(str(r["category"] or ""), int(r["cnt"])) for r in category_rows],
            }
        except Exception:
            return {
                "total_entries": 0,
                "counts_by_status": {},
                "counts_by_source": {},
                "categories": [],
            }

    def _invalidate_summary_cache(self) -> None:
        with self._summary_cache_lock:
            self._summary_cache = None
            self._summary_cache_stamp = None

    def _db_stat_stamp(self) -> tuple[int, int]:
        try:
            stat = self._db_path.stat()
            return int(stat.st_mtime_ns), int(stat.st_size)
        except OSError:
            return 0, 0

    def _get_summary_snapshot(self, conn: sqlite3.Connection) -> _SummarySnapshot:
        stamp = self._db_stat_stamp()
        with self._summary_cache_lock:
            if self._summary_cache is not None and self._summary_cache_stamp == stamp:
                return self._summary_cache

        total_row = conn.execute("SELECT COUNT(*) AS count FROM lexicon_entries").fetchone()
        total_rows = int(total_row["count"]) if total_row is not None else 0

        counts_rows = conn.execute(
            """
            SELECT status, COUNT(*) AS count
            FROM lexicon_entries
            GROUP BY status
            ORDER BY status ASC
            """
        ).fetchall()
        counts_by_status = {str(row["status"]): int(row["count"]) for row in counts_rows}

        if self._table_exists(conn, "lexicon_categories"):
            categories_rows = conn.execute(
                """
                SELECT name
                FROM (
                    SELECT name AS name
                    FROM lexicon_categories
                    WHERE TRIM(name) <> ''
                    UNION
                    SELECT category AS name
                    FROM lexicon_entries
                    WHERE TRIM(category) <> ''
                )
                ORDER BY name ASC
                """
            ).fetchall()
        else:
            categories_rows = conn.execute(
                """
                SELECT DISTINCT category AS name
                FROM lexicon_entries
                WHERE TRIM(category) <> ''
                ORDER BY category ASC
                """
            ).fetchall()
        categories = [str(row["name"]).strip() for row in categories_rows if str(row["name"]).strip()]
        if "Auto Added" not in categories:
            categories.append("Auto Added")
        categories = sorted(set(categories))

        lexicon_version: int | None = None
        updated_at: str | None = None
        if self._table_exists(conn, "lexicon_meta"):
            meta_row = conn.execute(
                """
                SELECT lexicon_version, updated_at
                FROM lexicon_meta
                WHERE id = 1
                """
            ).fetchone()
            if meta_row is not None:
                lexicon_version = int(meta_row["lexicon_version"])
                updated_at = str(meta_row["updated_at"])

        snapshot = SqliteLexiconManagementStore._SummarySnapshot(
            total_rows=total_rows,
            counts_by_status=counts_by_status,
            available_categories=categories,
            lexicon_version=lexicon_version,
            updated_at=updated_at,
        )
        with self._summary_cache_lock:
            self._summary_cache = snapshot
            self._summary_cache_stamp = stamp
        return snapshot

    def _table_exists(self, conn: sqlite3.Connection, table_name: str) -> bool:
        row = conn.execute(
            """
            SELECT 1
            FROM sqlite_master
            WHERE type = 'table' AND name = ?
            LIMIT 1
            """,
            (str(table_name),),
        ).fetchone()
        return bool(row)

    def _has_index(self, conn: sqlite3.Connection, index_name: str) -> bool:
        if index_name in self._index_availability_cache:
            return bool(self._index_availability_cache[index_name])
        row = conn.execute(
            """
            SELECT 1
            FROM sqlite_master
            WHERE type = 'index' AND name = ?
            LIMIT 1
            """,
            (str(index_name),),
        ).fetchone()
        available = bool(row)
        self._index_availability_cache[index_name] = available
        return available

    def _resolve_forced_sort_profile_index_name(
        self,
        *,
        conn: sqlite3.Connection,
        status_filter: str,
        source_filter: str,
        category_filter: str,
        value_filter: str,
        request_filter: str,
        id_min: int | None,
        id_max: int | None,
        reviewed_by_filter: str,
        sort_by: str,
        sort_direction: str,
    ) -> str:
        if sort_by != "id" or sort_direction != "desc":
            return ""
        if status_filter == "all":
            return ""
        if not category_filter:
            return ""
        if value_filter or request_filter or reviewed_by_filter:
            return ""
        if id_min is not None or id_max is not None:
            return ""

        if source_filter != "all" and self._has_index(
            conn,
            SqliteLexiconManagementStore._SORT_PROFILE_INDEX_WITH_SOURCE,
        ):
            return SqliteLexiconManagementStore._SORT_PROFILE_INDEX_WITH_SOURCE
        if self._has_index(conn, SqliteLexiconManagementStore._SORT_PROFILE_INDEX_NO_SOURCE):
            return SqliteLexiconManagementStore._SORT_PROFILE_INDEX_NO_SOURCE
        return ""

    def _ensure_category_table(self, conn: sqlite3.Connection) -> None:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS lexicon_categories (
                name TEXT PRIMARY KEY,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            )
            """
        )
        conn.execute(
            """
            INSERT OR IGNORE INTO lexicon_categories(name)
            SELECT DISTINCT category
            FROM lexicon_entries
            WHERE TRIM(category) <> ''
            """
        )

    def _list_categories_with_connection(self, conn: sqlite3.Connection) -> list[str]:
        categories: set[str] = set()
        try:
            rows = conn.execute(
                "SELECT name FROM lexicon_categories WHERE TRIM(name) <> '' ORDER BY name ASC"
            ).fetchall()
            categories.update(str(row[0]).strip() for row in rows if str(row[0]).strip())
        except sqlite3.Error:
            return ["Auto Added"]
        rows = conn.execute(
            """
            SELECT DISTINCT category
            FROM lexicon_entries
            WHERE TRIM(category) <> ''
            ORDER BY category ASC
            """
        ).fetchall()
        categories.update(str(row[0]).strip() for row in rows if str(row[0]).strip())
        if "Auto Added" not in categories:
            categories.add("Auto Added")
        return sorted(categories)

    def _row_to_entry_record(self, row: sqlite3.Row) -> LexiconEntryRecord:
        confidence = row["confidence"]
        parsed_confidence: float | None
        if confidence is None:
            parsed_confidence = None
        else:
            try:
                parsed_confidence = float(confidence)
            except (TypeError, ValueError):
                parsed_confidence = None
        return LexiconEntryRecord(
            id=int(row["id"]),
            category=str(row["category"] or ""),
            value=str(row["value"] or ""),
            normalized=str(row["normalized"] or ""),
            source=str(row["source"] or ""),
            confidence=parsed_confidence,
            first_seen_at=str(row["first_seen_at"]) if row["first_seen_at"] is not None else None,
            request_id=str(row["request_id"]) if row["request_id"] is not None else None,
            status=str(row["status"] or ""),
            created_at=str(row["created_at"]) if row["created_at"] is not None else None,
            reviewed_at=str(row["reviewed_at"]) if row["reviewed_at"] is not None else None,
            reviewed_by=str(row["reviewed_by"]) if row["reviewed_by"] is not None else None,
            review_note=str(row["review_note"]) if row["review_note"] is not None else None,
        )

    def _sanitize_limit(self, value: object) -> int:
        try:
            parsed = int(value)
        except (TypeError, ValueError):
            parsed = 100
        return max(1, min(500, parsed))

    def _sanitize_offset(self, value: object) -> int:
        try:
            parsed = int(value)
        except (TypeError, ValueError):
            parsed = 0
        return max(0, parsed)

    def _sanitize_optional_positive_int(self, value: object) -> int | None:
        if value is None:
            return None
        try:
            parsed = int(value)
        except (TypeError, ValueError):
            return None
        if parsed <= 0:
            return None
        return parsed

    def _sanitize_optional_float(self, value: object) -> float | None:
        if value is None:
            return None
        try:
            return float(value)
        except (TypeError, ValueError):
            return None

    def _safe_status_filter(self, value: object) -> str:
        status = str(value or "").strip()
        return status if status in ALLOWED_SQLITE_STATUS_FILTERS else "all"

    def _safe_edit_status(self, value: object) -> str:
        status = str(value or "").strip()
        return status if status in EDITABLE_ENTRY_STATUSES else "pending_review"

    def _safe_source_filter(self, value: object) -> str:
        source = str(value or "").strip().lower()
        return source if source in ALLOWED_SQLITE_SOURCE_FILTERS else "all"

    def _safe_text_filter(self, value: object) -> str:
        return re.sub(r"\s+", " ", str(value or "").strip())

    def _safe_sort_column(self, value: object) -> str:
        sort_column = str(value or "").strip()
        return sort_column if sort_column in ALLOWED_SQLITE_SORT_COLUMNS else "id"

    def _safe_sort_direction(self, value: object) -> str:
        sort_direction = str(value or "").strip().lower()
        return sort_direction if sort_direction in ALLOWED_SQLITE_SORT_DIRECTIONS else "desc"

    def _normalize_category_name(self, value: object) -> str:
        return re.sub(r"\s+", " ", str(value or "").strip())

    def _normalize_entry_value(self, value: object) -> str:
        return re.sub(r"\s+", " ", str(value or "").strip())

    def _parse_entry_id(self, value: object) -> int:
        try:
            parsed = int(value)
        except (TypeError, ValueError):
            return 0
        return parsed if parsed > 0 else 0

    def _sync_sqlite_sequence(self, conn: sqlite3.Connection, *, table_name: str) -> None:
        sync_sqlite_sequence(conn, table_name=table_name)
