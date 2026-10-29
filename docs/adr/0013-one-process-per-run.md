# 0013. One process per run, no daemon through T1

- Status: Accepted
- Date: 2026-10-28
- Decided by: the owner (D9 in `VISION.md` §15)
- Refs: `VISION.md` §6.4, §7.2, §11.1; `spikes/dbos/README.md` ("One process per run"); issue #36

## Context

At the local tiers (T0 laptop, T1 workstation or CI), Whisperwind runs one OS process per active run and needs no background service. A run waiting on a person has no process at all. Pre-pivot ADR 0008, "Scheduling is external", set the same no-daemon stance for the 0.1.x engine.

DBOS assumes long-lived application processes: when a process launches, it recovers its executor's pending workflows through an internal queue that every DBOS process dequeues. The Phase 0 spike ran several run processes on one SQLite file and found:
- **Recovery isolation:**
  - With the run ID as the executor ID but one shared DBOS application name, a process resuming its own run also executed other runs recovered at the same moment.
  - With an application name per run, each run executed only in its own process.
- **Cross-run queues:** a DBOS queue's global concurrency limit held across processes, but other runs' processes executed a run's children. A child was stranded when the process that took it exited, which hung the run in two of three trials.
- **Concurrent writes:** several processes writing one SQLite file concurrently lost no writes.
- **Reads:** DBOS leaves SQLite in rollback-journal mode, where writers block readers for hundreds of milliseconds. In WAL mode, a stdlib `sqlite3` reader stayed at a few milliseconds.

## Decision

- **No daemon is required through T1.**
  - One OS process executes each active run.
  - A run waiting on a person has no process.
  - Durable timers are applied by `whw resume --due`, run from cron or CI.
  - `whw serve` is optional at T2 and above.
- **Each run's process uses its own DBOS application name, derived from the run ID, and the run ID as its executor ID.** This keeps recovery, and the queues a run uses, inside that run's process.
- **DBOS queues are per run.** DBOS requires queue names to be unique across applications.
- **Caps across runs are Whisperwind's own mechanism, not DBOS queues.** This covers concurrency per harness and per host (#57). A shared DBOS queue would let other runs' processes take, and strand, a run's work. The mechanism is designed in #57, for example as a small semaphore table in the same SQLite file. This record is the reason to build it rather than adopt DBOS's queues (`VISION.md` §10.1, step 5).
- **Whisperwind switches the SQLite file to WAL mode** before DBOS opens it.

## Consequences

- Recovery and supervision stay inside the run's own process, so killing a run's process never strands another run.
- Listing across runs can't use DBOS's default listings, which are scoped to the caller's application. `whw list` and `whw status` read SQLite directly, which also keeps them off the cost of importing DBOS. That makes DBOS's portable JSON serializer a requirement wherever step outputs are shown.
- Whisperwind owns a small cap mechanism, with its own crash-safety: a cap held by a process that dies must be released.
- At T2 and above, `whw serve` or remote workers may own shared DBOS queues, because those processes are long-lived. This record governs T0 and T1 only.

## Alternatives

- **A long-lived local worker that owns shared queues.** DBOS's global caps would then work across runs, but it reintroduces a background process at T1: something to start, supervise and upgrade.
- **One shared application name, with the run ID as the executor ID.** Rejected on the spike's evidence: recovery leaks runs into other runs' processes.
