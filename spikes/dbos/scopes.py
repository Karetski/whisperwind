"""Scopes on DBOS child workflows: each `parallel` branch runs as a child workflow
whose ID is the parent's ID plus the branch's scope path. Every rule that maps a
path onto DBOS lives in this module.

    python spikes/dbos/scopes.py run DB RUN_ID FLOW
    python spikes/dbos/scopes.py rerun DB RUN_ID SCOPE STEP

`run` starts or recovers a run of FLOW (`review` or `slow`). `rerun` reruns one
branch of a finished `review` run from STEP of the branch, leaving its siblings
alone, and prints the new run's result. The path syntax here is provisional;
the grammar is settled in its own ADR.
"""

from __future__ import annotations

import asyncio
import json
import os
import signal
import sqlite3
import sys
from collections import Counter
from contextlib import closing
from typing import Any

import anyio
from dbos import DBOS, SetWorkflowID
from dbos_slice import agent, flow, ledger, run, shell

_ordinals: Counter[tuple[str, str]] = Counter()


def child_id(parent_id: str, scope: str) -> str:
    """The DBOS workflow ID of a scope: its parent's ID, a slash, the scope path."""
    return f"{parent_id}/{scope}"


def fork_id(workflow_id: str) -> str:
    """A rerun can't reuse an ID, because DBOS gives every fork a new one."""
    return f"{workflow_id}~1"


async def parallel(*branches: tuple[Any, ...]) -> list[Any]:
    """Run each (workflow, *args) branch as a child workflow, all at once.

    A child workflow is recovered on its own, from its registered function and
    serialized inputs, so a branch can't be an arbitrary coroutine.
    """
    parent = DBOS.workflow_id or ""
    # The flow re-executes from the top on recovery, so ordinals repeat exactly.
    ordinal = _ordinals[(parent, "parallel")]
    _ordinals[(parent, "parallel")] += 1
    handles = []
    for index, (workflow, *args) in enumerate(branches):
        with SetWorkflowID(child_id(parent, f"parallel#{ordinal}/{index}")):
            handles.append(await DBOS.start_workflow_async(workflow, *args))
    return list(await asyncio.gather(*(handle.get_result() for handle in handles)))


# -- a fan-out flow -----------------------------------------------------------------


@DBOS.workflow()
async def review(focus: str) -> str:
    text = await agent(f"Review the diff for {focus}", reply=f"{focus}: no issues")
    tests = await shell(["sh", "-c", "sleep 0.3"])
    return f"{text} (tests {'pass' if tests.ok else 'fail'})"


@flow
async def review_change(goal: str) -> str:
    plan = await agent(f"Plan this change: {goal}", reply="one small patch")
    results = await parallel((review, "bugs"), (review, "security"), (review, "style"))
    verdict = await shell(["sh", "-c", "exit 0"])
    return f"{plan}; " + "; ".join(results) + f"; verdict {verdict.exit_code}"


# -- cancellation reaching a process group -------------------------------------------


@DBOS.step()
async def supervised_shell(argv: list[str]) -> dict[str, Any]:
    """Run a command in its own process group; kill the group if this workflow is cancelled.

    DBOS cancellation is checked between steps, so a running step learns of it
    only by watching its workflow's status.
    """
    workflow_id = DBOS.workflow_id or ""
    process = await asyncio.create_subprocess_exec(*argv, start_new_session=True)
    ledger(DBOS.step_id or 0, f"supervised_shell:{process.pid}")
    outcome: dict[str, Any] = {"cancelled": False}
    async with anyio.create_task_group() as group:

        async def watch() -> None:
            while True:
                await anyio.sleep(0.1)
                status = await DBOS.get_workflow_status_async(workflow_id)
                if status is not None and status.status == "CANCELLED":
                    os.killpg(process.pid, signal.SIGTERM)
                    outcome["cancelled"] = True
                    return

        async def wait() -> None:
            outcome["exit_code"] = await process.wait()
            group.cancel_scope.cancel()

        group.start_soon(watch)
        group.start_soon(wait)
    return outcome


@DBOS.workflow()
async def slow_branch(seconds: int) -> dict[str, Any]:
    return await supervised_shell(["sleep", str(seconds)])


@flow
async def slow(seconds: int) -> list[Any]:
    return await parallel((slow_branch, seconds), (slow_branch, seconds))


# -- rerunning one scope ------------------------------------------------------------


def first_result_step(db: str, workflow_id: str) -> int:
    """The parent's first step that awaits a child: forking from it re-awaits every child."""
    with closing(sqlite3.connect(db)) as conn:
        row = conn.execute(
            "SELECT min(function_id) FROM operation_outputs"
            " WHERE workflow_uuid = ? AND function_name = 'DBOS.getResult'",
            (workflow_id,),
        ).fetchone()
    return int(row[0])


async def rerun(db: str, run_id: str, scope: str, step: int) -> Any:
    """Rerun one branch from `step`, then the parent from where it awaits its branches."""
    old_child, parent_step = child_id(run_id, scope), first_result_step(db, run_id)

    async def fork() -> Any:
        with SetWorkflowID(fork_id(old_child)):
            await DBOS.fork_workflow_async(old_child, step)
        with SetWorkflowID(fork_id(run_id)):
            return await DBOS.fork_workflow_async(
                run_id, parent_step, replacement_children={old_child: fork_id(old_child)}
            )

    return await run(db, fork_id(run_id), fork, app_name(run_id))


def app_name(run_id: str) -> str:
    return f"whisperwind-spike-{run_id}"


async def main(argv: list[str]) -> None:
    command, db, run_id = argv[:3]
    if command == "rerun":
        result = await rerun(db, run_id, argv[3], int(argv[4]))
    else:
        workflow, args = {"review": (review_change, ["add rate limiting"]), "slow": (slow, [30])}[
            argv[3]
        ]
        result = await run(
            db, run_id, lambda: DBOS.start_workflow_async(workflow, *args), app_name(run_id)
        )
    print(json.dumps(result))


if __name__ == "__main__":
    asyncio.run(main(sys.argv[1:]))
