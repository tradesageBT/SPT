"""
Simple event logging to Postgres.
All writes are fire-and-forget — never raise, never block a request.
"""
import traceback
from database import db


def log(event: str, data: dict | None = None, ip: str | None = None):
    try:
        with db() as conn:
            conn.execute(
                """
                INSERT INTO events (event, data, ip, created_at)
                VALUES (?, ?, ?, NOW())
                """,
                (event, __import__("json").dumps(data or {}), ip),
            )
    except Exception:
        traceback.print_exc()  # print but never crash the caller


def init_events_table():
    try:
        with db() as conn:
            conn.executescript("""
                CREATE TABLE IF NOT EXISTS events (
                    id         SERIAL PRIMARY KEY,
                    event      TEXT NOT NULL,
                    data       TEXT,
                    ip         TEXT,
                    created_at TIMESTAMPTZ DEFAULT NOW()
                )
            """)
    except Exception:
        traceback.print_exc()
