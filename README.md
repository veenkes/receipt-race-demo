# receipt-race-demo

A small, self-contained demo of a test-first fix for a race between a stage worker and a watchdog. It was built to show the process: add a deterministic failing test, then fix the helper so the same test goes green.

## The bug

A job can end in only one of two ways. The stage worker finishes it (`done`), or the watchdog expires it (`timeout`). Whichever happens first should write a single terminal receipt. The other caller should see that a receipt already exists and back off.

The original helper did this in two steps:

1. `SELECT` to see whether a terminal receipt already exists
2. `INSERT` a new receipt if that read found nothing

That is a classic check-then-act race. If the worker and the watchdog both run the `SELECT` before either `INSERT` commits, both see an empty table and both write a receipt. The job then has two terminal outcomes at once.

## The test

`tests/test_receipt_race.py` does not sleep and does not retry. It injects a `threading.Barrier` into both callers so they have to finish the "is there a receipt?" read before either one writes. Then it asserts there is exactly one terminal receipt, and that only one caller was told it wrote that receipt.

On the unfixed code this test fails. After the fix it passes.

## The fix

A unique constraint on `receipts.job_id` makes "one terminal receipt per job" a database invariant. Both the worker and the watchdog still call the same helper. The helper now does one atomic statement:

```sql
INSERT INTO receipts (job_id, kind)
VALUES (...)
ON CONFLICT (job_id) DO NOTHING
```

and checks `rowcount`. Only the first writer succeeds. The second is a no-op. There is no window between the check and the write because they are the same statement.

The change lands in pull request [#1](https://github.com/veenkes/receipt-race-demo/pull/1). CI is red on the test commit (`e312c2f`, [failing run](https://github.com/veenkes/receipt-race-demo/actions/runs/43726904846)) and green on the fix commit (`1be9a78`, [passing run](https://github.com/veenkes/receipt-race-demo/actions/runs/43727002635)).

## How to run it

You need Python 3.12+ and PostgreSQL (16 is what CI uses).

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

# If the database does not exist yet:
createdb receipts

export DATABASE_URL=postgresql://postgres:postgres@localhost:5432/receipts
pytest
```

GitHub Actions runs the same `pytest` command against a `postgres:16` service container on every push.
