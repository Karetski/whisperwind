---
id: Q-011
title: What is the isolation and trust boundary for unattended agents?
status: open
---
## Question

Where do agents run (the base tree, a worktree, a container, a remote sandbox)? Who holds credentials? And what can an unattended agent reach?

## Why it matters

Unattended agents with private data, untrusted input and a way to send data out are the "lethal trifecta" ([problem](../research/problem.md) §1J). Teams need the same answer that a solo developer gets for free.

## Options

- **Workspace providers** (worktree, container, remote) behind one interface (October 2026).
- **Permission profiles** mapped onto each harness's permission flags.
- **Egress and credential policy** per step.

## Prior position

Workspace providers; flows are trusted code; sandboxing is for agents, not for flows.

## What would settle it

The scenarios from Q-001 that run unattended or for a team, plus what each harness can enforce natively.
