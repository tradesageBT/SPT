import os
import re
from contextlib import contextmanager
import psycopg2
import psycopg2.extras

DATABASE_URL = os.environ.get("DATABASE_URL", "").replace("postgres://", "postgresql://", 1)


class _Result:
    """Thin wrapper so callers can do .fetchall() / .fetchone() like sqlite3."""
    def __init__(self, cur):
        self._cur = cur

    def fetchall(self):
        rows = self._cur.fetchall()
        return [dict(r) for r in rows] if rows else []

    def fetchone(self):
        row = self._cur.fetchone()
        return dict(row) if row else None


class _Conn:
    """Makes psycopg2 look like sqlite3 so router code needs zero changes."""
    def __init__(self, conn):
        self._conn = conn

    @staticmethod
    def _adapt(sql):
        # sqlite3 positional: ? → %s
        # sqlite3 named:      :foo → %(foo)s
        sql = re.sub(r':(\w+)', r'%(\1)s', sql)
        sql = sql.replace("?", "%s")
        return sql

    def execute(self, sql, params=()):
        cur = self._conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        cur.execute(self._adapt(sql), params)
        return _Result(cur)

    def executemany(self, sql, params_seq):
        cur = self._conn.cursor()
        cur.executemany(self._adapt(sql), params_seq)
        return _Result(cur)

    def executescript(self, sql):
        cur = self._conn.cursor()
        for stmt in sql.split(";"):
            stmt = stmt.strip()
            if stmt:
                cur.execute(stmt)  # schema SQL — no param substitution needed

    def commit(self):
        self._conn.commit()

    def rollback(self):
        self._conn.rollback()

    def close(self):
        self._conn.close()


@contextmanager
def db():
    conn = psycopg2.connect(DATABASE_URL)
    wrapped = _Conn(conn)
    try:
        yield wrapped
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
                ppr             REAL DEFAULT 1.0,
                num_qbs         INTEGER DEFAULT 1,
                last_updated    TEXT
            );

            ALTER TABLE players_cache ADD COLUMN IF NOT EXISTS ppr REAL DEFAULT 1.0;
            ALTER TABLE players_cache ADD COLUMN IF NOT EXISTS num_qbs INTEGER DEFAULT 1;

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
                ppr                 REAL DEFAULT 1.0,
                tep                 REAL DEFAULT 0.0,
                last_synced_at      TEXT
            );

            ALTER TABLE leagues ADD COLUMN IF NOT EXISTS ppr REAL DEFAULT 1.0;
            ALTER TABLE leagues ADD COLUMN IF NOT EXISTS tep REAL DEFAULT 0.0;

            CREATE TABLE IF NOT EXISTS teams (
                id                      SERIAL PRIMARY KEY,
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

            ALTER TABLE teams ADD COLUMN IF NOT EXISTS positional_need TEXT;
            ALTER TABLE teams ADD COLUMN IF NOT EXISTS positional_rank TEXT;
            ALTER TABLE teams ADD COLUMN IF NOT EXISTS contention_category TEXT;
        """)
