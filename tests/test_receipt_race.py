import threading

import psycopg

from receipts import ReceiptStore, create_job, expire_job, finish_stage


def test_done_and_timeout_race_records_exactly_one_receipt(db_url: str) -> None:
    """Both callers must see "no receipt" before either writes.

    A barrier is injected after the existence check so the worker and the
    watchdog cannot sneak past each other. There is no sleep and no retry.
    """
    job_id = "job-race"
    with psycopg.connect(db_url) as setup:
        create_job(setup, job_id)

    barrier = threading.Barrier(2)
    outcomes: dict[str, bool] = {}
    errors: list[BaseException] = []

    def run(kind: str, record) -> None:
        try:
            conn = psycopg.connect(db_url)
            try:
                store = ReceiptStore(conn, after_check=barrier.wait)
                outcomes[kind] = record(store, job_id)
            finally:
                conn.close()
        except BaseException as exc:  # noqa: BLE001 - surface thread failures in the test
            errors.append(exc)

    worker = threading.Thread(target=run, args=("done", finish_stage), name="stage-worker")
    watchdog = threading.Thread(target=run, args=("timeout", expire_job), name="watchdog")
    worker.start()
    watchdog.start()
    worker.join()
    watchdog.join()

    assert errors == [], f"worker threads failed: {errors!r}"
    assert set(outcomes) == {"done", "timeout"}

    with psycopg.connect(db_url) as conn:
        kinds = [
            row[0]
            for row in conn.execute(
                "SELECT kind FROM receipts WHERE job_id = %s ORDER BY id",
                (job_id,),
            )
        ]

    assert len(kinds) == 1, f"expected exactly one terminal receipt, got {kinds}"
    assert kinds[0] in ("done", "timeout")
    assert sum(1 for won in outcomes.values() if won) == 1
