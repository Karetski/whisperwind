# DBOS spike

Phase 0 checks that Whisperwind's kernel can be built on DBOS Transact (ADR 0002). This directory holds the spike code. It isn't part of the package: phase P1 ports what survives into `src/whisperwind/` and deletes `spikes/`.

DBOS is pinned exactly (`dbos==3.3.0`) in the `spike` dependency group, because the crash points wrap private DBOS methods.

```sh
uv run --group spike pytest spikes -q
```

## First slice (#34)

`dbos_slice.py` is one sequential flow on DBOS with SQLite: an `agent` step on the fake harness that plans, then rounds of an `agent` step and a `shell` step until the tests pass on the second round. One process runs one run, and the run ID doubles as the DBOS workflow ID and executor ID. Agent steps write a `session_started` event to a `whw_events` table in DBOS's SQLite file.

`test_dbos_slice.py` finds every crash point a clean run passes: before and after each DBOS write (workflow start, each step checkpoint, workflow outcome) and each event write, 20 in all. For each point, it kills a fresh run there, resumes it in a new process, and checks four things:

- the resumed run returns the same result;
- no step whose checkpoint was committed before the kill runs again;
- every step ran;
- no checkpointed step's event was written twice.

All 20 points pass. A mutation check (deleting the checkpoints before resuming) confirmed that the test reports reruns.

## Findings

Measured on macOS arm64 with Python 3.11 and DBOS 3.3.0.

1. **Resume works.** Relaunching with the run's executor ID recovered only that run. Recovery re-enqueues the workflow on an internal queue, and a background thread dispatches it. Several run processes on one SQLite file are not tested here (#36).
2. **Steps are at-least-once, and so are their events.** A step killed after its effect but before its checkpoint runs again, and repeats its event writes. A kill right after the `session_started` write produced that event twice. Event writes need an idempotency key, such as the step path, the event kind and a sequence number (#42).
3. **Harness sessions can survive a rerun.** Deriving the session ID from the run and step gives a rerun step the same session to resume (#43).
4. **Crash injection needs private API.** DBOS's own debug triggers fire only after a step commits and after a workflow starts. The spike wraps three `SystemDatabase` methods (`init_workflow`, `record_operation_result`, `update_workflow_outcome`), so the crash suite (#38) depends on DBOS internals and must pin DBOS exactly. Asking upstream for before-commit trigger points would remove that dependency.
5. **DBOS pickles by default.** Workflow inputs, outputs and step outputs are stored as base64 pickles. Reading them without DBOS means unpickling, which runs code from the database. DBOS also ships a portable JSON serializer (the `serializer` config key), which #41 and #42 should evaluate.
6. **Virtual time works in one process, not across a restart.** Under today's `run_virtual` loop, a workflow that calls `DBOS.sleep_async(86400)` finished in 0.18 s of real time. But DBOS records the sleep's wake time from `time.time()`, so a resumed run computes its remaining wait from the real clock. A durable `sleep` that tests can run instantly across a restart needs its own wake-time step on Whisperwind's `Clock`, or an injectable time source in DBOS (#46).
7. **DBOS fails the wheel policy on Python 3.15.** Its dependency pyyaml 6.0.3 publishes wheels only up to CPython 3.14, so `--only-binary :all:` fails on 3.15, and CI's wheel check would fail once DBOS is a runtime dependency. DBOS installs from wheels on 3.11 and 3.14.
8. **One license needs a compound entry.** greenlet (through SQLAlchemy) declares `MIT AND PSF-2.0`. Both parts are allowed, but the exact-match check rejects the expression until the allowlist names it. Everything else DBOS brings is allowed.
9. **Installed size grows from about 12.5 MiB to 48 MiB.** SQLAlchemy (17 MiB) and `psycopg_binary` (17 MiB) account for most of it. DBOS requires the Postgres driver even on SQLite.
10. **Importing DBOS costs about 0.4–0.5 s; launching costs little.**
    - `import dbos` takes 410–530 ms, about 170 ms of it SQLAlchemy.
    - `import whisperwind.cli` takes about 30 ms and doesn't import DBOS.
    - `DBOS.launch()` takes about 20 ms on an existing database, and 95 ms the first time, when it creates the schema.

    Read-only commands stay fast only if they never import DBOS, which means reading SQLite directly, which in turn means finding 5 must be solved.
11. **Shutdown waits out a poll.** `DBOS.destroy()` takes about 1.1 s by default, because it waits for the notification listener's next poll (`notification_listener_polling_interval_sec`, 1.0 s). At 0.05 s it takes about 140 ms. That poll is also how a run notices a `send` from another process, so the interval trades shutdown time and answer latency against polling load. The slice uses 0.1 s.
