# 0006. Own a versioned harness contract; native adapters for depth, ACP for breadth

- Status: Accepted
- Date: 2026-10-24
- Decided by: the owner (D7 in `VISION.md` §15)
- Refs: `VISION.md` §9

## Context

Whisperwind delegates agent work to existing harnesses and never calls model APIs. The 0.1.x releases ship `claude`, `codex`, `command` and `fake` adapters on one adapter contract (pre-pivot ADR 0011, "Harness adapter architecture").

The Agent Client Protocol (ACP) reaches many agents through one protocol. But Claude Code and Codex, the two harnesses that matter most, speak it only through adapters that sit on the same native surfaces Whisperwind already drives. We found no first-class schema-constrained final answer in ACP. The native surfaces give exact cost, session forking and schema-validated output. Official harness SDKs became allowed with ADR 0003, but some bundle their own harness binary.

## Decision

- **Whisperwind owns one harness contract:**
  - start, resume and fork a session;
  - a stream of normalized events;
  - a final result: text, structured output, usage, cost and session ID;
  - cancel;
  - an optional interactive handoff;
  - declared capabilities, with graceful degradation when one is missing.

  The contract gains a version, and its event names align with ACP's `session/update` vocabulary, so the ACP mapping is near-identity.
- **Native adapters for depth.** `claude` keeps driving the Claude Code CLI's stream-json output. `codex` drives `codex exec --json`, and moves to `codex app-server` once its stability is confirmed.
- **One generic `acp` adapter for breadth,** built on the new kernel in phase P4.
- **`command` and `fake` stay.** `command` covers any CLI that prints JSON lines. `fake` is the basis of every engine test and benchmark.
- **Official SDKs are adopted case by case,** when one removes owned code without forcing a bundled harness binary over the user's installed CLI.
- **The conformance kit gates every adapter:** recorded streams, `whw adapter test` and opt-in live runs.

## Consequences

- Whisperwind owns two native adapters and must follow their CLIs, which change monthly. Recorded-stream conformance tests are how changes get noticed.
- Every ACP agent becomes available through one adapter.
- Structured output uses the harness's native schema enforcement when it exists. Otherwise Whisperwind prompts for JSON, validates the result and retries.

## Alternatives

- **ACP as the only contract.** Less owned code, but Claude and Codex would run through ACP adapters, losing schema-constrained output and exact cost.
- **Official SDKs first.** Some bundle a pinned harness binary that would replace the CLI the user already installed and logged in to.
