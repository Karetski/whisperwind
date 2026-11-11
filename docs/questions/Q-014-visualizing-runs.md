---
id: Q-014
title: How are workflows and runs shown, before and during a run?
status: open
---
## Question

What can a person see of a workflow before it runs, and what do the TUI and the CLI show while it runs and after?

## Why it matters

Transparency (P-08) and attention (P-01). Code-defined workflows can't be drawn exactly before they run.

## Options

- **Three layers:** a static skeleton, a predicted shape from history, and the live trace (October 2026).
- **Live trace only,** plus a declared outline (Claude `meta.phases`).
- **A shape declared in config,** if authoring becomes declarative ([Q-004](Q-004-workflow-authoring.md)).

## Prior position

D8 and the TUI layout sketched in [prior work](../research/prior-work.md) §2.

## What would settle it

The authoring decision, then TUI sketches tested against the scenarios from Q-001.
