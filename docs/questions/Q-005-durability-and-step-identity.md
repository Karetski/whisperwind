---
id: Q-005
title: How is work made durable, and how is a step identified across resumes and edits?
status: open
---
## Question

Do we adopt a durable-execution engine or own a journal? And how does a step keep its identity when a run resumes, a branch fails, or the workflow is edited while paused?

## Why it matters

Durability is P-04. Step identity decides what reruns after a failure or an edit. That is the main weakness of Claude Code workflows, where one failed agent reruns every later one.

## Options

- **Adopt DBOS,** with hierarchical paths mapped onto child workflows (October 2026).
- **Adopt another engine:** Temporal, Restate, Hatchet, Absurd.
- **Own a small journal** (SQLite to Postgres) with intent and outcome records, after Vercel's durable-harness.

For identity: hierarchical paths plus fingerprints; global call order; content hashes.

## Prior position

DBOS (D2) with paths and fingerprints (proposed ADR 0014). The spikes proved it works but runs against a no-daemon design ([prior work](../research/prior-work.md) §3). The October owned-journal fallback kept the same flow API and paths.

## What would settle it

Decide [Q-002](Q-002-process-model.md) first: a long-lived server removes most of the DBOS friction. Then check whether steps that may have run need typed outcomes.
