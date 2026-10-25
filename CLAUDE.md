# Whisperwind

Whisperwind is a durable, local-first runtime for multi-agent coding workflows written in plain Python. A flow is an `async def` function decorated with `@flow`; its steps (`agent`, `shell`, `human`, `sleep`, `@step` functions, subflows) are journaled on DBOS Transact, and combinators (`parallel`, `pipeline`, `race`) fan work out concurrently. Agent work is delegated to existing harnesses (Claude Code, Codex CLI, any ACP agent) through adapters; Whisperwind never calls model APIs. The CLI is the engine, with `--json` and stable exit codes; the TUI is a client on top.

The project is pre-release. The kernel is built in phases (`VISION.md` §13); nothing in the new model runs yet.

## Where things are

| Read | For |
|---|---|
| `VISION.md` | The locked direction: principles, flow model, architecture, what to adopt and what to own, the phased roadmap, risks and the decision log. |
| `README.md` | Whisperwind as designed, for users, with a status section saying what runs today. |
| GitHub issues | The roadmap as work: one milestone per phase (Now, P0–P5), with the phase's exit criteria in its description. |
| `docs/adr/` | Decision records, numbered from 0001. The directory is created with the first one. |
| `src/whisperwind/` | The implementation. `VISION.md` §12 says which modules are kept and ported, reworked, replaced or retired. |
| `tests/` | Behavior as tested. |

## Legacy code

The tree still holds the YAML engine that the 0.1.x releases ship: the YAML flow format and its validator, expression and template languages, step loop and run store, the flow editor, the current TUI screens, and the YAML flows in `examples/`, `flows/` and `tests/flows/`. It is **frozen**: bug fixes only, no new features, and nothing new builds on it. It is deleted in P4, after the Python kernel reaches parity. Until then both engines live on `main`, and the new kernel is reached through `whw run <file>.py`.

Modules the new kernel keeps (harness adapters, process supervision, budgets, workspaces, structured output, the conformance kit) are ported, not rewritten.

## Rules for this project

- **The code and its tests define what exists; `VISION.md` and the README define what is intended.** The README's status section says which is which. When code and docs disagree about something that exists, stop and raise it; don't invent behavior.
- **`VISION.md` is locked.** It changes only when direction changes, in a reviewed commit of its own. Decisions in its §15 marked *Proposed* are the owner's to accept; don't build on one as if it were settled.
- **Dependencies install from wheels; Python 3.11+.** Any runtime dependency is allowed if it publishes wheels for every tier-1 platform and has a compatible license (`VISION.md` §10.4).
- **Adopt before building.** Run the adopt checklist (`VISION.md` §10.1) before building a capability. Building something a maintained library already does needs an ADR saying why.
- **Decisions get ADRs.** Each accepted decision and each build-instead-of-adopt call is a short ADR in `docs/adr/`: context, decision, consequences, alternatives.
- **Small slices.** The kernel lands in reviewable slices (DBOS wiring, then paths, then fingerprints, then each primitive), each leaving the build green.
- **Tests first.** Engine tests use the fake adapter; unit tests never call a real harness or spend money.
- **Keep the README in sync.** A change that makes something real, or changes user-visible behavior, updates the README and its status section in the same change.
- **Verify external facts.** Harness CLIs, SDKs, DBOS and ACP change often; check current docs instead of relying on memory.

## Coding conduct

@.claude/conduct.md

## Vendored agentkit

`.claude/conduct.md` and `.claude/skills/` are verbatim copies from [agentkit](https://github.com/Karetski/agentkit) at commit `e8216e1`. Edit them upstream in agentkit and re-copy; don't edit the copies here. `hot-path-budget-audit` is intentionally not vendored: Whisperwind's engine is I/O-bound, with no per-tick latency budget. Ignore mentions of it in the conduct and other skills.

Re-sync from a local agentkit checkout:

```sh
AK=~/Developer/agentkit
for s in architecture-canon behavioral-testing commit-discipline debugging-methodology \
         function-shape principle-review simplify-ruthless wire-drift-check; do
  rm -rf ".claude/skills/$s" && cp -R "$AK/skills/$s" ".claude/skills/$s"
done
cp "$AK/CLAUDE.md" .claude/conduct.md
```

Then update the commit hash above.
