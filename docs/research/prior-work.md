# Prior work: what was built, decided and learned before the spec reset

Condensed on 2026-11-10 from the October 2026 vision (`VISION.md`), its 11 accepted ADRs, the proposed ADRs on the spike branches (0012–0015) and the Phase 0 spike findings. Every decision here is **reopened** ([ADR-0002](../adr/0002-spec-first-reset.md)). This file records what was decided and why, so a reopened question starts from the reasoning instead of from scratch.

The sources are in git:

| Tag | Holds |
|---|---|
| `archive/v0.1-yaml-engine` | The 0.1.x engine, `VISION.md`, October 2026 ADRs 0001–0011, the README "as designed" |
| `archive/dbos-spikes` | `spikes/dbos/` (code, tests and the full findings README), proposed ADRs 0014 (path grammar) and 0015 (flow API) |
| `archive/adr-d5-d9` | Proposed ADRs 0012 (scopes as DBOS child workflows) and 0013 (one process per run) |

## 1. The 0.1.x engine (shipped, now retired)

About 16,000 lines of Python, released on PyPI as 0.1.x:
- **Flows** were YAML graphs, with a custom expression language (687 lines), a type language (379 lines), `${{ }}` templates, `visits` counters for loops, and `map` over subflows one item at a time.
- **Execution** was a sequential step loop with a JSONL event log per run, locks and an inbox.
- **Adapters** existed for `claude` (stream-json), `codex` (`exec --json`), `command` (any JSON-lines CLI) and `fake`, behind one adapter contract, with a conformance kit of recorded streams and opt-in live runs.
- **Around it:** a Textual TUI with a graph view and a structural flow editor, budgets, worktree workspaces, human steps answerable from any process, and a CLI with `--json` and stable exit codes (4 meant "waiting on a human").

**Why it was retired.** Every capability beyond a fixed graph became a new keyword plus engine, validator and editor code. Agent work is increasingly dynamic: for each failing test, spawn a fixer; loop until the verifier is satisfied; race two harnesses. The engine was also sequential at its core, and about a third of the code was commodity (parsing, expressions, storage).

**What was judged right and worth keeping in intent:** durable, resumable runs; budgets, limits and timeouts; human steps answerable from anywhere; harness adapters gated by a conformance kit; worktree workspaces; a scriptable CLI with stable exit codes; a TUI.

## 2. The October 2026 direction

**North star:** "Write a coding-agent workflow as a Python function. Run it anywhere, on any harness, at any width. Never lose work. Always see what it's doing."

**Claimed gap:** harness-agnostic × durable × human-aware × local-first × terminal-native × Python. The November landscape research found this combination is no longer unoccupied ([landscape](landscape.md)).

### Decisions taken then (all reopened)

| Then | Decision | Reasoning recorded | Now |
|---|---|---|---|
| D1 | Flows are Python `async def` + `@flow`. YAML retires. | Code gives loops, helpers, types, debuggers and tests for free. The market converged on code (Claude workflows, LangGraph Functional API, DBOS, Temporal). | [Q-004](../questions/Q-004-workflow-authoring.md) |
| D2 | Adopt DBOS Transact for durable execution | A mature MIT library: checkpointed steps, recovery, durable sleep, messages, queues, fork-from-step, SQLite to Postgres | [Q-005](../questions/Q-005-durability-and-step-identity.md) |
| D3 | Any dependency allowed if it installs from wheels on every tier-1 platform | The pure-Python rule blocked DBOS, pydantic, libcst and every harness SDK. No evidence of "no compiled code" enterprise policies. | [Q-003](../questions/Q-003-implementation-language.md) |
| D4 | Python ≥ 3.11 | TaskGroup, ExceptionGroup, tomllib; 3.10 reached end of life on 2026-10-01 | Q-003 |
| D5 (proposed) | Concurrent scopes are DBOS child workflows; asyncio in flows; AnyIO inside the supervisor | Spike-proven (§3) | Q-005 |
| D6 | One small event table beside DBOS, keyed by step path, holding only facts DBOS doesn't record | Disjoint facts keep two writers coherent. High-volume output goes to files, not the database. | Q-005 |
| D7 | Own a versioned harness contract: native `claude` and `codex` for depth, one `acp` adapter for breadth, SDKs case by case | Claude and Codex speak ACP only through wrappers. Native surfaces give exact cost, forking and schema-checked output. | [Q-008](../questions/Q-008-harness-integration.md) |
| D8 | Visualization in three layers: L0 skeleton from `ast` (never executes), L1 predicted shape from history, L2 live trace. The TUI stops being a structural editor. | Code-defined flows can't be drawn exactly before they run (LangGraph documents this). Every mature system pairs a declared skeleton with a runtime trace. | [Q-014](../questions/Q-014-visualizing-runs.md) |
| D9 (proposed) | No daemon through the local tiers; one process per run; `whw serve` optional for teams | Pre-pivot stance; the spike found DBOS fights it (§3) | [Q-002](../questions/Q-002-process-model.md) |
| D10 | Config is TOML (stdlib `tomllib`) | Drop ruamel.yaml with YAML flows | Q-003 |
| D11 | Windows waits; supervision designed so Job Objects fit | Process-tree kill needs its own work and CI | Q-003 |
| D12 | An agent-facing server (MCP or ACP: "start a flow from inside Claude") deferred | Focus | [Q-001](../questions/Q-001-core-primitive.md) |
| D13 | Ships as a new major version; 0.1.x gets fixes only | Clean break | Superseded by ADR-0002 |

