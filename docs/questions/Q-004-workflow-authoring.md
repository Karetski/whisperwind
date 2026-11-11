---
id: Q-004
title: How do people author workflows?
status: open
---
## Question

Are workflows code in a general-purpose language, declarative config, or both? And what is the minimal vocabulary?

## Why it matters

Authoring is what users touch every day. It decides what can be visualised before a run, what can be linted, and whether agents can write workflows safely.

## Options

- **Code only:** Python or TypeScript functions with `agent`, `shell`, `human` and combinators.
- **Config only:** YAML or markdown, like Archon, Bernstein and gh-aw.
- **Code as the source of truth,** plus a small declarative layer for simple recipes.
- **Import existing formats:** Claude workflow scripts, Symphony specs.

## Prior position

Python `async def` with a vocabulary matching Claude Code workflows. Proposed ADR 0015 made steps lazy, serializable descriptions because of DBOS. See [prior work](../research/prior-work.md) §2.

## What would settle it

Write the scenarios from Q-001 in each candidate form and compare length, readability, and what each form lets the system know before the run starts. This depends on [Q-001](Q-001-core-primitive.md) and [Q-003](Q-003-implementation-language.md).
