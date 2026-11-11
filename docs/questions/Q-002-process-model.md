---
id: Q-002
title: Is there a long-lived local server, or does each run own its process?
status: open
---
## Question

Does `whw` start or attach to a per-user server that every surface talks to (the Superlogical/Rex model)? Or is each run its own process over a shared store, with a server only for teams?

## Why it matters

It decides how durable timers fire, how caps across runs work, how fast resume and status are, how the TUI gets live updates, and whether solo and team use are one mode or two.

## Options

- **A local server, the same everywhere.** Clients attach to it, and a team points its clients at a shared server. Timers, caps and live updates are natural. The cost is lifecycle work: start, upgrade, crash recovery.
- **Serverless by default.** One process per run, `resume --due` from cron, and a server as a team add-on. Lighter, but two operating modes.

## Prior position

Serverless through the local tiers (D9, proposed). The DBOS spikes showed the friction this causes: an application name per run, queues confined to one run, an owned cap mechanism, a recovery floor of about 1 s ([prior work](../research/prior-work.md) §3).

## What would settle it

[H-001](../../experiments/H-001-process-model/README.md), as the owner chose.
