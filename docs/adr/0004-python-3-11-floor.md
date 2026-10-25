# 0004. Python 3.11 is the minimum version

- Status: Accepted
- Date: 2026-10-24
- Decided by: the owner (D4 in `VISION.md` §15)
- Refs: `VISION.md` §11.2

## Context

The 0.1.x releases support Python 3.10 and newer (pre-pivot ADR 0001, "Implementation language"). Python 3.10 reached end of life on 2026-10-01. The new kernel relies on features added in 3.11: `asyncio.TaskGroup`, `asyncio.timeout`, `ExceptionGroup` and `except*`, and `tomllib`. 3.11 is also measurably faster.

## Decision

- `requires-python = ">=3.11"`. ruff and mypy target 3.11.
- CI tests every release from 3.11 through the newest CPython release.
- The documented install path uses a uv-managed Python, so users don't depend on their system interpreter.
- The floor is revisited in 2027, when 3.12 becomes the candidate.

## Consequences

- The kernel uses structured concurrency and timeouts from the standard library, with no backports.
- Users on a system Python older than 3.11 (stock macOS ships 3.9) install through uv, which downloads a supported interpreter.

## Alternatives

- **3.12 now.** Nothing the kernel needs is 3.12-only, and 3.11 is still supported upstream until 2027-10.
- **Stay on 3.10.** End of life, and it lacks `TaskGroup`, `asyncio.timeout` and `tomllib`, which would need backports.
