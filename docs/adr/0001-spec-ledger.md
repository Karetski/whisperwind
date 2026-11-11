---
id: ADR-0001
title: The spec lives in a ledger of small ID'd files
status: accepted
date: 2026-11-10
decided-by: owner
---
# ADR-0001. The spec lives in a ledger of small ID'd files

## Context

Whisperwind's design had grown into one 1,000-line vision document, a set of ADRs, a README written "as designed", milestones on GitHub and spike READMEs. Telling decided from proposed meant reading prose. Agents loaded far more than they needed, and humans couldn't review a change to the direction without rereading the whole document.

The project is now specifying before it builds ([ADR-0002](0002-spec-first-reset.md)). The spec has to be easy for a person to review and update, and cheap for a coding agent to navigate. An agent must be able to tell what is decided, what is proposed and what is open without judgement calls.

What we found about current practice (research of 2026-11-10):
- **Spec-driven tools** such as GitHub Spec Kit, Kiro and BMAD generate a large spec per feature. Reviewers report verbose output that is "tedious to review" (Böckeler, Oct 2025) and stories of 1,000+ lines (INNOQ, Apr 2026).
- **OpenSpec** keeps current-truth specs plus change folders that merge as deltas. Thoughtworks rated it Trial in Nov 2026. Its delta model pays off once code exists. It needs Node 22+.
- **Oxide-style RFDs** suit narrative design, but grow long. That is how the old vision document grew.
- **Evidence on agent context files** (ETH Zurich, Feb 2026): they help mainly when they state non-obvious rules, and they cost tokens. Small files reached through an index beat preloading.

## Decision

The spec is a **ledger**: small Markdown files, each item with a stable ID and a status. A generated index ties them together, and a stdlib Python script checks the rules in CI.

**Kinds of item**

| Kind | ID | Lives in | Statuses |
|---|---|---|---|
| Decision | `ADR-NNNN` | `docs/adr/NNNN-slug.md`, front matter | proposed, accepted, rejected, deprecated, superseded |
| Question | `Q-NNN` | `docs/questions/Q-NNN-slug.md`, front matter | open, answered, dropped |
| Hypothesis | `H-NNN` | `experiments/H-NNN-slug/README.md`, front matter | planned, running, confirmed, refuted, inconclusive |
| Principle | `P-NN` | a heading in `docs/principles.md` | candidate, accepted, retired |
| Requirement | `ARCH-`, `SDK-`, `CLI-`, `TUI-` or `DM-NNN` | a heading in `docs/spec/<area>.md` | draft, specified, implemented, verified, dropped |

A heading item is a level-2 to level-4 heading `ID Title`. The next line holds its fields as `key: value` pairs, for example `status: specified  decided-by: ADR-0004  verify: <test path>`.

**How work flows**

1. A **question** names something undecided, the options known, and what would settle it.
2. When reasoning can't settle it, a **hypothesis** states a claim, pass and fail criteria written *before* the experiment runs, and a time box. Its directory holds the experiment's code. It ends with a verdict and evidence.
3. A **decision** (MADR-style: context, decision, consequences, alternatives) cites its questions and hypotheses. The owner accepts it. Only an accepted decision is binding.
4. **Requirements** in `docs/spec/` state what the system shall do. They are EARS-style where that helps ("WHEN …, THE CLI SHALL …"), and cite the decision behind them. During implementation, tests name the requirement they verify.

Files stay under 300 lines. Research reports in `docs/research/` are dated and cite their sources. They are inputs to decisions, never binding. Tasks and discussion live in GitHub issues and PRs, which refer to ledger IDs; ledger files never cite issue numbers.

**What CI checks** (`python3 tools/ledger.py check`)
- Every item has a title and a valid status, and its ID is unique and matches its file name.
- Every ID mentioned outside code spans resolves to an item.
- An answered question names the decision that answered it. A superseded decision names its successor.
- A finished hypothesis has a result.
- A requirement that is specified or beyond cites only accepted decisions. A verified one names how it is verified.
- No file is over 300 lines.
- `docs/INDEX.md` matches what the script generates.

## Consequences

- An agent starts at `docs/INDEX.md`, opens only the items it needs, and can rely on statuses. "Never build on a proposed decision" becomes a rule CI enforces, not a convention.
- The script is about 200 lines of owned tooling, built rather than adopted. OpenSpec is the closest tool, but it has no questions, hypotheses or decisions, and it adds a Node toolchain to the repo before any code exists.
- IDs and front matter port cleanly to OpenSpec or sphinx-needs if the project outgrows this.
- Plans and task lists stay ephemeral, in issues and PRs. The spec holds only durable truth.

## Alternatives

- **Adopt OpenSpec now.** Rejected for the spec phase: it has no question, hypothesis or decision kinds, it adds Node 22+, and its deltas only pay off once there is a current truth to change. Revisit once implementation starts.
- **RFDs per subsystem with conformance tests as the spec.** Rejected: long narrative documents are what this replaces. Executable conformance tests return during implementation, as the `verify` field of requirements.
- **Keep VISION.md, the ADRs and GitHub milestones.** Rejected: it is the status quo this decision exists to fix.
