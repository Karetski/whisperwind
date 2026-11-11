# Whisperwind

Whisperwind is a lightweight, local-first platform for running coding agents you can trust. It drives the agent harnesses you already use, such as Claude Code, Codex and ACP agents, through repeatable workflows that are durable, bounded and built around human review. Its goal is **more trusted, reviewed change per hour of human attention**, from one developer to a team.

## Status

**Spec phase. Nothing here runs.** The project is being specified before it is built: architecture, SDK, CLI, TUI and data model. Risky assumptions are tested by small experiments first ([ADR-0002](docs/adr/0002-spec-first-reset.md)).

The 0.1.x releases on PyPI run an earlier YAML-based engine. It is retired and gets no fixes. Its code is at the tag `archive/v0.1-yaml-engine`, and what it and the October 2026 redesign taught us is in [prior work](docs/research/prior-work.md).

## How the repository is organised

The spec is a **ledger**: small files, each item with a stable ID and a status ([ADR-0001](docs/adr/0001-spec-ledger.md)). Start at [`docs/INDEX.md`](docs/INDEX.md).

| Path | Holds |
|---|---|
| [`docs/product.md`](docs/product.md) | The problem, the goal, users, non-goals |
| [`docs/principles.md`](docs/principles.md) | `P-NN`: principles that break ties |
| [`docs/questions/`](docs/questions) | `Q-NNN`: open questions, each with options, the earlier answer and what would settle it |
| [`experiments/`](experiments) | `H-NNN`: hypotheses with pass/fail criteria written in advance, a time box, and a verdict |
| [`docs/adr/`](docs/adr) | `ADR-NNNN`: decisions. Only accepted ones bind. |
| [`docs/spec/`](docs/spec) | `ARCH-`, `SDK-`, `CLI-`, `TUI-`, `DM-NNN`: requirements, each citing the decision behind it |
| [`docs/research/`](docs/research) | Dated research: the problem, the landscape, prior work |
| [`docs/templates/`](docs/templates) | Templates for questions, hypotheses and decisions |

A question becomes an experiment where evidence is needed. The answer becomes a decision that the owner accepts, and the decision becomes requirements. GitHub issues track the work and cite ledger IDs.

## Checking the ledger

```sh
python3 tools/ledger.py check            # rules and index freshness; runs in CI
python3 tools/ledger.py index            # regenerate docs/INDEX.md after editing
python3 -m unittest discover -s tools    # tests for the checker
```

## License

MIT
