# 0015. The flow API: primitive names and signatures

- Status: Proposed
- Date: 2026-10-28
- Decided by: awaiting the owner
- Refs: `VISION.md` §5.1, §5.2, §5.3, §5.6; ADRs 0001, 0012, 0014; `spikes/dbos/README.md`; issue #32

## Context

ADR 0001 makes a flow an `async def` decorated with `@flow`. `VISION.md` §5.2 and the README sketch its vocabulary, deliberately matching Claude Code dynamic workflows (`agent`, `parallel`, `pipeline`, `phase`, `log`, `budget`). They add `shell`, `human`, a durable `sleep` and user-defined steps, and leave exact names and signatures to this record.

The Phase 0 spikes constrain the design:
- **Branches must be serializable.** A branch of `parallel` or `pipeline` runs as a DBOS child workflow, which DBOS recovers on its own from a registered function and serialized inputs (ADR 0012). A branch can't be an arbitrary coroutine or closure.
- **Fingerprints must cover a step's inputs.** DBOS replays by step number and function name, and can't see an edited prompt. Each step's fingerprint covers its kind, its rendered prompt or command, and its options.
- **DBOS stays hidden.** Flow authors never see DBOS or AnyIO (ADR 0012).

The 0.1.x engine's agent and shell options (`harness`, `model`, `effort`, `permissions`, `session`, `on_resume`, `timeout`, `allow_tools`, `deny_tools`, `max_turns`, `workspace`) are known to its users, and the adapter contract uses the same names.

## Decision (proposed)

### Steps are lazy, serializable descriptions

Calling a step primitive builds a `Step[T]`, a description of the call (its kind and arguments), and runs nothing.
- **`await step`** runs it in the current scope.
- **Passing a step to a combinator** runs it as a branch, in its own scope.

A description is plain data, so a branch can be recovered from it as a DBOS child workflow. An un-awaited step does nothing, and `whw check` flags a step expression whose value is never used.

### Steps

```python
agent(
    prompt: str, *,
    harness: str | None = None,        # the project's default harness
    model: str | None = None,
    effort: Literal["low", "medium", "high", "max"] | None = None,
    output: type[T] | dict | None = None,  # pydantic model, dataclass, TypedDict, or JSON Schema
    instructions: str | None = None,
    session: str | None = None,        # calls naming the same session continue it
    permissions: Literal["read-only", "edit", "full"] | None = None,  # the project's default
    allow_tools: Sequence[str] = (), deny_tools: Sequence[str] = (),
    max_turns: int | None = None,
    budget_usd: float | None = None,
    timeout: Duration | None = None,
    workspace: str | None = None,
    on_resume: Literal["resume", "restart", "ask"] = "resume",
    label: str | None = None,
) -> Step[T | str]

shell(
    cmd: str | Sequence[str], *,       # a string runs through `sh -c`; a sequence is executed directly
    check: bool = True,                # raise ShellFailed on a non-zero exit
    timeout: Duration | None = None,
    cwd: str | None = None, env: Mapping[str, str] | None = None, stdin: str | None = None,
    workspace: str | None = None,
    on_resume: Literal["restart", "ask"] = "restart",
    label: str | None = None,
) -> Step[ShellResult]                 # exit_code, stdout, stderr, ok

human(
    question: str, *,
    choices: Sequence[str] | None = None,
    details: Any = None,               # shown with the question
    timeout: Duration = "7d",
    default: str | None = None,        # returned on timeout; without it, HumanTimeout is raised
    label: str | None = None,
) -> Step[str]

sleep(duration: Duration, *, label: str | None = None) -> Step[None]
sleep_until(when: datetime, *, label: str | None = None) -> Step[None]
```

- **`Duration`** is seconds, a `timedelta`, or a string such as `"90s"`, `"5m"` or `"7d"`.
- **`agent`** returns the parsed `output=` value, or the final text when there's no schema. Its cost, usage and session are recorded as events (ADR 0005), not returned.
- **`@step`** marks a user-defined effect: `@step(name=None, on_resume="restart")`, on a sync or async function. Calling the function returns a `Step[T]`. Its arguments and result must be serializable through pydantic, and the result is journaled.
- **Calling a `@flow` function** returns a `Step[T]` too: awaited, it runs as a subflow in a child scope, and passed to a combinator, it runs as a branch.
- **Deterministic helpers:** `now()` is journaled on first use and replayed. `random()` and `uuid()` derive from the run ID and the call's path, so they need no journal entry.

### Combinators

```python
parallel(*branches: Step, limit: int | None = None, return_exceptions: bool = False,
         label: str | None = None) -> Step[list]
pipeline(items: Iterable[I], *stages: StageFn, key: Callable[[I], str] = str,
         limit: int | None = None, label: str | None = None) -> Step[list]
race(*branches: Step, label: str | None = None) -> Step[T]
first(*branches: Step, until: Callable[[T], bool], label: str | None = None) -> Step[T]
```

- **`parallel`** is a barrier and returns results in argument order.
  - On the first failure, it cancels the remaining branches (their processes are killed) and raises an `ExceptionGroup`, as `asyncio.TaskGroup` does.
  - With `return_exceptions=True`, every branch finishes, and failures take their place in the result list.
- **`pipeline`** runs each item through the stages in turn, with no barrier between stages.
  - A stage is a `@flow` or `@step` function taking the previous stage's result, the item itself for the first stage. Being registered is what lets an item's child workflow re-run it after a crash.
  - A failed item's exception takes its place in the result list, and the other items continue.
  - `key` names the item in its path (ADR 0014).
