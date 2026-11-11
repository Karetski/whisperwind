# Landscape: tools that orchestrate coding agents

Researched on 2026-11-10 from vendor docs, repository READMEs and the GitHub API. Star counts are as of 2026-11-11. Capabilities are as each project describes itself; none were run. Inferences are marked *(inference)*. This is an input to decisions, not a decision.

## Headline

1. **The combination Whisperwind claimed is no longer unoccupied.** Smithers, Archon and Bernstein each claim multi-harness, durable or resumable runs, human approval gates, local-first and a CLI. Bernstein also has a TUI. None of them combines plain code flows, a transactional journal and a TUI over a `--json` CLI. *(inference)* What remains is a position on quality and framing, not on category.
2. **Claude Code now ships most of the October model, for Claude only:**
   - **Workflows:** JS `agent/parallel/pipeline/phase`, with a deterministic guard, resume within a session, 16 concurrent agents by default and schema-checked output.
   - **Agent view:** a supervisor daemon, worktrees, a "Needs input" queue and `claude agents --json`.

   Its own docs state the limits: workers are always Claude sessions; workflows have "no mid-run user input"; one failed agent reruns every later one; background sessions stop on reboot.
3. **Vercel `durable-harness`** (2026-10-19, 0.0.x) makes Claude Code, Codex, OpenCode and Pi sessions durable over an intent/outcome event log. It has no fan-out and no human gates.
4. **Durable-execution vendors wrap agent SDKs, not harness CLIs:**
   - Temporal: OpenAI Agents SDK integration (GA 2026-03-23), and Agent Harness for the Gemini, OpenAI Agents and PydanticAI SDKs (2026-08-20, pre-preview).
   - DBOS: OpenAI Agents SDK (Mar 2026).
   - Dapr: Claude Agent SDK.

   None of them orchestrates local harness CLIs.

## Closest open-source tools

