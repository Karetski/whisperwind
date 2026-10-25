# 0008. Configuration is TOML

- Status: Accepted
- Date: 2026-10-24
- Decided by: the owner (D10 in `VISION.md` §15)
- Refs: `VISION.md` §10.2; issue #87

## Context

Configuration describes the environment, never flow behavior: harness binaries and tested versions, environment variables allowed into steps, token prices, retention and similar settings. In the 0.1.x releases it is YAML: `.whisperwind/config.yaml` in a project and `config.yaml` in the per-user config directory, read with ruamel.yaml. Once YAML flows retire (ADR 0001), configuration is the only YAML left. Python 3.11 ships a TOML reader, `tomllib` (ADR 0004).

## Decision

- Configuration files are TOML: `.whisperwind/config.toml` in a project and `config.toml` in the per-user config directory, read with stdlib `tomllib`.
- The keys and the merge order (built-in defaults, user, project, then `--config`) stay the same.
- The switch is its own change (issue #87). ruamel.yaml leaves the runtime dependencies when the YAML engine is deleted in phase P4.

## Consequences

- Reading configuration needs no third-party parser.
- `tomllib` only reads. `whw init` writes its config from a template string, so no TOML writer is needed.
- Existing `config.yaml` files need a migration path, chosen in issue #87.

## Alternatives

- **Keep YAML configuration.** No migration, but ruamel.yaml would stay a runtime dependency after the YAML engine is gone, for one file.
