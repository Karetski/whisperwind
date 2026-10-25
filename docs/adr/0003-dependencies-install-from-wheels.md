# 0003. Dependencies install from wheels on every tier-1 platform

- Status: Accepted
- Date: 2026-10-24
- Decided by: the owner (D3 in `VISION.md` §15)
- Refs: `VISION.md` §10.2, §10.4

## Context

The 0.1.x releases require every runtime dependency to be pure Python (pre-pivot ADR 0001, "Implementation language"). The rule protected installation in restricted environments and made a single-file `.pyz` zipapp possible. It also blocks most of the ecosystem the new kernel needs: DBOS (through SQLAlchemy, greenlet and psycopg), pydantic, libcst, the official harness SDKs and the ACP SDK. Research found no evidence that blocking compiled code is a common enterprise policy; package proxies such as Artifactory and Nexus cache wheels, and policy gates target CVEs and licenses.

## Decision

- **Any runtime dependency is allowed if it installs from wheels, never from source, on every tier-1 platform:** manylinux x86_64, manylinux aarch64 and macOS arm64, plus Windows amd64 once Windows is supported.
- **Its license must be compatible:** MIT, BSD, Apache-2.0, MPL, LGPL (as a library), PSF-2.0 or EPL-1.0. BSL and SSPL are never runtime dependencies.
- **CI enforces both.** A job on each tier-1 platform's own runner installs the built wheel with `--only-binary :all:` on the oldest and newest supported Python and runs `whw --version`. pip-licenses checks the runtime environment against an exact allowlist of SPDX IDs and trove classifiers in `pyproject.toml`, so an unrecognized license fails. A package whose metadata doesn't list the license it is used under is exempted by name, with a comment naming that license.
- **The footprint stays visible.** CI records installed size and `whw --version` time on each platform. A dependency that breaks the footprint budget needs an ADR.
- **Heavy or optional integrations are extras** (`[otel]`, `[server]`, `[container]`, …), so the default install stays small.
- **The `.pyz` zipapp retires,** because it can't carry compiled code. The documented install is `uv tool install whisperwind`, with pipx as an alternative.

## Consequences

- DBOS, pydantic and libcst can be adopted instead of rebuilt.
- Platforms without wheels (musl/Alpine without musllinux wheels, ppc64le, s390x) and air-gapped mirrors that curate wheels one by one lose support.
- PSF-2.0 is allowed because `typing_extensions`, which Textual requires, uses it. EPL-1.0 is allowed because grandalf is licensed "GPLv2 | EPLv1" and is used under EPL-1.0. Its classifier names only GPLv2, so it is the one package exempted by name.
- A container image and per-platform PEX files may later serve users who want a single artifact.

## Alternatives

- **A pure-Python core with compiled extras.** Keeps the `.pyz`, but DBOS and pydantic are core to the kernel, not optional, so the core would still need them.
- **Keep the pure-Python rule.** It would mean owning a durable-execution engine, structured-output validation and source editing that maintained libraries already provide.
