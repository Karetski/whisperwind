---
id: H-001
title: A per-user local server beats one process per run on resume, caps and liveness
status: planned
tests: [Q-002]
timebox: 3d
---
## Hypothesis

We believe that a long-lived per-user server, which every CLI, TUI and run attaches to, gives faster resume, working caps across runs and live updates. We also believe its startup, upgrade and crash-recovery costs stay small enough that a solo developer never notices it.

The criteria below are a draft. The owner confirms them before the experiment runs.

## Method

Build two throwaway prototypes over the same fake harness and the same SQLite store:
1. **Serverless:** one process per run, cron-style `resume --due`.
2. **Server:** a per-user server started on demand by the first client, with clients connecting over a local socket.

Run identical scenarios on both:
- a sequential run killed and resumed;
- three runs sharing a per-harness cap of 2;
- a human wait answered from another shell;
- a timer that falls due while nothing is open;
- a TUI that watches a run.

Prior evidence: [prior work](../../docs/research/prior-work.md) §3.

## Pass if

- The server variant resumes a run in ≤ 300 ms, against the about 1.3 s DBOS-based floor.
- The server variant enforces a cap across three runs with zero stranded work in 20 trials.
- The first client starts the server in ≤ 150 ms, and later clients attach in ≤ 20 ms.
- Killing the server mid-run loses no completed step, and the next client recovers it automatically.

## Fail if

- The server needs manual start or stop in any scenario.
- Server crash recovery strands or duplicates a completed step.
- The serverless variant matches the server on every pass criterion. The extra moving part is then unjustified.

## Result

## Evidence
