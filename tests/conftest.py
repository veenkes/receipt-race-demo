import os

import psycopg
import pytest

from receipts import init_schema

DEFAULT_DATABASE_URL = "postgresql://postgres:postgres@localhost:5432/receipts"


@pytest.fixture
def db_url() -> str:
    url = os.environ.get("DATABASE_URL", DEFAULT_DATABASE_URL)
    with psycopg.connect(url, autocommit=True) as conn:
        conn.execute("DROP TABLE IF EXISTS receipts")
        conn.execute("DROP TABLE IF EXISTS jobs")
        init_schema(conn)
    return url
