# 0002. Adopt DBOS Transact for durable execution

- Status: Accepted
- Date: 2026-10-24
- Decided by: the owner (D2 in `VISION.md` §15)
- Refs: `VISION.md` §5.3, §5.4, §6, §10.3

## Context

Whisperwind's runs must survive crashes, restarts and multi-day human waits without rerunning work that already finished. The 0.1.x engine owns this: an append-only JSONL event log per run, a derived state snapshot, run locks and a sequential step loop (pre-pivot ADR 0012, "Run storage and resume semantics"). Extending it to concurrent fan-out, queues with global limits, and a shared database for teams means building and proving a durable-execution engine ourselves.

DBOS Transact is an MIT-licensed library that provides checkpointed workflow steps, recovery, durable sleep, `send`/`recv` messages, queues with concurrency limits and fork-from-step, on SQLite by default and Postgres for scale. Research ran it end to end on SQLite: a crash and recovery, a fan-out through a queue, and a human wait through `send`/`recv`.

## Decision

- Durable execution is built on DBOS Transact. Resume follows DBOS's model: the flow function re-executes, and completed steps return their recorded results instead of running again.
- Whisperwind owns what DBOS doesn't know about: step paths and fingerprints, harness-session resume, process supervision, budgets, workspaces and the terminal experience. Step paths map onto DBOS child workflows with caller-chosen IDs.
- Whisperwind depends only on the MIT library. It never requires DBOS Conductor, which is proprietary.
- Before phase P1 builds on DBOS, phase P0 verifies eight must-hold properties, V1–V8 in `VISION.md` §10.3: concurrent child workflows, per-run recovery without a daemon, resume after an edit with a pinned version, multi-day `recv`, fork of one scope, cancellation that reaches a process, performance, and the crash-injection suite.
- If a must-hold property fails and upstream can't fix it, the fallback is a thin owned SQLite journal that copies DBOS's semantics. The flow API and the step paths stay the same either way.

## Consequences

- Correctness of the journal, recovery and queues is DBOS's. Correctness of our integration with it is proven by the crash-injection suite, which kills the run at every checkpoint and event write.
- Postgres and remote workers (phase P5) are a configuration of DBOS rather than a second backend to write.
- Runtime dependencies grow: SQLAlchemy, greenlet and `psycopg[binary]`. Decision 0003 allows them; installed size and startup time are tracked in CI.
- DBOS identifies steps by call order within a workflow, so hierarchical step paths depend on the child-workflow mapping. The mapping stays in one module so it can change without touching flows.
- Live agent events (streamed output, tool calls, cost as it accrues) aren't facts DBOS records. Where they live is decision D6.

## Alternatives

- **Own a thin SQLite journal.** Native hierarchical paths and no new dependencies, but crash windows, leases, idempotency, queues and scale-out are ours to build and prove. Kept as the fallback.
- **Temporal.** Needs a server, and its full-replay sandbox is a known source of user pain. An adapter for organizations that already run Temporal may be evaluated after phase P5, off the critical path.
