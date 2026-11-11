# Product

Status: **draft.** The owner's answers of 2026-11-10 are recorded below. Sections marked *open* wait on the linked questions.

## Problem

Coding agents now write code faster than people can trust it. Running more of them in parallel produces more pull requests, not more delivered work: review time and time to merge rise while delivery stays flat ([problem](research/problem.md) §1A). Agents grade their own work too generously, parallel writers collide, costs multiply, harness CLIs fail silently, and context is lost between sessions. Each harness vendor is building orchestration for its own agents only ([landscape](research/landscape.md)).

## Goal

**More trusted, reviewed change per hour of human attention.**

This is the measure the owner set. Running more agents counts only when it raises this number.

Also important, and never traded away silently:
- **Repeatable automation:** a recipe that worked once runs the same way again.
- **Throughput** when the work allows it.
- **Portability** across harnesses, machines and team sizes.
- **Lightness:** cheap to install, start and understand.

## Shape

A **lightweight platform** that lets people solve their own agent-workflow problems, not a purpose-built tool for one workflow. In the spirit of Superlogical ([landscape](research/landscape.md#design-reference-superlogical)): a few excellent primitives, composable, safe to run unattended, and the same system from one developer to a team.

The core primitive is open ([Q-001](questions/Q-001-core-primitive.md)). It will be derived from scenarios.

## Users

The same system scales from a **solo developer** in the terminal to **larger teams** sharing flows, runs and budgets. The first usable version is judged by the solo developer's experience, and nothing in it may block the team case ([Q-012](questions/Q-012-solo-to-team.md)).

The solo developer this targets:
- already uses Claude Code, Codex or another harness daily;
- has more agent output than review capacity;
- wants repeatable recipes such as plan, implement, verify, review and ask;
- runs work overnight or in the background, and engages on their own schedule.

## Unit of value

*Open.* Candidates: a **merged, reviewed change**, which the research favours; a **run**; or a **workflow definition**. This decides what the product counts, shows and optimises for. It is settled with Q-001.

## Greenfield or brownfield

*Open.* Most published successes are greenfield, and practitioners flag existing codebases as the hard case. The owner's own use decides which comes first.

## Non-goals (candidates)

These carry over from the October 2026 design, and each is reopened ([ADR-0002](adr/0002-spec-first-reset.md)):
- calling model APIs or building an agent; harnesses do agent work ([Q-008](questions/Q-008-harness-integration.md));
- a visual drag-and-drop flow editor;
- a general-purpose data or ETL orchestrator;
- a hosted service as the only way to run.

## Success signals (to define)

How the goal is measured in practice, which the spec has to make observable: review minutes per merged change, the share of runs needing no rework, cost per merged change, and time from "needs you" to answered. To be settled with [Q-009](questions/Q-009-human-attention.md).
