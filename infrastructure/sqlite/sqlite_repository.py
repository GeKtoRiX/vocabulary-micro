from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import sqlite3
from typing import Any


class SqliteRepositoryError(RuntimeError):
    """Raised when SQLite read operations fail."""


@dataclass(frozen=True)
class SqliteTableSnapshot:
    name: str
    columns: list[str]
    rows: list[tuple[Any, ...]]


class SqliteExportRepository:
    def __init__(self, db_path: Path) -> None:
        self._db_path = Path(db_path)

    @property
    def db_path(self) -> Path:
        return self._db_path

    def read_table_snapshots(self) -> list[SqliteTableSnapshot]:
        try:
            with sqlite3.connect(self._db_path) as conn:
                conn.row_factory = sqlite3.Row
                table_rows = conn.execute(
                    """
                    SELECT name
                    FROM sqlite_master
                    WHERE type = 'table'
                      AND name NOT LIKE 'sqlite_%'
                    ORDER BY name ASC
                    """
                ).fetchall()
                table_names = [str(row["name"]).strip() for row in table_rows if str(row["name"]).strip()]

                snapshots: list[SqliteTableSnapshot] = []
                for table_name in table_names:
                    escaped_table = self._quote_identifier(table_name)
                    columns_info = conn.execute(f"PRAGMA table_info({escaped_table})").fetchall()
                    column_names = [
                        str(column["name"]).strip()
                        for column in columns_info
                        if str(column["name"]).strip()
                    ]

                    rows: list[tuple[Any, ...]] = []
                    if column_names:
                        for row in conn.execute(f"SELECT * FROM {escaped_table}"):
                            rows.append(tuple(row[column] for column in column_names))
                    snapshots.append(
                        SqliteTableSnapshot(
                            name=table_name,
                            columns=column_names,
                            rows=rows,
                        )
                    )
                return snapshots
        except sqlite3.Error as exc:
            raise SqliteRepositoryError(str(exc)) from exc

    def _quote_identifier(self, value: str) -> str:
        return '"' + str(value).replace('"', '""') + '"'
