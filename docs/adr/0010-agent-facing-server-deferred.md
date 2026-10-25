# 0010. An agent-facing server waits until after phase P4

- Status: Accepted
- Date: 2026-10-24
- Decided by: the owner (D12 in `VISION.md` §15)
- Refs: `VISION.md` §15

## Context

Whisperwind could expose itself to agents as an MCP server or an ACP agent, so that a user could start and follow a flow from inside Claude Code or another harness. Its CLI already supports scripted use: every command has `--json` output and stable exit codes.

## Decision

- No MCP server or ACP agent is built before phase P4 completes. The decision is revisited after P4.
- Until then, agents drive Whisperwind through the CLI.

## Consequences

- The kernel's API can change freely through P4, without a server protocol to keep stable.
- Starting a flow from inside a harness means the agent runs `whw` as a shell command.

## Alternatives

- **Build it in phase P3,** alongside the new TUI. It would reach agent workflows sooner, but on a kernel API that is still moving.
