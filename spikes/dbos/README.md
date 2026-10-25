# DBOS spike

Phase 0 checks that Whisperwind's kernel can be built on DBOS Transact (ADR 0002). This directory holds the spike code. It isn't part of the package: phase P1 ports what survives into `src/whisperwind/` and deletes `spikes/`.

DBOS is pinned exactly (`dbos==3.3.0`) in the `spike` dependency group, because the crash points wrap private DBOS methods.

```sh
uv run --group spike pytest spikes -q
```

## First slice (#34)

`dbos_slice.py` is one sequential flow on DBOS with SQLite: an `agent` step on the fake harness that plans, then rounds of an `agent` step and a `shell` step until the tests pass on the second round. One process runs one run, and the run ID doubles as the DBOS workflow ID and executor ID. Agent steps write a `session_started` event to a `whw_events` table in DBOS's SQLite file.

The crash suite (`crash_suite.py`, run by `test_crash_suite.py`; see below) finds every crash point a clean run of the slice passes: before and after each DBOS write (workflow start, each step checkpoint, workflow outcome) and each event write, 20 in all. For each point, it kills a fresh run there, resumes it in a new process, and checks the four things listed under the crash-injection suite below.

All 20 points pass. A mutation check (deleting the checkpoints before resuming) confirmed that the test reports reruns.

## Findings

Measured on macOS arm64 with Python 3.11 and DBOS 3.3.0.

