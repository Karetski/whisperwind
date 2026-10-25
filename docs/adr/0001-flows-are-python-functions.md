# 0001. Flows are Python functions

- Status: Accepted
- Date: 2026-10-24
- Decided by: the owner (D1 in `VISION.md` §15)
- Refs: `VISION.md` §2.1, §5, §8.4, §12

## Context

The 0.1.x releases define a flow as one YAML file: a graph of nodes with routing, plus an expression language, a template language and a type language. Pre-pivot ADR 0002, "Flow file format and expressions", chose YAML so that the TUI, agents and the user's editor could all read and write the same file, and rejected Python flows because code can't be safely written back by a tool.

Every capability beyond a fixed graph has since become a new keyword plus engine and validator code: visit counters for loops, `map` over subflows for data-dependent work, `templates` and `include` for reuse. The shapes agent work now takes, such as one fixer per failing test, several reviewers with a vote, or loop until a verifier is satisfied, are a few lines of ordinary code and a design project in a declarative graph. Code also brings control flow, imports, type checking, debuggers, unit tests and editor support that YAML had to approximate.

## Decision

- A flow is an `async def` function decorated with `@flow`. Its steps (`agent`, `shell`, `human`, `sleep`, `@step` functions, subflows) are awaited calls, and combinators (`parallel`, `pipeline`, `race`, `map`) run work concurrently.
- The function signature is the flow's input schema: type hints drive input validation and `--help` text.
- YAML flows retire. The YAML engine is frozen (bug fixes only) and is deleted in phase P4, after the Python kernel reaches parity. The five examples are rewritten in Python by hand as the parity test.
- If the project has external users with YAML flows by then, a one-shot `whw migrate flow.yaml` emits Python and is removed one release later.
- The primitive names and signatures are settled in a separate ADR.

## Consequences

- The format, expression, template, type and structural-editing layers (about 5,000 lines, `VISION.md` §12) are deleted in P4 instead of maintained.
- Flow code must follow a determinism contract (effects only through steps, deterministic between steps, concurrency only through combinators). It is enforced by `whw check` lint and by step fingerprints that detect divergence on resume, not by a sandbox.
- The TUI can no longer edit a flow's structure by rewriting a file it fully understands. How flows are previewed and edited instead is decision D8.
- Until P4, two engines live on `main`, and the new one is reached through `whw run <file>.py`.

## Alternatives

- **Keep YAML as a second front-end that compiles to the new kernel.** Two authoring formats would double validation, documentation and tests, and would keep the format and expression layers alive.
- **Keep YAML and add the missing constructs.** Each construct costs engine, validator and editor work, and concurrency would still be bolted onto a sequential step loop.
