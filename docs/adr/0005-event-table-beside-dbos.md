# 0005. One event table beside DBOS, keyed by step path

- Status: Accepted
- Date: 2026-10-24
- Decided by: the owner (D6 in `VISION.md` §15)
- Refs: `VISION.md` §6.3, §16

## Context

DBOS records workflow status, step outputs, messages and queues (ADR 0002). Whisperwind also needs facts DBOS doesn't record: a harness session started and its ID (needed to resume it), progress while a step runs, usage and cost as they accrue, and where a step's output files are. The 0.1.x engine kept everything in one append-only `events.jsonl` per run (pre-pivot ADR 0012, "Run storage and resume semantics").

## Decision

- Whisperwind keeps **one event table in DBOS's database**: the same SQLite file locally, the same Postgres for teams.
- **Every event is keyed by step path**, the same identity DBOS's records map to.
- **Facts are disjoint.** If DBOS records a fact, the event table never duplicates it.
- **High-volume output stays out of the database.** Raw harness streams, stdout and stderr go to per-step files under the run directory, and the event table holds pointers to them.
- **Requests from other processes**, such as answers and cancels, go through DBOS (`send`, cancel), not through the event table.
- **JSONL is an export format only**, never a source of truth.
- Every view (TUI, `whw status` and `logs`, OpenTelemetry, history statistics) is a projection over DBOS's tables and the event table together.

## Consequences

- There are two writers to one database. Disjoint facts and a shared path key keep them coherent, and a property test must check that each projection agrees with DBOS's status.
- The database stays small and recovery stays fast, because streams never enter it.
- Moving to Postgres in phase P5 carries the event table along, with no second backend to write.
- The event table's schema and its migrations are Whisperwind's to own.

## Alternatives

- **A separate event store** (a second database, or a JSONL log as the source of truth). It is independent of DBOS's schema, but leaves two stores to keep consistent, back up and move to Postgres.
- **One owned journal for everything.** A single event spine, but it means not adopting DBOS, which ADR 0002 rejected.
