"""SQLite storage for transcription history."""
import sqlite3
from datetime import datetime
from src.config import DB_PATH


def _get_conn() -> sqlite3.Connection:
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    """Create tables if not exist."""
    with _get_conn() as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS transcriptions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                text TEXT NOT NULL,
                language TEXT,
                duration_secs REAL,
                source_app TEXT,
                created_at TEXT NOT NULL DEFAULT (datetime('now', 'localtime'))
            )
        """)
        conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_created_at 
            ON transcriptions(created_at DESC)
        """)


def save_transcription(
    text: str,
    language: str | None = None,
    duration_secs: float | None = None,
    source_app: str | None = None,
) -> int:
    """Save a transcription and return its ID."""
    with _get_conn() as conn:
        cursor = conn.execute(
            """INSERT INTO transcriptions (text, language, duration_secs, source_app)
               VALUES (?, ?, ?, ?)""",
            (text, language, duration_secs, source_app),
        )
        return cursor.lastrowid


def get_recent(limit: int = 20) -> list[dict]:
    """Get recent transcriptions."""
    with _get_conn() as conn:
        rows = conn.execute(
            "SELECT * FROM transcriptions ORDER BY created_at DESC LIMIT ?",
            (limit,),
        ).fetchall()
        return [dict(r) for r in rows]


def search(query: str, limit: int = 20) -> list[dict]:
    """Full-text search transcriptions."""
    with _get_conn() as conn:
        rows = conn.execute(
            "SELECT * FROM transcriptions WHERE text LIKE ? ORDER BY created_at DESC LIMIT ?",
            (f"%{query}%", limit),
        ).fetchall()
        return [dict(r) for r in rows]
