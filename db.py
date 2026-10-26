"""PostgreSQL connection pool + tiny SQL migration runner.

DATABASE_URL example: postgresql://incident:password@localhost:5432/incidents
Migrations live in ./migrations/NNN_name.sql and are applied once, in filename order. The token {{EMBED_DIM}}
in a migration is replaced with EMBED_DIM (the embedding vector size), so it must match your embedding model.
"""
import os
import re
import threading
from contextlib import contextmanager
from pathlib import Path

import psycopg
from psycopg.rows import dict_row
from psycopg_pool import ConnectionPool, PoolTimeout

import rag_config

MIGRATIONS = Path(__file__).parent / "migrations"
_pool = None
_pool_lock = threading.Lock()


def database_url() -> str:
    return os.getenv("DATABASE_URL", "postgresql://incident:incident@localhost:5432/incidents")


def pool() -> ConnectionPool:
    global _pool
    with _pool_lock:
        if _pool is None:
            _pool = ConnectionPool(
                database_url(), min_size=1, max_size=int(os.getenv("DB_POOL_MAX", "10")),
                timeout=float(os.getenv("DB_CONNECT_TIMEOUT", "8")),
                kwargs={"row_factory": dict_row, "options": "-c timezone=UTC"}, open=True)
        return _pool


def close_pool():
    global _pool
    with _pool_lock:
        if _pool is not None:
            _pool.close()
            _pool = None


@contextmanager
def conn():
    """A transaction: commits when the block ends normally, rolls back if it raises."""
    with pool().connection() as c:
        yield c


class DatabaseUnavailable(RuntimeError):
    pass


def safe_url() -> str:
    return re.sub(r"://([^:/@]+):[^@]*@", r"://\1:***@", database_url())      # never print the password


def check_connection():
    """Fail fast with an actionable one-line error instead of a 30-second hang and a stack trace."""
    try:
        with conn() as c:
            c.execute("SELECT 1")
    except (PoolTimeout, psycopg.OperationalError) as e:
        close_pool()
        raise DatabaseUnavailable(
            f"Cannot connect to PostgreSQL at {safe_url()}. Check that Postgres is running (systemctl status postgresql), "
            f"that DATABASE_URL in .env is right, and that the user, password and database exist. ({type(e).__name__})") from None


def migrate():
    check_connection()
    with conn() as c:
        c.execute("SELECT pg_advisory_xact_lock(727001)")          # two app processes starting together won't race
        c.execute("CREATE TABLE IF NOT EXISTS schema_migrations "
                  "(version text PRIMARY KEY, applied_at timestamptz NOT NULL DEFAULT now())")
        done = {r["version"] for r in c.execute("SELECT version FROM schema_migrations")}
        for f in sorted(MIGRATIONS.glob("*.sql")):
            if f.name in done:
                continue
            c.execute(f.read_text(encoding="utf-8").replace("{{EMBED_DIM}}", str(rag_config.embed_dim())))
            c.execute("INSERT INTO schema_migrations (version) VALUES (%s)", (f.name,))


def vector_dim():
    """Dimension of document_chunks.embedding as created, or None if the table doesn't exist."""
    with conn() as c:
        row = c.execute(
            "SELECT a.atttypmod AS d FROM pg_attribute a WHERE a.attrelid = to_regclass('document_chunks') "
            "AND a.attname = 'embedding' AND NOT a.attisdropped").fetchone()
    return row["d"] if row else None
