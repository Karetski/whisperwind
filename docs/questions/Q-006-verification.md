---
id: Q-006
title: Where does trust in an agent's output come from?
status: open
---
## Question

What does Whisperwind provide so a change can be trusted without a person re-checking everything? Gates, independent evaluators, oracles, or evidence attached to a change?

## Why it matters

This is the core of the goal ([product](../product.md)) and of P-02. Agents grade themselves too generously, and tests are weak oracles ([problem](../research/problem.md) §1B).

## Options

- **Gates as a first-class step:** deterministic checks (tests, types, lint) that a change must pass before it moves on.
- **Independent evaluators:** a separate agent with a clean context sees only the diff and the spec, possibly from another vendor.
- **Safe outputs:** agents propose changes, and the runtime applies them only after the gates pass (gh-aw).
- **Evidence bundles:** each change carries what was run, what passed and what it cost, so review is faster.

## Prior position

Not addressed beyond schema-checked agent output.

## What would settle it

Scenarios from Q-001, plus the owner's own review workflow: what would let them approve a change in a minute instead of ten?
