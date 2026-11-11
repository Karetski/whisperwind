---
id: ADR-0002
title: Specify before building; every earlier decision is reopened
status: accepted
date: 2026-11-10
decided-by: owner
---
# ADR-0002. Specify before building; every earlier decision is reopened

## Context

In October 2026 the project set a new direction: Python `async def` flows on DBOS Transact, driving existing agent harnesses. Thirteen decisions were recorded, and a Phase 0 spike programme followed (nine stacked PRs). The spikes worked, but they surfaced friction between DBOS's model and a no-daemon, one-process-per-run design. Meanwhile the field moved:
- Claude Code shipped workflows, agent view and agent teams.
- OpenAI open-sourced Symphony.
- At least three open-source tools now claim the combination Whisperwind set out to own: multi-harness, durable, human-gated, local-first ([landscape](../research/landscape.md)).
- Research on practice shows that review and verification, not generation, is the bottleneck ([problem](../research/problem.md)).

The owner chose to stop building and write a complete spec first: architecture, SDK, CLI, TUI and data model, with risky assumptions tested by experiments before they become decisions.

## Decision

- **No implementation lives on `main` during the spec phase.** The 0.1.x YAML engine, its tests and its packaging are deleted. Its last state is the tag `archive/v0.1-yaml-engine`, and 0.1.x stays installable from PyPI. It gets no further fixes.
- **The Phase 0 spike work is closed unmerged** and kept at the tags `archive/dbos-spikes` and `archive/adr-d5-d9`. Its findings carry forward as evidence in [prior work](../research/prior-work.md), not as decisions.
- **Every earlier decision is reopened.** This covers the October 2026 decisions D1–D13, the 11 accepted ADRs of that period, and the proposals on the spike branches. Each relevant one becomes a question that records the earlier answer and its reasoning. Old decision records are retired. They survive in git history and are cited as "October 2026 ADR NNNN".
- **Roadmap issues and milestones are closed.** New issues are created from the ledger when work is ready.
- **Experiments are the only code during the spec phase.** Each one lives under `experiments/` with a hypothesis, and is never imported by anything else.

## Consequences

- The repository is a spec plus experiments. Nothing in it runs for users until a decision says what to build.
- Work already paid for isn't lost. The spikes' numbers and findings are condensed in prior work, and the code is reachable through the archive tags.
- Each reopened question can be closed quickly when the earlier answer still holds. Reopening gives no option an advantage, the earlier one included.

## Alternatives

- **Keep building on the October direction while writing the spec.** Rejected by the owner: the spec should drive the build, and the build was already shaping the spec.
- **Rewrite history so `main` starts clean.** Rejected: it would be destructive for clones, and the history has value. Cutting forward with archive tags keeps everything.
