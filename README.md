# Whisperwind

Whisperwind is a durable, local-first runtime for multi-agent coding workflows written in plain Python. You write a **flow** as an `async def` function: "plan with one agent, implement with another until the tests pass, run two reviewers in parallel, ask me before committing". Whisperwind runs it by driving the agent CLIs you already use, **Claude Code**, **Codex CLI** and any **ACP** agent, in headless mode. It never calls model APIs itself.

- **Flows are Python.** Loops, branches, helpers, imports, type checking, debuggers and unit tests come from the language. There is no DSL.
- **Any harness, in one flow.** Each step picks its harness. Adapters share one versioned contract, checked by a conformance kit.
- **Concurrent by default.** Fan out to hundreds of agents with `parallel` and `pipeline`. Caps and budgets hold under parallelism.
- **Durable.** Every effect is a journaled step. A crashed, killed or edited run resumes where it stopped, and a run can wait days for a person with no process running.
- **Bounded.** Every run has budgets (USD and tokens), step limits and timeouts.
- **Local-first.** A SQLite file and no daemon on a laptop; Postgres and workers for a team. The flow file doesn't change.
- **Terminal-native and scriptable.** A live TUI, and a CLI with `--json` output and stable exit codes.

## Status

**Pre-release. Nothing described in this README runs yet.** This README describes Whisperwind as designed. The kernel is being built in phases, each with exit criteria, tracked as [GitHub milestones](https://github.com/Karetski/whisperwind/milestones). [`VISION.md`](VISION.md) has the reasoning, architecture, roadmap and decision log. This section changes as each phase lands.

The 0.1.x releases on PyPI run an earlier, YAML-based flow format. It is frozen, gets bug fixes only, and will be removed.

## Install

You need Python 3.11+, git, and Linux or macOS.

```sh
uv tool install whisperwind     # or: pipx install whisperwind
whisperwind --version           # `whw` is a short alias
```

With uv, the Python is managed for you, so the system interpreter doesn't matter.

To run agent steps, install and log in to [Claude Code](https://code.claude.com/docs/en/overview), [Codex CLI](https://github.com/openai/codex) or any [ACP](https://agentclientprotocol.com) agent. `whw adapters --probe` shows what Whisperwind can find.

## A flow

```python
from dataclasses import dataclass
from whisperwind import flow, agent, shell, human, parallel, phase, FlowFailed

@dataclass
class Plan:
    summary: str
    steps: list[str]

@dataclass
class Review:
    approve: bool
    issues: list[str]

@flow(phases=["Plan", "Implement", "Review"], budget_usd=5)
async def implement_feature(goal: str, max_rounds: int = 3) -> str:
    """Plan, implement until the tests pass, review twice, ask before committing."""
    with phase("Plan"):
        plan = await agent(f"Plan this change: {goal}",
                           harness="claude", profile="read-only", output=Plan)

    with phase("Implement"):
        for _ in range(max_rounds):
            await agent(f"Implement this plan:\n{plan.steps}",
                        harness="claude", session="impl")   # rounds share one session
            tests = await shell("npm test", check=False)
            if tests.ok:
                break
        else:
            raise FlowFailed(f"tests still fail after {max_rounds} rounds")

    with phase("Review"):
        bugs, security = await parallel(
            agent("Review the diff for bugs", harness="codex", output=Review),
            agent("Review the diff for security issues", harness="claude", output=Review),
        )

    issues = bugs.issues + security.issues
    if await human("Commit?", details=issues, choices=["commit", "stop"]) == "commit":
        await shell(["git", "commit", "-am", plan.summary])
    return plan.summary
```

```sh
whw run flows/implement.py --goal "add rate limiting"   # or by name: whw run implement-feature
whw status @last
whw tui
```

The function signature is the input schema: type hints become `--input` validation and `--help` text. Flows live in `flows/*.py` in a project, or in an installed package that registers them under the `whisperwind.flows` entry point. Long prompts can live in files next to the flow: `prompt("review.md", diff=…)`.

The names and signatures above are a draft. They are settled in an ADR before the kernel is built.

## Flow primitives

| Kind | Primitive | What it does |
|---|---|---|
| **Step** | `agent(prompt, harness=, output=, session=, profile=, workspace=, label=, …)` | One harness turn. `output=` takes a pydantic model, dataclass or TypedDict, or a raw JSON Schema dict. The answer is checked against it, with retries to fix invalid output. |
| | `shell(cmd, check=, timeout=, workspace=)` | One command in its own process group. |
| | `human(question, choices=, timeout=, default=)` | Waits for a person, for days if needed, with no process running. |
| | `sleep(duration)` / `sleep_until(t)` | A durable timer. |
| | `@step` on any function | A user-defined effect, such as calling the GitHub API. Its result is journaled. |
| | calling another `@flow` | A subflow, run as a child scope. |
| | `now()`, `random()`, `uuid()` | Deterministic on replay. |
| **Combinator** | `parallel(*steps, limit=)` | A barrier. Returns results in order. A failure surfaces as an `ExceptionGroup` unless `return_exceptions=True`. |
| | `pipeline(items, *stages, limit=)` | Each item flows through the stages with no barrier between stages. The default for fan-out. |
| | `race(*steps)` / `first(*steps, until=)` | The first result wins, and the losers are cancelled (their processes killed). |
| | Python `for`, `while`, `if`, `try` | Ordinary control flow. |
| **Structure** | `with phase("Name"):` | Groups steps for display and addressing. |
| | `label=` | A stable, human-meaningful step name. |
| **Context** | `budget.remaining()`, `log()`, `run.id`, `run.inputs` | Read-only run context and narrator lines. |

## Durability

Whisperwind runs on [DBOS Transact](https://docs.dbos.dev/), a durable-execution library. Resume works by re-running the flow function and serving completed steps from the journal, so completed steps never rerun. An agent step that was cut off resumes its harness session when one was recorded. Steps marked `on_resume="ask"` ask before running again; `on_resume="restart"` starts them over.

This asks three things of flow code:

1. **Effects only through steps.** Anything that touches the world (agents, commands, files, network, clocks, randomness) goes through a step primitive or a `@step` function.
2. **Deterministic between steps.** Given the same step results, flow code makes the same calls.
3. **Concurrency only through combinators.** Use `parallel`, `pipeline` and `race`, not raw `asyncio.create_task` or `gather`.

`whw check flow.py` lints for each of these without running the flow. Every step also carries a fingerprint (its kind, rendered prompt or command, and options). If a resumed run reaches a step whose fingerprint changed, Whisperwind reports the divergence by path and lets you rerun from there, in that scope only, or abort. **Editing a flow while a run is paused is supported.**

## Step paths

Every step has a path: the scopes it was called in, plus its position or label. The same path names the step in the CLI, the TUI, the journal and telemetry.

```
plan/agent#0                          the planning agent
implement/agent#2                     the third implementation round
review/parallel#0/1/agent#0           the second reviewer in the first parallel group
review/security-review                a step with label="security-review"
```

```sh
whw logs @last/review/parallel#0/1
whw resume @last --from implement
```

Concurrent branches have their own scopes, so a failure in one branch never invalidates another, and editing a prompt in one phase leaves the others cached.

## Limits and concurrency

| Limit | Scope | Default |
|---|---|---|
| `limit=` on a combinator | that call | the run's cap |
| Concurrent agents | run | 8 |
| Concurrent agents per harness | every run on the host | per-harness config |
| Writers per workspace | workspace | 1 |
| Budget (USD, tokens) | run, phase, step | $25 per run |

Budgets are reserved before a step starts and settled when it finishes, so parallel steps can't overspend together: total spend never exceeds the budget by more than the largest single in-flight step's overshoot. USD figures are estimates; for harnesses that report only tokens, prices come from the config.

**Workspaces.** Parallel agents that write get one git worktree each. Read-only agents share the base tree. Whisperwind never merges or pushes; your flow does that with `shell("git …")`. Container and remote-sandbox workspaces come later.

## Harnesses

| Harness | What it is |
|---|---|
| `claude` | Claude Code, driven through its stream-json output |
| `codex` | Codex CLI |
| `acp` | Any [Agent Client Protocol](https://agentclientprotocol.com) agent: Gemini CLI, Copilot, Cursor, goose, OpenCode, Qwen and others |
| `command` | Any CLI that prints JSON lines, described in a config file. No code needed. |
| `fake` | A scripted test double: no processes, no cost |

Structured output uses the harness's own schema enforcement when it has one. A package can add an adapter under the `whisperwind.adapters` entry point. `whw adapter test <name>` checks an adapter against recorded streams; add `--live` to check it against the real CLI, which costs money.

**Permission profiles**, set per agent step. Anything that would prompt for approval is denied.

| Profile | What the agent can do |
|---|---|
| `read-only` | Cannot change files. |
| `edit` (default) | Can edit files in its workspace, and run only the commands you allow. |
| `full` | Can do anything you can. Refused unless you pass `--allow-full` or allow it in the config. |

## Commands

All commands accept `--json`. A run can be named by its ID, a unique prefix, or `@last`, followed by a step path.

| Command | Purpose |
|---|---|
| `init` | Set up `.whisperwind/` in a project. |
| `run <flow>` | Start a run. Inputs come from the flow's signature. |
| `resume <run> [--from <path>] [--due]` | Continue a run. `--due` applies expired timers and human timeouts; run it from cron or CI. |
| `status [<run>] [--watch] [--format mermaid\|json]`, `list` | Show a run's tree, the active runs, or run history. |
| `logs <run>[/<path>] [-f]` | Show a step's output and events. |
| `respond <run>` | Answer a waiting human step, from any process. |
| `cancel <run>[/<path>]` | Cancel a run or one scope, killing its processes. |
| `check <flow>` | Lint a flow for the durability rules, without running it. |
| `graph <flow> [--format text\|mermaid\|json]` | Print a flow's skeleton, read from source without running it. |
| `adapters [--probe]`, `adapter test` | List harness adapters; test one. |
| `gc` | Delete old finished runs and their worktrees. |
| `tui` | Open the terminal UI. |

**Exit codes**:

| Code | Meaning |
|---|---|
| 0 | OK / the run succeeded |
| 1 | The run failed |
| 2 | Bad usage or a bad answer |
| 3 | Invalid flow or inputs |
| 4 | Waiting for a person |
| 5 | Cancelled |
| 6 | Not found |
| 7 | Conflict: the run is locked |
| 8 | The run was interrupted and can be resumed |
| 70 | Internal error |

## Terminal UI

`whw tui` shows a live call tree and timeline for each run, over a static skeleton of the flow:

```
┌ run 7f3a · implement-feature · ● running · $1.82 / $5.00 · 12m 04s ─────────────────────┐
│ ▾ Plan                     ✓   1m12s  │ Plan       ████                                  │
│   ✓ agent#0     claude     $0.21      │ Implement      ██████████████▓▓▓▓                │
│ ▾ Implement  ↻ 2 of ≤3     ●          │  agent#0       █████                             │
│   ✓ agent#0     claude     $0.44      │  shell#0            █                            │
│   ✗ shell#0     exit 1                │  agent#1             ██████▓▓▓▓                  │
│   ● agent#1     claude     $0.31 …    │ Review                                           │
│ ▸ Review     ⇉ ×2 (usually 2)  ○      │                                                  │
│ ? human#0    Commit?           ○      │                                                  │
├───────────────────────────────────────┴──────────────────────────────────────────────────┤
│ implement/agent#1 · claude · session 9c2e… · Editing src/limits/middleware.ts            │
│ > Running npm test -- limits                                                             │
└ ↑↓ select  ⏎ detail  l logs  a answer  p pause  x cancel  r rerun step  / filter  ? help ┘
```

| Screen | Content |
|---|---|
| Runs | Active, waiting and recent runs, with cost, status and age. Runs waiting for you come first. |
| Run | The live tree, timeline and detail pane. Answer human steps inline; pause, cancel, or rerun a step or scope. |
| Flow | The flow's skeleton, what past runs of it usually did (rounds, duration, cost), lint results and an inputs form. |
| Step | Prompt, streaming output, structured result, usage and session ID. Hand off to an interactive harness session. |

The TUI is a client of the CLI: every action has a command. Prompts are edited as files in `$EDITOR`; structural changes go through your editor or an agent, and you approve the diff.

**Telemetry.** The optional `whisperwind[otel]` extra exports runs as OpenTelemetry spans using the GenAI semantic conventions, named by step path.

## Scaling up

| Tier | Runs | State | Install |
|---|---|---|---|
| Laptop | One process per run, no daemon | A SQLite file | `uv tool install whisperwind` |
| Workstation / CI | Many runs on one host; caps across them; `whw resume --due` from cron | A shared SQLite file | same |
| Team server | `whw serve` (HTTP + SSE), the TUI connects remotely | Postgres | `whisperwind[server]`, container image |
| Enterprise | Remote workers; container and remote sandboxes | Postgres | image + extras |

The flow file is the same on every tier.

## Configuration

Configuration lives in `.whisperwind/` in a project, with a per-user file under it. It describes the environment, never flow behavior: harness binaries and tested versions, extra environment variables allowed into steps, token prices, the default hook for waiting human steps, retention for `gc`, patterns masked in logs, and whether the `full` profile is allowed. The file format is still to be decided (`VISION.md` decision D10).

## Security

- Flows are trusted code from your repository, like a Makefile. They run in-process and are not sandboxed.
- Agents and commands run in their own process groups, inside workspaces, and start from a clean environment with only an allowlist of variables plus the auth variables each harness needs.
- Run directories are private (mode `0700`) and ignored by git.
- Plugins and command adapters run with your privileges.

## Development

Requires [uv](https://docs.astral.sh/uv/).

```sh
uv sync                 # create .venv with the locked dev dependencies
uv run pytest           # tests (never call a real harness or spend money)
uv run ruff check .     # lint
uv run ruff format .    # format
uv run mypy             # type check
uv tool install -e .    # `whisperwind` and `whw` commands that run this checkout
```

TUI screens are checked against SVG snapshots in `tests/__snapshots__/`. After an intended screen change, run `uv run pytest --snapshot-update` and commit the updated snapshots. On every pull request, CI posts a comment showing each added, changed or removed screen as text, with a diff for the changed ones.

Releases are published to PyPI and GitHub by pushing a `vX.Y.Z` tag that matches `__version__` in `src/whisperwind/__init__.py`.

## License

MIT, see [`LICENSE`](LICENSE).
