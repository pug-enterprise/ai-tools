"""
SQLite schema and connection management.
All tables are created on first connect (idempotent).
"""

import sqlite3
import threading
from pathlib import Path

from config import settings

_local = threading.local()


def get_conn() -> sqlite3.Connection:
    """Return a thread-local SQLite connection."""
    if not hasattr(_local, "conn"):
        db_path = Path(settings.db_path)
        db_path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(str(db_path), check_same_thread=False)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        _local.conn = conn
        _create_schema(conn)
    return _local.conn


def _create_schema(conn: sqlite3.Connection) -> None:
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS articles (
            id          TEXT PRIMARY KEY,
            title       TEXT NOT NULL,
            url         TEXT NOT NULL,
            published_at TEXT NOT NULL,
            category    TEXT NOT NULL DEFAULT '',
            content     TEXT NOT NULL DEFAULT '',
            status      TEXT NOT NULL DEFAULT 'new',
            error       TEXT
        );

        CREATE TABLE IF NOT EXISTS summaries (
            id          TEXT PRIMARY KEY,
            article_id  TEXT NOT NULL REFERENCES articles(id),
            text        TEXT NOT NULL,
            created_at  TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS video_jobs (
            id              TEXT PRIMARY KEY,
            summary_id      TEXT NOT NULL REFERENCES summaries(id),
            openart_job_id  TEXT,
            video_url       TEXT,
            local_path      TEXT,
            status          TEXT NOT NULL DEFAULT 'pending',
            created_at      TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS tiktok_posts (
            id              TEXT PRIMARY KEY,
            video_job_id    TEXT NOT NULL REFERENCES video_jobs(id),
            post_mode       TEXT NOT NULL,
            tiktok_video_id TEXT,
            status          TEXT NOT NULL DEFAULT 'uploading',
            posted_at       TEXT
        );
    """)
    conn.commit()
