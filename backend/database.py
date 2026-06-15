import sqlite3
import os
from contextlib import contextmanager

DB_PATH = os.path.join(os.path.dirname(__file__), "..", "spt.db")


def get_connection():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    return conn


@contextmanager
def db():
    conn = get_connection()
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def init_db():
    with db() as conn:
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS players_cache (
                sleeper_id      TEXT PRIMARY KEY,
                name            TEXT,
                position        TEXT,
                nfl_team        TEXT,
                age             REAL,
                years_exp       INTEGER,
                fc_value        INTEGER DEFAULT 0,
                last_updated    TEXT
            );

            CREATE TABLE IF NOT EXISTS picks_cache (
                pick_key        TEXT PRIMARY KEY,
                season          INTEGER,
                round           INTEGER,
                subtype         TEXT,
                fc_value        INTEGER DEFAULT 0,
                last_updated    TEXT
            );

            CREATE TABLE IF NOT EXISTS leagues (
                sleeper_league_id   TEXT PRIMARY KEY,
                league_name         TEXT,
                season              TEXT,
                scoring_settings    TEXT,
                roster_positions    TEXT,
                num_qbs             INTEGER DEFAULT 1,
                last_synced_at      TEXT
            );

            CREATE TABLE IF NOT EXISTS teams (
                id                      INTEGER PRIMARY KEY AUTOINCREMENT,
                sleeper_league_id       TEXT NOT NULL,
                roster_id               INTEGER NOT NULL,
                owner_id                TEXT,
                display_name            TEXT,
                avatar                  TEXT,
                total_value             INTEGER DEFAULT 0,
                player_value            INTEGER DEFAULT 0,
                pick_value              INTEGER DEFAULT 0,
                starter_value           INTEGER DEFAULT 0,
                bench_value             INTEGER DEFAULT 0,
                positional_breakdown    TEXT,
                positional_surplus      TEXT,
                contention_score        REAL DEFAULT 0.5,
                roster_data             TEXT,
                computed_at             TEXT,
                UNIQUE(sleeper_league_id, roster_id)
            );
        """)
