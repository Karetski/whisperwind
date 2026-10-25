# Architecture decision records

Each accepted decision in `VISION.md` §15, and each call to build a capability instead of adopting a library (`VISION.md` §10.1, step 5), is recorded here. A record is short: context, decision, consequences, alternatives.

| ADR | Decision | Status |
|---|---|---|
| [0001](0001-flows-are-python-functions.md) | Flows are Python `async def` functions decorated with `@flow`; YAML flows retire | Accepted |
| [0002](0002-adopt-dbos-for-durable-execution.md) | Adopt DBOS Transact for durable execution | Accepted |
| [0003](0003-dependencies-install-from-wheels.md) | Dependencies install from wheels on every tier-1 platform | Accepted |
| [0004](0004-python-3-11-floor.md) | Python 3.11 is the minimum version | Accepted |
| [0005](0005-event-table-beside-dbos.md) | One event table beside DBOS, keyed by step path | Accepted |
| [0006](0006-harness-strategy.md) | Own a versioned harness contract; native adapters for depth, ACP for breadth | Accepted |
| [0007](0007-visualization-and-editing.md) | Show flows in three layers; the TUI is not a structural editor | Accepted |
| [0008](0008-config-format-toml.md) | Configuration is TOML | Accepted |
| [0009](0009-windows-in-p4.md) | Windows support waits for phase P4 | Accepted |
| [0010](0010-agent-facing-server-deferred.md) | An agent-facing server waits until after phase P4 | Accepted |
| [0011](0011-new-major-version.md) | The Python kernel ships as a new major version | Accepted |

## Adding a record

Copy the shape of an existing record: a title, then `Status`, `Date`, `Decided by` and `Refs` lines, then the sections Context, Decision, Consequences and Alternatives. Numbers are sequential and never reused. A record that is replaced stays in place with its status changed to `Superseded by NNNN`.

## Pre-pivot records

Before the move to Python flows on DBOS, the project kept a different set of ADRs, also numbered from 0001. They are not restored; they remain in git history up to commit `db914ab`, which removed them. A record here that reverses one of them cites it as "pre-pivot ADR NNNN" with its title, for history only.
