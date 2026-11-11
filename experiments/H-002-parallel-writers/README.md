---
id: H-002
title: Parallel readers with one serialized writer beat parallel writers on trusted change per attention-hour
status: planned
tests: [Q-007]
timebox: 3d
---
## Hypothesis

We believe that, for typical repository tasks, fanning out read-only agents (research, proposals, reviews) and having one writer apply the change produces more merged, trusted change per minute of human review than one worktree per parallel writer. We believe this holds at equal or lower cost.

The criteria below are a draft. The owner confirms them before the experiment runs.

## Method

Pick 6 to 10 real tasks from the owner's repositories:
- some that partition cleanly (per file or per failing test);
- some that don't.

Run each under three strategies, on the same harness and model:
1. **One agent.**
2. **Parallel readers, one writer:** N proposers or reviewers, one writer applies the change.
3. **Parallel writers:** N worktrees, then a merge.

For each run, record:
- merged or not, after the owner's review;
- review minutes;
- merge conflicts;
- rework rounds;
- total cost and wall time.

Prior evidence: [problem](../../docs/research/problem.md) §1D, §2.

## Pass if

- Strategy 2 has the best review-minutes per merged change on non-partitionable tasks.
- Strategy 2 is within 20% of the best on partitionable tasks.
- Strategy 2 costs no more than strategy 3.

## Fail if

- Strategy 3 wins review-minutes per merged change on partitionable tasks by more than 20%. Partitioned parallel writes then become first-class.
- Strategy 1 matches both multi-agent strategies within noise. Fan-out is then not the lever.

## Result

## Evidence