1. **Resume works.** Relaunching with the run's executor ID recovered only that run. Recovery re-enqueues the workflow on an internal queue, and a background thread dispatches it. Several run processes on one SQLite file are not tested here (#36).
2. **Steps are at-least-once, and so are their events.** A step killed after its effect but before its checkpoint runs again, and repeats its event writes. A kill right after the `session_started` write produced that event twice. Event writes need an idempotency key, such as the step path, the event kind and a sequence number (#42).
3. **A rerun step can resume its harness session.** Before running, an agent step looks for the `session_started` event an earlier attempt wrote. If it finds one, it resumes that session instead of starting a new one (#43). The crash suite asserts this.
4. **Crash injection needs private API.** DBOS's own debug triggers fire only after a step commits and after a workflow starts. The spike wraps three `SystemDatabase` methods (`init_workflow`, `record_operation_result`, `update_workflow_outcome`), so the crash suite (#38) depends on DBOS internals and must pin DBOS exactly. Asking upstream for before-commit trigger points would remove that dependency.
5. **DBOS pickles by default.** Workflow inputs, outputs and step outputs are stored as base64 pickles. Reading them without DBOS means unpickling, which runs code from the database. DBOS also ships a portable JSON serializer (the `serializer` config key), which #41 and #42 should evaluate.
6. **Virtual time works in one process, not across a restart.** Under today's `run_virtual` loop, a workflow that calls `DBOS.sleep_async(86400)` finished in 0.18 s of real time. But DBOS records the sleep's wake time from `time.time()`, so a resumed run computes its remaining wait from the real clock. A durable `sleep` that tests can run instantly across a restart needs its own wake-time step on Whisperwind's `Clock`, or an injectable time source in DBOS (#46).
7. **DBOS fails the wheel policy on Python 3.15.** Its dependency pyyaml 6.0.3 publishes wheels only up to CPython 3.14, so `--only-binary :all:` fails on 3.15, and CI's wheel check would fail once DBOS is a runtime dependency. DBOS installs from wheels on 3.11 and 3.14.
8. **One license needs a compound entry.** greenlet (through SQLAlchemy) declares `MIT AND PSF-2.0`. Both parts are allowed, but the exact-match check rejects the expression until the allowlist names it. Everything else DBOS brings is allowed.
9. **Installed size grows from about 12.5 MiB to 48 MiB.** SQLAlchemy (17 MiB) and `psycopg_binary` (17 MiB) account for most of it. DBOS requires the Postgres driver even on SQLite.
10. **Importing DBOS costs about 120 ms; launching costs little.**
    - `import dbos` takes about 120 ms in-process (150 ms for a whole interpreter), about 50 ms of it SQLAlchemy.
    - `import whisperwind.cli` takes about 30 ms and doesn't import DBOS.
    - `DBOS.launch()` takes 7–10 ms on an existing database.

    Earlier in the same session, the same measurements came out three to four times higher, apparently because of load on the machine. Treat local timings as rough; the CI benchmark (#39 below) is the reference. Read-only commands stay under the 100 ms startup target only if they never import DBOS, which means reading SQLite directly, which in turn means finding 5 must be solved.
11. **Shutdown waits out a poll.** `DBOS.destroy()` takes about 1.0 s by default, because it waits for the notification listener's next poll (`notification_listener_polling_interval_sec`, 1.0 s). At 0.05 s it takes about 60 ms. That poll is also how a run notices a `send` from another process, so the interval trades shutdown time and answer latency against polling load. The slice uses 0.1 s.

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

The path syntax is provisional (#33). `review` is a fan-out of three branches, each an agent step and a shell step. `slow` runs two branches whose supervised shell step holds a 30-second process. `test_scopes.py` covers V1, V5 and V6. The crash suite kills and resumes the fan-out at each of its 48 crash points, which include child-workflow starts and awaits of a child's result.

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

## Paused runs: edits and human waits (#37)

`paused.py` runs a flow loaded from a file:
- `agent` records a fingerprint of its prompt with its checkpoint, and both `agent` and `shell` map DBOS's step-mismatch error to a path;
- `human` waits on `DBOS.recv` for up to three days;
- a run still waiting after a few seconds exits with code 4, and `respond` answers it from another process.

`test_paused.py` pauses runs, edits or answers them, and resumes them.

### Findings

1. **V4 holds.**
   - When a `human` wait starts, DBOS records its deadline as a `DBOS.sleep` step holding the wall-clock wake time.
   - The process can then exit: the run stays PENDING with no process.
   - `DBOSClient.send` from another process stores the answer, and the next resume receives it with the deadline unchanged.
   - A run whose process is still waiting gets the answer 0.2–0.3 s after `send` returns. The answering process itself takes about 0.2 s.
2. **Resuming after an answer takes about 2.2 s** in a fresh process. Most of it is waiting: recovery dispatch waits for DBOS's internal queue to poll (1 s), then the result is polled for (#39).
3. **Nothing wakes a run whose deadline passes while it has no process.** `whw resume --due` (VISION.md §6.4) has to find runs whose recorded wake time has passed. The `DBOS.sleep` row stores the time as plain text, so SQL can read it without unpickling.
4. **V3 holds once the application version is pinned.**
   - DBOS's default version is an MD5 of every registered workflow's source. So any edit, even to a step the run hasn't reached, changes it, and recovery then skips the paused run forever. `test_paused.py` records this.
   - With `application_version` pinned per project, edited flows resume, and an edit to a step after the pause takes effect.
   - DBOS's alternative, patching (`enable_patching` and `DBOS.patch()`), makes flow authors write version branches, so it doesn't fit flows written by users.
5. **DBOS can't see an edit to a step that already ran,** because it replays by step number and function name. With the fingerprint check disabled, a run whose finished prompt was edited replayed the old result and succeeded. With it, the resume reports `agent#0: prompt changed since the run paused`.
6. **Inserting or removing a step before the pause shifts step numbers.** DBOS then raises `DBOSUnexpectedStepError` (`step 1, function _fingerprinted_agent_step was recorded when _shell_step was expected`), which the spike reports as `shell#0: a different step was recorded here`. Every primitive must catch it, or the workflow ends in ERROR.
7. **A divergence must not end the workflow.** `resume_workflow` skips workflows in ERROR as well as SUCCESS, so an errored run can't continue. The spike stops the run process without recording an outcome: the run stays PENDING, and reverting the edit resumes it. Accepting an edit to finished steps would mean forking from the step that diverged, which creates a new run ID (scope finding 5).
8. **DBOS's internal steps take step numbers too.** A `recv` with a timeout records its deadline at the next step number, and every await of a child's result is a step. So DBOS step numbers never line up with Whisperwind's per-kind ordinals (#33).

## Crash-injection suite (#38)

`crash_suite.py` is the V8 harness. A flow is described by the command that runs it against a working directory, plus its expected result. The harness:
1. runs the flow once uninterrupted, to list its crash points: before and after every DBOS write (workflow and child-workflow start, step checkpoint, await of a child's result, workflow outcome) and every event write;
2. for each point, kills a fresh run there, resumes it in a new process, and checks that:
   - the resumed run returns the uninterrupted run's result;
   - no step whose checkpoint was committed before the kill runs again;
   - every rerun agent step that had started a harness session resumes it;
   - no checkpointed step writes its session event twice.

`test_crash_suite.py` runs it over the sequential slice (20 crash points) and the three-branch fan-out (48), and checks one kill after a session started end to end. Every later primitive adds its flow here.

### Findings

1. **V8 holds** for the sequential slice and the fan-out: every kill resumes correctly.
2. **Each check has been seen to fail.**
   - Deleting a pending step's checkpoint before resuming makes the rerun check fire.
   - Turning off session resume makes the session check fire at exactly the six points where an agent step's session had started but its checkpoint hadn't been committed.
3. **A kill can't land inside a DBOS transaction.** The crash points sit before and after each write, and each write commits atomically. So the suite tests the windows between writes, not torn writes.
4. **It kills once per run.** A kill during recovery itself (dequeue, re-execution) isn't covered yet. Repeating kill-and-resume from each resumed state would cover it, at the cost of a run time quadratic in the number of points.
5. **The suite takes about 3 minutes in total:** 45 s for the sequential slice and 2.5 minutes for the fan-out. Each point costs a crash run and a resume, and the resume spends most of its time waiting about 1 s for DBOS's internal recovery queue to poll (#39).

## Benchmark baseline (#39)

`bench.py` measures each metric VISION.md §7.4 proposes, on the fake harness, and prints a Markdown table of the measurements next to their targets. The `bench` CI job runs it on Linux, writes the table to the job summary, and uploads the numbers as JSON. The benchmark records a baseline and never fails the build: making these targets gates is #60.

### Findings

Measured on macOS arm64 with Python 3.11 and DBOS 3.3.0.

| Metric | Target | Measured | Met |
|---|---|---|---|
| Overhead per step (checkpoint + event append) | ≤ 10 ms p95 | 0.70 ms p95, 0.64 ms mean | yes |
| Concurrent agent steps in one run | ≥ 200, loop lag ≤ 50 ms p99 | 200 branches waiting 1 s each finish in 1.25 s; loop lag 2 ms p99 | yes |
| RSS with 50 agents in flight | ≤ 150 MB | 81 MiB peak, 74 MiB before the fan-out | yes |
| Queue dispatch latency, DBOS's default 1 s poll | ≤ 1 s p95 | 1.96 s p95, 1.41 s median | **no** |
| Queue dispatch latency, 0.1 s poll | ≤ 1 s p95 | 0.73 s p95, 0.18 s median | yes |
| Steps per run | 10,000 | 10,000 steps in 6.6 s, with no slowdown by the end; 8.1 MiB database | yes |
| Recovery of a run with 1,000 completed steps | ≤ 1 s | 1.30 s from spawn to the next step | **no** |
| `whw status` cold start, reading SQLite directly | ≤ 100 ms | 10 ms | yes |
| `whw status` cold start, through `DBOSClient` | ≤ 100 ms | 161 ms | **no** |

1. **V7 holds where the configuration is Whisperwind's.** Per-step overhead is far inside its target. Queue dispatch meets its target once Whisperwind registers its queues with a 0.1 s poll instead of DBOS's default 1 s.
2. **Recovery misses its target because of DBOS's internal queue, not replay.** Timing a resume's phases:
   - imports finish at 0.14 s;
   - the run is re-enqueued for recovery at 0.15 s;
   - the internal queue dequeues it at 1.14 s;
   - replaying the 1,000 checkpointed steps then takes about 0.15 s.

   The internal queue polls every second, and DBOS exposes no setting for it. The same wait makes every resume take over a second (paused-run finding 2). Meeting the target needs either a configurable internal-queue poll upstream, or a revised target in VISION.md. That revision is the owner's call.
3. **`whw status` must not go through DBOS.** A fresh interpreter that reads SQLite with stdlib `sqlite3` takes 10 ms; one that lists workflows through `DBOSClient` takes 161 ms, most of it importing DBOS. That makes the portable serializer (first-slice finding 5) a requirement for any status that shows step outputs.
4. **Fan-out width costs little.** 50 and 200 branches each finished within 0.25 s of the 1 s their agents wait, with event-loop lag of 2 ms at p99. Wider fan-outs and the rest of the concurrency targets are P2 (#60).
