---
id: Q-010
title: How are spend and limits enforced across harnesses and billing models?
status: open
---
## Question

How does a budget hold when steps run in parallel on several harnesses, some billed by API usage and some by subscription quota?

## Why it matters

This is P-05. Multi-agent work costs 2–15× a single agent, and subscription limits are unpredictable ([problem](../research/problem.md) §1C).

## Options

- **Reserve, then settle** per step (October 2026). The invariant: overshoot never exceeds the largest single in-flight step.
- **Quota awareness:** detect a usage limit, then pause, fail over to another harness, or wait.
- **One ledger across harnesses:** cost and tokens per step, run, workflow and merged change.

## Prior position

Reserve-then-settle under parallelism, a $25 per-run default, caps per run, harness and host.

## What would settle it

What the harnesses actually report today (cost, tokens, quota signals), and the scenarios from Q-001.
