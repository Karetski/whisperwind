# Principles

Each principle is a candidate until the owner accepts it. A principle wins ties between options. Changing one is a decision with its own ADR. Sources: the October 2026 principles ([prior work](research/prior-work.md)) and the November research ([problem](research/problem.md), [landscape](research/landscape.md)).

### P-01 Human attention is the scarce resource
status: candidate

Every feature is judged by whether it raises trusted, reviewed change per hour of human attention ([product](product.md)). More agent output that needs more review is a cost, not a win.

### P-02 Verify outcomes, never trust claims
status: candidate

An agent's report, a harness's exit code and a step's "success" are claims. Gates that are deterministic, independent or human decide what counts as done ([Q-006](questions/Q-006-verification.md)).

### P-03 Delegate agent work to harnesses
status: candidate

Whisperwind drives existing agent harnesses and doesn't call model APIs or implement an agent loop. Harness-specific depth lives behind adapters ([Q-008](questions/Q-008-harness-integration.md)).

### P-04 Durable by default
status: candidate

No completed work is lost to a crash, a reboot or a wait for a person. Resuming continues; it doesn't start over ([Q-005](questions/Q-005-durability-and-step-identity.md)).

### P-05 Bounded by default
status: candidate

Every run has limits on spend, concurrency and time, and they hold under parallelism and across harnesses ([Q-010](questions/Q-010-budgets-and-cost.md)).

### P-06 One system from solo to team
status: candidate

A laptop and a team use the same system and the same workflow definitions. Scaling up changes where things run and who can see them, never what a workflow says ([Q-012](questions/Q-012-solo-to-team.md)).

### P-07 Every surface is a client of one engine
status: candidate

The CLI, the TUI, the SDK and agents themselves reach the same operations. Anything one surface can do, the CLI can do with `--json` output and stable exit codes.

### P-08 Transparent by construction
status: candidate

Every step traces to its harness session, its inputs and its cost. Views and telemetry are projections of one record, never side channels.

### P-09 Small kernel, composable edges
status: candidate

A few primitives that compose, rather than features for particular workflows. New harnesses, step kinds and workspace providers need no kernel change.

### P-10 Adopt before building
status: candidate

A capability that a maintained library or open standard provides is adopted. Building instead needs an ADR saying why.

### P-11 Design for the next model generation
status: candidate

Each component states which model weakness it assumes. A component that only works around today's weakness is kept thin and expected to expire. What lasts is durability, gates, budgets, isolation and visibility.

### P-12 Interoperate through open standards
status: candidate

Speak ACP, MCP, OTel and AGENTS.md, and import or export existing workflow formats, rather than invent private ones.

### P-13 Light to install, quick to start
status: candidate

Starting is one command with no infrastructure. Commands that don't run agents answer instantly. Heavy capabilities are optional.
