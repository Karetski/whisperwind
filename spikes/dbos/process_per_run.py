"""Several run processes on one SQLite file: which process executes a recovered
run, whether concurrent writers and a reader get along, and how a queue's global
concurrency limit behaves across processes.

    python spikes/dbos/process_per_run.py steps DB RUN_ID COUNT APP
    python spikes/dbos/process_per_run.py fanout DB RUN_ID COUNT APP

APP is `shared` (every run uses one DBOS application name) or `per-run` (each run
uses its own). Crash points and the ledger work as in `dbos_slice.py`.
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
import time
from typing import Any

from dbos import DBOS
from dbos_slice import APP_NAME, agent, flow, run

# The fan-out's queue: at most two children execute at once, across every process.
QUEUE = "capped"


@flow
async def count_steps(count: int) -> int:
    for i in range(count):
        await agent(f"step {i}", reply="ok")
    return count


@DBOS.step()
async def _hold(seconds: float) -> None:
    start = time.time()
    await asyncio.sleep(seconds)
    if path := os.environ.get("SPIKE_LEDGER"):
        with open(path, "a") as f:
            f.write(f"hold {DBOS.workflow_id} {os.getpid()} {start} {time.time()}\n")


@DBOS.workflow()
async def child(seconds: float) -> None:
    await _hold(seconds)


@flow
async def fan_out(count: int) -> int:
    queue = await DBOS.retrieve_queue_async(QUEUE)
    assert queue is not None
    handles = [await queue.enqueue_async(child, 0.3) for _ in range(count)]
    for handle in handles:
        await handle.get_result()
    return count


def app_name(mode: str, run_id: str) -> str:
    return APP_NAME if mode == "shared" else f"{APP_NAME}-{run_id}"


async def main(command: str, db: str, run_id: str, count: int, mode: str) -> None:
    workflow: Any = count_steps if command == "steps" else fan_out

    async def start() -> Any:
        if workflow is fan_out:
            # Queues live in the database, so a recovered run finds this one registered.
            await DBOS.register_queue_async(QUEUE, global_concurrency=2, polling_interval_sec=0.1)
        return await DBOS.start_workflow_async(workflow, count)

    print(json.dumps(await run(db, run_id, start, app_name(mode, run_id))))


if __name__ == "__main__":
    command, db, run_id, count, mode = sys.argv[1:6]
    asyncio.run(main(command, db, run_id, int(count), mode))
