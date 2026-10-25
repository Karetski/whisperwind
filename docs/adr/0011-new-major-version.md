# 0011. The Python kernel ships as a new major version

- Status: Accepted
- Date: 2026-10-24
- Decided by: the owner (D13 in `VISION.md` §15)
- Refs: `VISION.md` §13

## Context

The 0.1.x releases on PyPI run the YAML engine. The Python kernel changes how flows are written (ADR 0001), where run state lives (ADR 0002), the installation channels (ADR 0003) and the configuration format (ADR 0008). Nothing about a 0.1.x project carries over unchanged.

## Decision

- The Python kernel ships as a new major version, 1.0. Phase P4's exit criteria include tagging its beta.
- The 0.1.x line gets bug fixes only.

## Consequences

- Users choose the engine by version: 0.1.x for YAML flows, the new major for Python flows.
- Once P4 deletes the YAML engine from `main`, a 0.1.x fix is made on a maintenance branch cut from the last 0.1.x tag.

## Alternatives

- **Gradual minor releases** of 0.x with both engines until P4. A smoother path on paper, but every minor release would ship two engines and an API still in motion.
