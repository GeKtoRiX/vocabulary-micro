from __future__ import annotations

from pathlib import Path
import sqlite3

from core.domain import LexiconDeleteRequest, LexiconQuery, LexiconUpdateRequest
from infrastructure.sqlite.management_store import SqliteLexiconManagementStore


def _bootstrap_lexicon_entries(db_path: Path) -> None:
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            """
            CREATE TABLE lexicon_entries (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                category TEXT NOT NULL,
                value TEXT NOT NULL,
                normalized TEXT NOT NULL,
                source TEXT NOT NULL DEFAULT 'manual',
                confidence REAL,
                first_seen_at TEXT,
                request_id TEXT,
                status TEXT NOT NULL DEFAULT 'approved',
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                reviewed_at TEXT,
                reviewed_by TEXT,
                review_note TEXT,
                UNIQUE(category, normalized)
            )
            """
        )


def _bootstrap_full_schema(db_path: Path) -> None:
    _bootstrap_lexicon_entries(db_path)
    with sqlite3.connect(db_path) as conn:
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
            CREATE TABLE IF NOT EXISTS lexicon_meta (
                id INTEGER PRIMARY KEY,
                lexicon_version INTEGER NOT NULL,
                updated_at TEXT NOT NULL
            )
            """
        )
        conn.execute(
            """
            INSERT OR REPLACE INTO lexicon_meta(id, lexicon_version, updated_at)
            VALUES (1, 7, '2026-03-03T00:00:00+00:00')
            """
        )
        conn.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_lexicon_entries_status_source_category_id_desc
            ON lexicon_entries(status, source, category, id DESC)
            """
        )
        conn.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_lexicon_entries_status_category_id_desc
            ON lexicon_entries(status, category, id DESC)
            """
        )
        conn.commit()


def _insert_entry(db_path: Path, *, value: str) -> int:
    with sqlite3.connect(db_path) as conn:
        cursor = conn.execute(
            """
            INSERT INTO lexicon_entries(category, value, normalized, source, status)
            VALUES (?, ?, ?, 'manual', 'approved')
            """,
            ("Noun", value, value.lower()),
        )
        return int(cursor.lastrowid)


def _insert_custom_entry(
    db_path: Path,
    *,
    category: str,
    value: str,
    source: str,
    status: str,
    request_id: str,
    confidence: float | None,
    reviewed_by: str | None = None,
) -> int:
    with sqlite3.connect(db_path) as conn:
        cursor = conn.execute(
            """
            INSERT INTO lexicon_entries(
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
            )
            VALUES (?, ?, ?, ?, ?, CURRENT_TIMESTAMP, ?, ?, CURRENT_TIMESTAMP, NULL, ?, NULL)
            """,
            (
                category,
                value,
                value.lower(),
                source,
                confidence,
                request_id,
                status,
                reviewed_by,
            ),
        )
        conn.commit()
        return int(cursor.lastrowid)


def test_management_store_reuses_last_deleted_id(tmp_path: Path) -> None:
    db_path = tmp_path / "lexicon.sqlite3"
    _bootstrap_lexicon_entries(db_path)
    first_id = _insert_entry(db_path, value="alpha")
    second_id = _insert_entry(db_path, value="beta")
    assert first_id == 1
    assert second_id == 2

    store = SqliteLexiconManagementStore(db_path)
    mutation = store.delete_entries(LexiconDeleteRequest(entry_ids=[second_id]))

    recreated_id = _insert_entry(db_path, value="gamma")

    assert mutation.success is True
    assert mutation.affected_count == 1
    assert recreated_id == 2


def test_management_store_resets_sequence_after_delete_all(tmp_path: Path) -> None:
    db_path = tmp_path / "lexicon.sqlite3"
    _bootstrap_lexicon_entries(db_path)
    only_id = _insert_entry(db_path, value="single")
    assert only_id == 1

    store = SqliteLexiconManagementStore(db_path)
    mutation = store.delete_entries(LexiconDeleteRequest(entry_ids=[only_id]))

    recreated_id = _insert_entry(db_path, value="again")

    assert mutation.success is True
    assert mutation.affected_count == 1
    assert recreated_id == 1


def test_management_store_search_entries_handles_missing_db(tmp_path: Path) -> None:
    store = SqliteLexiconManagementStore(tmp_path / "missing.sqlite3")
    result = store.search_entries(LexiconQuery(status="approved", limit=10, offset=0))

    assert result.rows == []
    assert result.total_rows == 0
    assert "SQLite file not found" in result.message
    assert result.status_filter == "approved"
    assert result.limit == 10


def test_management_store_search_entries_applies_filters_and_sanitization(tmp_path: Path) -> None:
    db_path = tmp_path / "lexicon.sqlite3"
    _bootstrap_full_schema(db_path)
    _insert_custom_entry(
        db_path,
        category="Verb",
        value="run",
        source="manual",
        status="approved",
        request_id="req-1",
        confidence=0.8,
        reviewed_by="ui",
    )
    _insert_custom_entry(
        db_path,
        category="Noun",
        value="runner",
        source="auto",
        status="pending_review",
        request_id="req-2",
        confidence=0.4,
    )

    store = SqliteLexiconManagementStore(db_path)
    result = store.search_entries(
        LexiconQuery(
            status="approved",
            limit=999,
            offset=-3,
            category_filter="verb",
            value_filter="ru",
            source_filter="manual",
            request_filter="req-1",
            id_min=9,
            id_max=1,
            reviewed_by_filter="ui",
            confidence_min=0.9,
            confidence_max=0.1,
            sort_by="unknown",
            sort_direction="up",
        )
    )

    assert result.limit == 500
    assert result.offset == 0
    assert result.sort_by == "id"
    assert result.sort_direction == "desc"
    assert result.id_min == 1 and result.id_max == 9
    assert result.confidence_min == 0.1 and result.confidence_max == 0.9
    assert len(result.rows) == 1
    assert result.rows[0].value == "run"
    assert result.lexicon_version == 7
    assert result.updated_at == "2026-03-03T00:00:00+00:00"


def test_management_store_get_entry_and_update_entry_paths(tmp_path: Path) -> None:
    db_path = tmp_path / "lexicon.sqlite3"
    _bootstrap_full_schema(db_path)
    entry_id = _insert_custom_entry(
        db_path,
        category="Verb",
        value="run",
        source="manual",
        status="pending_review",
        request_id="req-1",
        confidence=0.9,
    )

    store = SqliteLexiconManagementStore(db_path)
    assert store.get_entry(0) is None
    fetched = store.get_entry(entry_id)
    assert fetched is not None and fetched.value == "run"

    update_ok = store.update_entry(
        LexiconUpdateRequest(
            entry_id=entry_id,
            status="approved",
            category="Verb",
            value="Run",
        )
    )
    assert update_ok.success is True
    updated = store.get_entry(entry_id)
    assert updated is not None
    assert updated.status == "approved"
    assert updated.reviewed_by == "ui"
    assert updated.normalized == "run"

    reset = store.update_entry(
        LexiconUpdateRequest(
            entry_id=entry_id,
            status="pending_review",
            category="Verb",
            value="run",
        )
    )
    assert reset.success is True
    reset_row = store.get_entry(entry_id)
    assert reset_row is not None
    assert reset_row.reviewed_at is None
    assert reset_row.reviewed_by is None


def test_management_store_update_entry_validation_and_missing_paths(tmp_path: Path) -> None:
    db_path = tmp_path / "lexicon.sqlite3"
    _bootstrap_full_schema(db_path)
    _insert_custom_entry(
        db_path,
        category="Verb",
        value="run",
        source="manual",
        status="approved",
        request_id="req-1",
        confidence=1.0,
    )
    store = SqliteLexiconManagementStore(db_path)

    invalid_id = store.update_entry(
        LexiconUpdateRequest(entry_id=0, status="approved", category="Verb", value="run")
    )
    empty_value = store.update_entry(
        LexiconUpdateRequest(entry_id=1, status="approved", category="Verb", value=" ")
    )
    empty_category = store.update_entry(
        LexiconUpdateRequest(entry_id=1, status="approved", category=" ", value="run")
    )
    missing_category = store.update_entry(
        LexiconUpdateRequest(entry_id=1, status="approved", category="Idiom", value="run")
    )
    not_found = store.update_entry(
        LexiconUpdateRequest(entry_id=999, status="approved", category="Verb", value="run")
    )
    missing_db = SqliteLexiconManagementStore(tmp_path / "nope.sqlite3").update_entry(
        LexiconUpdateRequest(entry_id=1, status="approved", category="Verb", value="run")
    )

    assert invalid_id.success is False and "valid entry" in invalid_id.message
    assert empty_value.success is False and "value must not be empty" in empty_value.message
    assert empty_category.success is False and "category must not be empty" in empty_category.message
    assert missing_category.success is False and "does not exist" in missing_category.message
    assert not_found.success is False and "not found" in not_found.message
    assert missing_db.success is False and "SQLite file not found" in missing_db.message


def test_management_store_update_entry_integrity_error(tmp_path: Path) -> None:
    db_path = tmp_path / "lexicon.sqlite3"
    _bootstrap_full_schema(db_path)
    first = _insert_custom_entry(
        db_path,
        category="Verb",
        value="run",
        source="manual",
        status="approved",
        request_id="req-1",
        confidence=1.0,
    )
    second = _insert_custom_entry(
        db_path,
        category="Verb",
        value="walk",
        source="manual",
        status="approved",
        request_id="req-2",
        confidence=1.0,
    )
    store = SqliteLexiconManagementStore(db_path)
    result = store.update_entry(
        LexiconUpdateRequest(entry_id=second, status="approved", category="Verb", value="run")
    )
    assert first != second
    assert result.success is False
    assert "constraint" in result.message


def test_management_store_delete_entries_paths(tmp_path: Path) -> None:
    db_path = tmp_path / "lexicon.sqlite3"
    _bootstrap_full_schema(db_path)
    row_id = _insert_custom_entry(
        db_path,
        category="Verb",
        value="run",
        source="manual",
        status="approved",
        request_id="req-1",
        confidence=1.0,
    )
    store = SqliteLexiconManagementStore(db_path)

    invalid = store.delete_entries(LexiconDeleteRequest(entry_ids=[0, -1, "x"]))  # type: ignore[list-item]
    not_found = store.delete_entries(LexiconDeleteRequest(entry_ids=[999]))
    deleted = store.delete_entries(LexiconDeleteRequest(entry_ids=[row_id]))
    missing_db = SqliteLexiconManagementStore(tmp_path / "nope.sqlite3").delete_entries(
        LexiconDeleteRequest(entry_ids=[1])
    )

    assert invalid.success is False and "valid entry" in invalid.message
    assert not_found.success is False and "no matching entries" in not_found.message
    assert deleted.success is True and deleted.affected_count == 1
    assert missing_db.success is False and "SQLite file not found" in missing_db.message


def test_management_store_category_operations_and_statistics(tmp_path: Path) -> None:
    db_path = tmp_path / "lexicon.sqlite3"
    _bootstrap_full_schema(db_path)
    _insert_custom_entry(
        db_path,
        category="Verb",
        value="run",
        source="manual",
        status="approved",
        request_id="req-1",
        confidence=0.9,
    )
    store = SqliteLexiconManagementStore(db_path)

    categories = store.list_categories()
    assert "Verb" in categories and "Auto Added" in categories

    empty_create = store.create_category("   ")
    created = store.create_category("Idiom")
    duplicate = store.create_category("Idiom")
    empty_delete = store.delete_category("   ")
    in_use_delete = store.delete_category("Verb")
    missing_delete = store.delete_category("Missing")
    deleted = store.delete_category("Idiom")
    stats = store.get_statistics()

    assert "must not be empty" in empty_create.message
    assert "Created category" in created.message
    assert "already exists" in duplicate.message
    assert "must not be empty" in empty_delete.message
    assert "is used by" in in_use_delete.message
    assert "not found" in missing_delete.message
    assert "Deleted category" in deleted.message
    assert stats["total_entries"] == 1
    assert stats["counts_by_status"]["approved"] == 1
    assert stats["counts_by_source"]["manual"] == 1


def test_management_store_statistics_fallback_on_error(tmp_path: Path) -> None:
    db_path = tmp_path / "broken.sqlite3"
    db_path.write_text("not a sqlite db", encoding="utf-8")
    store = SqliteLexiconManagementStore(db_path)
    stats = store.get_statistics()
    assert stats == {
        "total_entries": 0,
        "counts_by_status": {},
        "counts_by_source": {},
        "categories": [],
    }


def test_management_store_private_sanitizers_and_index_resolution(tmp_path: Path) -> None:
    db_path = tmp_path / "lexicon.sqlite3"
    _bootstrap_full_schema(db_path)
    store = SqliteLexiconManagementStore(db_path)

    assert store._sanitize_limit("bad") == 100
    assert store._sanitize_limit(0) == 1
    assert store._sanitize_offset(-5) == 0
    assert store._sanitize_optional_positive_int("2") == 2
    assert store._sanitize_optional_positive_int("-1") is None
    assert store._sanitize_optional_float("0.5") == 0.5
    assert store._sanitize_optional_float("bad") is None
    assert store._safe_status_filter("bad") == "all"
    assert store._safe_edit_status("approved") == "approved"
    assert store._safe_edit_status("x") == "pending_review"
    assert store._safe_source_filter("MANUAL") == "manual"
    assert store._safe_text_filter(" a   b ") == "a b"
    assert store._safe_sort_column("value") == "value"
    assert store._safe_sort_column("bad") == "id"
    assert store._safe_sort_direction("ASC") == "asc"
    assert store._safe_sort_direction("bad") == "desc"
    assert store._normalize_category_name("  A   B ") == "A B"
    assert store._normalize_entry_value("  A   B ") == "A B"
    assert store._parse_entry_id("7") == 7
    assert store._parse_entry_id("bad") == 0

    with sqlite3.connect(db_path) as conn:
        forced = store._resolve_forced_sort_profile_index_name(
            conn=conn,
            status_filter="approved",
            source_filter="manual",
            category_filter="Verb",
            value_filter="",
            request_filter="",
            id_min=None,
            id_max=None,
            reviewed_by_filter="",
            sort_by="id",
            sort_direction="desc",
        )
    assert forced in {
        "idx_lexicon_entries_status_source_category_id_desc",
        "idx_lexicon_entries_status_category_id_desc",
    }


def test_management_store_search_forced_index_and_sqlite_error_fallback(tmp_path: Path) -> None:
    db_path = tmp_path / "lexicon.sqlite3"
    _bootstrap_full_schema(db_path)
    _insert_custom_entry(
        db_path,
        category="Verb",
        value="run",
        source="manual",
        status="approved",
        request_id="req-1",
        confidence=0.8,
    )
    store = SqliteLexiconManagementStore(db_path)
    indexed = store.search_entries(
        LexiconQuery(
            status="approved",
            source_filter="manual",
            category_filter="Verb",
            sort_by="id",
            sort_direction="desc",
            limit=10,
            offset=0,
        )
    )
    assert indexed.filtered_rows == 1
    assert indexed.rows[0].value == "run"

    bad_db = tmp_path / "broken.sqlite3"
    bad_db.write_text("not sqlite", encoding="utf-8")
    fallback = SqliteLexiconManagementStore(bad_db).search_entries(LexiconQuery())
    assert fallback.filtered_rows == 0
    assert fallback.rows == []
    assert "Failed to read SQLite data" in fallback.message


def test_management_store_get_entry_none_and_sqlite_error_and_confidence_parsing(tmp_path: Path) -> None:
    db_path = tmp_path / "lexicon.sqlite3"
    _bootstrap_full_schema(db_path)
    entry_id = _insert_custom_entry(
        db_path,
        category="Verb",
        value="run",
        source="manual",
        status="approved",
        request_id="req-1",
        confidence=None,
    )
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            """
            INSERT INTO lexicon_entries(category, value, normalized, source, confidence, request_id, status)
            VALUES ('Verb', 'walk', 'walk', 'manual', 'bad-float', 'req-2', 'approved')
            """
        )
        conn.commit()
    store = SqliteLexiconManagementStore(db_path)
    assert store.get_entry(9999) is None
    row = store.get_entry(entry_id)
    assert row is not None and row.confidence is None
    bad_conf = store.search_entries(LexiconQuery(value_filter="walk"))
    assert len(bad_conf.rows) == 1
    assert bad_conf.rows[0].confidence is None

    broken = tmp_path / "broken.sqlite3"
    broken.write_text("no sqlite", encoding="utf-8")
    assert SqliteLexiconManagementStore(broken).get_entry(1) is None


def test_management_store_delete_entries_multi_message_and_sqlite_error(tmp_path: Path) -> None:
    db_path = tmp_path / "lexicon.sqlite3"
    _bootstrap_lexicon_entries(db_path)
    first = _insert_entry(db_path, value="one")
    second = _insert_entry(db_path, value="two")
    store = SqliteLexiconManagementStore(db_path)
    multi = store.delete_entries(LexiconDeleteRequest(entry_ids=[first, second]))
    assert multi.success is True
    assert multi.message == "Deleted 2 selected rows."

    broken = tmp_path / "broken.sqlite3"
    broken.write_text("no sqlite", encoding="utf-8")
    failed = SqliteLexiconManagementStore(broken).delete_entries(LexiconDeleteRequest(entry_ids=[1]))
    assert failed.success is False
    assert "Delete failed:" in failed.message


def test_management_store_cache_and_private_branches(tmp_path: Path) -> None:
    db_path = tmp_path / "lexicon.sqlite3"
    _bootstrap_lexicon_entries(db_path)
    _insert_entry(db_path, value="alpha")
    store = SqliteLexiconManagementStore(db_path)

    # Force stable stamp to hit cached snapshot return path.
    store._db_stat_stamp = lambda: (1, 1)  # type: ignore[method-assign]
    with sqlite3.connect(db_path) as conn:
        conn.row_factory = sqlite3.Row
        first = store._get_summary_snapshot(conn)
        second = store._get_summary_snapshot(conn)
    assert first is second

    # Branch with no lexicon_categories table.
    no_cat_db = tmp_path / "no_cat.sqlite3"
    _bootstrap_lexicon_entries(no_cat_db)
    _insert_entry(no_cat_db, value="beta")
    no_cat_store = SqliteLexiconManagementStore(no_cat_db)
    with sqlite3.connect(no_cat_db) as conn:
        conn.row_factory = sqlite3.Row
        snap = no_cat_store._get_summary_snapshot(conn)
    assert "Auto Added" in snap.available_categories

    # _has_index cache hit branch.
    with sqlite3.connect(no_cat_db) as conn:
        first_check = no_cat_store._has_index(conn, "missing_idx")
        second_check = no_cat_store._has_index(conn, "missing_idx")
    assert first_check is False and second_check is False

    # _db_stat_stamp OSError fallback.
    class _BadPath:
        def stat(self):  # noqa: ANN001
            raise OSError("no stat")

    no_cat_store._db_path = _BadPath()  # type: ignore[assignment]
    assert no_cat_store._db_stat_stamp() == (0, 0)


def test_management_store_resolve_index_early_returns_and_category_list_error(tmp_path: Path) -> None:
    db_path = tmp_path / "lexicon.sqlite3"
    _bootstrap_lexicon_entries(db_path)
    _insert_entry(db_path, value="alpha")
    store = SqliteLexiconManagementStore(db_path)

    with sqlite3.connect(db_path) as conn:
        assert (
            store._resolve_forced_sort_profile_index_name(
                conn=conn,
                status_filter="approved",
                source_filter="all",
                category_filter="Verb",
                value_filter="",
                request_filter="",
                id_min=None,
                id_max=None,
                reviewed_by_filter="",
                sort_by="value",
                sort_direction="desc",
            )
            == ""
        )
        assert (
            store._resolve_forced_sort_profile_index_name(
                conn=conn,
                status_filter="all",
                source_filter="manual",
                category_filter="Verb",
                value_filter="",
                request_filter="",
                id_min=None,
                id_max=None,
                reviewed_by_filter="",
                sort_by="id",
                sort_direction="desc",
            )
            == ""
        )
        assert (
            store._resolve_forced_sort_profile_index_name(
                conn=conn,
                status_filter="approved",
                source_filter="manual",
                category_filter="",
                value_filter="",
                request_filter="",
                id_min=None,
                id_max=None,
                reviewed_by_filter="",
                sort_by="id",
                sort_direction="desc",
            )
            == ""
        )
        assert (
            store._resolve_forced_sort_profile_index_name(
                conn=conn,
                status_filter="approved",
                source_filter="manual",
                category_filter="Verb",
                value_filter="",
                request_filter="",
                id_min=1,
                id_max=None,
                reviewed_by_filter="",
                sort_by="id",
                sort_direction="desc",
            )
            == ""
        )
        assert (
            store._resolve_forced_sort_profile_index_name(
                conn=conn,
                status_filter="approved",
                source_filter="manual",
                category_filter="Verb",
                value_filter="",
                request_filter="",
                id_min=None,
                id_max=None,
                reviewed_by_filter="",
                sort_by="id",
                sort_direction="desc",
            )
            == ""
        )

    # _list_categories_with_connection sqlite error branch.
    conn = sqlite3.connect(db_path)
    conn.close()
    assert store._list_categories_with_connection(conn) == ["Auto Added"]
