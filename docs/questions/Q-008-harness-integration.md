---
id: Q-008
title: How does Whisperwind drive agent harnesses?
status: open
---
## Question

What is the contract between Whisperwind and a harness, and which integration paths are first-class: native CLIs, ACP, vendor SDKs or app-server?

## Why it matters

Harnesses are the product's reach (P-03). Their CLIs change monthly and fail silently ([problem](../research/problem.md) §1G).

## Options

- **An owned versioned contract** with native adapters for depth and ACP for breadth (October 2026).
- **ACP only.** Least code, but Claude and Codex then run through wrappers, losing native schema output and exact cost.
- **Vendor SDKs first.** Rich, but some bundle a harness binary that overrides the one the user installed.

## Prior position

D7: an owned contract (start, resume, fork, events, result, cancel, handoff, capabilities), adapters for `claude`, `codex`, `acp`, `command` and `fake`, and a conformance kit of recorded streams.

## What would settle it

A current survey of Claude Code, Codex app-server and the ACP registry, plus the contract shape implied by Q-001 and [Q-006](Q-006-verification.md) (outcomes verified, not trusted).
