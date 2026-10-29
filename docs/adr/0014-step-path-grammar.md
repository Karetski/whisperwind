# 0014. Step path grammar, ordinals and escaping

- Status: Proposed
- Date: 2026-10-28
- Decided by: awaiting the owner
- Refs: `VISION.md` §5.4; ADR 0012; `spikes/dbos/README.md`; `spikes/paths/` (reference implementation and property tests); issue #33

## Context

A step's identity is its path: the chain of scopes it was called in, plus its position or label. The same path is:
- the TUI node;
- the OpenTelemetry span name;
- the CLI argument;
- the key that finds the step in DBOS.

`VISION.md` §5.4 sketches paths by example (`review/parallel#0/1/agent#0`, `audit/pipeline#0/item[src/a.ts]/stage#1/agent#0`, `review/security-review`) and leaves the grammar to this record.

The Phase 0 spikes add constraints:
- **Workflow IDs:** DBOS accepts `/`, `#` and `~` in workflow IDs, so a concurrent scope's child workflow can be named by its path (ADR 0012).
- **Step numbers:** DBOS numbers steps in call order within a workflow, and its own internal steps take numbers too: awaiting a child's result, and a `recv`'s timeout. So a step's DBOS number can't be computed from its path.
- **Forks:** every fork gets a new workflow ID, so rerunning a scope can't keep the scope's workflow ID equal to its path.
- **Shell use:** paths are typed in shells (`whw logs @last/review/parallel#0/1`), so common paths should need no quoting.

## Decision (proposed)

### Segments

| Segment | Form | Example | Identity |
|---|---|---|---|
| Name | `[a-z][a-z0-9._-]*` | `plan`, `security-review` | A phase or a label; independent of position |
| Call | `<kind>#<n>` | `agent#0`, `parallel#1`, `stage#2`, `summarize#0` | The nth call of a kind in its scope, from 0 |
| Branch | `<n>` | `0`, `1` | The nth branch of a `parallel`, `race` or `map` call |
| Item | `item[<key>]` | `item[src/a.ts]` | A `pipeline` item, by its key |

- **A path is segments joined by `/`.**
- **A kind is a Python identifier:**
  - a primitive (`agent`, `shell`, `human`, `sleep`);
  - a combinator (`parallel`, `pipeline`, `race`, `map`);
  - `stage`, for a pipeline stage;
  - the name of a `@step` function or of a subflow's flow function.
- **Ordinals and indexes are written without leading zeros.**
- **Escaping happens only inside `item[...]`,** where `\` escapes `]` and `\`, and every other character, `/` included, is literal. Names, kinds and numbers never need escaping.

### Names

- **A phase's segment is its name slugged:** lower case, with each run of characters other than letters, digits, `.` and `_` turned into `-`. So `phase("Security review")` is `security-review`. Two phases in one scope that slug to the same segment are an error when the flow loads.
- **A `label=` must already be a valid name.** Two calls with the same label in one scope are an error at the second call.

### Ordinals

- **Counted per kind, per scope, from 0.** A scope is the innermost phase or concurrent scope (a branch, an item, a subflow). So `implement/agent#2` and `implement/shell#2` are the third agent and shell calls in the `implement` phase.
- **A labelled call doesn't consume an ordinal.** Labelling a step leaves its unlabelled siblings' paths as they were.
- **Branches of `parallel` and `race` are numbered by argument position, and `map` branches by item position.** A `pipeline` item is identified by its key, so reordering the input list keeps item identities. How the key is chosen is the flow API's to settle (#32).

### Addresses

- **An address is a run reference, optionally followed by `/` and a path.** The run reference is any of:
  - a run ID;
  - a unique prefix or suffix of one;
  - `@last`;
  - `@last:<flow>`.

  Example: `@last/review/parallel#0/1`.
- **A path prefix matches whole segments,** so `implement` matches `implement/agent#2`, and `impl` matches nothing. `--from <path>` means the first step at or under that prefix.

### Mapping onto DBOS

- **A run is the DBOS workflow `<run-id>`.**
- **A concurrent scope is the child workflow `<run-id>/<scope path>`,** for example `<run-id>/review/parallel#0/1`. Phases are naming scopes only and create no workflow.
- **A step is a DBOS step in the workflow of its innermost concurrent scope.** When a step starts, Whisperwind records its path, workflow ID and DBOS step number in the event table (ADR 0005), so a path resolves by lookup, never by counting.
- **Reruns create attempts.**
  - Rerunning a scope creates the next attempt of the run, with the workflow ID `<run-id>~<n>`.
  - Re-executed scopes get `<run-id>~<n>/<scope path>`.
  - Scopes the fork copies keep the IDs they had.

  Paths are the same in every attempt. A run reference may name an attempt (`<run-id>~2`), and `@last` means the latest attempt of the latest run. `~` is reserved in run IDs.

## Open choices for the owner

1. **Phase segments: slugged (proposed) or verbatim.** Verbatim keeps the author's spelling (`Plan`), but needs escaping for spaces and capitals in shells, and stops matching `VISION.md`'s examples (`plan/agent#0`).
2. **Labels don't consume ordinals (proposed), or do.** Consuming keeps one counter per kind, but adding a label to a step would shift the paths of later unlabelled siblings.
3. **Ordinals per kind (proposed), or one counter per scope.** One counter (`agent#0`, `shell#1`, `agent#2`) is simpler, but inserting a step of any kind shifts every later step in the scope. Per kind, only later calls of that kind move.
4. **`map` branches by index (proposed), or by key like `pipeline`.** Keys survive reordering, but make `map`'s paths depend on a key function.
5. **Rerun identity: attempts with `~<n>` (proposed), or a new run ID per rerun with a link to its source.** Attempts keep one run ID for the user, at the cost of a lookup from path and attempt to workflow ID.
6. **Item keys in brackets (proposed, as in `VISION.md`), or a delimiter shells leave alone.** Brackets read naturally, but zsh users must quote every item path. An alternative such as `item=src%2Fa.ts` needs no quoting, but percent-encodes `/` and reads worse.

## Consequences

- **Edits stay local.** An edit in one scope never changes another scope's paths. Inserting a call shifts only later calls of the same kind in the same scope, and the fingerprint check reports those as a divergence (`spikes/dbos/README.md`, "Paused runs").
- **Labels and item keys make identity explicit** where position would be fragile.
- **The event table must record each step's path, workflow ID and DBOS step number.** The CLI and TUI resolve paths through it.
- **Most paths need no quoting in bash or in zsh's default setup.**
  - `#` starts a comment only at the start of a word, so `parallel#0` works unquoted. zsh with `extended_glob` turned on treats `#` as a glob operator, and those users must quote.
  - `item[...]` is a glob pattern to both shells. zsh refuses it unquoted ("no matches found"), so item paths always need quotes there; bash passes it through when nothing matches.

## Alternatives

- **Global call order** (Claude Code workflows, LangGraph). One failure mid-fan-out reruns every later sibling, and any reordering invalidates everything after it.
- **Content hashes as identity.** Two identical prompts collide, and every edit is a new identity, with nothing to report as a divergence.
- **DBOS step numbers as paths.** They aren't stable under DBOS's internal steps, and they mean nothing to a user.