- **`race`** returns the first branch to succeed and cancels the rest. If every branch fails, it raises an `ExceptionGroup`.
- **`first`** returns the first result for which `until` is true, and cancels the rest.
- **`limit`** caps the call's concurrent branches within the run. Caps across runs come from configuration (ADR 0013), not from flow code.
- **A branch must be a `Step`.** That means a step primitive's result, a `@step` call or a `@flow` call; never a lambda or a closure. `whw check` flags a violation, and so does a `TypeError` at the call.

### Structure and context

- **`with phase("Name"):`** groups steps for display and addressing. Phases may nest. `@flow(phases=[...])` declares their display order, and `whw check` warns about a phase the flow doesn't declare.
- **`label=`** on any step or combinator gives it a stable path segment (ADR 0014).
- **`log(message)`** writes a narrator line to the run's events. It isn't a step, and doesn't affect replay.
- **Read-only context:**
  - `budget.remaining()` gives the run's remaining USD and tokens;
  - `run.id` is the run's ID;
  - `run.inputs` holds its inputs, as validated.
- **`prompt("review.md", **values)`** reads a prompt file next to the flow, and substitutes `$name` placeholders with `string.Template`. The fingerprint covers the rendered text.

### Flows

```python
@flow(name: str | None = None, *, phases: Sequence[str] = (), budget_usd: float | None = None,
      budget_tokens: int | None = None, max_steps: int | None = None, timeout: Duration | None = None)
```

- **The decorated function must be `async def`.** Its name in kebab case (`implement_feature` becomes `implement-feature`) is the flow's name, unless `name=` says otherwise.
- **The signature is the input schema.**
  - Each parameter becomes a `--kebab-case` option, validated against its type hint through pydantic.
  - Hints may be `str`, `int`, `float`, `bool`, `Path`, `Literal[...]`, enums, lists of those, or a pydantic model passed as JSON.
  - A parameter's default makes it optional, and the docstring is the `--help` text.
- **The return value must be serializable through pydantic,** and becomes the run's result.
- **Discovery:** `whw run` finds flows in `flows/*.py` in a project, or in modules an installed package registers under the `whisperwind.flows` entry point.

### Errors

- **`FlowFailed(message)`:** raised by flow code to fail the run with a message.
- **`ShellFailed`:** a `check=True` command exited non-zero.
- **`HumanTimeout`:** no answer, and no default, by the deadline.
- **`AgentFailed`:** a harness error, or invalid output after its retries.
- **`BudgetExceeded`:** a budget or step limit was reached.
- **Divergence is not raised into flow code.** The kernel reports it by path and stops the run without recording an outcome, so the run stays resumable (`spikes/dbos/README.md`, "Paused runs").

### The `VISION.md` §5.1 example against these names

```python
from dataclasses import dataclass
from whisperwind import FlowFailed, agent, flow, human, parallel, phase, shell


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
        plan = await agent(
            f"Plan this change: {goal}", harness="claude", permissions="read-only", output=Plan
        )

    with phase("Implement"):
        for _ in range(max_rounds):
            # rounds share one session
            await agent(f"Implement this plan:\n{plan.steps}", harness="claude", session="impl")
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

The only change from the draft is `permissions="read-only"` for `profile="read-only"` (choice 1 below). Every `agent(...)` passed to `parallel` is a lazy description, so the draft's shape works as written.

## Open choices for the owner

1. **`permissions=` (proposed) or `profile=`.** `permissions` is the 0.1.x engine's and the adapter contract's name. `profile` is the draft's, and reads better if profiles grow beyond permissions.
2. **`agent` returns its output (proposed) or a result object** (`.output`, `.text`, `.cost_usd`, `.session`). The output keeps flows terse. A result object makes cost and session usable from flow code.
3. **Sessions named by string (proposed), or 0.1.x's `new` / `continue` / `resume` / `fork` vocabulary.** Names read well in loops (`session="impl"`); forking a named session would need its own option, such as `fork_session="impl"`.
4. **No `map` (proposed), or `map(fn, items, limit=)`.** A one-stage `pipeline` is the same thing. `map` would be shorter, but adds a fourth combinator.
5. **`string.Template` `$name` placeholders in prompt files (proposed), or `str.format` `{name}`.** `{name}` collides with the JSON and code that prompts often contain.
6. **`random()` and `uuid()` derived from the path (proposed), or journaled like `now()`.** Derived values cost nothing to replay, but change when a call's path changes.
7. **`shell(check=True)` by default (proposed), or `False` like `subprocess.run`.** Failing loudly is safer in a flow, and the draft's `check=False` on the test run implies `True` is the default.

## Consequences

- A step expression that isn't awaited does nothing, like an un-awaited coroutine. The lint and the type checker (`Step` isn't `T`) catch most cases.
- Combinators accept only registered work, so a branch that needs several steps is a `@flow` or `@step` function rather than an inline closure.
- Fingerprints come from a step's description, so they're computed before the step runs, which is how divergence is reported without running anything.
- If `permissions=` is accepted, the README's `profile=` (in its example and its primitives table) and `VISION.md` §5.1's example are renamed in the same change.

## Alternatives

- **Primitives as coroutines** (`agent(...)` starts work when awaited, and `parallel` takes coroutines). It's familiar from asyncio, but coroutines can't be serialized, so branches couldn't be child workflows (ADR 0012).
- **Branches as lambdas** (`parallel(lambda: agent(...), ...)`). Closures can't be serialized either, and they hide a branch's inputs from the fingerprint.
- **A decorator per branch** (`@branch`). Heavier than passing a description, for the common case of a single step.