### The flow model

- **Steps** were the unit of effect and of journaling: `agent(prompt, harness=, output=, session=, permissions=, …)`, `shell(cmd, check=)`, `human(question, choices=, timeout=, default=)`, durable `sleep`, `@step` for user effects, and subflows. `now()`, `random()` and `uuid()` were deterministic on replay.
- **Combinators:** `parallel` (a barrier with ExceptionGroup semantics), `pipeline` (per-item stages, no barrier between stages; the default for fan-out), `race` and `first`. Structure came from `with phase("Name")` and `label=`.
- **Durability contract:** resume re-runs the flow function and serves completed steps from the journal, as DBOS does, rather than Temporal-style replay in a sandbox. Flow code has to:
  - make effects only through steps;
  - be deterministic between steps;
  - use only the combinators for concurrency.

  Enforcement was a lint (`whw check`, stdlib `ast`) plus detection at runtime, not a sandbox.
- **Proposed in ADR 0015: steps are lazy, serializable descriptions.** Calling `agent(...)` builds a `Step[T]`. Awaiting it runs it in the current scope; passing it to a combinator runs it as a branch. This was forced by DBOS: a branch has to be recoverable as a child workflow from its serialized inputs, so it can't be a coroutine or a closure.
- **Step identity, "the hardest design problem".** A step's identity is a hierarchical **path**: a scope chain plus a per-kind ordinal (`review/parallel#0/1/agent#0`), or a label. A **fingerprint** (a hash of kind, rendered prompt and options) detects edits on replay. The alternatives each fail somewhere:
  - global call order, used by Claude workflows: one failure reruns every later sibling;
  - a source hash, DBOS's default: any edit strands paused runs;
  - a content hash: identical prompts collide.

  Proposed ADR 0014 settled the grammar:
  - per-kind ordinals;
  - labels that don't consume ordinals;
  - pipeline items keyed `item[<key>]`;
  - reruns as attempts `<run>~<n>`;
  - addresses such as `@last/review/parallel#0/1`.
- **Editing a flow while a run is paused was a supported feature:** the run reports a divergence by path, and the user chooses to rerun that scope or abort.

### Architecture

The kernel had these components, each with one job:
- **Flow SDK:** turns calls into journaled steps with paths and fingerprints.
- **DBOS:** checkpoints, recovery, timers, messages, queues.
- **Governor:** budgets by reserve-then-settle, plus caps that queues can't express.
- **Event log:** harness sessions, progress, usage, pointers to output files.
- **Supervisor:** process groups, timeouts, cancel and kill.
- **Harness adapters.**
- **Workspace providers:** worktree, container, remote.
- **Analyzer:** skeleton and lint, never executes the flow.
- **Projections:** CLI, TUI, OTel and history are read-only views over one database.

Two other positions:
- **Budgets under parallelism:** reserve each step's cap before it starts, then settle to actual spend. The intended invariant was that overshoot never exceeds the largest single in-flight step. Measured overshoot of harness-native caps had been 5×.
- **Tiers:** T0 laptop → T1 workstation/CI → T2 team server (`whw serve`, Postgres) → T3 workers and sandboxes. The flow file was invariant across tiers.

### TUI and CLI intent

- **Run screen:** a live tree (run → phase → scope → step) beside a waterfall timeline, with a detail pane showing the harness session, streaming output and cost, and inline answers to human steps.
- **Runs screen:** "needs you" first. There was also a flow screen (skeleton plus history overlay) and a step screen.
- **Layout and keys:** lazygit-style numbered panels with key hints, borrowing from Claude Code `/workflows`, Turborepo, the Temporal timeline and Dagger.
- **Rule:** every TUI action has a CLI equivalent with `--json`.

### Performance targets (proposed)

| Target | Value |
|---|---|
| Non-TUI CLI cold start | ≤ 100 ms |
| Overhead per step | ≤ 10 ms p95 |
| Queue dispatch | ≤ 1 s p95 |
| Concurrent agent steps per run | ≥ 200, event-loop lag ≤ 50 ms p99 |
| Steps per run | 10,000 |
| Recovery of a run with 1,000 steps | ≤ 1 s |
| Event to screen | ≤ 250 ms |
| Memory with 50 agents | ≤ 150 MB RSS |

