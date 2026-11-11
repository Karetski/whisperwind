# Whisperwind

Whisperwind is a lightweight, local-first platform for running coding agents people can trust. It drives existing agent harnesses (Claude Code, Codex, ACP agents) through durable, bounded, review-centred workflows. Its goal is more trusted, reviewed change per hour of human attention.

**The project is in its spec phase. There is no implementation.** Only the spec ledger and experiments exist (`docs/adr/0002-spec-first-reset.md`).

## Start here

1. Read `docs/INDEX.md`. It lists every question, hypothesis, decision, principle and requirement, with its status and file.
2. Open only the items your task needs. `docs/product.md` and `docs/principles.md` are short and always relevant.
3. The ledger's rules are in `docs/adr/0001-spec-ledger.md`. Templates are in `docs/templates/`.

## Rules for this project

- **Status is binding.** Only an `accepted` ADR is a decision. Never build on, or write a requirement against, a `proposed` ADR, an `open` question or a `candidate` principle as if it were settled. CI rejects a `specified` requirement that cites an unaccepted ADR.
- **Decisions are the owner's.** Draft ADRs as `proposed`, present the tradeoff, and let the owner accept. The same goes for promoting principles from `candidate`, and for confirming a hypothesis's pass/fail criteria before its experiment runs.
- **Every earlier decision is reopened.** `docs/research/prior-work.md` records the October 2026 positions and the spike evidence as inputs, not as answers.
- **Experiments are the only code.** Each lives in `experiments/H-NNN-slug/`, next to the README holding its hypothesis. Experiments are throwaway; nothing imports them. Write the criteria before running, then record the result and evidence and set a terminal status.
- **Keep files small and standalone.** Each ledger file stays under 300 lines. Cite other items by ID. Never cite GitHub issue numbers, dates of conversations, or "as discussed".
- **Research is dated and sourced.** Files in `docs/research/` cite primary sources with dates, and mark inferences. Harness CLIs, SDKs and protocols change monthly: check current docs instead of relying on memory.
- **Run the ledger check before committing:** `python3 tools/ledger.py index && python3 tools/ledger.py check`. Its tests: `python3 -m unittest discover -s tools`.
- **Adopt before building** applies to tooling too: building something a maintained tool already does needs an ADR.

## Coding conduct

@.claude/conduct.md

## Vendored agentkit

`.claude/conduct.md` and `.claude/skills/` are verbatim copies from [agentkit](https://github.com/Karetski/agentkit) at commit `e8216e1`. Edit them upstream in agentkit and re-copy; don't edit the copies here. `hot-path-budget-audit` is intentionally not vendored: the project has no per-tick latency budget. Ignore mentions of it in the conduct and other skills.

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
