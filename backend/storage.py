"""SQLite storage for scan history."""

from __future__ import annotations

import os
import sqlite3
from contextlib import closing, contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator

DEFAULT_PATH = Path(__file__).resolve().parent / "netlens.db"

COLUMNS = (
    "timestamp",
    "score",
    "status",
    "where_problem",
    "latency_ms",
    "jitter_ms",
    "packet_loss",
    "dns_ms",
    "download_mbps",
    "upload_mbps",
    "gateway_ms",
    "gateway_loss",
)


def db_path() -> Path:
    return Path(os.getenv("NETLENS_DB", str(DEFAULT_PATH)))


@contextmanager
def _connect() -> Iterator[sqlite3.Connection]:
    with closing(sqlite3.connect(db_path())) as connection:
        connection.row_factory = sqlite3.Row
        with connection:
            yield connection


def init_db() -> None:
    with _connect() as connection:
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS scans (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp TEXT NOT NULL,
                score INTEGER NOT NULL,
                status TEXT NOT NULL,
                where_problem TEXT,
                latency_ms REAL,
                jitter_ms REAL,
                packet_loss REAL,
                dns_ms REAL,
                download_mbps REAL,
                upload_mbps REAL,
                gateway_ms REAL,
                gateway_loss REAL
            )
            """
        )
        _migrate_legacy(connection)


def _migrate_legacy(connection: sqlite3.Connection) -> None:
    """Copy rows from the v0.1 ``diagnostics`` table once.

    v0.1 download speeds were simulated, so they are not carried over.
    """
    legacy = connection.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='diagnostics'"
    ).fetchone()
    if not legacy:
        return
    has_rows = connection.execute("SELECT 1 FROM scans LIMIT 1").fetchone()
    if not has_rows:
        connection.execute(
            """
            INSERT INTO scans (timestamp, score, status, latency_ms, packet_loss, dns_ms)
            SELECT timestamp, score, status, latency_ms, packet_loss, dns_ms
            FROM diagnostics ORDER BY id
            """
        )
    connection.execute("ALTER TABLE diagnostics RENAME TO diagnostics_v01")


def save_scan(result: dict[str, Any]) -> int:
    metrics = result["metrics"]
    row = {
        "timestamp": result.get("timestamp") or datetime.now(timezone.utc).isoformat(),
        "score": result["score"],
        "status": result["status"],
        "where_problem": result["location"]["where"],
        **{key: metrics.get(key) for key in COLUMNS[4:]},
    }
    with _connect() as connection:
        cursor = connection.execute(
            f"INSERT INTO scans ({', '.join(COLUMNS)}) VALUES ({', '.join('?' * len(COLUMNS))})",
            [row[column] for column in COLUMNS],
        )
        return int(cursor.lastrowid)


def history(limit: int = 50) -> list[dict[str, Any]]:
    with _connect() as connection:
        rows = connection.execute(
            f"SELECT id, {', '.join(COLUMNS)} FROM scans ORDER BY id DESC LIMIT ?",
            (limit,),
        ).fetchall()
    return [dict(row) for row in reversed(rows)]


def clear_history() -> int:
    with _connect() as connection:
        return connection.execute("DELETE FROM scans").rowcount
