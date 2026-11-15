"""Stage worker and watchdog share one helper to record a job's terminal receipt."""

from __future__ import annotations

from collections.abc import Callable
from typing import Literal

import psycopg

TerminalKind = Literal["done", "timeout"]
AfterCheckHook = Callable[[], None]


SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS jobs (
    id TEXT PRIMARY KEY,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS receipts (
    id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    job_id TEXT NOT NULL REFERENCES jobs(id),
    kind TEXT NOT NULL CHECK (kind IN ('done', 'timeout')),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
"""


def init_schema(conn: psycopg.Connection) -> None:
    conn.execute(SCHEMA_SQL)
    if not conn.autocommit:
        conn.commit()


def create_job(conn: psycopg.Connection, job_id: str) -> None:
    conn.execute("INSERT INTO jobs (id) VALUES (%s)", (job_id,))
    if not conn.autocommit:
        conn.commit()


class ReceiptStore:
    """Persists terminal receipts for jobs.

    after_check is a test seam. It runs after the "does a receipt already
    exist?" read and before the write, so a test can hold both callers
    there at the same time.
    """

    def __init__(
        self,
        conn: psycopg.Connection,
        after_check: AfterCheckHook | None = None,
    ) -> None:
        self._conn = conn
        self._after_check = after_check

    def try_record_terminal(self, job_id: str, kind: TerminalKind) -> bool:
        """Record a terminal receipt if the job does not already have one.

        Returns True if this caller wrote the receipt, False if one already
        existed.
        """
        if kind not in ("done", "timeout"):
            raise ValueError(f"unsupported receipt kind: {kind!r}")

        with self._conn.cursor() as cur:
            cur.execute(
                """
                SELECT 1
                  FROM receipts
                 WHERE job_id = %s
                 LIMIT 1
                """,
                (job_id,),
            )
            already_present = cur.fetchone() is not None
            if self._after_check is not None:
                self._after_check()
            if already_present:
                self._conn.commit()
                return False
            cur.execute(
                """
                INSERT INTO receipts (job_id, kind)
                VALUES (%s, %s)
                """,
                (job_id, kind),
            )
        self._conn.commit()
        return True


def finish_stage(store: ReceiptStore, job_id: str) -> bool:
    """Stage worker path: the job finished successfully."""
    return store.try_record_terminal(job_id, "done")


def expire_job(store: ReceiptStore, job_id: str) -> bool:
    """Watchdog path: the job ran too long and timed out."""
    return store.try_record_terminal(job_id, "timeout")
