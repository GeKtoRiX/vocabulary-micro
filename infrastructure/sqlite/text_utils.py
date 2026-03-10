from __future__ import annotations

import re
import sqlite3


TOKEN_PATTERN = re.compile(r"[^\W\d_]+(?:[-'][^\W\d_]+)*", re.UNICODE)
CYRILLIC_PATTERN = re.compile(r"[\u0400-\u04FF]")
WEIRD_UNICODE_PATTERN = re.compile(r"[\u200b-\u200f\u202a-\u202e\ufeff]")

# Broader non-Latin script detector: covers Cyrillic, Hebrew, Arabic, Devanagari,
# Japanese kana, CJK (Chinese/Japanese/Korean), and Hangul (Korean).
# Used by is_english() / _is_english_text() to reject definitively non-English input.
NON_LATIN_SCRIPT_PATTERN = re.compile(
    r"["
    r"\u0400-\u04FF"   # Cyrillic
    r"\u0590-\u05FF"   # Hebrew
    r"\u0600-\u06FF"   # Arabic
    r"\u0900-\u097F"   # Devanagari
    r"\u3040-\u30FF"   # Hiragana + Katakana
    r"\u3400-\u4DBF"   # CJK Extension A
    r"\u4E00-\u9FFF"   # CJK Unified Ideographs
    r"\uAC00-\uD7AF"   # Hangul Syllables
    r"\uF900-\uFAFF"   # CJK Compatibility Ideographs
    r"]"
)

_IDENTIFIER_RE = re.compile(r"^[a-zA-Z_][a-zA-Z0-9_]*$")


def normalize_whitespace(value: str) -> str:
    return re.sub(r"\s+", " ", value).strip()


def looks_like_weird_unicode(value: str) -> bool:
    return WEIRD_UNICODE_PATTERN.search(value) is not None


def sync_sqlite_sequence(conn: sqlite3.Connection, *, table_name: str) -> None:
    """Resync sqlite_sequence counter for an AUTOINCREMENT table after a delete.

    Must be called within an active transaction for atomic behaviour.
    """
    if not _IDENTIFIER_RE.match(table_name):
        raise ValueError(f"Invalid table name: {table_name!r}")
    row = conn.execute(
        f"SELECT COALESCE(MAX(id), 0) FROM {table_name}"  # noqa: S608 – table_name validated above
    ).fetchone()
    max_id = int(row[0]) if row is not None else 0
    if max_id <= 0:
        conn.execute("DELETE FROM sqlite_sequence WHERE name = ?", (table_name,))
        return
    cursor = conn.execute(
        "UPDATE sqlite_sequence SET seq = ? WHERE name = ?",
        (max_id, table_name),
    )
    if int(cursor.rowcount if cursor.rowcount is not None else 0) <= 0:
        conn.execute(
            "INSERT INTO sqlite_sequence(name, seq) VALUES (?, ?)",
            (table_name, max_id),
        )


def safe_ensure_column(
    conn: sqlite3.Connection,
    *,
    table_name: str,
    column_name: str,
    column_def: str,
) -> None:
    """Add a column to a table if it does not already exist.

    Validates table_name and column_name against a strict identifier pattern
    to prevent SQL injection via dynamic DDL statements.
    """
    if not _IDENTIFIER_RE.match(table_name):
        raise ValueError(f"Invalid table name: {table_name!r}")
    if not _IDENTIFIER_RE.match(column_name):
        raise ValueError(f"Invalid column name: {column_name!r}")
    rows = conn.execute(f"PRAGMA table_info({table_name});").fetchall()
    existing = {str(row["name"]) if isinstance(row, sqlite3.Row) else str(row[1]) for row in rows}
    if column_name in existing:
        return
    conn.execute(f"ALTER TABLE {table_name} ADD COLUMN {column_name} {column_def};")