## 3. What the Phase 0 spikes proved (DBOS 3.3.0, Python 3.11)

**What held:**
- **V1, concurrent child workflows.** Child workflows with caller-chosen IDs start concurrently. IDs may contain `/`, `#` and `~`.
- **V2, one process per run.** Holds only with a DBOS *application name per run*. With a shared name, recovery leaked runs into other processes, and in one trial two runs hung.
- **V3, edit while paused.** Holds only with the application version pinned per project. DBOS's default version (an MD5 of the workflow source) strands paused runs on any edit.
- **V4, multi-day human waits.** A human wait of days holds with no process running. `send` from another process answers it; latency is 0.2–0.3 s while the run's process is alive.
- **V5, rerun one scope.** Holds as a two-step fork: fork the branch, then fork the parent with `replacement_children`.
- **V6, cancel.** Holds only with a supervisor: DBOS checks cancellation between steps, and a running process survived 17.8 s after its cancel until a status-polling watcher killed it in 0.2 s.
- **V7, performance.** Partly met (numbers below).
- **V8, crash injection.** A sequential slice (20 crash points) and a 3-branch fan-out (48 points) all resumed correctly. Mutation checks confirmed the suite detects reruns.

**Friction, the real findings:**
- **Steps are at-least-once.** A kill after a step's effect but before its checkpoint reruns the step and duplicates its events. Event writes need idempotency keys.
- **Harness-session resume turns "rerun" into "continue".** An agent step looks up the session an earlier attempt recorded and resumes it.
- **Cross-run caps don't work.** DBOS queues hold their global limit across processes, but other runs' processes executed and stranded a run's children, hanging 2 of 3 trials. Caps across runs would need a long-lived worker or an owned mechanism.
- **Forks change identity.** Every fork gets a new workflow ID, so rerunning a scope means a new run ID (`run~1`) and the parent link is lost. Paths and DBOS IDs must be separated.
- **DBOS internal steps take step numbers,** so DBOS numbering never lines up with user-visible ordinals.
- **Divergence must not end the workflow.** An ERROR run can't be resumed, so the run process has to stop without recording an outcome.
- **Outputs are pickled by default.** Reading them without DBOS means unpickling, which runs code. The portable JSON serializer would be required.
- **Durable time can't be virtualised across a restart.** DBOS takes wake times from the real clock.
- **SQLite needs WAL.** DBOS leaves rollback-journal mode, where reader p99 was 195–490 ms against about 4 ms in WAL.
- **The pull-ins are heavy.** Install size grows from 12.5 to 48 MiB (SQLAlchemy and psycopg-binary, required even on SQLite). Importing DBOS costs 120–460 ms. pyyaml had no 3.15 wheels.
- **Crash injection needed private DBOS methods,** which means pinning DBOS exactly.

**Benchmarks** (macOS arm64 / Linux CI):

| Metric | Target | Result |
|---|---|---|
| Overhead per step | ≤ 10 ms p95 | 0.70 / 2.33 ms (met) |
| 200 concurrent waiting branches | lag ≤ 50 ms p99 | 2 / 4 ms (met) |
| Memory with 50 agents | ≤ 150 MB | 81 / 139 MiB (barely) |
| Queue dispatch, default 1 s poll | ≤ 1 s | 1.96 / 1.20 s (missed) |
| Queue dispatch, 0.1 s poll | ≤ 1 s | 0.73 / 0.16 s (met) |
| 10,000 steps | no slowdown | 6.6 / 19.2 s (met) |
| Recovery of 1,000 steps | ≤ 1 s | 1.30 / 1.66 s (missed: DBOS's internal queue polls once a second and isn't configurable) |
| Status cold start, raw SQLite | ≤ 100 ms | 10 / 13 ms (met) |
| Status cold start, via DBOSClient | ≤ 100 ms | 161 / 491 ms (missed) |

**Net reading.** DBOS works, but against the grain of a no-daemon, one-process-per-run design. An application name per run, queues confined to one run, an owned cap mechanism, owned path bookkeeping, a recovery floor of about 1 s, and reading SQLite directly to stay fast are each workarounds. A long-lived local process would remove most of them. This is input to [Q-002](../questions/Q-002-process-model.md) and Q-005.

## 4. Lessons about how the project was run

- A single locked vision document grew past 1,000 lines. It mixed reasoning, decisions and roadmap, so it couldn't be reviewed in pieces ([ADR-0001](../adr/0001-spec-ledger.md)).
- Spikes with pass/fail criteria written in advance (V1–V8) produced the most durable knowledge of the whole period. Keep that habit.
- Stacking nine PRs before any merged made review harder, not easier.
