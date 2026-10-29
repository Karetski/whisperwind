# 0012. Concurrent scopes are DBOS child workflows

- Status: Accepted
- Date: 2026-10-28
- Decided by: the owner (D5 in `VISION.md` §15)
- Refs: `VISION.md` §5.4, §7.1; `spikes/dbos/README.md` ("Scopes on child workflows"); issue #35

## Context

Flows fan work out with combinators (`parallel`, `pipeline`, `race`, `map`), and every concurrent scope must survive a crash, be rerun on its own, and be cancellable together with the processes it holds. The 0.1.x engine had no concurrency at all: pre-pivot ADR 0007, "No parallelism in v1", deferred it.

The Phase 0 spike ran fan-outs on DBOS 3.3 with SQLite and found:
- **Concurrency:** child workflows with caller-chosen IDs start concurrently from an async workflow.
- **Crash recovery:** a fan-out resumes correctly after a kill at any of its crash points.
- **Rerunning one scope:** forking the branch, then forking the parent with `replacement_children`, reruns one scope without touching its siblings. Every fork gets a new workflow ID, and a forked branch loses its link to its parent.
- **Branch inputs:** DBOS recovers each child workflow on its own, from its registered function and serialized inputs, so a branch can't be an arbitrary coroutine.
- **Cancellation:** DBOS checks cancellation only between steps. A step already running a process keeps running until something watches the workflow's status. A supervised step that polled its status in an AnyIO task group killed its process group within 0.2 s of the cancel.
- **Failure:** when one branch was cancelled, the parent failed while the other branch kept running.

## Decision

- **Each concurrent scope is a DBOS child workflow:** a parallel branch, a pipeline item, a subflow. Its workflow ID derives from the run ID and the scope's path. The grammar is settled in its own ADR (#33). All path-to-DBOS mapping lives in one module.
- **Fan-out within a run starts child workflows directly.** A per-run DBOS queue is used where a limit within the run is needed. Limits across runs are a separate mechanism (ADR 0013).
- **Flow code is plain asyncio.** Flow authors never see DBOS or AnyIO.
- **The process supervisor uses AnyIO** task groups and cancel scopes inside steps. A step that holds a process watches its workflow's status and kills its process group when the workflow is cancelled, because DBOS won't interrupt a running step.
- **Branches are registered workflows with serializable inputs.** The flow API (#32) has to express `parallel(agent(...), ...)` in those terms, for example with `agent(...)` returning a serializable step description.
- **Rerunning a scope is a two-step fork:** first the scope's child workflow, then its parent with `replacement_children`. A scope's path is therefore not its workflow ID, and the path grammar must tell a scope's path apart from the fork or attempt that executed it.
- **Combinators own failure semantics,** because DBOS has none for siblings. When a branch fails or is cancelled, the combinator cancels or awaits the rest according to its policy.

## Consequences

- Fan-out, rerun-one-scope and crash recovery come from DBOS. The crash-injection suite proves the integration for each new combinator.
- Watching for cancellation costs one database read per running step per poll. At 200 concurrent steps and a 0.1 s poll, that's 2,000 reads a second, so a per-process watcher or a DBOS notification should replace per-step polling before P2's width targets.
- After a fork, the run tree can't come from DBOS's parent links alone. Whisperwind records scope parentage itself.
- Choosing the parent's fork step reads DBOS's own step names (`DBOS.getResult`), a dependency on DBOS internals that the version pin and crash suite guard.

## Alternatives

- **AnyIO everywhere, flows included.** DBOS is asyncio-native, and Trio is incompatible with Textual's event loop, so AnyIO in flows would add an abstraction with nothing to abstract over.
- **Raw `asyncio.TaskGroup` only, with no child workflows.** Simpler, but a crash would lose the fan-out's structure, and no scope could be rerun or cancelled on its own.
