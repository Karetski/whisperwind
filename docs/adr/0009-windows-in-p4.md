# 0009. Windows support waits for phase P4

- Status: Accepted
- Date: 2026-10-24
- Decided by: the owner (D11 in `VISION.md` §15)
- Refs: `VISION.md` §10.4, §11.2; issue #76

## Context

Whisperwind supports Linux and macOS. Steps run in POSIX process groups, and cancelling a step kills its whole process tree with signals. On Windows, killing a process tree reliably needs Job Objects (through `ctypes`), and Windows needs its own CI.

## Decision

- Windows support is built in phase P4 (issue #76), not earlier.
- Until then, the process supervisor keeps OS-specific process-tree handling behind one interface, so a Job Objects implementation fits without changing its callers.
- Windows amd64 joins the tier-1 platforms, and the wheel check, when support lands.

## Consequences

- Phases P1–P3 build and test on Linux and macOS only.
- Every supervisor change in the meantime must keep the process-tree code behind that interface.

## Alternatives

- **Support Windows from phase P1.** It avoids a later port, but every kernel slice would carry Windows CI and Job Objects work before the kernel's shape has settled.
