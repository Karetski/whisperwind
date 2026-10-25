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

## One process per run (#36)

`process_per_run.py` runs one of two flows per process, against a shared SQLite file:
- `steps`: N agent steps, each a DBOS checkpoint plus an event write;
- `fanout`: N child workflows on a queue with `global_concurrency=2`.

Each run uses either one shared DBOS application name or a name of its own. `test_process_per_run.py` asserts the two properties the process model relies on. `measure_process_per_run.py` reproduces the numbers below.

### Findings

Measured on macOS arm64 with Python 3.11 and DBOS 3.3.0.

1. **V2 holds only with an application name per run.** The executor ID alone isn't enough:
   - Startup recovery re-enqueues the run's pending workflows on DBOS's internal queue.
   - Every DBOS process always dequeues the internal queue, and `listen_queues` can't exclude it.
   - The dequeue filters by queue, status, application version and application name, but not by executor.

   So with a shared name, when four crashed runs resumed at once, one process executed all four in each of six trials, and in one trial two runs hung. With a name per run (`whisperwind-spike-<run>`), every run executed only in its own process in every trial. `test_process_per_run.py` asserts this, and fails when switched to a shared name.
2. **An application name per run has costs.**
   - Queue names must be unique across applications in one database, so a queue belongs to one run.
   - DBOS's listing APIs default to the caller's own application. Listing across runs needs an explicit list of names, a client with no application of its own, or a direct SQL read.
3. **A queue's global limit holds across processes, but its work doesn't stay home.** With three runs sharing a queue capped at 2:
   - peak concurrency stayed at 2;
   - 25–50% of children executed in another run's process;
   - in two of three trials a run hung, because a child was left PENDING under the executor of a process that had already exited.

   Draining on shutdown with `DBOS.destroy(workflow_completion_timeout_sec=30)` didn't prevent it: runs still hung in two of three trials. Per-host and per-harness caps across runs (#57) therefore can't use a shared DBOS queue under one process per run. They need either a long-lived worker that owns the queue (decision D9) or a cap mechanism of Whisperwind's own.
4. **Concurrent writers are fine.** Six runs of 100 steps each wrote one SQLite file at once:
   - 600 of 600 step outputs and 600 of 600 events landed;
   - no process failed;
   - no "database is locked" error appeared.
5. **DBOS leaves SQLite in rollback-journal mode, so Whisperwind must switch on WAL.** Without WAL, writers block readers:
   - a `whw status`-style reader polling with stdlib `sqlite3` saw p99 latency of 195–490 ms, against about 4 ms in WAL mode;
   - the same 600 steps took 5.5 s instead of 3.0 s.

   WAL persists in the file. `dbos_slice.run()` now switches it on before launching DBOS, so the rollback numbers come from runs made before that change.
6. **SQLite version.** DBOS uses `RETURNING`, which needs SQLite 3.35 or newer. uv-managed CPython 3.11, 3.12 and 3.15 bundle SQLite 3.53, Homebrew's 3.13 and 3.14 bundle 3.54, and macOS's system Python 3.9 bundles 3.51. python.org's installers were not checked. Distribution Pythons with an older SQLite (Ubuntu 20.04, RHEL 8) would fail, which the documented uv-managed install avoids.

## Scopes on child workflows (#35)

`scopes.py` holds every rule that maps a scope path onto DBOS:
- `parallel` runs each branch as a child workflow with the ID `<parent>/parallel#<n>/<i>`;
- `rerun` reruns one branch by forking.

The path syntax is provisional (#33). `review` is a fan-out of three branches, each an agent step and a shell step. `slow` runs two branches whose supervised shell step holds a 30-second process. `test_scopes.py` covers V1, V5, V6, and kill-and-resume at each of the fan-out's 48 crash points. The crash points now include child-workflow starts and awaits of a child's result.

### Findings

1. **V1 holds.**
   - Child workflows with caller-chosen IDs start concurrently from an async workflow on SQLite: the three branches' shell steps started less than 0.3 s apart, the time one of them takes.
   - DBOS accepts `/`, `#` and `~` in workflow IDs, and records each child's `parent_workflow_id`.
   - Every kill-and-resume of the fan-out returns the same result without rerunning a checkpointed step. A mutation check (deleting a pending branch's checkpoints) confirmed the test reports reruns.
2. **A branch must be a registered workflow with serializable inputs.** DBOS recovers each child workflow on its own, from its function and inputs, so `parallel` can't take arbitrary coroutines. For `parallel(agent(...), agent(...))` in VISION.md §5.1 to work, `agent(...)` must return a serializable step description that can run as a child workflow, or branches must be `@step` or `@flow` functions (#32).
3. **Scope ordinals are deterministic,** because the flow function re-executes from the top on recovery. The spike counts them per workflow ID in a module-level counter. The kernel should keep them in the workflow's own context, so re-executing a workflow twice in one process can't skew them.
4. **V5 holds, as a two-step fork.**
   - First, fork the branch from step k. The fork gets a new ID, `…/parallel#0/1~1`.
   - Then fork the parent from its first `DBOS.getResult` step, with `replacement_children` mapping the old branch to the new one.

   Only the branch's steps from k on, and the parent's steps after the fan-out, run again. Earlier steps and sibling branches are copied, not re-executed.
5. **A fork costs identity.**
   - Every fork has a new workflow ID, so rerunning a scope produces a new run ID (`run-1~1`), and a scope's path no longer equals its workflow ID. The path grammar (#33) must separate a scope's path from the fork or attempt that executed it.
   - A forked branch has no `parent_workflow_id`, so the run tree can't rely on DBOS's parent link after a rerun.
   - Choosing the parent's fork step means reading DBOS's step names (`DBOS.getResult`) from `operation_outputs`.
6. **V6 holds only with a supervisor.**
   - DBOS checks cancellation between steps. Cancelling a branch marks it CANCELLED, but a step already running keeps going: a plain shell step's process was still alive 17.8 s after the cancel.
   - A step that watches its own workflow's status every 0.1 s, in an AnyIO task group, and kills its process group on CANCELLED stopped the process within 0.2 s. AnyIO's task groups work inside a DBOS async step on the asyncio backend.
   - Polling costs one database read per running step per 0.1 s, about 2,000 reads a second at 200 concurrent steps. A per-process watcher or a DBOS notification would scale better (#39).
7. **A cancelled or failed branch doesn't stop its siblings.** When one branch was cancelled, the parent failed with ERROR while the other branch kept running. `parallel` must cancel or await its remaining branches when one fails (#56).
