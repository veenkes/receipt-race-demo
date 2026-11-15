import psycopg

from receipts import ReceiptStore, create_job, expire_job, finish_stage


def _kinds(conn: psycopg.Connection, job_id: str) -> list[str]:
    rows = conn.execute(
        "SELECT kind FROM receipts WHERE job_id = %s ORDER BY id",
        (job_id,),
    ).fetchall()
    return [row[0] for row in rows]


def test_stage_worker_records_a_done_receipt(db_url: str) -> None:
    with psycopg.connect(db_url) as conn:
        create_job(conn, "job-done")
        store = ReceiptStore(conn)
        assert finish_stage(store, "job-done") is True
        assert _kinds(conn, "job-done") == ["done"]


def test_second_writer_is_rejected_when_called_sequentially(db_url: str) -> None:
    with psycopg.connect(db_url) as conn:
        create_job(conn, "job-seq")
        store = ReceiptStore(conn)
        assert finish_stage(store, "job-seq") is True
        assert expire_job(store, "job-seq") is False
        assert _kinds(conn, "job-seq") == ["done"]
