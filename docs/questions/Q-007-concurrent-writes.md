---
id: Q-007
title: How are concurrent writes to a codebase handled?
status: open
---
## Question

Are parallel writers first-class (a worktree each, with merging as the flow's job)? Or is the default parallel readers with one serialized writer, and parallel writes only with explicit partitioning?

## Why it matters

The evidence says parallel writers mostly fail: Cursor's 20 agents ran at the throughput of 2–3, and CooperBench pairs were 30% worse ([problem](../research/problem.md) §1D, §2). Getting this wrong multiplies cost and review load.

## Options

- **Parallel readers, one serialized writer** by default; partitioned writes when opted in.
- **Parallel writers first-class,** with a worktree per writer.

## Prior position

A worktree per parallel writer; merging is the flow's job (October 2026).

## What would settle it

[H-002](../../experiments/H-002-parallel-writers/README.md), as the owner chose.
