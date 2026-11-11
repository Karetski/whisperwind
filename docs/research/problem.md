# Problem: running coding agents beyond one interactive session

Researched on 2026-11-10. **[P]** marks a primary source read directly; **[S]** marks secondary coverage, to verify before quoting. Inferences are marked *(inference)*. The owner confirmed every pain theme below from their own experience. This is an input to decisions, not a decision.

## 1. The pain

**A. Review and verification are the bottleneck, not generation.**
- Willison [P], [2025-10-05](https://simonwillison.net/2025/Oct/5/parallel-coding-agents/): "the natural bottleneck on all of this is how fast I can review the results."
- Ronacher [P], ["The Final Bottleneck", 2026-02-13](https://lucumr.pocoo.org/2026/2/13/the-final-bottleneck/): "if input grows faster than throughput, you have an accumulating failure". He asks for backpressure.
- Osmani [P], [2026-03-26](https://addyosmani.com/blog/code-agent-orchestra/): "The bottleneck is no longer generation. It's verification." He recommends WIP limits.
- Faros AI [S], 10k+ developers: review time +91%, PR size +154%, delivery flat.
- Harvard working paper [S], 718 firms ([LeadDev, Oct 2026](https://leaddev.com/ai/ai-isnt-making-developers-more-productive-its-making-them-busier)): +23% PRs, PR-to-merge time +49%, resolved issues flat.

**B. Agents grade themselves too generously, and tests are weak oracles.**
- Anthropic [P], [2025-11-26](https://www.anthropic.com/engineering/effective-harnesses-for-long-running-agents): agents "declare the job done" early.
- Anthropic [P], [2026-03-24](https://www.anthropic.com/engineering/harness-design-long-running-apps): agents "reliably skew positive when grading their own work."
- Böckeler [P], [2026-04-02](https://martinfowler.com/articles/harness-engineering.html): behavioural correctness is "the elephant in the room". She notes the harness "is most needed where it is hardest to build."
- Carlini [P], [2026-02-05](https://www.anthropic.com/engineering/building-c-compiler): with an imperfect verifier, the agent "will solve the wrong problem."

**C. Cost multiplies.**
- Anthropic [P], [2025-06-13](https://www.anthropic.com/engineering/multi-agent-research-system): agents use about 4× the tokens of chat, multi-agent systems about 15×.
- A full planner/generator/evaluator harness cost $200 over 6 h, against $9 over 20 min for a solo run [P].
- [Vals AI](https://www.vals.ai/blog/multi-agent-vibe-code-bench) [P], 2026-10-09: teams cost 1.8–5.1× as much as one agent.
- Users report subscription limits are unpredictable [S].

**D. Parallel writers collide.**
- Cursor [P], [2026-01-14](https://cursor.com/blog/scaling-agents): 20 agents behind locks ran at the effective throughput of 2–3. A dedicated integrator role "created more bottlenecks than it solved."
- Carlini [P]: agents overwrote each other's fixes until GCC served as an oracle and each agent got its own file.
- Worktrees defer conflicts to merge time, and don't isolate databases [S].

**E. Context and state get lost between agents and sessions.**
- Anthropic [P]: work was left "half-implemented and undocumented". Durable artifacts fixed it: a feature list, a progress file, `init.sh`, git.
- Cognition [P], [2026-04-22](https://cognition.com/blog/multi-agents-working): handing over context "without overwhelming the receiver". Managers "assume shared state" that their children lack.

**F. Long-running work fails partway.**
- Anthropic [P]: "errors compound", so resume from the point of failure.
- Claude agent teams [P]: no resume for in-process teammates, and no teams in headless `-p` mode.

**G. Harness CLIs are unreliable** [S, 2026 issue reports]: `claude -p` hangs on stream-json, stalls for about 405 s, exits 0 "success" mid-task, and kills background tasks at the end of a turn. *(inference)* Exit codes and liveness can't be trusted. Outcomes must be checked.

**H. Observability and reproducibility.** Runs are "non-deterministic between runs, even with identical prompts" (Anthropic [P]). Huntley calls nondeterminism "the Achilles' heel of Ralph" [P]. Cursor: "the prompts matter more" [P]. *(inference)* The prompt plus the model version is the artifact to version.

**I. Human attention.**
- Hashimoto [P], [2026-02-05](https://mitchellh.com/writing/my-ai-adoption-journey): notifications off. He decides when to engage, mostly by starting an agent at the end of the day.
- Ronacher [P], ["The Coming Loop", 2026-06-23](https://lucumr.pocoo.org/2026/6/23/the-coming-loop/): humans risk becoming "a messenger". He wants ways to "jolt the human back into the loop."
- Agent teams route every permission prompt to the lead session [P].

**J. Security** [S]: prompt-injection incidents against triage bots and CI-hosted agents in 2026, a CVE where Gemini CLI ran code before its sandbox started, and an agent that deleted a production database. Willison's "lethal trifecta" remains the model: untrusted input plus private data plus a way to send data out.

## 2. Patterns, by evidence

**Works:**
- **A separate evaluator with a clean context** (Anthropic, Cognition [P]). It's worth it only when the task is beyond what the model does reliably on its own.
- **Parallel readers with a single writer.** Cognition [P]: "multi-agent systems work best today when writes stay single-threaded." Claude agent teams recommend starting with research and review.
- **Planner → isolated workers → judge, with a fresh start each cycle,** at Cursor's scale [P]. A different model per role helped, and "many of our improvements came from removing complexity."
- **Fan-out per independent failure when an oracle exists** (Carlini [P]).
- **Plain loops with backpressure** for greenfield or disposable work (Huntley, Ronacher [P]). Huntley wouldn't use one on an existing codebase.
- **Deterministic steps interleaved with agent steps.** Stripe's "blueprints", about 1,300 PRs a week, all human-reviewed [S].

**Mixed or weak:**
- **Teams vs one agent.** Vals AI [P]: only 1 of 4 configurations gained, and for one model, more effort beat adding a team.
- **Collaborating peers.** [CooperBench](https://arxiv.org/abs/2601.13295) [P]: 30% lower success together.
- **Best-of-N.** The selector is the hard part: 42% on one attempt, 71% if any of 16 attempts counts, 59% with a real selector (DeepSWE [S]).
- **Orchestrator megasystems.** Gas Town was mostly used to build itself (Yegge via Willison [P]).

*(inference)* What holds up is diversity in *reading* (reviewers, hypotheses, research) plus serialized *writing*, gated by deterministic checks. Fan-out of writes needs partitioned ownership and an external oracle.

## 3. Direction of the field

**Facts:**
- **Harnesses are absorbing orchestration:** Claude subagents, teams, hooks, worktrees, workflows; [OpenAI Symphony](https://openai.com/index/open-source-codex-orchestration-symphony/) (2026-04-27).
- **Harness components expire** (Anthropic [P]). Each one "encodes an assumption about what the model can't do on its own", and those assumptions "can quickly go stale". Context resets went at Opus 4.5, sprint decomposition at 4.6.
- **Task horizons double about every 89 days** ([METR, 2026-01-29](https://metr.org/blog/2026-01-29-time-horizon-1-1/)).
- **Async agents that produce PRs are mainstream,** but their PRs merge less often than human ones [S].
- **Open protocols are maturing:** ACP has a registry, AGENTS.md and MCP are under the Linux Foundation's AAIF, and the OTel agent spans are still Development.

**To stay relevant, a local tool needs to** *(inference)*:
- own what harnesses won't: cross-vendor runs, budgets that span harnesses, human waits that survive crashes, deterministic gates, an auditable record;
- treat each harness as an unreliable subprocess;
- manage human attention: batching, WIP limits, being pulled in on the user's schedule;
- speak OTel and ACP rather than invent formats.

**Likely obsolete within one or two model generations:** context-reset scaffolding, task decomposition for a single feature, hand-built agent messaging, and "loop until done" wrappers.

## 4. Sharp questions this raises

Each one is tracked in the ledger:

| Raised question | Ledger |
|---|---|
| Unit of value: a workflow, a run, or a merged change? | [product](../product.md) |
| Does Whisperwind raise throughput, or ration it with backpressure? | [Q-009](../questions/Q-009-human-attention.md) |
| Which primitives survive the next model generation? | P-11 in [principles](../principles.md) |
| What does Whisperwind own that harnesses can't? | [Q-013](../questions/Q-013-positioning.md) |
| Where does verification come from? | [Q-006](../questions/Q-006-verification.md) |
| Should parallel writers be first-class? | [Q-007](../questions/Q-007-concurrent-writes.md) |
| Greenfield or brownfield? | [product](../product.md) |
| Why does durability matter to this user? | [Q-005](../questions/Q-005-durability-and-step-identity.md) |
| What is the trust boundary for unattended agents? | [Q-011](../questions/Q-011-isolation-and-trust.md) |
