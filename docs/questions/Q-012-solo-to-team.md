---
id: Q-012
title: How does the same system scale from one developer to a team?
status: open
---
## Question

What changes when a second person, a CI job or a worker pool joins: shared run history, shared budgets, identity, remote access?

## Why it matters

P-06. The owner wants one system from solo to team, in the spirit of Superlogical, where the local app runs its own server and connects to others.

## Options

- **Same server, local or shared:** team use means pointing clients at a shared server.
- **Tiers:** laptop, workstation, team server, workers (October 2026).
- **Issue tracker as the control plane,** as in Symphony.

## Prior position

Four tiers, T0 to T3; Postgres and `whw serve` at the team tier.

## What would settle it

[Q-002](Q-002-process-model.md) and the team scenarios from Q-001.
