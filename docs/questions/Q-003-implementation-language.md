---
id: Q-003
title: What language and runtime is the implementation built in?
status: open
---
## Question

What language is the core (engine, CLI, TUI) written in, which languages get SDKs, and how is it distributed?

## Why it matters

It bounds startup time, install weight, the dependency ecosystem (durable engines, TUI frameworks, harness SDKs) and who can contribute. Distribution, config format and platform support follow from it.

## Options

- **Python core and SDK** (October 2026: D1, D3, D4, D10, D11).
- **TypeScript core and SDK.** Aligns with Claude workflows, Smithers and most agent tooling, and ships as a single binary through Bun or Node.
- **A compiled core (Go or Rust)** with thin Python and TypeScript SDKs speaking a protocol to it.

## Prior position

Python ≥ 3.11, dependencies from wheels only, TOML config, Windows deferred. See [prior work](../research/prior-work.md).

## What would settle it

The owner chose to keep the spec language-neutral (wire protocol, journal schema, CLI contract) and decide this in an ADR once the architecture is settled. Inputs: [Q-001](Q-001-core-primitive.md), [Q-002](Q-002-process-model.md), [Q-005](Q-005-durability-and-step-identity.md).