| Tool | Shape | License, signal | Idea worth taking |
|---|---|---|---|
| [Smithers](https://github.com/smithersai/smithers) | TSX workflow trees (`<Parallel>`, `<Loop>`, approvals, signals, timers); every step persisted to SQLite; resume, rewind, fork, replay; jj/git worktree per task; Claude Code, Codex, Cursor, Pi, Gemini; Prometheus/OTel; no TUI | MIT, 448★, active | Time travel tied to VCS snapshots |
| [Archon](https://github.com/coleam00/archon) | YAML node graphs (prompt, bash, script, loop, approval, child workflow); Claude Code, Codex, Pi; worktree per run; SQLite or Postgres; CLI, web console, chat apps | MIT, 23.9k★ | One **attention queue** across runs |
| [Bernstein](https://pypi.org/project/bernstein/) | Python with YAML workflows; deterministic scheduler; checkpoint per node; `resume` refuses when the spec changed; 50+ CLI adapters; merge gates; TUI; MCP and REST; HMAC-chained audit | Apache-2.0, 1.2k★, v3.24.1 on 2026-11-05 | Spec-digest check on resume; verifiable run receipts |
| [Gas Town](https://github.com/gastownhall/gastown) + Beads | Go and tmux; 20–30 agents in named roles; work state in git | MIT, 18.8k★ | Work state outside any run database |
| [AWS CAO](https://github.com/awslabs/cli-agent-orchestrator) | Supervisor and workers over tmux; agents coordinate through MCP tools (`handoff`, `assign`, `send_message`) | Apache-2.0, 1.5k★ | Orchestration exposed *to agents* as tools |
| Agent Orchestrator (OrchestratorInc) | Worktree and tmux per agent; eight plugin slots; CI and review feedback routed back to the agent | Apache-2.0, 14.4k★ | Review and CI loop back to the agent that wrote the code |
| Vibe Kanban | Local kanban across harnesses | Apache-2.0, 28.6k★; community-maintained since April 2026 | Kanban as the review surface |
| Google Scion | Container per agent ("hypervisor for agents"); experimental | Apache-2.0, 2.1k★ | Isolation over constraints |

Worktree GUIs and terminals in the same space:
- Conductor (closed source);
- Nimbalyst (successor to Crystal);
- Paradev (16k★);
- Emdash;
- T3 Code (56k★);
- cmux (28.8k★), a terminal with agent notifications;
- claude-squad (AGPL).

Loop and swarm tools: ralph (22k★), ralph-orchestrator, ruflo (81k★). Stale or retired: uzi, coder/agentapi (archived), Crystal (archived).

## Vendor and platform surfaces

- **Codex:** `app-server` (bidirectional JSON-RPC over stdio, built for orchestrators), cloud tasks, and the Agents API (2026-09-10, a managed harness with subagents).
- **OpenAI Symphony** (Apache-2.0, 28k★): a spec plus a reference daemon. It polls Linear, claims an issue, isolates a workspace, runs Codex and restarts stalled runs. The **issue tracker is the control plane.**
- **GitHub:**
  - Agent HQ / Mission Control (cloud, multi-vendor);
  - Copilot CLI `/fleet`;
  - **gh-aw**, markdown workflows compiled to Actions. Its **"safe outputs"** idea: the agent proposes writes, and the trusted runtime performs them.
- **Cursor:** Cloud Agents API (beta), SDK (beta), an Agents Window spanning local, worktree, SSH and cloud.
- **Factory Missions:** orchestrator, worker and **validator** droids running for days.
- **Devin:** "Devin manages Devins". **Jules:** `--parallel` up to 5. **Kiro:** parallel tasks derived from the spec's dependency graph.
- **Cloudflare Workflows:** `waitForEvent` for waits of weeks, plus a Sandbox SDK that runs Claude Code headless. **Trigger.dev:** waitpoint tokens.

## Protocols

- **ACP:** registry since 2026-01-28 (Zed and JetBrains), 25–30+ agents, Python SDK `agent-client-protocol`. It is the cheapest breadth path. Thoughtworks rates it Assess.
- **MCP Tasks** (SEP-1686): experimental, moving to an extension.
- **A2A** 1.0: no coding-harness use found.
- **AG-UI:** targets frontends.
- **OTel GenAI agent spans:** still Development status.

## Design reference: Superlogical

Not a competitor; the owner cites its philosophy. Superlogical is Mitchell Hashimoto's company, announced in July 2026, and its first product is Rex, a terminal multiplexer in beta. Sources: [superlogical.com](https://www.superlogical.com/), [public testing post](https://www.superlogical.com/updates/public-testing-beginning) (2026-10-05) and [Hashimoto's post](https://mitchellh.com/writing/superlogical) (2026-07-29).

- **Thesis:** "the missing layer is a durable session around the work itself", "driven by software while remaining visible and controllable by people". Interactive, automatic and production work should "share one well-crafted underlying system instead of living in separate tools."
- **Plan:** 1. "Build an incredible multiplexer." 2. "Make everything in it composable." 3. "Make it safe and operable in production."
- **Architecture:** the macOS app "self-hosts its own Rex server and it is able to connect to other Rex servers". Servers can be fully self-hosted. Sessions survive closing the app and reconnecting from another device. Live sharing is "built in from the start."
- **Model:** "Rex is and will always be free." No account, and "we do not see or share your data."
- **On AI:** "AI makes this fragmentation more visible and costly, but it did not create it."

## Comparison

Y = yes, ~ = partial or claimed, N = no.

| | Format | Multi-harness | Durable | Long human waits | Isolation | Local | TUI | CLI/API |
|---|---|---|---|---|---|---|---|---|
| Claude Code workflows | code (JS) | N | ~ in session | N | Y | Y | Y | ~ |
| Claude Code agent view | chat | N | ~ not across reboot | ~ | Y | Y | Y | Y |
| Agent HQ / gh-aw | chat / md | Y | Y | ~ | Y | N | N | Y |
| Symphony | spec + daemon | N | ~ | ~ | Y | Y | N | ~ |
| Smithers | code (TSX) | Y | Y | Y | Y | Y | N | Y |
| Archon | YAML | Y | Y | Y | Y | Y | N (web) | Y |
| Bernstein | YAML | Y | Y | ~ | Y | Y | Y | Y |
| durable-harness | code (TS) | Y | Y | N | sandbox | Y | N | lib |

## Likely to be commoditized within 6–12 months *(inference)*

- Anthropic is likely to add mid-run input and cross-reboot resume, since its docs list both as limits.
- OpenAI is converging on app-server, Symphony and cloud.
- GitHub owns multi-vendor work in the cloud.
- Vercel or Temporal could extend harness durability to fan-out.
- Least likely from any vendor: **local, cross-vendor orchestration under one journal.**

## Differentiation candidates

Each is tied to a gap above. *(inference)*

1. **Identity-keyed replay.** Only invalidated steps rerun, where Claude workflows rerun everything after a failure. Bernstein's spec-digest refusal is the safety half.
2. **Human steps that survive a reboot, and one attention inbox across runs.** Archon's attention queue and cmux's traction show demand.
3. **Typed "may have run" outcomes for side effects,** after durable-harness. A resume then asks a person or runs a check instead of guessing.
4. **Failover and racing across vendors when quota runs out.** No single vendor will ship this.
5. **Safe outputs as the default:** agents propose, gates check, the runtime applies, and the journal is the audit trail.
6. **ACP for breadth, with native app-server and Claude surfaces for depth.**
7. **One cost ledger across harnesses,** covering both subscription and API billing.
8. **Fork and rewind over the journal plus VCS snapshots.**
9. **Interop:** run Claude workflow scripts or Symphony specs on any harness. Demand evidence is weak.

## Not covered

Amp, Gemini CLI subagents, the OpenCode server and SDK, Sweep, Container Use internals, Sculptor, HumanLayer.
