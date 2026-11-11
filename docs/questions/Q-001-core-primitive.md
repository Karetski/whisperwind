---
id: Q-001
title: What is the core primitive everything else is built from?
status: open
---
## Question

Which one concept is the kernel, so that everything else becomes a client or a composition of it?

## Why it matters

It fixes the data model, the SDK, the CLI verbs and what the TUI shows. It also decides whether Whisperwind is a workflow engine, a run and session substrate, or a toolkit ([product](../product.md), "Shape").

## Options

- **A durable run.** A journal of steps with an inbox, a budget and controls. Workflows-as-code, one-shot CLI commands and agents calling in through MCP are all clients that drive runs. Closest to Superlogical's "durable session around the work".
- **A workflow defined as code.** The flow function is primary, and a run is what executing it produces. This was the October 2026 model.
- **Composable CLI verbs.** `agent`, `gate`, `ask` and `journal` each work alone and compose from any shell or language. The SDK is sugar on top.

## Prior position

Workflow-as-code (D1), with an agent-facing server deferred (D12). See [prior work](../research/prior-work.md).

## What would settle it

The owner chose to derive it from concrete scenarios first. Write five to eight scenarios, from solo to team, and check which primitive serves all of them with the least machinery.
