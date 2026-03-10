from __future__ import annotations

from pathlib import Path
import sqlite3

from infrastructure.adapters.assignment_gateway import AssignmentSqliteStore


def test_assignment_store_persists_to_isolated_assignments_db(tmp_path: Path) -> None:
    assignments_db_path = tmp_path / "assignments.db"
    store = AssignmentSqliteStore(assignments_db_path)
    try:
        saved = store.save_assignment(
            title="Week 1",
            content_original="Original text",
            content_completed="Completed text",
        )
        rows = store.list_assignments(limit=10, offset=0)
    finally:
        store.close()

    assert saved.id > 0
    assert saved.title == "Week 1"
    assert saved.status == "PENDING"
    assert assignments_db_path.exists()
    assert len(rows) == 1
    assert rows[0].content_completed == "Completed text"
    assert rows[0].lexicon_coverage_percent == 0.0


def test_assignment_store_schema_does_not_create_lexicon_tables(tmp_path: Path) -> None:
    assignments_db_path = tmp_path / "assignments.db"
    store = AssignmentSqliteStore(assignments_db_path)
    store.close()

    with sqlite3.connect(assignments_db_path) as conn:
        tables = {
            str(row[0])
            for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            ).fetchall()
        }

    assert "assignments" in tables
    assert "assignment_audio" in tables
    assert "lexicon_entries" not in tables


def test_assignment_store_updates_status_and_coverage(tmp_path: Path) -> None:
    assignments_db_path = tmp_path / "assignments.db"
    store = AssignmentSqliteStore(assignments_db_path)
    try:
        saved = store.save_assignment(
            title="Week 2",
            content_original="Original",
            content_completed="Completed",
        )
        updated = store.update_assignment_status(
            assignment_id=saved.id,
            status="COMPLETED",
            lexicon_coverage_percent=95.5,
        )
    finally:
        store.close()

    assert updated is not None
    assert updated.status == "COMPLETED"
    assert updated.lexicon_coverage_percent == 95.5


def test_assignment_store_updates_content_and_can_fetch_row(tmp_path: Path) -> None:
    assignments_db_path = tmp_path / "assignments.db"
    store = AssignmentSqliteStore(assignments_db_path)
    try:
        saved = store.save_assignment(
            title="Draft",
            content_original="Original A",
            content_completed="Completed A",
        )
        updated = store.update_assignment_content(
            assignment_id=saved.id,
            title="Draft Updated",
            content_original="Original B",
            content_completed="Completed B",
        )
        fetched = store.get_assignment(assignment_id=saved.id)
    finally:
        store.close()

    assert updated is not None
    assert updated.title == "Draft Updated"
    assert updated.content_original == "Original B"
    assert updated.content_completed == "Completed B"
    assert fetched is not None
    assert fetched.title == "Draft Updated"
    assert fetched.content_completed == "Completed B"


def test_assignment_store_deletes_assignment(tmp_path: Path) -> None:
    assignments_db_path = tmp_path / "assignments.db"
    store = AssignmentSqliteStore(assignments_db_path)
    try:
        saved = store.save_assignment(
            title="Delete me",
            content_original="Original",
            content_completed="Completed",
        )
        deleted = store.delete_assignment(assignment_id=saved.id)
        fetched = store.get_assignment(assignment_id=saved.id)
    finally:
        store.close()

    assert deleted is True
    assert fetched is None


def test_assignment_store_preserves_full_multiline_assignment_text(tmp_path: Path) -> None:
    assignments_db_path = tmp_path / "assignments.db"
    store = AssignmentSqliteStore(assignments_db_path)
    original_text = "# Original\n\n- Task 1\n- Task 2\n"
    completed_text = "## Completed\n\n1. Fill in *phrasal verbs*.\n2. Add **idioms**.\n"
    try:
        saved = store.save_assignment(
            title="Markdown Assignment",
            content_original=original_text,
            content_completed=completed_text,
        )
        fetched = store.get_assignment(assignment_id=saved.id)
    finally:
        store.close()

    assert fetched is not None
    assert fetched.content_original == original_text
    assert fetched.content_completed == completed_text


def test_assignment_store_reuses_last_deleted_id(tmp_path: Path) -> None:
    assignments_db_path = tmp_path / "assignments.db"
    store = AssignmentSqliteStore(assignments_db_path)
    try:
        first = store.save_assignment(
            title="A1",
            content_original="O1",
            content_completed="C1",
        )
        second = store.save_assignment(
            title="A2",
            content_original="O2",
            content_completed="C2",
        )
        assert first.id == 1
        assert second.id == 2

        deleted = store.delete_assignment(assignment_id=second.id)
        recreated = store.save_assignment(
            title="A3",
            content_original="O3",
            content_completed="C3",
        )
    finally:
        store.close()

    assert deleted is True
    assert recreated.id == 2


def test_assignment_store_resets_sequence_after_delete_all(tmp_path: Path) -> None:
    assignments_db_path = tmp_path / "assignments.db"
    store = AssignmentSqliteStore(assignments_db_path)
    try:
        saved = store.save_assignment(
            title="Single",
            content_original="Original",
            content_completed="Completed",
        )
        assert saved.id == 1

        deleted = store.delete_assignment(assignment_id=saved.id)
        recreated = store.save_assignment(
            title="Again",
            content_original="Original2",
            content_completed="Completed2",
        )
    finally:
        store.close()

    assert deleted is True
    assert recreated.id == 1


def test_assignment_store_persists_assignment_audio_metadata_and_reads_latest(tmp_path: Path) -> None:
    assignments_db_path = tmp_path / "assignments.db"
    store = AssignmentSqliteStore(assignments_db_path)
    try:
        saved = store.save_assignment(
            title="Audio",
            content_original="Orig",
            content_completed="Completed",
        )
        first = store.save_audio_record(
            assignment_id=saved.id,
            audio_path="audio/a1.wav",
            audio_format="wav",
            voice="af_heart",
            style_preset="neutral",
            duration_sec=1.5,
            sample_rate=24_000,
        )
        second = store.save_audio_record(
            assignment_id=saved.id,
            audio_path="audio/a2.wav",
            audio_format="mp3",
            voice="af_heart",
            style_preset="narrator",
            duration_sec=2.2,
            sample_rate=24_000,
        )
        latest = store.get_latest_audio_record(assignment_id=saved.id)
        listed = store.list_audio_records(assignment_id=saved.id, limit=10, offset=0)
    finally:
        store.close()

    assert first.id > 0
    assert second.id > first.id
    assert latest is not None
    assert latest.id == second.id
    assert latest.audio_path == "audio/a2.wav"
    assert [row.id for row in listed] == [second.id, first.id]
    assert listed[0].audio_format == "mp3"
    assert listed[1].audio_format == "wav"
