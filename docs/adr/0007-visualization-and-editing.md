# 0007. Show flows in three layers; the TUI is not a structural editor

- Status: Accepted
- Date: 2026-10-24
- Decided by: the owner (D8 in `VISION.md` §15)
- Refs: `VISION.md` §8

## Context

Flows are Python functions (ADR 0001), so they can't be drawn exactly before they run: loop counts, fan-out widths and branches depend on data. The 0.1.x TUI draws and edits a YAML graph, which pre-pivot ADR 0002, "Flow file format and expressions", chose so that the TUI could write the flow file safely. Mature systems for code-defined work pair a declared skeleton with a runtime trace.

## Decision

- **Three layers, lined up by step path:**
  - **L0 skeleton:** stdlib `ast` over the flow module. It shows phases, inputs, call sites with their labels, badges for loops, branches and fan-out, and opaque boxes for calls it can't resolve.
  - **L1 predicted shape:** statistics from past runs of the flow, such as typical iterations, durations and cost.
  - **L2 live trace:** this run's events as a call tree, a timeline and per-step detail.
- **Preview never executes the flow.** A dry run on the fake harness stays available as an explicit, labeled test tool, never as a preview.
- **The TUI is not a structural editor.** Edits go where write-back is safe:
  - prompts, in prompt files next to the flow;
  - literal arguments, at their exact `ast` source span, re-parsed to verify, and refused when the argument isn't a literal;
  - structure, through an agent that edits the flow and shows the diff, with `whw check` and a fake-harness run before the user accepts it;
  - anything, in the user's own editor, later with an optional language server.

## Consequences

- The TUI loses structural graph editing, which users of the 0.1.x editor will notice. Prompt files, literal edits and agent-proposed diffs are the answer.
- The skeleton is approximate by design. History and the live trace fill in what static analysis can't know.
- Step paths are what pin a live step onto its skeleton call site and aggregate history.

## Alternatives

- **Dry-run tracing for previews** (Prefect's approach). It shows a concrete shape, but executes user code between steps and shows only the one path that run took.
